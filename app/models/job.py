from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.models.download_request import DownloadRequest


class JobStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Job:
    id: str
    request: DownloadRequest
    status: JobStatus = JobStatus.QUEUED
    provider: str = "pending"
    title: str = "Preparing download"
    percent: float = 0.0
    speed_bytes: int = 0
    eta_seconds: int | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    output_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["request"] = asdict(self.request)
        data["request"]["destination"] = (
            str(self.request.destination) if self.request.destination else None
        )
        data["request"]["selected_files"] = list(self.request.selected_files)
        data["request"]["batch_items"] = list(self.request.batch_items)
        data["request"]["batch_item_titles"] = list(self.request.batch_item_titles)
        data["request"]["batch_item_thumbnails"] = list(
            self.request.batch_item_thumbnails
        )
        for key in ("created_at", "updated_at", "completed_at"):
            value = getattr(self, key)
            data[key] = value.isoformat() if value else None
        return data
