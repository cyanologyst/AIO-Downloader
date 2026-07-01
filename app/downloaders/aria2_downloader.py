from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.downloaders.aria2_rpc import Aria2Config, Aria2RpcClient
from app.downloaders.base import BaseDownloader, DownloadContext
from app.models import DownloadArtifact, DownloadRequest, DownloadResult
from app.utils.subprocess_utils import subprocess_window_options

DIRECT_EXTENSIONS = {
    ".7z", ".apk", ".avi", ".bin", ".bz2", ".csv", ".deb", ".dmg", ".doc",
    ".docx", ".exe", ".flac", ".gz", ".img", ".iso", ".jpg", ".json", ".m4a",
    ".mkv", ".mov", ".mp3", ".mp4", ".msi", ".pdf", ".png", ".rar", ".rpm",
    ".tar", ".torrent", ".txt", ".wav", ".webm", ".webp", ".xz", ".zip",
}


class Aria2Downloader(BaseDownloader):
    provider_name = "aria2"

    def __init__(self, config: Aria2Config) -> None:
        self.client = Aria2RpcClient(config)
        self._gids: dict[str, str] = {}

    async def can_handle(self, url: str) -> bool:
        if url.startswith("magnet:"):
            return True
        path = Path(urlparse(url).path)
        if path.suffix.lower() in DIRECT_EXTENSIONS or (
            path.exists() and path.suffix.lower() == ".torrent"
        ):
            return True
        if urlparse(url).scheme not in {"http", "https"}:
            return False
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                response = await client.head(url)
                if response.status_code >= 400:
                    response = await client.get(url, headers={"Range": "bytes=0-0"})
                content_type = response.headers.get("content-type", "").lower()
                disposition = response.headers.get("content-disposition", "").lower()
                return "attachment" in disposition or (
                    content_type
                    and not content_type.startswith(("text/html", "application/xhtml", "application/json"))
                )
        except Exception:
            return False

    async def download(
        self, request: DownloadRequest, context: DownloadContext
    ) -> DownloadResult:
        assert request.destination
        request.destination.mkdir(parents=True, exist_ok=True)
        options = {
            "dir": str(request.destination),
            "continue": "true",
            "follow-torrent": "true",
            "bt-save-metadata": "true",
            "bt-metadata-only": "false",
            "seed-time": "0",
        }
        if request.selected_files:
            options["select-file"] = ",".join(request.selected_files)
        local = Path(request.url).expanduser()
        if local.exists() and local.suffix.lower() == ".torrent":
            gid = await self.client.add_torrent(local, options)
        else:
            gid = await self.client.add_uri(request.url, options)
        self._gids[context.job_id] = gid
        title = self._title(request.url)
        try:
            while True:
                status = await self.client.status(gid)
                followed_by = status.get("followedBy") or []
                if followed_by and followed_by[0] != gid:
                    gid = str(followed_by[0])
                    self._gids[context.job_id] = gid
                    context.progress(
                        title=title,
                        status="downloading",
                        metadata={"metadata_gid": status.get("gid"), "aria2_gid": gid},
                    )
                    await asyncio.sleep(0.2)
                    continue
                state = status.get("status", "active")
                total = int(status.get("totalLength") or 0)
                downloaded = int(status.get("completedLength") or 0)
                speed = int(status.get("downloadSpeed") or 0)
                percent = downloaded / total * 100 if total else 0
                eta = int((total - downloaded) / speed) if total and speed else None
                files = status.get("files") or []
                if files and files[0].get("path"):
                    title = Path(files[0]["path"]).name or title
                context.progress(
                    title=title,
                    percent=percent,
                    speed_bytes=speed,
                    eta_seconds=eta,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    status="paused" if state == "paused" else "downloading",
                )
                if state == "complete":
                    paths = [
                        Path(item["path"]) for item in files
                        if item.get("path") and str(item.get("selected", "true")).lower() != "false"
                    ]
                    artifacts = tuple(
                        DownloadArtifact(
                            path=path,
                            size_bytes=path.stat().st_size if path.exists() and path.is_file() else None,
                        )
                        for path in paths
                    )
                    return DownloadResult(self.provider_name, title, artifacts)
                if state in {"error", "removed"}:
                    raise RuntimeError(status.get("errorMessage") or f"aria2 job {state}")
                await asyncio.sleep(0.7)
        finally:
            self._gids.pop(context.job_id, None)

    async def pause(self, job_id: str) -> bool:
        if gid := self._gids.get(job_id):
            await self.client.pause(gid)
            return True
        return False

    async def resume(self, job_id: str) -> bool:
        if gid := self._gids.get(job_id):
            await self.client.resume(gid)
            return True
        return False

    async def cancel(self, job_id: str) -> bool:
        if gid := self._gids.get(job_id):
            await self.client.cancel(gid)
            return True
        return False

    @staticmethod
    def _title(url: str) -> str:
        if url.startswith("magnet:"):
            from urllib.parse import parse_qs
            return parse_qs(urlparse(url).query).get("dn", ["Magnet download"])[0]
        return unquote(Path(urlparse(url).path).name) or "Direct download"


async def inspect_torrent(binary: str, torrent_path: Path) -> list[dict[str, str]]:
    process = await asyncio.create_subprocess_exec(
        binary,
        "--show-files=true",
        str(torrent_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **subprocess_window_options(),
    )
    stdout, _ = await process.communicate()
    if process.returncode:
        raise RuntimeError(stdout.decode(errors="replace").strip() or "Could not inspect torrent")
    files: list[dict[str, str]] = []
    for line in stdout.decode(errors="replace").splitlines():
        match = re.match(r"\s*(\d+)\|(.+)$", line)
        if match:
            files.append({"index": match.group(1), "path": match.group(2).strip()})
    return files
