from __future__ import annotations

import re
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path

import httpx
import yt_dlp.cookies as ytdlp_cookies
from websockets.sync.client import connect as websocket_connect
from yt_dlp.cookies import SUPPORTED_BROWSERS, extract_cookies_from_browser

from app.utils.runtime import config_dir


@dataclass(slots=True)
class BrowserProfile:
    name: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path}


BROWSER_LABELS = {
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "brave": "Brave",
    "firefox": "Firefox",
    "chromium": "Chromium",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}

CHROMIUM_BROWSERS = {"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"}


def supported_cookie_browsers() -> list[dict[str, object]]:
    browsers: list[dict[str, object]] = []
    for browser in sorted(SUPPORTED_BROWSERS):
        if browser == "safari" and sys.platform != "darwin":
            continue
        profiles = _detect_profiles(browser)
        browsers.append(
            {
                "id": browser,
                "label": BROWSER_LABELS.get(browser, browser.title()),
                "profiles": [profile.to_dict() for profile in profiles],
            }
        )
    return browsers


def export_browser_cookies(browser: str, profile: str = "") -> dict[str, object]:
    browser = browser.strip().lower()
    if browser not in SUPPORTED_BROWSERS:
        raise ValueError(f"Unsupported browser: {browser}")
    if browser == "safari" and sys.platform != "darwin":
        raise ValueError("Safari cookie export is only available on macOS.")

    profile = _normalize_profile_path(browser, profile.strip())
    try:
        with _patched_cookie_database_open():
            jar = extract_cookies_from_browser(browser, profile=profile or None)
    except Exception as exc:
        if _should_try_chromium_devtools_export(str(exc), browser):
            return export_chromium_cookies_via_devtools(browser, profile)
        raise RuntimeError(_friendly_cookie_error(str(exc), browser)) from exc
    if not jar:
        raise RuntimeError("No cookies were exported. Make sure the browser profile is signed in.")

    return _save_cookie_jar(browser, profile, jar)


def export_chromium_cookies_via_devtools(browser: str, profile: str = "") -> dict[str, object]:
    browser = browser.strip().lower()
    if browser not in CHROMIUM_BROWSERS:
        raise RuntimeError("Chrome DevTools cookie export only works with Chromium-based browsers.")

    executable = _chromium_executable(browser)
    if not executable:
        label = BROWSER_LABELS.get(browser, browser.title())
        raise RuntimeError(f"Could not find {label}. Install it or choose a different browser.")

    source_user_data_dir, profile_name = _resolve_chromium_profile(browser, profile)
    if not source_user_data_dir.exists():
        raise RuntimeError(f"Could not find Chromium user data directory: {source_user_data_dir}")

    temp_user_data_dir = _clone_chromium_user_data_for_cookie_export(source_user_data_dir, profile_name)
    port = _free_local_port()
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={temp_user_data_dir}",
        f"--profile-directory={profile_name}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "about:blank",
    ]
    process = subprocess.Popen(command)
    try:
        websocket_url = _wait_for_devtools_websocket(port)
        cookies = _read_cookies_from_devtools(websocket_url)
        if not cookies:
            raise RuntimeError("Chrome opened, but no cookies were returned. Make sure the selected profile is signed in.")
        jar = ytdlp_cookies.YoutubeDLCookieJar()
        for cookie_data in cookies:
            cookie = _devtools_cookie_to_cookiejar_cookie(cookie_data)
            if cookie:
                jar.set_cookie(cookie)
        if not jar:
            raise RuntimeError("Chrome returned cookies, but none could be exported.")
        return _save_cookie_jar(browser, f"{profile_name}-devtools", jar)
    finally:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        shutil.rmtree(temp_user_data_dir, ignore_errors=True)


@contextmanager
def _patched_cookie_database_open():
    original = ytdlp_cookies._open_database_copy

    def open_database_copy_or_readonly(database_path: str, tmpdir: str):
        try:
            return original(database_path, tmpdir)
        except PermissionError as exc:
            if sys.platform != "win32":
                raise
            try:
                connection = sqlite3.connect(f"{Path(database_path).resolve().as_uri()}?mode=ro&immutable=1", uri=True)
                return connection.cursor()
            except Exception:
                raise exc

    ytdlp_cookies._open_database_copy = open_database_copy_or_readonly
    try:
        yield
    finally:
        ytdlp_cookies._open_database_copy = original


def _detect_profiles(browser: str) -> list[BrowserProfile]:
    if sys.platform != "win32":
        return []
    home = Path.home()
    local = Path.home()
    appdata = Path.home()
    import os

    if os.getenv("LOCALAPPDATA"):
        local = Path(os.environ["LOCALAPPDATA"])
    if os.getenv("APPDATA"):
        appdata = Path(os.environ["APPDATA"])

    roots = {
        "chrome": local / "Google" / "Chrome" / "User Data",
        "edge": local / "Microsoft" / "Edge" / "User Data",
        "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
        "chromium": local / "Chromium" / "User Data",
        "vivaldi": local / "Vivaldi" / "User Data",
        "opera": appdata / "Opera Software" / "Opera Stable",
        "firefox": appdata / "Mozilla" / "Firefox" / "Profiles",
    }
    root = roots.get(browser, home / "__aio_missing_browser_root__")
    if not root.exists():
        return []
    if browser == "firefox":
        return [
            BrowserProfile(profile.name, str(profile.resolve()))
            for profile in sorted(root.iterdir())
            if profile.is_dir() and (profile / "cookies.sqlite").exists()
        ]
    if browser == "opera":
        return [BrowserProfile("Default", str(root.resolve()))]
    candidates = ["Default", *[f"Profile {index}" for index in range(1, 21)]]
    profiles = []
    for name in candidates:
        profile = root / name
        if profile.is_dir():
            profiles.append(BrowserProfile(name, str(profile.resolve())))
    return profiles


def _save_cookie_jar(browser: str, profile: str, jar: ytdlp_cookies.YoutubeDLCookieJar) -> dict[str, object]:
    output_dir = config_dir() / "cookies"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_profile = _safe_filename(Path(profile).name if profile else "default")
    output_path = output_dir / f"{browser}-{safe_profile}.cookies.txt"
    jar.save(str(output_path), ignore_discard=True, ignore_expires=True)
    return {
        "browser": browser,
        "profile": profile,
        "path": str(output_path.resolve()),
        "count": len(jar),
    }


def _normalize_profile_path(browser: str, profile: str) -> str:
    if not profile:
        return ""
    if browser not in CHROMIUM_BROWSERS:
        return profile
    path = Path(profile).expanduser()
    if path.name.lower() == "cookies" and path.parent.name.lower() == "network":
        return str(path.parent.parent.resolve())
    return profile


def _should_try_chromium_devtools_export(message: str, browser: str) -> bool:
    compact = " ".join(message.split()).lower()
    return browser in CHROMIUM_BROWSERS and "failed to decrypt with dpapi" in compact


def _chromium_executable(browser: str) -> Path | None:
    import os

    local = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    program_files = [Path(value) for value in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)")) if value]
    paths = {
        "chrome": [
            local / "Google" / "Chrome" / "Application" / "chrome.exe",
            *[root / "Google" / "Chrome" / "Application" / "chrome.exe" for root in program_files],
        ],
        "edge": [
            local / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            *[root / "Microsoft" / "Edge" / "Application" / "msedge.exe" for root in program_files],
        ],
        "brave": [
            local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            *[root / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe" for root in program_files],
        ],
        "chromium": [
            local / "Chromium" / "Application" / "chrome.exe",
            *[root / "Chromium" / "Application" / "chrome.exe" for root in program_files],
        ],
        "vivaldi": [
            local / "Vivaldi" / "Application" / "vivaldi.exe",
            *[root / "Vivaldi" / "Application" / "vivaldi.exe" for root in program_files],
        ],
    }
    for candidate in paths.get(browser, []):
        if candidate.exists():
            return candidate.resolve()
    return None


def _resolve_chromium_profile(browser: str, profile: str) -> tuple[Path, str]:
    if profile:
        profile_path = Path(profile).expanduser().resolve()
        if profile_path.name.lower() == "cookies" and profile_path.parent.name.lower() == "network":
            profile_path = profile_path.parent.parent
        if profile_path.name.lower() == "network":
            profile_path = profile_path.parent
        return profile_path.parent, profile_path.name

    profiles = _detect_profiles(browser)
    if profiles:
        default = next((item for item in profiles if item.name == "Default"), profiles[0])
        profile_path = Path(default.path).resolve()
        return profile_path.parent, profile_path.name

    import os

    local = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    roots = {
        "chrome": local / "Google" / "Chrome" / "User Data",
        "edge": local / "Microsoft" / "Edge" / "User Data",
        "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
        "chromium": local / "Chromium" / "User Data",
        "vivaldi": local / "Vivaldi" / "User Data",
    }
    return roots.get(browser, local), "Default"


def _clone_chromium_user_data_for_cookie_export(source_user_data_dir: Path, profile_name: str) -> Path:
    temp_user_data_dir = Path(tempfile.mkdtemp(prefix="aio-chrome-cookie-export-"))
    source_user_data_dir = source_user_data_dir.resolve()
    source_profile_dir = source_user_data_dir / profile_name
    target_profile_dir = temp_user_data_dir / profile_name

    if not source_profile_dir.exists():
        shutil.rmtree(temp_user_data_dir, ignore_errors=True)
        raise RuntimeError(f"Could not find Chromium profile directory: {source_profile_dir}")

    try:
        _copy_file_if_exists(source_user_data_dir / "Local State", temp_user_data_dir / "Local State")
        _copy_chromium_profile(source_profile_dir, target_profile_dir)
        _copy_chromium_cookie_database(source_profile_dir, target_profile_dir)
    except Exception:
        shutil.rmtree(temp_user_data_dir, ignore_errors=True)
        raise

    return temp_user_data_dir


def _copy_chromium_profile(source: Path, target: Path) -> None:
    heavy_or_noisy_dirs = {
        "blob_storage",
        "cache",
        "code cache",
        "crashpad",
        "databases",
        "dawncache",
        "file system",
        "gpucache",
        "grshadercache",
        "indexeddb",
        "local storage",
        "optimization hints",
        "safe browsing",
        "service worker",
        "session storage",
        "sessions",
        "shared dictionary",
        "storage",
        "webrtc logs",
    }

    lock_or_live_files = {"lock", "singletoncookie", "singletonlock", "singletonsocket"}

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name.lower() in heavy_or_noisy_dirs | lock_or_live_files}
        if Path(directory).name.lower() == "network":
            ignored.update(name for name in names if name.lower() in {"cookies", "cookies-journal"})
        return ignored

    shutil.copytree(source, target, ignore=ignore)


def _copy_chromium_cookie_database(source_profile_dir: Path, target_profile_dir: Path) -> None:
    source_cookie_db = source_profile_dir / "Network" / "Cookies"
    if not source_cookie_db.exists():
        return
    target_cookie_db = target_profile_dir / "Network" / "Cookies"
    target_cookie_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_cookie_db, target_cookie_db)
    except OSError:
        _sqlite_backup_copy(source_cookie_db, target_cookie_db)
    _copy_file_if_exists(source_profile_dir / "Network" / "Cookies-journal", target_profile_dir / "Network" / "Cookies-journal")


def _copy_file_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _sqlite_backup_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = f"{source.resolve().as_uri()}?mode=ro&immutable=1"
    source_connection = sqlite3.connect(uri, uri=True)
    try:
        target_connection = sqlite3.connect(str(target))
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
    finally:
        source_connection.close()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_devtools_websocket(port: int, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            pages = httpx.get(f"http://127.0.0.1:{port}/json", timeout=1.5).json()
            for page in pages:
                if page.get("webSocketDebuggerUrl"):
                    return str(page["webSocketDebuggerUrl"])
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(
        "Could not connect to the temporary Chrome cookie bridge. AIO Downloader copied your "
        "Chrome profile to a temporary folder, but Chrome did not expose the local DevTools "
        "socket in time. Retry once; if it still fails, use Firefox or a Netscape cookies.txt export."
    ) from last_error


def _read_cookies_from_devtools(websocket_url: str) -> list[dict[str, object]]:
    with websocket_connect(websocket_url, open_timeout=10) as websocket:
        websocket.send(json.dumps({"id": 1, "method": "Network.enable"}))
        _wait_for_devtools_response(websocket, 1)
        websocket.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        response = _wait_for_devtools_response(websocket, 2)
    if "error" in response:
        message = response["error"].get("message", "Chrome DevTools rejected cookie export")
        raise RuntimeError(str(message))
    return list(response.get("result", {}).get("cookies", []))


def _wait_for_devtools_response(websocket, message_id: int) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        message = json.loads(websocket.recv(timeout=2))
        if message.get("id") == message_id:
            return message
    raise RuntimeError("Timed out while waiting for Chrome DevTools cookie export.")


def _devtools_cookie_to_cookiejar_cookie(cookie: dict[str, object]) -> Cookie | None:
    name = str(cookie.get("name") or "")
    value = str(cookie.get("value") or "")
    domain = str(cookie.get("domain") or "")
    path = str(cookie.get("path") or "/")
    if not name or not domain:
        return None
    expires_raw = cookie.get("expires")
    expires = None
    if isinstance(expires_raw, (int, float)) and expires_raw > 0:
        expires = int(expires_raw)
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=path,
        path_specified=bool(path),
        secure=bool(cookie.get("secure")),
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None} if cookie.get("httpOnly") else {},
    )


def _friendly_cookie_error(message: str, browser: str) -> str:
    compact = " ".join(message.split())
    label = BROWSER_LABELS.get(browser, browser.title())
    if "failed to decrypt with dpapi" in compact.lower():
        if browser in CHROMIUM_BROWSERS:
            return (
                f"{label} blocked cookie decryption with Windows DPAPI. This is common with recent "
                "Chromium-based browsers and cannot always be bypassed by external apps. "
                "Recommended fix: sign in with Firefox and fetch Firefox cookies, or export a Netscape "
                "cookies.txt file from your browser and select that file here."
            )
        return (
            f"{label} cookies could not be decrypted with Windows DPAPI. Try fetching from another "
            "browser profile or select a Netscape cookies.txt file manually."
        )
    if "could not copy chrome cookie database" in compact.lower() or "permission" in compact.lower():
        return (
            f"{label} is locking its cookie database. Fully close {label} first "
            "(including background/tray processes), then click Fetch cookies again. "
            "If it still fails, choose Firefox or export a Netscape cookies.txt file manually."
        )
    return compact or "Cookie export failed."


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-._")
    return cleaned or "default"
