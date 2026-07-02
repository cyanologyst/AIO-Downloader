from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

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

    profile = profile.strip()
    jar = extract_cookies_from_browser(browser, profile=profile or None)
    if not jar:
        raise RuntimeError("No cookies were exported. Make sure the browser profile is signed in.")

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


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-._")
    return cleaned or "default"
