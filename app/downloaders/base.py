from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.models import DownloadRequest, DownloadResult

ProgressCallback = Callable[..., None]


@dataclass(slots=True)
class DownloadContext:
    job_id: str
    progress: ProgressCallback


class BaseDownloader(ABC):
    provider_name = "base"

    @abstractmethod
    async def can_handle(self, url: str) -> bool: ...

    @abstractmethod
    async def download(
        self, request: DownloadRequest, context: DownloadContext
    ) -> DownloadResult: ...

    async def pause(self, job_id: str) -> bool:
        return False

    async def resume(self, job_id: str) -> bool:
        return False

    async def cancel(self, job_id: str) -> bool:
        return False

    async def skip(self, job_id: str) -> bool:
        return False
