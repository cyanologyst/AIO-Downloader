from pathlib import Path

from app.services import browser_cookies
from app.services.browser_cookies import (
    _friendly_cookie_error,
    _normalize_profile_path,
    _resolve_chromium_profile,
    _should_try_chromium_devtools_export,
)


def test_normalize_chromium_cookie_database_path_to_profile():
    profile = _normalize_profile_path(
        "chrome",
        r"C:\Users\Example\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies",
    )

    assert profile.endswith(r"Google\Chrome\User Data\Default")


def test_friendly_cookie_error_explains_locked_chrome_database():
    message = _friendly_cookie_error("Could not copy Chrome cookie database", "chrome")

    assert "locking its cookie database" in message
    assert "Fetch cookies again" in message


def test_friendly_cookie_error_explains_chromium_dpapi_limit():
    message = _friendly_cookie_error(
        "Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927 for more info",
        "chrome",
    )

    assert "blocked cookie decryption" in message
    assert "Firefox" in message
    assert "cookies.txt" in message


def test_dpapi_error_triggers_chromium_devtools_fallback():
    assert _should_try_chromium_devtools_export("Failed to decrypt with DPAPI", "chrome")
    assert not _should_try_chromium_devtools_export("Failed to decrypt with DPAPI", "firefox")


def test_resolve_chromium_profile_from_cookie_database_path():
    user_data, profile = _resolve_chromium_profile(
        "chrome",
        r"C:\Users\Example\AppData\Local\Google\Chrome\User Data\Profile 2\Network\Cookies",
    )

    assert profile == "Profile 2"
    assert str(user_data).endswith(r"Google\Chrome\User Data")


def test_devtools_cookie_export_saves_cookie_jar(monkeypatch, tmp_path):
    profile_dir = tmp_path / "Default"
    cookie_dir = profile_dir / "Network"
    cookie_dir.mkdir(parents=True)
    (cookie_dir / "Cookies").write_bytes(b"placeholder")

    monkeypatch.setattr(browser_cookies, "_chromium_executable", lambda _browser: Path("C:/Chrome/chrome.exe"))
    monkeypatch.setattr(browser_cookies, "_resolve_chromium_profile", lambda _browser, _profile: (tmp_path, "Default"))
    monkeypatch.setattr(browser_cookies, "_free_local_port", lambda: 9222)
    monkeypatch.setattr(browser_cookies, "_wait_for_devtools_websocket", lambda _port: "ws://127.0.0.1/devtools/page/1")
    monkeypatch.setattr(
        browser_cookies,
        "_read_cookies_from_devtools",
        lambda _url: [
            {
                "name": "SID",
                "value": "abc",
                "domain": ".youtube.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": 4102444800,
            }
        ],
    )
    monkeypatch.setattr(browser_cookies, "config_dir", lambda: tmp_path / "config")

    class FakeProcess:
        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(browser_cookies.subprocess, "Popen", lambda _command: FakeProcess())

    result = browser_cookies.export_chromium_cookies_via_devtools("chrome", str(tmp_path / "Default"))

    assert result["count"] == 1
    assert Path(result["path"]).read_text(encoding="utf-8").count("youtube.com") == 1
