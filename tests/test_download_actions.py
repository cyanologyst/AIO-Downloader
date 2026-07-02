from pathlib import Path

from app.config import SettingsStore
from app.models import DownloadRequest, Job, JobStatus
from app.web.app import create_app


def test_open_path_allows_known_job_output_outside_current_download_dir(monkeypatch, tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update({"download_dir": str(tmp_path / "current-downloads")})
    app = create_app(store)
    jobs = app.extensions["job_service"]

    output = tmp_path / "previous-downloads" / "video.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"media")

    with jobs._lock:
        jobs.jobs["done"] = Job(
            id="done",
            request=DownloadRequest.from_dict({"url": "https://example.com/video"}),
            status=JobStatus.COMPLETED,
            provider="yt-dlp",
            title="Done",
            output_path=str(output),
        )
        jobs._notify_locked()

    opened: list[list[str]] = []
    monkeypatch.setattr("app.web.app.subprocess.Popen", lambda command, **_kwargs: opened.append(command))

    response = app.test_client().post("/api/open-path", json={"path": str(output)})

    assert response.status_code == 200
    assert opened


def test_delete_download_removes_single_job(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    app = create_app(store)
    jobs = app.extensions["job_service"]

    with jobs._lock:
        jobs.jobs["old"] = Job(
            id="old",
            request=DownloadRequest.from_dict({"url": "https://example.com/file"}),
            status=JobStatus.FAILED,
            provider="yt-dlp",
            title="Old",
        )
        jobs._notify_locked()

    response = app.test_client().delete("/api/downloads/old")

    assert response.status_code == 200
    assert jobs.get_job("old") is None
