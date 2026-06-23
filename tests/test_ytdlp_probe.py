import asyncio

import yt_dlp

from app.downloaders.ytdlp_downloader import YtdlpDownloader


def test_probe_caches_generic_extraction_result():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    calls = []

    def fake_probe(url):
        calls.append(url)
        return {"supported": True, "extractor": "Generic", "title": "Embedded video"}

    downloader._probe_sync = fake_probe
    url = "https://unknown.example/video-page"

    first = asyncio.run(downloader.probe(url))
    second = asyncio.run(downloader.probe(url))

    assert first["supported"] is True
    assert second == first
    assert calls == [url]


def test_probe_rejects_non_http_urls():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(downloader.probe("magnet:?xt=urn:btih:abc"))
    assert result["supported"] is False


def test_probe_preserves_custom_resolver_sites():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(downloader.probe("https://missav.ws/example-video"))
    assert result["supported"] is True


def test_probe_marks_custom_playlist_for_review():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(downloader.probe("https://hstream.moe/hentai/example-series"))
    assert result["supported"] is True
    assert result["batch_candidate"] is True


def test_probe_marks_pornhub_pornstar_profile_for_review():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(
        downloader.probe("https://www.pornhub.com/pornstar/example-profile")
    )
    assert result["supported"] is True
    assert result["batch_candidate"] is True


def test_probe_marks_hanime_brand_for_review():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(
        downloader.probe("https://hanime.tv/browse/brands/ms-pictures")
    )
    assert result["supported"] is True
    assert result["batch_candidate"] is True


def test_probe_marks_hanime_playlist_for_review():
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    result = asyncio.run(
        downloader.probe("https://hanime.tv/playlists/y1udyamtfnx5gt2do767")
    )
    assert result["supported"] is True
    assert result["batch_candidate"] is True


def test_probe_reports_authentication_block(monkeypatch):
    downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
    monkeypatch.setattr(
        downloader,
        "_specific_extractor",
        lambda _url: "Youtube",
    )

    class FakeYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot; use cookies")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    result = asyncio.run(downloader.probe("https://example.com/video"))

    assert result["supported"] is False
    assert result["recognized"] is True
    assert result["requires_auth"] is True
    assert result["extractor"] == "Youtube"
