from __future__ import annotations

try:
    from app.utils.windows_asyncio import install_socketpair_retry

    install_socketpair_retry()
except Exception:
    pass
