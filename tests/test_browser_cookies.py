from app.services.browser_cookies import _friendly_cookie_error, _normalize_profile_path


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
