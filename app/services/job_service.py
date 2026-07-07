from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import SettingsStore
from app.downloaders.base import BaseDownloader, DownloadContext
from app.downloaders.registry import DownloaderRegistry
from app.models import DownloadRequest, Job, JobStatus
from app.services.queue_service import QueueService
from app.utils.paths import safe_subdir

logger = logging.getLogger(__name__)


def _new_event_loop() -> asyncio.AbstractEventLoop:
    """Create a Proactor-compatible loop, retrying a rare Windows socketpair race.

    Windows' default Proactor loop is required for async subprocess support. On
    some systems, loop construction can intermittently raise
    ``ConnectionError("Unexpected peer connection")`` while creating the
    internal wakeup socket. Retrying keeps the desktop app launchable without
    falling back to SelectorEventLoop, which would break downloader processes.
    """

    last_error: BaseException | None = None
    for attempt in range(5):
        try:
            return asyncio.new_event_loop()
        except ConnectionError as exc:
            last_error = exc
            time.sleep(0.08 * (attempt + 1))
    if last_error:
        raise last_error
    return asyncio.new_event_loop()


class JobService:
    def __init__(self, registry: DownloaderRegistry, settings: SettingsStore) -> None:
        self.registry = registry
        self.settings = settings
        self.jobs: dict[str, Job] = {}
        self._providers: dict[str, BaseDownloader] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._events = threading.Condition(self._lock)
        self._event_version = 0
        self._loop = _new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="download-loop", daemon=True)
        self._thread.start()
        self.queue = QueueService(settings.get().max_concurrent_downloads)
        self._history_path = settings.path.parent / "jobs.json"
        self._load_history()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self, request: DownloadRequest) -> Job:
        settings = self.settings.get()
        destination = safe_subdir(settings.download_path, request.output_subdir)
        destination.mkdir(parents=True, exist_ok=True)
        request = replace(request, destination=destination)
        job = Job(
            id=uuid.uuid4().hex[:12],
            request=request,
            title=self._initial_title(request.url),
            metadata=(
                {
                    "batch": True,
                    "batch_manifest_id": request.batch_manifest_id,
                    "total_items": len(request.batch_items),
                    "completed_items": 0,
                    "failed_count": 0,
                    "thumbnail_url": request.thumbnail_url,
                    "items": [
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
                        for index, url in enumerate(request.batch_items, 1)
                    ],
                }
                if request.batch_items
                else {}
            ),
        )
        with self._lock:
            self.jobs[job.id] = job
            self._notify_locked()
        asyncio.run_coroutine_threadsafe(self._schedule(job.id), self._loop)
        return job

    async def _schedule(self, job_id: str) -> None:
        task = asyncio.current_task()
        if task:
            self._tasks[job_id] = task
        await self.queue.acquire()
        try:
            await self._run(job_id)
        finally:
            await self.queue.release()
            self._tasks.pop(job_id, None)

    async def _run(self, job_id: str) -> None:
        job = self._get(job_id)
        if not job or job_id in self._cancelled:
            return
        self._update(job_id, status=JobStatus.STARTING)
        provider = await self.registry.resolve(job.request)
        if provider is None:
            self._finish(job_id, JobStatus.FAILED, error="Unsupported URL or download type")
            return
        self._providers[job_id] = provider
        self._update(job_id, provider=provider.provider_name)
        try:
            result = await provider.download(
                job.request,
                DownloadContext(
                    job_id=job_id,
                    progress=lambda **values: self._progress(job_id, **values),
                ),
            )
            if job_id in self._cancelled:
                self._finish(job_id, JobStatus.CANCELLED)
                return
            total = sum(artifact.size_bytes or 0 for artifact in result.artifacts)
            self._finish(
                job_id,
                JobStatus.COMPLETED,
                title=result.title,
                percent=100.0,
                downloaded_bytes=total,
                total_bytes=total,
                output_path=result.output_path,
                metadata=result.metadata,
            )
        except asyncio.CancelledError:
            self._finish(job_id, JobStatus.CANCELLED)
        except Exception as exc:
            if job_id in self._cancelled:
                self._finish(job_id, JobStatus.CANCELLED)
            else:
                error = str(exc).encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                try:
                    self._finish(job_id, JobStatus.FAILED, error=error)
                finally:
                    logger.exception("Download job %s failed", job_id)
        finally:
            self._providers.pop(job_id, None)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.to_dict() for job in jobs]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self._get(job_id)
        return job.to_dict() if job else None

    def pause(self, job_id: str) -> bool:
        return self._control(job_id, "pause")

    def resume(self, job_id: str) -> bool:
        return self._control(job_id, "resume")

    def resume_batch(self, job_id: str) -> Job | None:
        job = self._get(job_id)
        if not job or not job.metadata.get("batch"):
            return None
        items = [
            item
            for item in (job.metadata.get("items") or [])
            if isinstance(item, dict)
            and item.get("status") not in {"completed", "skipped"}
            and str(item.get("url") or "").startswith(("http://", "https://"))
        ]
        if not items:
            return None
        request = replace(
            job.request,
            batch_items=tuple(str(item["url"]) for item in items),
            batch_item_titles=tuple(
                str(item.get("title") or f"Item {index}")
                for index, item in enumerate(items, 1)
            ),
            batch_item_thumbnails=tuple(
                str(item.get("thumbnail_url") or "") for item in items
            ),
            batch_title=f"Resume — {job.request.batch_title or job.title}",
        )
        resumed = self.start(request)
        with self._lock:
            job.metadata = {**job.metadata, "resumed_by": resumed.id}
            job.touch()
            self._notify_locked()
        return resumed

    def cancel(self, job_id: str) -> bool:
        job = self._get(job_id)
        if not job or job.status in {
            JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED
        }:
            return False
        self._cancelled.add(job_id)
        provider = self._providers.get(job_id)
        if provider:
            future = asyncio.run_coroutine_threadsafe(provider.cancel(job_id), self._loop)
            try:
                supported = bool(future.result(timeout=8))
            except Exception:
                supported = False
        else:
            supported = True
            task = self._tasks.get(job_id)
            if task:
                self._loop.call_soon_threadsafe(task.cancel)
        self._finish(job_id, JobStatus.CANCELLED)
        return supported

    def skip(self, job_id: str) -> bool:
        return self._control(job_id, "skip")

    def retry_failed(self, job_id: str) -> Job | None:
        job = self._get(job_id)
        if not job:
            return None
        failed = job.metadata.get("failed_items") or []
        urls = tuple(
            str(item.get("url") or "")
            for item in failed
            if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://"))
        )
        if not urls:
            return None
        request = replace(
            job.request,
            batch_items=urls,
            batch_item_titles=tuple(
                str(item.get("title") or f"Item {index}")
                for index, item in enumerate(failed, 1)
                if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://"))
            ),
            batch_item_thumbnails=tuple(
                str(item.get("thumbnail_url") or "")
                for item in failed
                if isinstance(item, dict)
                and str(item.get("url") or "").startswith(("http://", "https://"))
            ),
            batch_title=f"Retry failed — {job.title}",
        )
        return self.start(request)

    def wait_for_events(self, version: int, timeout: float = 15.0) -> tuple[int, list[dict[str, Any]]]:
        with self._events:
            if self._event_version <= version:
                self._events.wait(timeout)
            return self._event_version, self.list_jobs()

    def update_limit(self, limit: int) -> None:
        asyncio.run_coroutine_threadsafe(self.queue.set_limit(limit), self._loop)

    def clear_finished(self) -> int:
        with self._lock:
            finished = [
                job_id for job_id, job in self.jobs.items()
                if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
            ]
            for job_id in finished:
                self.jobs.pop(job_id, None)
                self._cancelled.discard(job_id)
            if finished:
                self._notify_locked()
            return len(finished)

    def delete(self, job_id: str) -> bool:
        job = self._get(job_id)
        if not job:
            return False
        if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            self.cancel(job_id)
        with self._lock:
            removed = self.jobs.pop(job_id, None)
            self._cancelled.discard(job_id)
            self._providers.pop(job_id, None)
            self._tasks.pop(job_id, None)
            if removed:
                self._notify_locked()
            return bool(removed)

    def _control(self, job_id: str, action: str) -> bool:
        provider = self._providers.get(job_id)
        if not provider:
            return False
        future = asyncio.run_coroutine_threadsafe(getattr(provider, action)(job_id), self._loop)
        try:
            supported = bool(future.result(timeout=8))
        except Exception:
            logger.exception("Job control failed: %s %s", action, job_id)
            return False
        if supported and action != "skip":
            job = self._get(job_id)
            is_batch_pause = (
                action == "pause"
                and bool(job and job.metadata.get("batch"))
            )
            self._update(
                job_id,
                status=(
                    job.status
                    if is_batch_pause and job
                    else JobStatus.PAUSED if action == "pause" else JobStatus.DOWNLOADING
                ),
                metadata=(
                    {**(job.metadata if job else {}), "pause_after_current": True}
                    if is_batch_pause
                    else job.metadata if job else {}
                ),
            )
        return supported

    def _progress(self, job_id: str, **values: Any) -> None:
        status = values.pop("status", "downloading")
        metadata = values.pop("metadata", None)
        if metadata:
            job = self._get(job_id)
            values["metadata"] = {**(job.metadata if job else {}), **metadata}
        values["status"] = JobStatus(status)
        self._update(job_id, **values)

    def _finish(self, job_id: str, status: JobStatus, **values: Any) -> None:
        values.update(
            status=status,
            speed_bytes=0,
            eta_seconds=None,
            completed_at=datetime.now(timezone.utc),
        )
        self._update(job_id, **values)

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            for key, value in values.items():
                setattr(job, key, value)
            job.touch()
            self._notify_locked()

    def _get(self, job_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(job_id)

    def _notify_locked(self) -> None:
        self._persist_locked()
        self._event_version += 1
        self._events.notify_all()

    def _persist_locked(self) -> None:
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._history_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps([job.to_dict() for job in self.jobs.values()], indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._history_path)
        except OSError:
            logger.exception("Unable to persist download history")

    def _load_history(self) -> None:
        if not self._history_path.exists():
            return
        try:
            records = json.loads(self._history_path.read_text(encoding="utf-8"))
            for data in records if isinstance(records, list) else []:
                if not isinstance(data, dict):
                    continue
                request = DownloadRequest.from_dict(data.get("request") or {})
                status = JobStatus(str(data.get("status") or JobStatus.FAILED))
                metadata = dict(data.get("metadata") or {})
                if status in {
                    JobStatus.QUEUED,
                    JobStatus.STARTING,
                    JobStatus.DOWNLOADING,
                    JobStatus.PAUSED,
                }:
                    status = JobStatus.PAUSED if metadata.get("batch") else JobStatus.FAILED
                    metadata["interrupted_by_restart"] = True
                job = Job(
                    id=str(data["id"]),
                    request=request,
                    status=status,
                    provider=str(data.get("provider") or "pending"),
                    title=str(data.get("title") or "Saved download"),
                    percent=float(data.get("percent") or 0),
                    speed_bytes=0,
                    eta_seconds=None,
                    downloaded_bytes=int(data.get("downloaded_bytes") or 0),
                    total_bytes=int(data.get("total_bytes") or 0),
                    output_path=data.get("output_path"),
                    error=data.get("error"),
                    metadata=metadata,
                    created_at=self._parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
                    updated_at=self._parse_datetime(data.get("updated_at")) or datetime.now(timezone.utc),
                    completed_at=self._parse_datetime(data.get("completed_at")),
                )
                self.jobs[job.id] = job
            with self._lock:
                self._persist_locked()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            logger.exception("Unable to load download history")

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    @staticmethod
    def _initial_title(url: str) -> str:
        if url.startswith("magnet:"):
            return "Magnet download"
        return url.rsplit("/", 1)[-1][:120] or "New download"
