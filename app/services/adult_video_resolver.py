from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

from app.services.javhdporn import is_javhdporn_url, resolve_javhdporn_video_url

PACKED_JS_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).*?\(\s*'(?P<payload>(?:\\'|[^'])*)'\s*,\s*"
    r"(?P<radix>\d+)\s*,\s*(?P<count>\d+)\s*,\s*"
    r"'(?P<symbols>(?:\\'|[^'])*)'\.split\('\|'\)",
    re.S,
)
MEDIA_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.(?:mp4|m3u8)(?:\?[^\s\"'<>]*)?", re.I)
JAVTIFUL_CONFIG_RE = re.compile(
    r'<script[^>]+id=["\']frontWatchConfig["\'][^>]*>(?P<json>.*?)</script>', re.I | re.S
)
MISSAV_LIKE = {"missav.com", "missav.live", "missav.ws", "missav123.com", "njavtv.com"}
GENERIC_RESOLVED = {"alphaporno.com", "camsoda.com", "nonktube.com", "sexu.com"}


@dataclass(frozen=True, slots=True)
class ResolvedAdultVideo:
    url: str
    referer: str | None = None


def resolve_adult_video_url(url: str, timeout: float = 30.0) -> ResolvedAdultVideo:
    if is_javhdporn_url(url):
        return ResolvedAdultVideo(resolve_javhdporn_video_url(url, timeout), url)
    value = _host(url)
    if any(_domain(value, item) for item in MISSAV_LIKE):
        return ResolvedAdultVideo(_resolve_missav(url, timeout), url)
    if _domain(value, "javtiful.com"):
        return ResolvedAdultVideo(_resolve_generic(url, timeout), url)
    if any(_domain(value, item) for item in GENERIC_RESOLVED):
        return ResolvedAdultVideo(_resolve_generic(url, timeout), url)
    return ResolvedAdultVideo(url)


def resolved_output_template(output_dir: Path, original_url: str) -> str:
    token = hashlib.sha1(original_url.encode()).hexdigest()[:12]
    return str(output_dir / f"%(title).160B [{token}].%(ext)s")


def _resolve_missav(url: str, timeout: float) -> str:
    page = _fetch(url, timeout)
    for decoded in _decode_packed(page):
        urls = _media_urls(decoded)
        if urls:
            return next((item for item in urls if "playlist.m3u8" in item), urls[0])
    raise RuntimeError("Could not resolve media from this MissAV/NJAV page.")


def _resolve_generic(url: str, timeout: float) -> str:
    page = _fetch(url, timeout)
    if value := _front_config(page):
        return value
    for decoded in _decode_packed(page):
        urls = _media_urls(decoded)
        if urls:
            return next((item for item in urls if ".m3u8" in item), urls[0])
    urls = [
        item for item in _media_urls(page)
        if "/previews/" not in item.lower() and "_preview." not in item.lower()
    ]
    if urls:
        return next((item for item in urls if ".m3u8" in item), urls[0])
    raise RuntimeError("Could not resolve media from this public video page.")


def _fetch(url: str, timeout: float) -> str:
    try:
        from curl_cffi import requests
    except ImportError as exc:
        raise RuntimeError("This provider requires curl-cffi.") from exc
    response = requests.get(
        url, impersonate="chrome", timeout=timeout,
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    response.raise_for_status()
    return str(response.text)


def _front_config(page: str) -> str | None:
    match = JAVTIFUL_CONFIG_RE.search(page)
    if not match:
        return None
    config = json.loads(unescape(match.group("json")))
    for source in sorted(config.get("playerSources", []), key=_source_size, reverse=True):
        if value := str(source.get("src") or ""):
            return value
    return None


def _decode_packed(page: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in PACKED_JS_RE.finditer(page):
        try:
            payload = ast.literal_eval(f"'{match.group('payload')}'")
            symbols = tuple(ast.literal_eval(f"'{match.group('symbols')}'").split("|"))
        except (SyntaxError, ValueError):
            continue
        decoded = _unpack(payload, int(match.group("radix")), symbols)
        if ".m3u8" in decoded or ".mp4" in decoded:
            values.append(decoded)
    return tuple(values)


def _unpack(payload: str, radix: int, symbols: tuple[str, ...]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = _base_to_int(match.group(), radix)
        return symbols[index] if index is not None and index < len(symbols) and symbols[index] else match.group()
    return re.sub(r"\b\w+\b", replace, payload)


def _base_to_int(value: str, radix: int) -> int | None:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    number = 0
    for character in value.lower():
        digit = alphabet.find(character)
        if digit < 0 or digit >= radix:
            return None
        number = number * radix + digit
    return number


def _media_urls(value: str) -> tuple[str, ...]:
    results: list[str] = []
    for match in MEDIA_URL_RE.findall(value.replace("\\/", "/")):
        item = unescape(match).replace("\\u0026", "&")
        if item not in results:
            results.append(item)
    return tuple(results)


def _source_size(source: dict[str, object]) -> int:
    match = re.search(r"\d+", str(source.get("size") or ""))
    return int(match.group()) if match else 0


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _domain(value: str, domain: str) -> bool:
    return value == domain or value.endswith(f".{domain}")
