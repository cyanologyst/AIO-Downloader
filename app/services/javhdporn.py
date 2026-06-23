from __future__ import annotations

import re
from html import unescape
from urllib.parse import urldefrag, urljoin, urlparse

MEDIA_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.(?:mp4|m3u8)(?:\?[^\s\"'<>]*)?", re.I)
VIDEO_PAGE_RE = re.compile(
    r"https?://(?:www\.)?javhdporn\.net/(?:v\d+/)?video/[^\"'<> ]+/?", re.I
)
SLUG_CODE_RE = re.compile(r"([a-z]{2,10})[-_]?0*(\d{2,6})", re.I)


def is_javhdporn_url(url: str) -> bool:
    value = (urlparse(url.strip()).hostname or "").lower()
    return value == "javhdporn.net" or value.endswith(".javhdporn.net")


def resolve_javhdporn_video_url(url: str, timeout: float = 30.0) -> str:
    if not is_javhdporn_url(url):
        return url
    try:
        from curl_cffi import requests
    except ImportError as exc:
        raise RuntimeError("JavHDPorn support requires curl-cffi.") from exc
    session = requests.Session(impersonate="chrome")
    page = _fetch(session, url, timeout)
    code = _code_from_url(url)
    if media := _matching_media(page, code):
        return media
    for candidate in _candidate_pages(page, url, code):
        if media := _matching_media(_fetch(session, candidate, timeout), code):
            return media
    raise RuntimeError("Could not resolve a JavHDPorn media URL.")


def _fetch(session, url: str, timeout: float) -> str:
    response = session.get(url, timeout=timeout, headers={"Accept-Language": "en-US,en;q=0.9"})
    response.raise_for_status()
    return str(response.text)


def _matching_media(page: str, code: str | None) -> str | None:
    urls = _media_urls(page)
    if code:
        normalized = _normalize(code)
        return next((url for url in urls if normalized in _normalize(url)), None)
    return urls[0] if len(urls) == 1 else None


def _media_urls(page: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in MEDIA_URL_RE.findall(page):
        value = unescape(match).replace("\\/", "/").rstrip(".,")
        if value not in values and "/preview." not in value.lower():
            values.append(value)
    return tuple(values)


def _candidate_pages(page: str, current: str, code: str | None) -> tuple[str, ...]:
    current_path = urlparse(urldefrag(current)[0]).path.rstrip("/")
    normalized = _normalize(code or "")
    values: list[str] = []
    for raw in VIDEO_PAGE_RE.findall(page):
        candidate = urljoin(current, unescape(raw).replace("\\/", "/").rstrip(".,"))
        if urlparse(candidate).path.rstrip("/") == current_path:
            continue
        if normalized and normalized not in _normalize(candidate):
            continue
        if candidate not in values:
            values.append(candidate)
    return tuple(values)


def _code_from_url(url: str) -> str | None:
    match = SLUG_CODE_RE.search(urlparse(url).path)
    return f"{match.group(1).lower()}-{int(match.group(2))}" if match else None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
