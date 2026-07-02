from pathlib import Path

from app.config.settings import Settings, SettingsStore
from app.services import tool_installer
from app.services.tool_installer import ToolInstallOutcome, install_missing_tools
from app.web.app import create_app


def test_install_missing_tools_installs_unavailable_tool(monkeypatch, tmp_path):
    installed = tmp_path / "bin" / "yt-dlp.exe"
    installed.parent.mkdir()
    installed.write_text("fake exe", encoding="utf-8")

    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(tool_installer, "apply_managed_tool_path", lambda: None)
    monkeypatch.setattr(tool_installer, "managed_bin_dir", lambda: tmp_path / "isolated-bin")
    monkeypatch.setattr(tool_installer, "managed_binary", lambda _name: "")
    monkeypatch.setattr(tool_installer, "_install_tool", lambda _name: str(installed))

    settings = Settings(ytdlp_bin="missing-ytdlp")
    outcomes, paths = install_missing_tools(settings, ["yt-dlp"])

    assert outcomes[0].status == "installed"
    assert paths == {"ytdlp_bin": str(installed)}


def test_install_missing_route_updates_runtime_settings(monkeypatch, tmp_path):
    fake_deno = tmp_path / "deno.exe"
    fake_deno.write_text("fake exe", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = create_app(store)

    def fake_install(_settings, _tools=None, force_tools=None):
        return (
            [ToolInstallOutcome("deno", "installed", str(fake_deno), "Installed successfully")],
            {"deno_bin": str(fake_deno)},
        )

    monkeypatch.setattr("app.web.app.install_missing_tools", fake_install)

    response = app.test_client().post("/api/tools/install-missing", json={})

    assert response.status_code == 200
    assert response.get_json()["installed"] == ["deno"]
    assert store.get().deno_bin == str(fake_deno)


def test_portable_lite_route_forces_bundled_ytdlp_replacement(monkeypatch, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update({"ytdlp_bin": str(tmp_path / "_internal" / "AIO Downloader.exe")})
    app = create_app(store)
    observed: dict[str, object] = {}

    def fake_install(_settings, _tools=None, force_tools=None):
        observed["force_tools"] = set(force_tools or [])
        fresh = tmp_path / "tools" / "bin" / "yt-dlp.exe"
        return (
            [ToolInstallOutcome("yt-dlp", "installed", str(fresh), "Installed successfully")],
            {"ytdlp_bin": str(fresh)},
        )

    monkeypatch.setattr("app.web.app.is_portable_lite", lambda: True)
    monkeypatch.setattr("app.web.app.is_bundled_tool", lambda path, name: name == "yt-dlp")
    monkeypatch.setattr("app.web.app.install_missing_tools", fake_install)

    response = app.test_client().post("/api/tools/install-missing", json={})

    assert response.status_code == 200
    assert "yt-dlp" in observed["force_tools"]
    assert store.get().ytdlp_bin.endswith("yt-dlp.exe")


def test_install_missing_tools_can_force_replace_available_tool(monkeypatch, tmp_path):
    installed = tmp_path / "bin" / "yt-dlp.exe"
    installed.parent.mkdir()
    installed.write_text("fresh exe", encoding="utf-8")

    monkeypatch.setattr(tool_installer, "apply_managed_tool_path", lambda: None)
    monkeypatch.setattr(tool_installer, "managed_bin_dir", lambda: tmp_path / "isolated-bin")
    monkeypatch.setattr(tool_installer, "resolve_tool", lambda _name, _configured="": "bundled-yt-dlp")
    monkeypatch.setattr(tool_installer, "_install_tool", lambda _name: str(installed))

    settings = Settings(ytdlp_bin="bundled-yt-dlp")
    outcomes, paths = install_missing_tools(settings, ["yt-dlp"], force_tools=["yt-dlp"])

    assert outcomes[0].status == "installed"
    assert paths == {"ytdlp_bin": str(installed)}
