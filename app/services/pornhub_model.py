from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yt_dlp

PROFILE_RE = re.compile(
    r"^/(?P<kind>model|pornstar)/(?P<slug>[A-Za-z0-9_-]+)(?:/videos)?/?$",
    re.I,
)


@dataclass(frozen=True, slots=True)
class PornHubModelPlaylist:
    title: str
    slug: str
    urls: tuple[str, ...]
    titles: tuple[str, ...]


def is_pornhub_model_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return (host == "pornhub.com" or host.endswith(".pornhub.com")) and bool(
        PROFILE_RE.fullmatch(parsed.path.rstrip("/") + "/")
    )


async def resolve_pornhub_model_playlist(
    url: str, cookies_file: str = "", proxy: str = ""
) -> PornHubModelPlaylist:
    return await asyncio.to_thread(_resolve, url, cookies_file, proxy)


def _resolve(url: str, cookies_file: str, proxy: str) -> PornHubModelPlaylist:
    if not is_pornhub_model_url(url):
        raise ValueError("Unsupported PornHub profile URL")
    options: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "socket_timeout": 45,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookies_file and Path(cookies_file).exists():
        options["cookiefile"] = cookies_file
    if proxy:
        options["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(str(exc)) from exc
    resolved = [
        (value, str(entry.get("title") or f"Video {index}"))
        for index, entry in enumerate(info.get("entries") or [], 1)
        if isinstance(entry, dict)
        and (value := _entry_url(url, entry))
    ]
    urls = tuple(value for value, _title in resolved)
    titles = tuple(title for _value, title in resolved)
    if not urls:
        raise RuntimeError("No public videos found on this PornHub profile page.")
    match = PROFILE_RE.fullmatch(urlparse(url).path.rstrip("/") + "/")
    slug = match.group("slug") if match else "profile"
    kind = match.group("kind").lower() if match else "profile"
    return PornHubModelPlaylist(
        str(info.get("title") or f"PornHub {kind} {slug}"),
        slug,
        urls,
        titles,
    )


def _entry_url(base: str, entry: object) -> str | None:
    if not isinstance(entry, dict) or not entry.get("url"):
        return None
    value = urljoin(base, str(entry["url"]))
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return value if (host == "pornhub.com" or host.endswith(".pornhub.com")) and "view_video.php" in parsed.path else None
