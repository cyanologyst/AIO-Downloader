import asyncio

from app.downloaders.aria2_downloader import Aria2Downloader
from app.downloaders.aria2_rpc import Aria2Config
from app.downloaders.gallery_downloader import GalleryDownloader
from app.downloaders.registry import DownloaderRegistry
from app.downloaders.spotify_downloader import SpotifyDownloader
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.models import DownloadRequest


def make_registry(tmp_path):
    registry = DownloaderRegistry(
        [
            SpotifyDownloader("spotdl", "ffmpeg"),
            GalleryDownloader(),
            Aria2Downloader(Aria2Config("aria2c", tmp_path)),
            YtdlpDownloader("yt-dlp", "ffmpeg"),
        ]
    )
    ytdlp = next(provider for provider in registry.providers if provider.provider_name == "yt-dlp")
    ytdlp._probe_sync = lambda url: {
        "supported": "video-page" in url or "youtube.com" in url,
        "extractor": "Generic",
        "title": "",
    }
    aria2 = next(provider for provider in registry.providers if provider.provider_name == "aria2")

    async def fake_aria2_support(url):
        return url.startswith("magnet:") or url.endswith(("file.zip", "video.webm"))

    aria2.can_handle = fake_aria2_support
    return registry


def resolve(registry, request):
    return asyncio.run(registry.resolve(request))


def test_auto_detects_magnet(tmp_path):
    provider = resolve(make_registry(tmp_path), DownloadRequest("magnet:?xt=urn:btih:abc"))
    assert provider.provider_name == "aria2"


def test_auto_detects_direct_file(tmp_path):
    provider = resolve(make_registry(tmp_path), DownloadRequest("https://example.com/file.zip"))
    assert provider.provider_name == "aria2"


def test_auto_does_not_treat_webpage_suffix_as_direct_before_ytdlp(tmp_path):
    provider = resolve(
        make_registry(tmp_path),
        DownloadRequest("https://example.com/wiki/video-page.webm"),
    )
    assert provider.provider_name == "yt-dlp"


def test_auto_detects_youtube(tmp_path):
    provider = resolve(make_registry(tmp_path), DownloadRequest("https://youtube.com/watch?v=abc"))
    assert provider.provider_name == "yt-dlp"


def test_auto_detects_gallery_before_ytdlp(tmp_path):
    provider = resolve(
        make_registry(tmp_path), DownloadRequest("https://example.com/manga/chapter-1")
    )
    assert provider.provider_name == "gallery"


def test_auto_uses_ytdlp_generic_probe_before_gallery_fallback(tmp_path):
    provider = resolve(
        make_registry(tmp_path),
        DownloadRequest("https://example.com/manga/video-page"),
    )
    assert provider.provider_name == "yt-dlp"


def test_explicit_audio_uses_ytdlp(tmp_path):
    provider = resolve(
        make_registry(tmp_path),
        DownloadRequest("https://example.com/watch/123", type="audio"),
    )
    assert provider.provider_name == "yt-dlp"
