import pytest

from app.utils.paths import safe_existing_path, safe_subdir


def test_safe_subdir_stays_inside_root(tmp_path):
    assert safe_subdir(tmp_path, "music") == (tmp_path / "music").resolve()


def test_safe_subdir_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_subdir(tmp_path, "../outside")


def test_safe_existing_path_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_existing_path(tmp_path, "../outside")
