from pathlib import Path

import yt_dlp

from app.services.batch_manifest import BatchItem, BatchManifest, BatchManifestService


def test_manifest_persists_and_selects_items(tmp_path: Path):
    service = BatchManifestService(
        tmp_path / "batches",
        download_dir=tmp_path,
    )
    manifest = BatchManifest(
        id="manifest123",
        source_url="https://example.com/playlist",
        title="Example",
        provider="Test",
        items=(
            BatchItem(
                1,
                "https://example.com/1",
                "One",
                60,
                100,
                "https://img.example.com/1.jpg",
            ),
            BatchItem(2, "https://example.com/2", "Two", 120, 200),
        ),
        created_at="2026-06-22T00:00:00+00:00",
        free_bytes=1000,
    )
    service.save(manifest)

    loaded, selected = service.select("manifest123", [2])

    assert loaded.title == "Example"
    assert selected == (manifest.items[1],)
    assert loaded.to_dict()["estimated_size_bytes"] == 300
    assert loaded.items[0].thumbnail_url == "https://img.example.com/1.jpg"


def test_youtube_playlist_thumbnail_fallback_from_id():
    thumbnail = BatchManifestService._thumbnail_url(
        {"id": "dQw4w9WgXcQ"},
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )

    assert thumbnail == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_youtube_playlist_thumbnail_fallback_from_url():
    thumbnail = BatchManifestService._thumbnail_url(
        {},
        "https://youtu.be/dQw4w9WgXcQ",
    )

    assert thumbnail == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_social_profile_manifest_uses_profile_title_and_avatar(monkeypatch, tmp_path: Path):
    service = BatchManifestService(tmp_path / "batches", download_dir=tmp_path)

    class FakeYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            return {
                "title": "Ignored profile title",
                "extractor_key": "Instagram",
                "thumbnail": "https://img.example.com/avatar.jpg",
                "entries": [
                    {
                        "url": "https://www.instagram.com/p/one/",
                        "title": "One",
                        "thumbnail": "https://img.example.com/one.jpg",
                    },
                    {
                        "url": "https://www.instagram.com/p/two/",
                        "title": "Two",
                    },
                ],
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    manifest = service._inspect_ytdlp("https://www.instagram.com/example.user/")

    assert manifest[0] == "example.user (Instagram)"
    assert manifest[1] == "Instagram"
    assert manifest[3] == "https://img.example.com/avatar.jpg"
    assert manifest[2][0].thumbnail_url == "https://img.example.com/one.jpg"
