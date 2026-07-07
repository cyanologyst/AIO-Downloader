from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.downloaders.base import BaseDownloader, DownloadContext
from app.models import DownloadArtifact, DownloadRequest, DownloadResult
from app.utils.paths import snapshot_files
from app.utils.subprocess_utils import require_executable, subprocess_window_options, terminate_process_any
from app.utils.runtime import is_bundled_tool
from app.services.browser_cookies import ensure_ytdlp_cookie_file
from app.services.spotify_public_fallback import (
    SpotifyFallbackError,
    SpotifyPublicAudioDownloader,
    SpotifyPublicClient,
    cap_filename,
    sanitize_filename,
    write_audio_tags,
)

logger = logging.getLogger(__name__)

SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?"
    r"(?:track|album|playlist|artist|episode|show)/[A-Za-z0-9]+",
    re.I,
)


class SpotifyDownloader(BaseDownloader):
    provider_name = "spotify"

    def __init__(self, binary: str, ffmpeg: str, cookies_file: str = "") -> None:
        self.binary = binary
        self.ffmpeg = ffmpeg
        self.cookies_file = cookies_file
        self._processes: dict[str, object] = {}
        self._fallback_cancelled: set[str] = set()

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
            "--print-errors",
            "--headless",
            "--threads",
            "1",
            "--audio",
            "youtube",
        ]
        if self.ffmpeg:
            command += ["--ffmpeg", self.ffmpeg]
        cookie_file = ensure_ytdlp_cookie_file(self.cookies_file)
        if cookie_file:
            command += ["--cookie-file", cookie_file]
        try:
            await asyncio.to_thread(self._run_command_sync, command, context, request.playlist)
        except RuntimeError as exc:
            if not self._should_try_public_fallback(str(exc)):
                raise
            logger.warning("spotDL failed; trying Spotify public fallback: %s", exc)
            context.progress(
                title="spotDL auth failed — trying public Spotify fallback",
                percent=0,
                status="downloading",
            )
            return await asyncio.to_thread(
                self._download_public_fallback_sync,
                request,
                context,
                str(exc),
            )
        created = sorted(snapshot_files(request.destination) - before)
        artifacts = tuple(
            DownloadArtifact(path, "audio", path.stat().st_size) for path in created
        )
        title = artifacts[0].path.stem if len(artifacts) == 1 else f"{len(artifacts)} Spotify tracks"
        return DownloadResult(self.provider_name, title, artifacts)

    @staticmethod
    def _should_try_public_fallback(message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in (
                "could not get client token",
                "could not get session auth tokens",
                "rate/request limit",
                "retry will occur after",
                "invalid_client",
                "failed to get client",
                "spotify",
            )
        )

    def _download_public_fallback_sync(
        self,
        request: DownloadRequest,
        context: DownloadContext,
        original_error: str,
    ) -> DownloadResult:
        assert request.destination
        cookie_file = ensure_ytdlp_cookie_file(self.cookies_file)
        client = SpotifyPublicClient()
        try:
            collection = client.resolve(request.url)
            if not collection.tracks:
                raise SpotifyFallbackError("Spotify public fallback found no tracks.")
            target_dir = request.destination
            if collection.kind in {"playlist", "album"}:
                target_dir = request.destination / sanitize_filename(collection.title, "Spotify")
                target_dir.mkdir(parents=True, exist_ok=True)
            audio = SpotifyPublicAudioDownloader(ffmpeg=self.ffmpeg, cookies_file=cookie_file)
            artifacts: list[DownloadArtifact] = []
            total = len(collection.tracks)
            for index, track in enumerate(collection.tracks, start=1):
                if context.job_id in self._fallback_cancelled:
                    raise SpotifyFallbackError("Spotify fallback cancelled.")
                if track.id and (not track.cover_url or not track.release_date or not track.album):
                    try:
                        enriched = client.get_track(track.id)
                        track.cover_url = track.cover_url or enriched.cover_url or collection.cover_url
                        track.release_date = track.release_date or enriched.release_date
                        track.album = track.album or enriched.album
                    except SpotifyFallbackError:
                        track.cover_url = track.cover_url or collection.cover_url
                else:
                    track.cover_url = track.cover_url or collection.cover_url
                title = track.title or f"Track {index}"
                artists = track.artists or "Unknown Artist"
                context.progress(
                    title=f"Spotify fallback {index}/{total}: {title}",
                    percent=((index - 1) / total) * 100,
                    status="downloading",
                )
                filename = cap_filename(
                    f"{index:02d}. {sanitize_filename(title)} - {sanitize_filename(artists)}.{request.audio_format}"
                    if total > 1
                    else f"{sanitize_filename(title)} - {sanitize_filename(artists)}.{request.audio_format}"
                )
                destination = target_dir / filename
                if destination.exists():
                    final_path = destination
                else:
                    def hook(info: dict[str, object], *, base_percent: float = (index - 1) / total * 100) -> None:
                        if context.job_id in self._fallback_cancelled:
                            raise SpotifyFallbackError("Spotify fallback cancelled.")
                        if info.get("status") == "downloading":
                            downloaded = info.get("downloaded_bytes") or 0
                            total_bytes = info.get("total_bytes") or info.get("total_bytes_estimate") or 0
                            if total_bytes:
                                item_percent = min(100.0, float(downloaded) / float(total_bytes) * 100)
                                context.progress(
                                    title=f"Spotify fallback {index}/{total}: {title}",
                                    percent=base_percent + (item_percent / total * 0.9),
                                    status="downloading",
                                    downloaded_bytes=int(downloaded),
                                    total_bytes=int(total_bytes),
                                    speed_bytes=int(info.get("speed") or 0),
                                    eta_seconds=(
                                        int(info["eta"])
                                        if info.get("eta") is not None
                                        else None
                                    ),
                                )

                    final_path = audio.download_track(
                        track,
                        destination,
                        request.audio_format,
                        progress_hook=hook,
                    )
                    write_audio_tags(final_path, track)
                artifacts.append(
                    DownloadArtifact(final_path, "audio", final_path.stat().st_size)
                )
                context.progress(
                    title=f"Spotify fallback {index}/{total}: {title}",
                    percent=(index / total) * 100,
                    status="downloading",
                )
            title = (
                artifacts[0].path.stem
                if len(artifacts) == 1
                else f"{len(artifacts)} Spotify tracks"
            )
            return DownloadResult(
                self.provider_name,
                title,
                tuple(artifacts),
                metadata={
                    "fallback": "spotify-public",
                    "collection": collection.title,
                    "spotdl_error": original_error[-500:],
                },
            )
        finally:
            self._fallback_cancelled.discard(context.job_id)
            client.close()

    def _run_command_sync(
        self, command: list[str], context: DownloadContext, is_playlist: bool = False
    ) -> None:
        env = os.environ.copy()
        patch_dir = str((Path(__file__).resolve().parents[1] / "runtime_patches").resolve())
        project_dir = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in [patch_dir, project_dir, existing_pythonpath] if item
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **subprocess_window_options(),
        )
        self._processes[context.job_id] = process
        lines: list[str] = []
        try:
            context.progress(
                title="Resolving Spotify playlist" if is_playlist else "Resolving Spotify track",
                percent=0,
                status="downloading",
            )
            assert process.stdout
            output_queue: queue.Queue[str | None] = queue.Queue()

            def read_output() -> None:
                try:
                    for raw in iter(process.stdout.readline, b""):
                        output_queue.put(raw.decode(errors="replace").strip())
                finally:
                    output_queue.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            last_output_at = time.monotonic()
            idle_timeout = 180 if is_playlist else 90
            stream_closed = False
            while not stream_closed:
                if process.poll() is not None:
                    # Drain anything the reader already captured before checking the exit code.
                    stream_closed = True
                try:
                    line = output_queue.get(timeout=0.5)
                except queue.Empty:
                    if time.monotonic() - last_output_at > idle_timeout and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        raise RuntimeError(
                            "spotDL stalled while resolving Spotify audio. This usually means "
                            "YouTube/YT Music is blocked or timing out on this network."
                        )
                    continue
                if line is None:
                    stream_closed = True
                    continue
                lines.append(line)
                if line:
                    last_output_at = time.monotonic()
                    context.progress(
                        title="Spotify download",
                        percent=None,
                        status="downloading",
                    )
                match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", line)
                if match:
                    context.progress(
                        title="Spotify download",
                        percent=min(100, float(match.group(1))),
                        status="downloading",
                    )
            code = process.wait()
            if code != 0:
                raise RuntimeError("\n".join(lines[-8:]) or f"spotDL exited with code {code}")
        finally:
            self._processes.pop(context.job_id, None)

    async def cancel(self, job_id: str) -> bool:
        process = self._processes.get(job_id)
        if not process:
            self._fallback_cancelled.add(job_id)
            return True
        await terminate_process_any(process)
        return True

    def _binary_command(self) -> list[str]:
        if is_bundled_tool(self.binary, "spotdl"):
            return [sys.executable, "--aio-tool", "spotdl"]
        return [require_executable(self.binary, "spotDL")]
