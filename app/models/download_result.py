from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DownloadArtifact:
    path: Path
    media_type: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    provider: str
    title: str
    artifacts: tuple[DownloadArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def output_path(self) -> str | None:
        return str(self.artifacts[0].path) if self.artifacts else None
