from __future__ import annotations

import re
from pathlib import Path


def safe_subdir(root: Path, value: str | None) -> Path:
    root = root.expanduser().resolve()
    if not value:
        return root
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("output_subdir must be a relative folder inside the download directory")
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]+', "-", value).strip().strip(".")
    if not cleaned:
        raise ValueError("output_subdir is invalid")
    candidate = (root / cleaned).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("output_subdir escapes the download directory")
    return candidate


def safe_existing_path(root: Path, value: str) -> Path:
    root = root.expanduser().resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path is outside the configured download directory")
    return candidate


def snapshot_files(folder: Path) -> set[Path]:
    return {path for path in folder.rglob("*") if path.is_file()} if folder.exists() else set()
