from app.config.settings import Settings, SettingsStore


def test_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_DIR", "Custom")
    monkeypatch.setenv("MAX_CONCURRENT_DOWNLOADS", "4")
    monkeypatch.setenv("MANGA_AUTO_CONVERT_PDF", "false")
    settings = Settings.from_env()
    assert settings.download_dir == "Custom"
    assert settings.max_concurrent_downloads == 4
    assert settings.manga_auto_convert_pdf is False


def test_settings_store_persists_public_values(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    updated = store.update({"default_audio_format": "m4a", "max_concurrent_downloads": 3})
    assert updated.default_audio_format == "m4a"
    assert SettingsStore(tmp_path / "settings.json").get().max_concurrent_downloads == 3
