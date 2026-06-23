from __future__ import annotations

import asyncio
import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yt_dlp

from app.services.hentai_playlist import is_hentai_playlist_url, resolve_hentai_playlist
from app.services.pornhub_model import is_pornhub_model_url, resolve_pornhub_model_playlist
from app.services.video_sites import platform_label


@dataclass(frozen=True, slots=True)
class BatchItem:
    index: int
    url: str
    title: str
    duration_seconds: int | None = None
    size_bytes: int | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True, slots=True)
class BatchManifest:
    id: str
    source_url: str
    title: str
    provider: str
    items: tuple[BatchItem, ...]
    created_at: str
    free_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "items": [asdict(item) for item in self.items],
            "item_count": len(self.items),
            "estimated_size_bytes": sum(item.size_bytes or 0 for item in self.items),
        }


class BatchManifestService:
    def __init__(
        self,
        path: Path,
        *,
        download_dir: Path,
        cookies_file: str = "",
        proxy: str = "",
    ) -> None:
        self.path = path
        self.download_dir = download_dir
        self.cookies_file = cookies_file
        self.proxy = proxy
        self._lock = threading.RLock()
        self.path.mkdir(parents=True, exist_ok=True)

    async def inspect(self, url: str) -> BatchManifest:
        if is_hentai_playlist_url(url):
            playlist = await resolve_hentai_playlist(url)
            items = tuple(
                BatchItem(
                    index,
                    item_url,
                    (
                        playlist.titles[index - 1]
                        if index - 1 < len(playlist.titles)
                        else self._url_title(item_url)
                    ),
                    (
                        playlist.durations[index - 1]
                        if index - 1 < len(playlist.durations)
                        else None
                    ),
                    None,
                    (
                        playlist.thumbnails[index - 1]
                        if index - 1 < len(playlist.thumbnails)
                        else None
                    ),
                )
                for index, item_url in enumerate(playlist.urls, 1)
            )
            title, provider = playlist.title, playlist.site
        elif is_pornhub_model_url(url):
            playlist = await resolve_pornhub_model_playlist(
                url, self.cookies_file, self.proxy
            )
            items = tuple(
                BatchItem(
                    index,
                    item_url,
                    playlist.titles[index - 1]
                    if index - 1 < len(playlist.titles)
                    else f"Video {index}",
                )
                for index, item_url in enumerate(playlist.urls, 1)
            )
            title, provider = playlist.title, "PornHub"
        else:
            title, provider, items = await asyncio.to_thread(self._inspect_ytdlp, url)
        if len(items) < 2:
            raise ValueError("This URL did not resolve to a multi-item playlist or profile.")
        manifest = BatchManifest(
            id=uuid.uuid4().hex[:12],
            source_url=url,
            title=title,
            provider=provider,
            items=items,
            created_at=datetime.now(timezone.utc).isoformat(),
            free_bytes=self._free_bytes(),
        )
        self.save(manifest)
        return manifest

    def get(self, manifest_id: str) -> BatchManifest | None:
        path = self.path / f"{manifest_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BatchManifest(
                id=str(data["id"]),
                source_url=str(data["source_url"]),
                title=str(data["title"]),
                provider=str(data["provider"]),
                items=tuple(BatchItem(**item) for item in data.get("items") or []),
                created_at=str(data["created_at"]),
                free_bytes=data.get("free_bytes"),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def save(self, manifest: BatchManifest) -> None:
        with self._lock:
            self.path.mkdir(parents=True, exist_ok=True)
            (self.path / f"{manifest.id}.json").write_text(
                json.dumps(manifest.to_dict(), indent=2),
                encoding="utf-8",
            )

    def select(self, manifest_id: str, indexes: list[int]) -> tuple[BatchManifest, tuple[BatchItem, ...]]:
        manifest = self.get(manifest_id)
        if not manifest:
            raise ValueError("Batch manifest was not found.")
        wanted = set(indexes)
        selected = tuple(item for item in manifest.items if item.index in wanted)
        if not selected:
            raise ValueError("Select at least one batch item.")
        return manifest, selected

    def _inspect_ytdlp(self, url: str) -> tuple[str, str, tuple[BatchItem, ...]]:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "lazy_playlist": False,
            "socket_timeout": 30,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            options["cookiefile"] = self.cookies_file
        if self.proxy:
            options["proxy"] = self.proxy
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False) or {}
        except yt_dlp.utils.DownloadError as exc:
            raise RuntimeError(str(exc)) from exc
        raw_entries = info.get("entries") or []
        items: list[BatchItem] = []
        for index, entry in enumerate(raw_entries, 1):
            if not isinstance(entry, dict):
                continue
            item_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
            if not item_url.startswith(("http://", "https://")):
                continue
            size = entry.get("filesize") or entry.get("filesize_approx")
            duration = entry.get("duration")
            items.append(
                BatchItem(
                    index=index,
                    url=item_url,
                    title=str(entry.get("title") or f"Item {index}"),
                    duration_seconds=int(duration) if duration else None,
                    size_bytes=int(size) if size else None,
                    thumbnail_url=str(entry.get("thumbnail") or "") or None,
                )
            )
        return (
            str(info.get("title") or "Batch download"),
            str(info.get("extractor_key") or platform_label(url)),
            tuple(items),
        )

    def _free_bytes(self) -> int | None:
        try:
            return shutil.disk_usage(self.download_dir).free
        except OSError:
            return None

    @staticmethod
    def _url_title(url: str) -> str:
        value = url.rstrip("/").rsplit("/", 1)[-1]
        return value.replace("-", " ").title() or "Batch item"
