from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.downloaders.base import BaseDownloader, DownloadContext
from app.models import DownloadArtifact, DownloadRequest, DownloadResult
from app.services.pdf_service import convert_folder_to_pdf

MANGADEX_RE = re.compile(
    r"https?://(?:www\.)?mangadex\.org/chapter/([0-9a-f-]{36})", re.I
)
GALLERY_RE = re.compile(r"(manga|comic|chapter|gallery|doujin|mangadex|manganato)", re.I)
NHENTAI_RE = re.compile(r"https?://(?:www\.)?nhentai\.[^/\s]+/g/(\d+)/?", re.I)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


class GalleryDownloader(BaseDownloader):
    provider_name = "gallery"

    def __init__(self, remove_images_after_pdf: bool = False) -> None:
        self.remove_images_after_pdf = remove_images_after_pdf

    async def can_handle(self, url: str) -> bool:
        return bool(MANGADEX_RE.search(url) or NHENTAI_RE.search(url) or GALLERY_RE.search(url))

    async def download(
        self, request: DownloadRequest, context: DownloadContext
    ) -> DownloadResult:
        assert request.destination
        chapter = MANGADEX_RE.search(request.url)
        if chapter:
            title, folder, urls = await self._mangadex(chapter.group(1), request.destination)
        elif NHENTAI_RE.search(request.url):
            title, folder, urls = await self._nhentai(request.url, request.destination)
        else:
            title, folder, urls = await self._generic(request.url, request.destination)
        artifacts: list[DownloadArtifact] = []
        headers = {"User-Agent": "Mozilla/5.0 AIO-Downloader/1.0"}
        async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers) as client:
            total = len(urls)
            for index, url in enumerate(urls, 1):
                response = await client.get(url)
                response.raise_for_status()
                suffix = self._extension(url, response.headers.get("content-type", ""))
                path = folder / f"{index:04d}{suffix}"
                await asyncio.to_thread(path.write_bytes, response.content)
                artifacts.append(DownloadArtifact(path, "image", len(response.content)))
                context.progress(
                    title=title,
                    percent=index / total * 100,
                    downloaded_bytes=index,
                    total_bytes=total,
                    status="downloading",
                    metadata={"unit": "images"},
                )
        pdf_path = ""
        if request.convert_to_pdf:
            pdf = await asyncio.to_thread(
                convert_folder_to_pdf,
                folder,
                remove_images=self.remove_images_after_pdf,
                title=title,
            )
            pdf_path = str(pdf)
            artifacts.insert(0, DownloadArtifact(pdf, "pdf", pdf.stat().st_size))
        return DownloadResult(
            self.provider_name,
            title,
            tuple(artifacts),
            {
                "folder": str(folder),
                "image_count": len(urls),
                "pdf_created": bool(pdf_path),
                "pdf_path": pdf_path,
            },
        )

    async def _mangadex(self, chapter_id: str, root: Path) -> tuple[str, Path, list[str]]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(f"https://api.mangadex.org/at-home/server/{chapter_id}")
            response.raise_for_status()
            data = response.json()
        chapter = data["chapter"]
        names = chapter.get("data") or chapter.get("dataSaver") or []
        if not names:
            raise RuntimeError("MangaDex chapter returned no image pages")
        title = chapter_id
        folder = self._folder(root, title)
        base = data["baseUrl"].rstrip("/")
        image_hash = chapter["hash"]
        return title, folder, [f"{base}/data/{image_hash}/{name}" for name in names]

    async def _generic(self, url: str, root: Path) -> tuple[str, Path, list[str]]:
        headers = {"User-Agent": "Mozilla/5.0 AIO-Downloader/1.0"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = (
            soup.title.get_text(strip=True)
            if soup.title
            else Path(urlparse(str(response.url)).path).name or "Gallery"
        )
        urls: list[str] = []
        for image in soup.find_all("img"):
            source = (
                image.get("data-src")
                or image.get("data-original")
                or image.get("data-lazy-src")
                or image.get("src")
            )
            if not source:
                srcset = image.get("srcset") or image.get("data-srcset")
                if isinstance(srcset, str):
                    source = srcset.split(",")[-1].strip().split(" ")[0]
            if not isinstance(source, str):
                continue
            absolute = urljoin(str(response.url), source)
            path = urlparse(absolute).path.lower()
            if Path(path).suffix in IMAGE_EXTENSIONS and not any(
                word in path for word in ("logo", "avatar", "icon", "sprite")
            ):
                if absolute not in urls:
                    urls.append(absolute)
        if not urls:
            raise RuntimeError("No downloadable gallery images found on this page")
        return title[:120], self._folder(root, title), urls

    async def _nhentai(self, url: str, root: Path) -> tuple[str, Path, list[str]]:
        match = NHENTAI_RE.search(url)
        if not match:
            raise ValueError("Invalid nhentai gallery URL")
        gallery_id = match.group(1)
        parsed = urlparse(url)
        gallery_url = f"{parsed.scheme or 'https'}://{parsed.netloc}/g/{gallery_id}/"
        headers = {"User-Agent": "Mozilla/5.0 AIO-Downloader/1.0"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            response = await client.get(gallery_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else f"nhentai {gallery_id}"
            title = re.sub(r"\s*[»|-]\s*nhentai\s*$", "", title, flags=re.I).strip()
            badge = soup.select_one(".pages")
            try:
                count = int(badge.get_text(strip=True)) if badge else 0
            except ValueError:
                count = 0
            if not count:
                count_match = re.search(
                    r"Pages:\s*</span>\s*<span[^>]*>.*?(\d+)",
                    response.text,
                    re.I | re.S,
                )
                count = int(count_match.group(1)) if count_match else 0
            if not count:
                raise RuntimeError("Could not detect nhentai page count")
            urls: list[str] = []
            for page in range(1, count + 1):
                page_url = urljoin(gallery_url, f"/g/{gallery_id}/{page}/")
                reader = await client.get(page_url)
                reader.raise_for_status()
                page_soup = BeautifulSoup(reader.text, "html.parser")
                for image in page_soup.find_all("img"):
                    source = image.get("data-src") or image.get("data-original") or image.get("src")
                    if not isinstance(source, str):
                        continue
                    candidate = urljoin(page_url, source)
                    path = urlparse(candidate).path.lower()
                    if "/images/logo" not in path and Path(path).suffix.lower() in IMAGE_EXTENSIONS:
                        urls.append(candidate)
                        break
            if len(urls) != count:
                raise RuntimeError(f"Found {len(urls)} of {count} nhentai pages")
        return title, self._folder(root, title), urls

    @staticmethod
    def _folder(root: Path, title: str) -> Path:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", unquote(title))
        clean = re.sub(r"\s+", " ", clean).strip(" .")[:120] or "Gallery"
        folder = root / clean
        index = 2
        while folder.exists():
            folder = root / f"{clean} ({index})"
            index += 1
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def _extension(url: str, content_type: str) -> str:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            return ".jpg" if suffix == ".jpeg" else suffix
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
        return ".jpg"
