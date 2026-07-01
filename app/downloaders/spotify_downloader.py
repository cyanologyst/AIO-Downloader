from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from app.downloaders.base import BaseDownloader, DownloadContext
from app.models import DownloadArtifact, DownloadRequest, DownloadResult
from app.utils.paths import snapshot_files
from app.utils.subprocess_utils import require_executable, subprocess_window_options, terminate_process
from app.utils.runtime import is_bundled_tool

SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?"
    r"(?:track|album|playlist|artist|episode|show)/[A-Za-z0-9]+",
    re.I,
)


class SpotifyDownloader(BaseDownloader):
    provider_name = "spotify"

    def __init__(self, binary: str, ffmpeg: str) -> None:
        self.binary = binary
        self.ffmpeg = ffmpeg
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def can_handle(self, url: str) -> bool:
        return bool(SPOTIFY_RE.search(url))

    async def download(
        self, request: DownloadRequest, context: DownloadContext
    ) -> DownloadResult:
        assert request.destination
        request.destination.mkdir(parents=True, exist_ok=True)
        before = snapshot_files(request.destination)
        command = [
            *self._binary_command(),
            "download",
            request.url,
            "--output",
            str(request.destination / "{artists} - {title}.{output-ext}"),
            "--format",
            request.audio_format,
            "--overwrite",
            "skip",
            "--scan-for-songs",
            "--print-errors",
        ]
        if self.ffmpeg:
            command += ["--ffmpeg", self.ffmpeg]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **subprocess_window_options(),
        )
        self._processes[context.job_id] = process
        lines: list[str] = []
        try:
            assert process.stdout
            async for raw in process.stdout:
                line = raw.decode(errors="replace").strip()
                lines.append(line)
                match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", line)
                if match:
                    context.progress(
                        title="Spotify download",
                        percent=min(100, float(match.group(1))),
                        status="downloading",
                    )
            code = await process.wait()
            if code != 0:
                raise RuntimeError("\n".join(lines[-8:]) or f"spotDL exited with code {code}")
            created = sorted(snapshot_files(request.destination) - before)
            artifacts = tuple(
                DownloadArtifact(path, "audio", path.stat().st_size) for path in created
            )
            title = artifacts[0].path.stem if len(artifacts) == 1 else f"{len(artifacts)} Spotify tracks"
            return DownloadResult(self.provider_name, title, artifacts)
        finally:
            self._processes.pop(context.job_id, None)

    async def cancel(self, job_id: str) -> bool:
        process = self._processes.get(job_id)
        if not process:
            return False
        await terminate_process(process)
        return True

    def _binary_command(self) -> list[str]:
        if is_bundled_tool(self.binary, "spotdl"):
            return [sys.executable, "--aio-tool", "spotdl"]
        return [require_executable(self.binary, "spotDL")]
