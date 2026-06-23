from app.services.hentai_playlist import is_hentai_playlist_url
from app.services.pornhub_model import is_pornhub_model_url
from app.services.video_sites import (
    is_adult_video_url,
    is_hentai_video_url,
    platform_label,
    requires_deno_runtime,
)


def test_video_provider_detection():
    assert platform_label("https://www.youtube.com/watch?v=abc") == "YouTube"
    assert is_adult_video_url("https://missav.ws/example")
    assert is_hentai_video_url("https://hanime.tv/videos/example")
    assert requires_deno_runtime("https://hanime.tv/videos/example")


def test_batch_page_detection():
    assert is_hentai_playlist_url("https://hstream.moe/hentai/example-series")
    assert is_hentai_playlist_url("https://hentaihaven.com/video/example-series")
    assert is_hentai_playlist_url("https://hanime.tv/browse/brands/ms-pictures")
    assert is_hentai_playlist_url("https://hanime.tv/playlists/y1udyamtfnx5gt2do767")
    assert is_pornhub_model_url("https://www.pornhub.com/model/example/")
    assert is_pornhub_model_url("https://www.pornhub.com/pornstar/example")
    assert is_pornhub_model_url("https://www.pornhub.com/pornstar/example/videos")
