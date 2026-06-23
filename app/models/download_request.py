from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_TYPES = {"auto", "direct", "torrent", "youtube", "audio", "gallery", "spotify"}
VALID_QUALITIES = {"best", "1080p", "720p", "480p", "audio"}
VALID_AUDIO_FORMATS = {"mp3", "m4a", "opus"}


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    url: str
    type: str = "auto"
    quality: str = "best"
    audio_format: str = "mp3"
    convert_to_pdf: bool = False
    output_subdir: str | None = None
    playlist: bool = False
    selected_files: tuple[str, ...] = ()
    batch_manifest_id: str | None = None
    batch_title: str | None = None
    batch_items: tuple[str, ...] = ()
    batch_item_titles: tuple[str, ...] = ()
    batch_item_thumbnails: tuple[str, ...] = ()
    batch_continue_on_error: bool = True
    destination: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadRequest":
        url = str(data.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        request_type = str(data.get("type", "auto")).lower()
        quality = str(data.get("quality", "best")).lower()
        audio_format = str(data.get("audio_format", "mp3")).lower()
        if request_type not in VALID_TYPES:
            raise ValueError(f"invalid download type: {request_type}")
        if quality not in VALID_QUALITIES:
            raise ValueError(f"invalid quality: {quality}")
        if audio_format not in VALID_AUDIO_FORMATS:
            raise ValueError(f"invalid audio format: {audio_format}")
        return cls(
            url=url,
            type=request_type,
            quality=quality,
            audio_format=audio_format,
            convert_to_pdf=bool(data.get("convert_to_pdf", False)),
            output_subdir=str(data["output_subdir"]).strip() if data.get("output_subdir") else None,
            playlist=bool(data.get("playlist", False)),
            selected_files=tuple(
                str(value) for value in (data.get("selected_files") or []) if str(value).isdigit()
            ),
            batch_manifest_id=(
                str(data["batch_manifest_id"]).strip()
                if data.get("batch_manifest_id")
                else None
            ),
            batch_title=str(data["batch_title"]).strip() if data.get("batch_title") else None,
            batch_items=tuple(
                str(value).strip()
                for value in (data.get("batch_items") or [])
                if str(value).strip().startswith(("http://", "https://"))
            ),
            batch_item_titles=tuple(
                str(value).strip()[:240]
                for value in (data.get("batch_item_titles") or [])
                if str(value).strip()
            ),
            batch_item_thumbnails=tuple(
                (
                    str(value).strip()
                    if str(value).strip().startswith(("http://", "https://", "/"))
                    else ""
                )
                for value in (data.get("batch_item_thumbnails") or [])
            ),
            batch_continue_on_error=bool(data.get("batch_continue_on_error", True)),
        )
