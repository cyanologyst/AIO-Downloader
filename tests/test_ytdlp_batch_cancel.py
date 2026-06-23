import asyncio

import pytest

from app.downloaders.base import DownloadContext
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.models import DownloadRequest


def test_cancel_stops_batch_before_next_item(tmp_path):
    async def scenario():
        downloader = YtdlpDownloader("yt-dlp", "ffmpeg")
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []
        updates = []

        async def fake_download_one(_request, url, _destination, _context, **_kwargs):
            calls.append(url)
            started.set()
            await release.wait()
            raise RuntimeError("terminated")

        downloader._download_one = fake_download_one
        request = DownloadRequest(
            url="https://example.com/profile",
            type="youtube",
            destination=tmp_path,
            batch_items=(
                "https://example.com/1",
                "https://example.com/2",
                "https://example.com/3",
            ),
            batch_item_titles=("One", "Two", "Three"),
        )
        task = asyncio.create_task(
            downloader.download(
                request,
                DownloadContext("batch-job", lambda **values: updates.append(values)),
            )
        )
        await started.wait()
        assert await downloader.cancel("batch-job") is True
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert calls == ["https://example.com/1"]
        final_items = updates[-1]["metadata"]["items"]
        assert [item["status"] for item in final_items] == [
            "interrupted",
            "pending",
            "pending",
        ]

    asyncio.run(scenario())
