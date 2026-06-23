from __future__ import annotations

import asyncio
import json
import shutil
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import yt_dlp
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

from app.config import SettingsStore
from app.downloaders.aria2_downloader import Aria2Downloader, inspect_torrent
from app.downloaders.aria2_rpc import Aria2Config
from app.downloaders.gallery_downloader import GalleryDownloader
from app.downloaders.registry import DownloaderRegistry
from app.downloaders.spotify_downloader import SpotifyDownloader
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.models import DownloadRequest
from app.services.job_service import JobService
from app.services.batch_manifest import BatchManifestService
from app.services.pdf_service import convert_folder_to_pdf
from app.services.video_sites import SUPPORTED_VIDEO_SITES, host as video_host, matches_domain
from app.services.torrent_search import (
    ProwlarrClient,
    RARBGClient,
    TPBClient,
    TorrentSearchError,
)
from app.utils.paths import safe_existing_path


def create_app(settings_store: SettingsStore | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    CORS(app)
    store = settings_store or SettingsStore()
    settings = store.get()
    settings.download_path.mkdir(parents=True, exist_ok=True)

    aria2 = Aria2Downloader(
        Aria2Config(
            binary=settings.aria2_bin,
            download_dir=settings.download_path,
            host=settings.aria2_rpc_host,
            port=settings.aria2_rpc_port,
            secret=settings.aria2_rpc_secret,
        )
    )
    ytdlp = YtdlpDownloader(
        settings.ytdlp_bin,
        settings.ffmpeg_bin,
        settings.ytdlp_cookies_file,
        settings.ytdlp_proxy,
        settings.deno_bin,
    )
    spotify = SpotifyDownloader(settings.spotdl_bin, settings.ffmpeg_bin)
    gallery = GalleryDownloader(settings.manga_remove_images_after_pdf)
    registry = DownloaderRegistry([spotify, gallery, aria2, ytdlp])
    jobs = JobService(registry, store)
    batches = BatchManifestService(
        Path("config/batches"),
        download_dir=settings.download_path,
        cookies_file=settings.ytdlp_cookies_file,
        proxy=settings.ytdlp_proxy,
    )

    app.extensions["settings_store"] = store
    app.extensions["job_service"] = jobs
    app.extensions["batch_service"] = batches

    @lru_cache(maxsize=128)
    def resolve_thumbnail(url: str, supplied_thumbnail: str = "") -> tuple[bytes, str]:
        parsed = urlparse(url)
        host = video_host(url)
        if supplied_thumbnail.startswith(("http://", "https://")):
            return fetch_thumbnail_image(supplied_thumbnail, url)
        if matches_domain(host, "youtube.com") and parsed.path == "/watch":
            video_id = str((parse_qs(parsed.query).get("v") or [""])[0])
            if video_id:
                return fetch_thumbnail_image(
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", url
                )
        if matches_domain(host, "youtu.be"):
            video_id = parsed.path.strip("/").split("/", 1)[0]
            if video_id:
                return fetch_thumbnail_image(
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", url
                )
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 20,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        if ytdlp.cookies_file and Path(ytdlp.cookies_file).exists():
            options["cookiefile"] = ytdlp.cookies_file
        if ytdlp.proxy:
            options["proxy"] = ytdlp.proxy
        thumbnail = ""
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(url, download=False) or {}
            thumbnail = str(info.get("thumbnail") or "")
        except yt_dlp.utils.DownloadError:
            pass
        if not thumbnail:
            try:
                page = httpx.get(
                    url,
                    timeout=20,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                page.raise_for_status()
                soup = BeautifulSoup(page.text, "html.parser")
                node = soup.select_one(
                    'meta[property="og:image"], meta[name="twitter:image"], '
                    'link[rel="image_src"]'
                )
                thumbnail = str(
                    (node.get("content") or node.get("href") or "") if node else ""
                )
            except httpx.HTTPError:
                pass
        if not thumbnail:
            return b"", ""
        return fetch_thumbnail_image(thumbnail, url)

    def fetch_thumbnail_image(thumbnail: str, referer: str = "") -> tuple[bytes, str]:
        headers = {"User-Agent": "Mozilla/5.0"}
        if referer:
            headers["Referer"] = referer
        image = httpx.get(
            thumbnail,
            timeout=20,
            follow_redirects=True,
            headers=headers,
        )
        image.raise_for_status()
        return image.content, str(image.headers.get("content-type") or "image/jpeg")

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/api/downloads/start")
    def start_downloads():
        payload: Any = request.get_json(silent=True)
        if payload is None:
            return _error("JSON body is required", 400)
        items = payload if isinstance(payload, list) else [payload]
        if not items or not all(isinstance(item, dict) for item in items):
            return _error("Expected a download object or list of objects", 400)
        try:
            created = [jobs.start(DownloadRequest.from_dict(item)).to_dict() for item in items]
        except (ValueError, OSError) as exc:
            return _error(str(exc), 400)
        return jsonify({"jobs": created}), 202

    @app.post("/api/ytdlp/probe")
    def probe_ytdlp():
        payload = request.get_json(silent=True)
        url = str(payload.get("url") or "").strip() if isinstance(payload, dict) else ""
        if not url:
            return _error("url is required", 400)
        try:
            return jsonify(asyncio.run(ytdlp.probe(url)))
        except (ValueError, RuntimeError) as exc:
            return _error(str(exc), 400)

    @app.get("/api/ytdlp/thumbnail")
    def ytdlp_thumbnail():
        url = str(request.args.get("url") or "").strip()
        supplied_thumbnail = str(request.args.get("thumbnail") or "").strip()
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if (
            parsed.scheme not in {"http", "https"}
            or not any(
                matches_domain(host, domain) for domain in SUPPORTED_VIDEO_SITES
            )
        ):
            return _error("Unsupported thumbnail URL", 400)
        try:
            image, content_type = resolve_thumbnail(url, supplied_thumbnail)
            if not image:
                return _error("Thumbnail not found", 404)
            return Response(
                image,
                mimetype=content_type,
                headers={"Cache-Control": "private, max-age=86400"},
            )
        except (
            yt_dlp.utils.DownloadError,
            httpx.HTTPError,
            OSError,
            ValueError,
        ) as exc:
            return _error(str(exc), 404)

    @app.get("/api/downloads")
    def list_downloads():
        return jsonify({"jobs": jobs.list_jobs()})

    @app.get("/api/events")
    def job_events():
        @stream_with_context
        def generate():
            version = -1
            while True:
                version, current_jobs = jobs.wait_for_events(version)
                yield f"event: jobs\ndata: {json.dumps({'jobs': current_jobs})}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/downloads/finished")
    def clear_finished_downloads():
        return jsonify({"removed": jobs.clear_finished()})

    @app.post("/api/downloads/<job_id>/pause")
    def pause_download(job_id: str):
        if not jobs.get_job(job_id):
            return _error("Job not found", 404)
        if not jobs.pause(job_id):
            return _error("Pause is not supported for this download", 409)
        return jsonify({"job": jobs.get_job(job_id)})

    @app.post("/api/downloads/<job_id>/resume")
    def resume_download(job_id: str):
        if not jobs.get_job(job_id):
            return _error("Job not found", 404)
        if not jobs.resume(job_id):
            return _error("Resume is not supported for this download", 409)
        return jsonify({"job": jobs.get_job(job_id)})

    @app.post("/api/downloads/<job_id>/resume-batch")
    def resume_saved_batch(job_id: str):
        job = jobs.resume_batch(job_id)
        if not job:
            return _error("No unfinished batch items are available to resume", 409)
        return jsonify({"job": job.to_dict()}), 202

    @app.post("/api/downloads/<job_id>/cancel")
    def cancel_download(job_id: str):
        if not jobs.get_job(job_id):
            return _error("Job not found", 404)
        jobs.cancel(job_id)
        return jsonify({"job": jobs.get_job(job_id)})

    @app.post("/api/downloads/<job_id>/skip")
    def skip_download(job_id: str):
        if not jobs.get_job(job_id):
            return _error("Job not found", 404)
        if not jobs.skip(job_id):
            return _error("Skip is only available for an active batch item", 409)
        return jsonify({"job": jobs.get_job(job_id)})

    @app.post("/api/downloads/<job_id>/retry-failed")
    def retry_failed_downloads(job_id: str):
        job = jobs.retry_failed(job_id)
        if not job:
            return _error("No failed batch items are available to retry", 409)
        return jsonify({"job": job.to_dict()}), 202

    @app.post("/api/batches/inspect")
    def inspect_batch():
        payload = request.get_json(silent=True)
        url = str(payload.get("url") or "").strip() if isinstance(payload, dict) else ""
        if not url:
            return _error("url is required", 400)
        try:
            manifest = asyncio.run(batches.inspect(url))
            return jsonify({"manifest": manifest.to_dict()})
        except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
            return _error(str(exc), 400)

    @app.get("/api/batches/<manifest_id>")
    def get_batch(manifest_id: str):
        manifest = batches.get(manifest_id)
        if not manifest:
            return _error("Batch manifest not found", 404)
        return jsonify({"manifest": manifest.to_dict()})

    @app.post("/api/batches/<manifest_id>/start")
    def start_batch(manifest_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            indexes = [int(value) for value in payload.get("indexes") or []]
            manifest, selected = batches.select(manifest_id, indexes)
            download_request = DownloadRequest.from_dict(
                {
                    "url": manifest.source_url,
                    "type": "youtube",
                    "quality": payload.get("quality", "best"),
                    "audio_format": payload.get("audio_format", "mp3"),
                    "playlist": True,
                    "batch_manifest_id": manifest.id,
                    "batch_title": manifest.title,
                    "batch_items": [item.url for item in selected],
                    "batch_item_titles": [item.title for item in selected],
                    "batch_item_thumbnails": [
                        item.thumbnail_url or "" for item in selected
                    ],
                    "batch_continue_on_error": bool(payload.get("continue_on_error", True)),
                }
            )
            return jsonify({"job": jobs.start(download_request).to_dict()}), 202
        except (ValueError, TypeError, OSError) as exc:
            return _error(str(exc), 400)

    @app.get("/api/settings")
    def get_settings():
        return jsonify(store.get().public_dict())

    @app.post("/api/settings")
    def save_settings():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("JSON object is required", 400)
        try:
            updated = store.update(payload)
            jobs.update_limit(updated.max_concurrent_downloads)
            ytdlp.cookies_file = updated.ytdlp_cookies_file
            ytdlp.proxy = updated.ytdlp_proxy
            ytdlp.deno_bin = updated.deno_bin
            resolve_thumbnail.cache_clear()
            batches.cookies_file = updated.ytdlp_cookies_file
            batches.proxy = updated.ytdlp_proxy
            batches.download_dir = updated.download_path
            gallery.remove_images_after_pdf = updated.manga_remove_images_after_pdf
            return jsonify(updated.public_dict())
        except (ValueError, TypeError, OSError) as exc:
            return _error(str(exc), 400)

    @app.post("/api/torrents/inspect")
    def inspect_torrent_file():
        current = store.get()
        torrents_dir = current.download_path / "_torrents"
        torrents_dir.mkdir(parents=True, exist_ok=True)
        try:
            if "file" in request.files:
                uploaded = request.files["file"]
                filename = secure_filename(uploaded.filename or "upload.torrent")
                if not filename.lower().endswith(".torrent"):
                    return _error("Only .torrent files are accepted", 400)
                path = _unique_file(torrents_dir / filename)
                uploaded.save(path)
            else:
                payload = request.get_json(silent=True) or {}
                source = str(payload.get("source") or "").strip()
                if not source:
                    return _error("A torrent file or URL is required", 400)
                local = Path(source).expanduser()
                if local.exists():
                    path = local.resolve()
                elif source.startswith(("http://", "https://")):
                    response = httpx.get(source, timeout=30, follow_redirects=True)
                    response.raise_for_status()
                    filename = secure_filename(Path(source.split("?", 1)[0]).name or "download.torrent")
                    if not filename.lower().endswith(".torrent"):
                        filename += ".torrent"
                    path = _unique_file(torrents_dir / filename)
                    path.write_bytes(response.content)
                else:
                    return _error("Torrent source was not found", 404)
            files = asyncio.run(inspect_torrent(current.aria2_bin, path))
            return jsonify({"source": str(path), "name": path.name, "files": files})
        except (OSError, RuntimeError, httpx.HTTPError) as exc:
            return _error(str(exc), 400)

    @app.get("/api/torrents/search")
    def search_torrents():
        query = str(request.args.get("q") or "").strip()
        provider = str(request.args.get("provider") or "tpb").lower()
        category = str(request.args.get("category") or "all").lower()
        page = max(1, int(request.args.get("page") or 1))
        page_size = max(10, min(50, int(request.args.get("page_size") or 20)))
        sort = str(request.args.get("sort") or "seeders").lower()
        order = str(request.args.get("order") or "desc").lower()
        if not query:
            return _error("Search query is required", 400)
        current = store.get()
        try:
            if provider == "tpb":
                client = TPBClient(current.tpb_api_url)
            elif provider == "rarbg":
                client = RARBGClient(current.rarbg_base_url)
            elif provider == "prowlarr":
                client = ProwlarrClient(
                    current.prowlarr_url,
                    current.prowlarr_api_key,
                    current.prowlarr_search_limit,
                )
            else:
                return _error("Unknown torrent search provider", 400)
            results = asyncio.run(client.search(query, category))
            reverse = order != "asc"
            key = {
                "title": lambda item: str(item.get("title") or "").lower(),
                "size": lambda item: int(item.get("size") or 0),
                "date": lambda item: _torrent_date_value(item.get("published_at")),
                "leechers": lambda item: int(item.get("leechers") or 0),
                "seeders": lambda item: int(item.get("seeders") or 0),
            }.get(sort, lambda item: int(item.get("seeders") or 0))
            results.sort(key=key, reverse=reverse)
            total = len(results)
            start = (page - 1) * page_size
            paged = results[start : start + page_size]
            return jsonify(
                {
                    "provider": provider,
                    "results": paged,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_previous": page > 1,
                    "has_next": start + page_size < total,
                    "sort": sort,
                    "order": order,
                }
            )
        except (TorrentSearchError, httpx.HTTPError, ValueError) as exc:
            return _error(str(exc), 400)

    @app.post("/api/torrents/resolve")
    def resolve_torrent_result():
        payload = request.get_json(silent=True) or {}
        provider = str(payload.get("provider") or "")
        source_url = str(payload.get("source_url") or "")
        if provider != "prowlarr" or not source_url:
            return jsonify({"source": source_url})
        current = store.get()
        try:
            client = ProwlarrClient(
                current.prowlarr_url,
                current.prowlarr_api_key,
                current.prowlarr_search_limit,
            )
            source = asyncio.run(
                client.resolve(source_url, current.download_path / "_torrents")
            )
            return jsonify({"source": source})
        except (TorrentSearchError, httpx.HTTPError, OSError) as exc:
            return _error(str(exc), 400)

    @app.post("/api/pdf/convert")
    def convert_pdf():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload.get("folder"):
            return _error("folder is required", 400)
        current = store.get()
        try:
            folder = safe_existing_path(current.download_path, str(payload["folder"]))
            if not folder.is_dir():
                return _error("Gallery folder was not found", 404)
            pdf_path = convert_folder_to_pdf(
                folder,
                remove_images=bool(
                    payload.get(
                        "remove_images", current.manga_remove_images_after_pdf
                    )
                ),
                title=str(payload.get("title") or folder.name),
            )
            return jsonify({"pdf_path": str(pdf_path)})
        except (ValueError, OSError) as exc:
            return _error(str(exc), 400)

    @app.get("/api/health")
    def health():
        current = store.get()
        dependencies = {
            "aria2c": bool(shutil.which(current.aria2_bin)),
            "yt-dlp": bool(shutil.which(current.ytdlp_bin)),
            "ffmpeg": bool(shutil.which(current.ffmpeg_bin)),
            "spotdl": bool(shutil.which(current.spotdl_bin)),
            "deno": bool(current.deno_bin and Path(current.deno_bin).exists())
            or bool(shutil.which("deno")),
        }
        return jsonify(
            {
                "status": "ok",
                "download_dir": str(current.download_path),
                "dependencies": dependencies,
            }
        )

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return _error_response("Not found", 404)
        return render_template("index.html"), 404

    return app


def _error(message: str, status: int):
    return _error_response(message, status)


def _error_response(message: str, status: int):
    return jsonify({"error": message}), status


def _unique_file(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique torrent filename")


def _torrent_date_value(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return 0
