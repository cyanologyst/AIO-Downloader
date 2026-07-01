from __future__ import annotations

import asyncio
import base64
import json
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.subprocess_utils import require_executable, subprocess_window_options


class Aria2RpcError(RuntimeError):
    pass


@dataclass(slots=True)
class Aria2Config:
    binary: str
    download_dir: Path
    host: str = "127.0.0.1"
    port: int = 6800
    secret: str = ""

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/jsonrpc"


class Aria2RpcClient:
    STATUS_KEYS = [
        "gid",
        "status",
        "totalLength",
        "completedLength",
        "downloadSpeed",
        "errorMessage",
        "followedBy",
        "following",
        "infoHash",
        "bittorrent",
        "files",
    ]

    def __init__(self, config: Aria2Config) -> None:
        self.config = config
        self._secret = config.secret or self._load_or_create_secret()
        self._request_id = 0
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    def _load_or_create_secret(self) -> str:
        path = self.config.download_dir / ".aria2.rpc-secret"
        try:
            if path.exists() and (value := path.read_text(encoding="utf-8").strip()):
                return value
            path.parent.mkdir(parents=True, exist_ok=True)
            value = secrets.token_urlsafe(24)
            path.write_text(value, encoding="utf-8")
            return value
        except OSError:
            return secrets.token_urlsafe(24)

    async def ensure_started(self) -> None:
        async with self._lock:
            if await self.is_ready():
                return
            binary = require_executable(self.config.binary, "aria2c")
            self.config.download_dir.mkdir(parents=True, exist_ok=True)
            session = self.config.download_dir / ".aria2.session"
            session.touch(exist_ok=True)
            self._process = await asyncio.create_subprocess_exec(
                binary,
                "--no-conf=true",
                "--enable-rpc=true",
                "--rpc-listen-all=false",
                f"--rpc-listen-port={self.config.port}",
                f"--rpc-secret={self._secret}",
                "--continue=true",
                "--seed-time=0",
                "--follow-torrent=true",
                "--bt-save-metadata=true",
                "--auto-file-renaming=true",
                "--max-connection-per-server=8",
                "--split=8",
                "--min-split-size=1M",
                "--summary-interval=0",
                f"--dir={self.config.download_dir}",
                f"--input-file={session}",
                f"--save-session={session}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                **subprocess_window_options(),
            )
            for _ in range(40):
                if await self.is_ready():
                    return
                if self._process.returncode is not None:
                    break
                await asyncio.sleep(0.2)
            detail = ""
            if self._process.stderr:
                detail = (await self._process.stderr.read()).decode(errors="replace").strip()
            raise RuntimeError(f"aria2 RPC daemon did not become ready{': ' + detail if detail else ''}")

    async def call(self, method: str, *params: Any) -> Any:
        self._request_id += 1
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(self._request_id),
                "method": method,
                "params": [f"token:{self._secret}", *params],
            }
        ).encode()

        def send() -> Any:
            request = urllib.request.Request(
                self.config.url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    decoded = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError) as exc:
                raise Aria2RpcError(str(exc)) from exc
            if "error" in decoded:
                raise Aria2RpcError(decoded["error"].get("message", str(decoded["error"])))
            return decoded.get("result")

        return await asyncio.to_thread(send)

    async def is_ready(self) -> bool:
        try:
            await self.call("aria2.getVersion")
            return True
        except Exception:
            return False

    async def add_uri(self, url: str, options: dict[str, str]) -> str:
        await self.ensure_started()
        return str(await self.call("aria2.addUri", [url], options))

    async def add_torrent(self, path: Path, options: dict[str, str]) -> str:
        await self.ensure_started()
        encoded = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
        return str(await self.call("aria2.addTorrent", encoded, [], options))

    async def status(self, gid: str) -> dict[str, Any]:
        return dict(await self.call("aria2.tellStatus", gid, self.STATUS_KEYS))

    async def pause(self, gid: str) -> None:
        await self.call("aria2.forcePause", gid)

    async def resume(self, gid: str) -> None:
        await self.call("aria2.unpause", gid)

    async def cancel(self, gid: str) -> None:
        await self.call("aria2.forceRemove", gid)
