from __future__ import annotations

import asyncio
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.extractor import gen_extractor_classes

from app.downloaders.base import BaseDownloader, DownloadContext
from app.models import DownloadArtifact, DownloadRequest, DownloadResult
from app.services.adult_video_resolver import resolve_adult_video_url
from app.services.hentai_playlist import is_hentai_playlist_url, resolve_hentai_playlist
from app.services.pornhub_model import is_pornhub_model_url, resolve_pornhub_model_playlist
from app.services.video_sites import (
    is_adult_video_url,
    is_hentai_video_url,
    platform_label,
    platform_slug,
    requires_deno_runtime,
    requires_generic_impersonation,
)
from app.utils.paths import snapshot_files
from app.utils.subprocess_utils import require_executable, subprocess_window_options, terminate_process
from app.utils.runtime import is_bundled_tool


class YtdlpDownloader(BaseDownloader):
    provider_name = "yt-dlp"

    def __init__(
        self,
        binary: str,
        ffmpeg: str,
        cookies_file: str = "",
        proxy: str = "",
        deno_bin: str = "",
    ) -> None:
        self.binary = binary
        self.ffmpeg = ffmpeg
        self.cookies_file = cookies_file
        self.proxy = proxy
        self.deno_bin = deno_bin
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._batch_pause_requested: set[str] = set()
        self._batch_skip_requested: set[str] = set()
        self._batch_cancel_requested: set[str] = set()
        self._batch_resume_events: dict[str, asyncio.Event] = {}
        self._progress_samples: dict[str, tuple[float, int]] = {}
        self._probe_cache: dict[str, tuple[float, dict[str, object]]] = {}
        self._probe_lock = threading.Lock()

    async def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        return bool((await self.probe(url))["supported"])

    async def probe(self, url: str) -> dict[str, object]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"supported": False, "extractor": "", "title": ""}
        cached = self._get_cached_probe(url)
        if cached is not None:
            return cached
        if (
            is_adult_video_url(url)
            or is_hentai_video_url(url)
            or is_hentai_playlist_url(url)
            or is_pornhub_model_url(url)
        ):
            result = {
                "supported": True,
                "extractor": platform_label(url),
                "title": "",
                "batch_candidate": bool(
                    is_hentai_playlist_url(url) or is_pornhub_model_url(url)
                ),
            }
            with self._probe_lock:
                self._probe_cache[url] = (time.monotonic(), result)
            return result
        specific = self._specific_extractor(url)
        if self._looks_like_batch_url(url, specific):
            try:
                batch_result = await asyncio.wait_for(
                    asyncio.to_thread(self._probe_flat_batch_sync, url),
                    timeout=12,
                )
                if batch_result:
                    with self._probe_lock:
                        self._probe_cache[url] = (time.monotonic(), batch_result)
                    return batch_result
            except Exception:
                pass
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._probe_sync, url),
                timeout=12,
            )
        except (TimeoutError, asyncio.TimeoutError):
            result = {
                "supported": False,
                "extractor": self._specific_extractor(url),
                "title": "",
                "reason": "yt-dlp probe timed out",
            }
        except Exception:
            result = {
                "supported": False,
                "extractor": self._specific_extractor(url),
                "title": "",
            }
        with self._probe_lock:
            self._probe_cache[url] = (time.monotonic(), result)
        return result

    def _probe_sync(self, url: str) -> dict[str, object]:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 8,
            "retries": 0,
            "extractor_retries": 0,
            "playlistend": 1,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            options["cookiefile"] = self.cookies_file
        if self.proxy:
            options["proxy"] = self.proxy
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            lowered = message.lower()
            return {
                "supported": False,
                "recognized": bool(self._specific_extractor(url)),
                "extractor": self._specific_extractor(url),
                "title": "",
                "requires_auth": any(
                    marker in lowered
                    for marker in (
                        "sign in",
                        "log in",
                        "login required",
                        "cookies",
                        "not a bot",
                        "authentication",
                    )
                ),
                "reason": message,
            }
        if not isinstance(info, dict):
            return {"supported": False, "extractor": "", "title": ""}
        entries = info.get("entries") or []
        supported = bool(
            info.get("formats")
            or info.get("url")
            or info.get("requested_formats")
            or entries
        )
        return {
            "supported": supported,
            "extractor": str(info.get("extractor_key") or info.get("extractor") or ""),
            "title": str(info.get("title") or ""),
            "batch_candidate": bool(
                entries or info.get("_type") in {"playlist", "multi_video"}
            ),
        }

    def _probe_flat_batch_sync(self, url: str) -> dict[str, object] | None:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": 2,
            "socket_timeout": 8,
            "retries": 0,
            "extractor_retries": 0,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            options["cookiefile"] = self.cookies_file
        if self.proxy:
            options["proxy"] = self.proxy
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        entries = [entry for entry in info.get("entries") or [] if entry]
        if len(entries) < 2:
            return None
        return {
            "supported": True,
            "extractor": str(info.get("extractor_key") or info.get("extractor") or ""),
            "title": str(info.get("title") or ""),
            "batch_candidate": True,
            "item_count_hint": len(entries),
        }

    def _get_cached_probe(self, url: str) -> dict[str, object] | None:
        with self._probe_lock:
            cached = self._probe_cache.get(url)
            if not cached:
                return None
            created_at, result = cached
            if time.monotonic() - created_at > 300:
                self._probe_cache.pop(url, None)
                return None
            return result

    @staticmethod
    def _specific_extractor(url: str) -> str:
        for extractor in gen_extractor_classes():
            if extractor.IE_NAME == "generic":
                continue
            try:
                if extractor.suitable(url):
                    return str(extractor.ie_key())
            except Exception:
                continue
        return ""

    @staticmethod
    def _looks_like_batch_url(url: str, extractor: str) -> bool:
        lowered = url.lower()
        extractor_lower = extractor.lower()
        return (
            "list=" in lowered
            or any(token in extractor_lower for token in ("playlist", "channel", "user", "tab"))
            or any(
                token in lowered
                for token in (
                    "/playlist",
                    "/channel/",
                    "/user/",
                    "/model/",
                    "/pornstar/",
                )
            )
        )

    async def download(
        self, request: DownloadRequest, context: DownloadContext
    ) -> DownloadResult:
        assert request.destination
        destination = self._destination(request)
        destination.mkdir(parents=True, exist_ok=True)
        title, urls = await self._resolve_batch(request)
        if not urls:
            raise RuntimeError("No downloadable items were found.")

        all_artifacts: list[DownloadArtifact] = []
        total = len(urls)
        item_states = [
            {
                "index": index,
                "url": url,
                "title": (
                    request.batch_item_titles[index - 1]
                    if index - 1 < len(request.batch_item_titles)
                    else f"Item {index}"
                ),
                "thumbnail_url": (
                    request.batch_item_thumbnails[index - 1]
                    if index - 1 < len(request.batch_item_thumbnails)
                    else ""
                ),
                "status": "pending",
                "error": "",
            }
            for index, url in enumerate(urls, 1)
        ]
        failed_items: list[dict[str, object]] = []
        completed_items = 0
        if total > 1:
            self._batch_cancel_requested.discard(context.job_id)
            self._batch_resume_events[context.job_id] = asyncio.Event()
            self._batch_resume_events[context.job_id].set()
        for index, url in enumerate(urls, start=1):
            if context.job_id in self._batch_cancel_requested:
                self._cleanup_batch(context.job_id)
                raise asyncio.CancelledError
            await self._wait_if_batch_paused(context, title, item_states, completed_items, total)
            item_states[index - 1]["status"] = "downloading"
            cancelled = False
            if total > 1:
                context.progress(
                    title=title,
                    status="downloading",
                    percent=(index - 1) / total * 100,
                    metadata={
                        "batch": True,
                        "current_item": index,
                        "total_items": total,
                        "completed_items": completed_items,
                        "failed_items": failed_items,
                        "items": item_states,
                        "platform": platform_label(url),
                    },
                )
            try:
                result = await self._download_one(
                    request,
                    url,
                    destination,
                    context,
                    index=index,
                    total=total,
                )
                all_artifacts.extend(result.artifacts)
                item_states[index - 1].update(title=result.title, status="completed")
                completed_items += 1
                if total == 1:
                    title = result.title
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if context.job_id in self._batch_cancel_requested:
                    cancelled = True
                    item_states[index - 1].update(status="interrupted", error="")
                    context.progress(
                        title=title,
                        status="cancelled",
                        percent=(index - 1) / total * 100,
                        metadata={
                            "batch": True,
                            "current_item": index,
                            "total_items": total,
                            "completed_items": completed_items,
                            "failed_count": len(failed_items),
                            "failed_items": failed_items,
                            "items": item_states,
                        },
                    )
                    raise asyncio.CancelledError
                skipped = context.job_id in self._batch_skip_requested
                self._batch_skip_requested.discard(context.job_id)
                status = "skipped" if skipped else "failed"
                item_states[index - 1].update(status=status, error=str(exc))
                failed_items.append(
                    {
                        "index": index,
                        "url": url,
                        "title": item_states[index - 1]["title"],
                        "status": status,
                        "error": str(exc),
                    }
                )
                if total == 1 or not request.batch_continue_on_error:
                    self._cleanup_batch(context.job_id)
                    raise
            finally:
                if total > 1 and not cancelled:
                    context.progress(
                        title=title,
                        status="downloading",
                        percent=index / total * 100,
                        metadata={
                            "batch": True,
                            "current_item": min(index + 1, total),
                            "total_items": total,
                            "completed_items": completed_items,
                            "failed_count": len(failed_items),
                            "failed_items": failed_items,
                            "items": item_states,
                        },
                    )
                if cancelled:
                    self._cleanup_batch(context.job_id)
        if not all_artifacts and failed_items:
            self._cleanup_batch(context.job_id)
            raise RuntimeError(f"All {len(failed_items)} batch items failed.")
        result = DownloadResult(
            self.provider_name,
            title if total > 1 else (all_artifacts[0].path.stem if all_artifacts else title),
            tuple(all_artifacts),
            {
                "batch": total > 1,
                "item_count": total,
                "completed_items": completed_items,
                "failed_count": len(failed_items),
                "failed_items": failed_items,
                "items": item_states,
                "batch_manifest_id": request.batch_manifest_id,
                "platform": platform_label(urls[0]),
            },
        )
        self._cleanup_batch(context.job_id)
        return result

    async def _resolve_batch(self, request: DownloadRequest) -> tuple[str, tuple[str, ...]]:
        if request.batch_items:
            return request.batch_title or "Selected batch", request.batch_items
        if is_hentai_playlist_url(request.url):
            playlist = await resolve_hentai_playlist(request.url)
            return playlist.title, playlist.urls
        if is_pornhub_model_url(request.url):
            playlist = await resolve_pornhub_model_playlist(
                request.url, self.cookies_file, self.proxy
            )
            return playlist.title, playlist.urls
        if request.playlist:
            return await asyncio.to_thread(self._extract_playlist, request.url)
        return platform_label(request.url), (request.url,)

    def _extract_playlist(self, url: str) -> tuple[str, tuple[str, ...]]:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "socket_timeout": 45,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            options["cookiefile"] = self.cookies_file
        if self.proxy:
            options["proxy"] = self.proxy
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        entries = info.get("entries") or []
        urls: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = str(entry.get("webpage_url") or entry.get("url") or "").strip()
            if value and value.startswith(("http://", "https://")):
                urls.append(value)
        if not urls and info.get("webpage_url"):
            urls.append(str(info["webpage_url"]))
        return str(info.get("title") or "Playlist download"), tuple(urls)

    async def _download_one(
        self,
        request: DownloadRequest,
        original_url: str,
        destination: Path,
        context: DownloadContext,
        *,
        index: int,
        total: int,
    ) -> DownloadResult:
        before = snapshot_files(destination)
        resolved = await asyncio.to_thread(
            resolve_adult_video_url, original_url
        ) if is_adult_video_url(original_url) else None
        download_url = resolved.url if resolved else original_url
        command = self._command(request, download_url, original_url, resolved.referer if resolved else None)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(destination),
            **subprocess_window_options(),
        )
        self._processes[context.job_id] = process
        self._progress_samples[context.job_id] = (time.monotonic(), 0)
        title = f"Item {index}"
        lines: list[str] = []
        try:
            assert process.stdout
            async for raw in process.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                lines.append(line)
                if line.startswith("AIO_TITLE:"):
                    title = line.removeprefix("AIO_TITLE:").strip()
                elif line.startswith("AIO_PROGRESS:"):
                    values = line.removeprefix("AIO_PROGRESS:").split("|")
                    if len(values) >= 5:
                        item_percent = self._number(values[0])
                        downloaded = int(self._number(values[1]))
                        total_bytes = int(self._number(values[2]))
                        if not total_bytes and item_percent > 0 and downloaded:
                            total_bytes = int(downloaded * 100 / item_percent)
                        speed = int(self._number(values[3]))
                        now = time.monotonic()
                        previous_time, previous_bytes = self._progress_samples.get(
                            context.job_id, (now, downloaded)
                        )
                        if speed <= 0 and downloaded > previous_bytes and now > previous_time:
                            speed = int((downloaded - previous_bytes) / (now - previous_time))
                        self._progress_samples[context.job_id] = (now, downloaded)
                        context.progress(
                            title=title if total == 1 else f"{title} ({index}/{total})",
                            percent=((index - 1) + item_percent / 100) / total * 100,
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes,
                            speed_bytes=speed,
                            eta_seconds=(
                                int(self._number(values[4]))
                                if values[4] not in {"NA", "None", ""}
                                else None
                            ),
                            status="downloading",
                            metadata={
                                "batch": total > 1,
                                "current_item": index,
                                "total_items": total,
                            },
                        )
            code = await process.wait()
            if code != 0:
                raise RuntimeError("\n".join(lines[-10:]) or f"yt-dlp exited with code {code}")
            created = sorted(snapshot_files(destination) - before)
            artifacts = tuple(
                DownloadArtifact(path, self._media_type(path), path.stat().st_size)
                for path in created
                if path.suffix.lower() not in {".part", ".ytdl"}
            )
            return DownloadResult(self.provider_name, title, artifacts)
        finally:
            self._processes.pop(context.job_id, None)
            self._progress_samples.pop(context.job_id, None)

    def _command(
        self,
        request: DownloadRequest,
        download_url: str,
        original_url: str,
        referer: str | None,
    ) -> list[str]:
        command = [
            *self._binary_command(),
            "--newline",
            "--no-colors",
            "--no-playlist",
            "--continue",
            "--part",
            "--concurrent-fragments", "4",
            "--retries", "10",
            "--fragment-retries", "10",
            "--extractor-retries", "3",
            "--file-access-retries", "3",
            "--socket-timeout", "30",
            "--progress-delta", "0.4",
            "--print", "before_dl:AIO_TITLE:%(title)s",
            "--progress",
            "--progress-template",
            "download:AIO_PROGRESS:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "-o", "%(title).180B [%(id)s].%(ext)s",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36",
        ]
        audio_only = request.type == "audio" or request.quality == "audio"
        if audio_only:
            require_executable(self.ffmpeg, "ffmpeg")
            command += ["-x", "--audio-format", request.audio_format, "--audio-quality", "0"]
        else:
            height = request.quality.removesuffix("p") if request.quality != "best" else None
            command += [
                "-f",
                f"bv*[height<={height}]+ba/b[height<={height}]" if height else "bv*+ba/b",
                "--merge-output-format",
                "mp4",
            ]
        if self.cookies_file and Path(self.cookies_file).exists():
            command += ["--cookies", self.cookies_file]
        if self.proxy:
            command += ["--proxy", self.proxy]
        if requires_generic_impersonation(original_url):
            command += ["--impersonate", "chrome"]
        if referer:
            command += ["--referer", referer]
        if requires_deno_runtime(original_url):
            deno = self.deno_bin or shutil.which("deno")
            if not deno:
                raise RuntimeError("Hanime requires Deno. Install it or set DENO_BIN.")
            command += ["--js-runtimes", f"deno:{deno}"]
        command.append(download_url)
        return command

    def _binary_command(self) -> list[str]:
        if is_bundled_tool(self.binary, "yt-dlp"):
            return [sys.executable, "--aio-tool", "yt-dlp"]
        return [require_executable(self.binary, "yt-dlp")]

    def _destination(self, request: DownloadRequest) -> Path:
        assert request.destination
        if is_hentai_video_url(request.url):
            return request.destination / "Hentai" / platform_slug(request.url)
        if is_adult_video_url(request.url):
            return request.destination / "Adult" / platform_slug(request.url)
        return request.destination

    async def cancel(self, job_id: str) -> bool:
        process = self._processes.get(job_id)
        event = self._batch_resume_events.get(job_id)
        if event:
            self._batch_cancel_requested.add(job_id)
        if event:
            event.set()
        if process:
            await terminate_process(process)
            return True
        return bool(event)

    async def pause(self, job_id: str) -> bool:
        if job_id not in self._batch_resume_events:
            return False
        self._batch_pause_requested.add(job_id)
        return True

    async def resume(self, job_id: str) -> bool:
        event = self._batch_resume_events.get(job_id)
        if not event:
            return False
        self._batch_pause_requested.discard(job_id)
        event.set()
        return True

    async def skip(self, job_id: str) -> bool:
        process = self._processes.get(job_id)
        if not process or job_id not in self._batch_resume_events:
            return False
        self._batch_skip_requested.add(job_id)
        await terminate_process(process)
        return True

    async def _wait_if_batch_paused(
        self,
        context: DownloadContext,
        title: str,
        item_states: list[dict[str, object]],
        completed_items: int,
        total: int,
    ) -> None:
        if context.job_id not in self._batch_pause_requested:
            return
        event = self._batch_resume_events.get(context.job_id)
        if not event:
            return
        event.clear()
        context.progress(
            title=title,
            status="paused",
            metadata={
                "batch": True,
                "pause_after_current": True,
                "completed_items": completed_items,
                "total_items": total,
                "items": item_states,
            },
        )
        await event.wait()
        context.progress(
            title=title,
            status="downloading",
            metadata={"batch": True, "pause_after_current": False},
        )

    def _cleanup_batch(self, job_id: str) -> None:
        self._batch_pause_requested.discard(job_id)
        self._batch_skip_requested.discard(job_id)
        self._batch_cancel_requested.discard(job_id)
        self._batch_resume_events.pop(job_id, None)

    @staticmethod
    def _number(value: str) -> float:
        cleaned = re.sub(r"[^\d.]", "", value or "")
        return float(cleaned or 0)

    @staticmethod
    def _media_type(path: Path) -> str:
        return "audio" if path.suffix.lower() in {".mp3", ".m4a", ".opus", ".flac"} else "video"
