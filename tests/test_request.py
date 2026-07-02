import pytest

from app.models.download_request import DownloadRequest


def test_request_defaults():
    request = DownloadRequest.from_dict({"url": "https://example.com/file.zip"})
    assert request.type == "auto"
    assert request.quality == "best"
    assert request.audio_format == "mp3"


def test_request_rejects_invalid_type():
    with pytest.raises(ValueError):
        DownloadRequest.from_dict({"url": "https://example.com", "type": "telegram"})


def test_request_accepts_playlist_and_torrent_selection():
    request = DownloadRequest.from_dict(
        {
            "url": "C:/tmp/example.torrent",
            "type": "torrent",
            "playlist": True,
            "selected_files": ["1", "3", "invalid"],
        }
    )
    assert request.playlist is True
    assert request.selected_files == ("1", "3")


def test_request_accepts_selected_batch_items():
    request = DownloadRequest.from_dict(
        {
            "url": "https://example.com/playlist",
            "batch_manifest_id": "abc123",
            "batch_title": "Example playlist",
            "batch_items": ["https://example.com/1", "https://example.com/2"],
            "batch_item_titles": ["One", "Two"],
            "batch_item_thumbnails": ["https://img.example.com/1.jpg", ""],
            "batch_continue_on_error": True,
        }
    )
    assert request.batch_items == (
        "https://example.com/1",
        "https://example.com/2",
    )
    assert request.batch_item_titles == ("One", "Two")
    assert request.batch_item_thumbnails == ("https://img.example.com/1.jpg", "")


def test_request_accepts_profile_thumbnail_url():
    request = DownloadRequest.from_dict(
        {
            "url": "https://www.instagram.com/example/",
            "thumbnail_url": "https://img.example.com/avatar.jpg",
        }
    )

    assert request.thumbnail_url == "https://img.example.com/avatar.jpg"
