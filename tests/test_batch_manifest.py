from pathlib import Path

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
