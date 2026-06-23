import asyncio

from app.downloaders.aria2_downloader import Aria2Downloader
from app.downloaders.aria2_rpc import Aria2Config
from app.downloaders.base import DownloadContext
from app.models import DownloadRequest


class FakeAria2Client:
    def __init__(self, output):
        self.output = output
        self.requested_gids = []
        self.options = None

    async def add_uri(self, _url, options):
        self.options = options
        return "metadata-gid"

    async def status(self, gid):
        self.requested_gids.append(gid)
        if gid == "metadata-gid":
            return {
                "gid": gid,
                "status": "complete",
                "followedBy": ["download-gid"],
                "files": [],
            }
        return {
            "gid": gid,
            "status": "complete",
            "totalLength": str(self.output.stat().st_size),
            "completedLength": str(self.output.stat().st_size),
            "downloadSpeed": "0",
            "files": [{"path": str(self.output), "selected": "true"}],
        }


def test_magnet_follows_metadata_gid_and_preserves_selection(tmp_path):
    output = tmp_path / "selected.bin"
    output.write_bytes(b"done")
    downloader = Aria2Downloader(Aria2Config("aria2c", tmp_path))
    fake = FakeAria2Client(output)
    downloader.client = fake
    request = DownloadRequest(
        url="magnet:?xt=urn:btih:abc",
        type="torrent",
        selected_files=("1", "3"),
        destination=tmp_path,
    )

    result = asyncio.run(
        downloader.download(request, DownloadContext("job", lambda **_values: None))
    )

    assert fake.requested_gids == ["metadata-gid", "download-gid"]
    assert fake.options["select-file"] == "1,3"
    assert result.artifacts[0].path == output
