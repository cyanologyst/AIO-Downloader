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

    def fake_install(_settings, _tools=None):
        return (
            [ToolInstallOutcome("deno", "installed", str(fake_deno), "Installed successfully")],
            {"deno_bin": str(fake_deno)},
        )

    monkeypatch.setattr("app.web.app.install_missing_tools", fake_install)

    response = app.test_client().post("/api/tools/install-missing", json={})

    assert response.status_code == 200
    assert response.get_json()["installed"] == ["deno"]
    assert store.get().deno_bin == str(fake_deno)
