import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models import DownloadRequest, Job, JobStatus
from app.services.job_service import JobService


def test_resume_batch_only_queues_unfinished_items(tmp_path: Path):
    service = JobService.__new__(JobService)
    service.jobs = {}
    service._lock = threading.RLock()
    service._events = threading.Condition(service._lock)
    service._event_version = 0
    service._history_path = tmp_path / "jobs.json"
    original = Job(
        id="old-batch",
        request=DownloadRequest(
            url="https://example.com/profile",
            type="youtube",
            playlist=True,
            batch_items=(
                "https://example.com/1",
                "https://example.com/2",
                "https://example.com/3",
                "https://example.com/4",
            ),
            batch_item_titles=("One", "Two", "Three", "Four"),
            batch_title="Example profile",
        ),
        status=JobStatus.CANCELLED,
        metadata={
            "batch": True,
            "items": [
                {"url": "https://example.com/1", "title": "One", "status": "completed"},
                {"url": "https://example.com/2", "title": "Two", "status": "interrupted"},
                {"url": "https://example.com/3", "title": "Three", "status": "pending"},
                {"url": "https://example.com/4", "title": "Four", "status": "skipped"},
            ],
        },
        created_at=datetime.now(timezone.utc),
    )
    service.jobs[original.id] = original
    captured = []

    def fake_start(request):
        captured.append(request)
        return Job(id="resumed", request=request)

    service.start = fake_start

    resumed = service.resume_batch(original.id)

    assert resumed is not None
    assert captured[0].batch_items == (
        "https://example.com/2",
        "https://example.com/3",
    )
    assert captured[0].batch_item_titles == ("Two", "Three")
    assert original.metadata["resumed_by"] == "resumed"
