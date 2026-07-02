import types

from app import launcher


def test_spotdl_launcher_returns_failure_instead_of_raising(monkeypatch):
    def boom():
        raise RuntimeError("spotdl exploded")

    entry_module = types.SimpleNamespace(console_entry_point=boom)
    monkeypatch.setitem(__import__("sys").modules, "spotdl.console.entry_point", entry_module)

    assert launcher._run_spotdl(["download", "https://open.spotify.com/track/example"]) == 1


def test_gettext_patch_returns_null_translation_for_missing_files():
    launcher._patch_gettext_missing_translation_fallback()

    import gettext

    translation = gettext.translation("base", localedir="C:/missing-locale-path")

    assert isinstance(translation, gettext.NullTranslations)
