from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class HentaiPlaylist:
    title: str
    site: str
    urls: tuple[str, ...]
    titles: tuple[str, ...] = ()
    thumbnails: tuple[str, ...] = ()
    durations: tuple[int | None, ...] = ()


def is_hentai_playlist_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    if host.endswith("hentaihaven.com"):
        return bool(
            re.fullmatch(r"video/[^/]+/?", path)
            or re.fullmatch(r"studio/[^/]+(?:/page/\d+)?/?", path)
        )
    if host.endswith("hstream.moe"):
        match = re.fullmatch(r"hentai/([a-z0-9-]+)/?", path)
        return bool(match and not re.search(r"-\d+$", match.group(1)))
    if host.endswith("hanime.tv"):
        return bool(
            re.fullmatch(r"browse/brands/[a-z0-9-]+/?", path)
            or re.fullmatch(r"playlists/[a-z0-9]+/?", path)
        )
    return False


async def resolve_hentai_playlist(url: str, timeout: float = 20.0) -> HentaiPlaylist:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        response = await _get_with_retries(client, url)
        response.raise_for_status()
        page = response.text

        if host.endswith("hentaihaven.com"):
            video = re.fullmatch(r"video/([^/]+)", path)
            if video:
                slug = video.group(1)
                episodes = _sorted(_hh_episodes(page, slug))
                title = _title(page, slug.replace("-", " ").title())
                thumbnail = _meta_image(page)
                return HentaiPlaylist(
                    title,
                    "HentaiHaven",
                    tuple(episodes),
                    tuple(_episode_title(title, item) for item in episodes),
                    tuple(thumbnail for _item in episodes),
                )
            studio = re.fullmatch(r"studio/([^/]+)(?:/page/\d+)?", path)
            if not studio:
                raise ValueError("Unsupported HentaiHaven playlist URL")
            pages = await _hh_studio_pages(client, url, page)
            series_urls: set[str] = set()
            for studio_page in pages:
                series_urls.update(
                    urljoin(url, match.group(1)).rstrip("/") + "/"
                    for match in re.finditer(
                        r"""href=["']([^"']*/video/[a-z0-9-]+/?)["']""",
                        studio_page,
                        re.I,
                    )
                    if "/episode-" not in match.group(1)
                )
            records = await _hh_series_records(client, sorted(series_urls))
            urls = tuple(item[0] for item in records)
            slug = studio.group(1)
            if not urls:
                raise RuntimeError("No available HentaiHaven studio videos were found.")
            return HentaiPlaylist(
                _title(page, f"{slug.replace('-', ' ').title()} Studio"),
                "HentaiHaven Studio",
                urls,
                tuple(item[1] for item in records),
                tuple(item[2] for item in records),
            )

        if host.endswith("hstream.moe"):
            match = re.fullmatch(r"hentai/([a-z0-9-]+)", path)
            if not match:
                raise ValueError("Unsupported HStream playlist URL")
            slug = match.group(1)
            episodes = {
                f"https://hstream.moe/hentai/{slug}-{number}"
                for number in re.findall(rf"/hentai/{re.escape(slug)}-(\d+)", page)
            }
            return HentaiPlaylist(
                _title(page, slug.replace("-", " ").title()),
                "HStream",
                tuple(_sorted(episodes)),
            )
        if host.endswith("hanime.tv"):
            playlist = re.fullmatch(r"playlists/([a-z0-9]+)", path)
            if playlist:
                records = _hanime_records(page, url)
                if not records:
                    raise RuntimeError("No public videos found on this Hanime playlist.")
                return HentaiPlaylist(
                    f"Hanime playlist · {_hanime_playlist_title(page, playlist.group(1))}",
                    "Hanime",
                    tuple(item[0] for item in records),
                    tuple(item[1] for item in records),
                    tuple(item[2] for item in records),
                    tuple(item[3] for item in records),
                )
            match = re.fullmatch(r"browse/brands/([a-z0-9-]+)", path)
            if not match:
                raise ValueError("Unsupported Hanime brand URL")
            records = _hanime_brand_records(page)
            if not records:
                raise RuntimeError("No public videos found on this Hanime studio page.")
            return HentaiPlaylist(
                f"Hanime · {match.group(1).replace('-', ' ').title()}",
                "Hanime",
                tuple(item[0] for item in records),
                tuple(item[1] for item in records),
                tuple(item[2] for item in records),
                tuple(item[3] for item in records),
            )
    raise ValueError("Unsupported hentai playlist site")


def _title(page: str, fallback: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    if not match:
        return fallback
    value = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return re.sub(r"\s*[-|]\s*(Hentai Haven|hstream\.moe).*$", "", value, flags=re.I) or fallback


def _hh_episodes(page: str, slug: str | None = None) -> set[str]:
    slug_part = re.escape(slug) if slug else r"[^/]+"
    return {
        f"https://hentaihaven.com/video/{match.group(1)}/episode-{match.group(2)}"
        for match in re.finditer(rf"/video/({slug_part})/episode-(\d+)", page)
    }


async def _get_with_retries(
    client: httpx.AsyncClient, url: str, attempts: int = 3
) -> httpx.Response:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url)
            if response.status_code < 500:
                return response
            error = httpx.HTTPStatusError(
                f"Server returned {response.status_code}",
                request=response.request,
                response=response,
            )
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            error = exc
        if attempt + 1 < attempts:
            await asyncio.sleep(0.35 * (attempt + 1))
    if error:
        raise error
    raise RuntimeError(f"Could not load {url}")


async def _hh_studio_pages(
    client: httpx.AsyncClient, base_url: str, first_page: str
) -> list[str]:
    pages = [first_page]
    seen = {base_url.rstrip("/") + "/"}
    current = first_page
    for _ in range(19):
        soup = BeautifulSoup(current, "html.parser")
        candidates = [
            urljoin(base_url, str(anchor.get("href") or ""))
            for anchor in soup.select('a[href*="/page/"]')
            if re.search(r"/studio/[^/]+/page/\d+/?$", str(anchor.get("href") or ""))
        ]
        next_url = next((item for item in candidates if item not in seen), None)
        if not next_url:
            break
        seen.add(next_url)
        try:
            response = await _get_with_retries(client, next_url)
            response.raise_for_status()
        except (httpx.HTTPError, RuntimeError):
            break
        current = response.text
        pages.append(current)
    return pages


async def _hh_series_records(
    client: httpx.AsyncClient, series_urls: list[str]
) -> list[tuple[str, str, str]]:
    semaphore = asyncio.Semaphore(5)

    async def inspect(series_url: str) -> list[tuple[str, str, str]]:
        async with semaphore:
            try:
                response = await _get_with_retries(client, series_url)
                response.raise_for_status()
            except (httpx.HTTPError, RuntimeError):
                return []
        slug = urlparse(series_url).path.strip("/").rsplit("/", 1)[-1]
        title = _title(response.text, slug.replace("-", " ").title())
        thumbnail = _meta_image(response.text)
        return [
            (episode, _episode_title(title, episode), thumbnail)
            for episode in _sorted(_hh_episodes(response.text, slug))
        ]

    groups = await asyncio.gather(*(inspect(url) for url in series_urls))
    records = [item for group in groups for item in group]
    return sorted(records, key=lambda item: item[0])


def _meta_image(page: str) -> str:
    soup = BeautifulSoup(page, "html.parser")
    node = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
    return str(node.get("content") or "") if node else ""


def _episode_title(series_title: str, url: str) -> str:
    match = re.search(r"episode-(\d+)", url)
    return f"{series_title} · Episode {match.group(1)}" if match else series_title


def _hanime_brand_records(page: str) -> list[tuple[str, str, str, int | None]]:
    return _hanime_embedded_records(page)


def _hanime_records(page: str, page_url: str = "https://hanime.tv/") -> list[tuple[str, str, str, int | None]]:
    embedded = _hanime_embedded_records(page)
    dom = _hanime_dom_records(page, page_url)
    if not dom:
        return embedded
    by_slug = {
        urlparse(item[0]).path.rstrip("/").rsplit("/", 1)[-1]: item
        for item in embedded
    }
    merged: list[tuple[str, str, str, int | None]] = []
    merged_slugs: set[str] = set()
    for item in dom:
        slug = urlparse(item[0]).path.rstrip("/").rsplit("/", 1)[-1]
        merged.append(by_slug.get(slug, item))
        merged_slugs.add(slug)
    merged.extend(
        item
        for item in embedded
        if urlparse(item[0]).path.rstrip("/").rsplit("/", 1)[-1] not in merged_slugs
    )
    return merged


def _hanime_embedded_records(page: str) -> list[tuple[str, str, str, int | None]]:
    pattern = re.compile(
        r'name:"((?:\\.|[^"\\])*)",slug:"([^"]+)".*?'
        r'poster_url:"([^"]+)".*?duration_in_ms:(\d+)',
        re.S,
    )
    records: list[tuple[str, str, str, int | None]] = []
    seen: set[str] = set()
    for encoded_name, slug, encoded_poster, duration_ms in pattern.findall(page):
        if slug in seen:
            continue
        seen.add(slug)
        name = json.loads(f'"{encoded_name}"')
        poster = json.loads(f'"{encoded_poster}"')
        records.append(
            (
                f"https://hanime.tv/videos/hentai/{slug}",
                name,
                poster,
                round(int(duration_ms) / 1000),
            )
        )
    return records


def _hanime_dom_records(page: str, page_url: str) -> list[tuple[str, str, str, int | None]]:
    soup = BeautifulSoup(page, "html.parser")
    records: list[tuple[str, str, str, int | None]] = []
    seen: set[str] = set()
    for item in soup.select(".video__item"):
        anchor = item.select_one('a[href*="/videos/hentai/"]')
        if not anchor:
            continue
        url = urljoin(page_url, str(anchor.get("href") or "")).split("?", 1)[0]
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        image = item.select_one(".video__item__image")
        style = str(image.get("style") or "") if image else ""
        thumbnail_match = re.search(r"url\(([^)]+)\)", style)
        thumbnail = thumbnail_match.group(1).strip("\"'") if thumbnail_match else ""
        title_node = item.select_one(".video__item__name, .video__item__title")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        records.append((url, title or slug.replace("-", " ").title(), thumbnail, None))
    return records


def _hanime_playlist_title(page: str, fallback: str) -> str:
    match = re.search(r'playlist:\{id:[^}]+?title:"((?:\\.|[^"\\])*)"', page, re.S)
    if not match:
        return fallback
    return json.loads(f'"{match.group(1)}"') or fallback


def _sorted(urls: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, str]:
        match = re.search(r"(?:episode-|-)(\d+)$", value.rstrip("/"))
        return (int(match.group(1)) if match else 999999, value)
    return sorted(urls, key=key)
