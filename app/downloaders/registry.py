from __future__ import annotations

from collections.abc import Iterable

from app.downloaders.base import BaseDownloader
from app.models import DownloadRequest


class DownloaderRegistry:
    def __init__(self, providers: Iterable[BaseDownloader] | None = None) -> None:
        self._providers = list(providers or [])

    @property
    def providers(self) -> tuple[BaseDownloader, ...]:
        return tuple(self._providers)

    def register(self, provider: BaseDownloader) -> None:
        self._providers.append(provider)

    async def resolve(self, request: DownloadRequest) -> BaseDownloader | None:
        aliases = {
            "direct": "aria2",
            "torrent": "aria2",
            "youtube": "yt-dlp",
            "audio": "yt-dlp",
            "gallery": "gallery",
            "spotify": "spotify",
        }
        if request.type != "auto":
            target = aliases[request.type]
            return next((p for p in self._providers if p.provider_name == target), None)

        providers = {provider.provider_name: provider for provider in self._providers}
        spotify = providers.get("spotify")
        aria2 = providers.get("aria2")
        ytdlp = providers.get("yt-dlp")
        gallery = providers.get("gallery")

        if spotify and await spotify.can_handle(request.url):
            return spotify
        if aria2 and self._is_obvious_aria2_source(request.url):
            return aria2
        if ytdlp and await ytdlp.can_handle(request.url):
            return ytdlp
        if gallery and await gallery.can_handle(request.url):
            return gallery
        if aria2 and await aria2.can_handle(request.url):
            return aria2
        return None

    @staticmethod
    def _is_obvious_aria2_source(url: str) -> bool:
        from pathlib import Path
        from urllib.parse import urlparse

        if url.startswith("magnet:"):
            return True
        local = Path(url).expanduser()
        if local.exists() and local.suffix.lower() == ".torrent":
            return True
        parsed = urlparse(url)
        return parsed.scheme == "file" and local.exists()
