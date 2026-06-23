from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup


class TorrentSearchError(RuntimeError):
    pass


class TPBClient:
    CATEGORIES = {"all": "0", "audio": "100", "video": "200", "apps": "300", "games": "400", "adult": "500", "other": "600"}

    def __init__(self, base_url: str = "https://apibay.org") -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, category: str = "all") -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                f"{self.base_url}/q.php",
                params={"q": query, "cat": self.CATEGORIES.get(category, "0"), "page": 0},
            )
            response.raise_for_status()
            data = response.json()
        return [
            {
                "title": unescape(str(item.get("name", "Unknown"))),
                "source_url": self.magnet(str(item.get("info_hash", "")), str(item.get("name", ""))),
                "size": int(item.get("size") or 0),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("leechers") or 0),
                "published_at": _timestamp(item.get("added")),
                "indexer": "The Pirate Bay",
                "category": item.get("category", ""),
            }
            for item in data if isinstance(item, dict) and item.get("info_hash")
        ]

    @staticmethod
    def magnet(info_hash: str, name: str) -> str:
        trackers = [
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://tracker.openbittorrent.com:80/announce",
        ]
        return f"magnet:?xt=urn:btih:{info_hash}&dn={quote(name)}" + "".join(
            f"&tr={quote(tracker)}" for tracker in trackers
        )


class RARBGClient:
    CATEGORIES = {"all": "", "movies": "movies", "tv": "tv", "games": "games", "music": "music", "anime": "anime", "apps": "apps", "books": "documentaries", "adult": "xxx"}

    def __init__(self, base_url: str = "https://rargb.to") -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, category: str = "all") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"search": query}
        value = self.CATEGORIES.get(category, "")
        if value:
            params["category[]"] = value
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125"},
        ) as client:
            response = await client.get(f"{self.base_url}/search/", params=params)
            response.raise_for_status()
        page = response.text
        lowered = page.lower()
        if any(term in lowered for term in ("captcha", "verify you are human", "cf-chl")):
            raise TorrentSearchError("The configured RARBG-style mirror requires human verification.")
        soup = BeautifulSoup(page, "html.parser")
        results: list[dict[str, Any]] = []
        for row in soup.select("tr.lista2"):
            cells = row.find_all("td")
            link = row.select_one('td.lista a[href^="/torrent/"]')
            if not link or len(cells) < 7:
                continue
            details_url = urljoin(self.base_url + "/", str(link.get("href", "")))
            results.append(
                {
                    "title": link.get("title") or link.get_text(" ", strip=True),
                    "source_url": "",
                    "details_url": details_url,
                    "size_text": cells[4].get_text(" ", strip=True),
                    "size": _size_bytes(cells[4].get_text(" ", strip=True)),
                    "seeders": _int(cells[5].get_text(strip=True)),
                    "leechers": _int(cells[6].get_text(strip=True)),
                    "published_at": cells[3].get_text(" ", strip=True),
                    "indexer": "RARBG-style",
                    "category": cells[2].get_text(" ", strip=True),
                }
            )
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for result in results[:100]:
                try:
                    detail = await client.get(result["details_url"])
                    detail.raise_for_status()
                    magnet = BeautifulSoup(detail.text, "html.parser").select_one('a[href^="magnet:"]')
                    result["source_url"] = str(magnet.get("href", "")) if magnet else ""
                except Exception:
                    pass
        return [item for item in results if item["source_url"]]


class ProwlarrClient:
    CATEGORIES = {"all": [], "movies": [2000], "tv": [5000], "anime": [5070], "music": [3000], "apps": [4000], "books": [8000], "adult": [6000]}

    def __init__(self, base_url: str, api_key: str, limit: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.limit = max(1, min(limit, 100))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def search(self, query: str, category: str = "all") -> list[dict[str, Any]]:
        if not self.enabled:
            raise TorrentSearchError("Prowlarr is not configured.")
        params: dict[str, Any] = {"query": query, "type": "search", "limit": 100}
        if categories := self.CATEGORIES.get(category, []):
            params["categories"] = ",".join(map(str, categories))
        async with httpx.AsyncClient(
            timeout=45, follow_redirects=False, headers={"X-Api-Key": self.api_key}
        ) as client:
            response = await client.get(urljoin(self.base_url + "/", "api/v1/search"), params=params)
            response.raise_for_status()
            releases = response.json()
        return [
            {
                "title": item.get("title", "Unknown"),
                "source_url": item.get("magnetUrl") or item.get("downloadUrl") or "",
                "size": int(item.get("size") or 0),
                "seeders": item.get("seeders"),
                "leechers": item.get("leechers"),
                "published_at": item.get("publishDate") or item.get("indexerFlags") or "",
                "indexer": item.get("indexer") or "Prowlarr",
                "category": ", ".join(
                    str(category.get("name") or category.get("id") or "")
                    for category in item.get("categories") or [] if isinstance(category, dict)
                ),
            }
            for item in releases[:100] if isinstance(item, dict)
        ]

    async def resolve(self, result_url: str, destination: Path) -> str:
        if result_url.startswith("magnet:"):
            return result_url
        url = urljoin(self.base_url + "/", result_url.lstrip("/")) if result_url.startswith("/") else result_url
        async with httpx.AsyncClient(
            timeout=45, follow_redirects=False, headers={"X-Api-Key": self.api_key}
        ) as client:
            response = await client.get(url)
            if response.is_redirect and (location := response.headers.get("Location", "")):
                if location.startswith("magnet:"):
                    return location
                response = await client.get(location)
            response.raise_for_status()
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "prowlarr-result.torrent"
        path.write_bytes(response.content)
        return str(path)


def _int(value: object) -> int:
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return 0


def _timestamp(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(str(value)), timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


def _size_bytes(value: str) -> int:
    match = re.search(r"([\d.]+)\s*(KB|MB|GB|TB)", value, re.I)
    if not match:
        return 0
    powers = {"KB": 1, "MB": 2, "GB": 3, "TB": 4}
    return int(float(match.group(1)) * 1024 ** powers[match.group(2).upper()])
