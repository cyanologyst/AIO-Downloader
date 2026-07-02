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
