from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else Path.cwd().resolve()


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", app_root())).resolve()


def user_data_root() -> Path:
    if not is_frozen():
        return app_root()
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    return Path(base).expanduser().resolve() / "AIO Downloader"


def config_dir() -> Path:
    return user_data_root() / "config"


def log_dir() -> Path:
    return user_data_root() / "logs"


def webview_data_dir() -> Path:
    return user_data_root() / "webview"


def managed_tools_root() -> Path:
    return app_root() / "tools"


def managed_bin_dir() -> Path:
    return managed_tools_root() / "bin"


def apply_managed_tool_path() -> None:
    bin_dir = managed_bin_dir()
    path = str(bin_dir)
    existing = os.environ.get("PATH", "")
    parts = existing.split(os.pathsep) if existing else []
    if path not in parts:
        os.environ["PATH"] = os.pathsep.join([path, *parts]) if existing else path


def managed_binary(name: str) -> str:
    exe_name = name if Path(name).suffix else f"{name}.exe" if sys.platform == "win32" else name
    candidate = managed_bin_dir() / exe_name
    return str(candidate) if candidate.exists() else ""


def bundled_binary(name: str) -> str:
    candidates = (
        resource_root() / "bin" / name,
        app_root() / "bin" / name,
        app_root() / "_internal" / "bin" / name,
    )
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def bundled_tool(name: str) -> str:
    return f"__aio_tool__:{name}" if is_frozen() else ""


def is_bundled_tool(value: str, name: str | None = None) -> bool:
    prefix = "__aio_tool__:"
    if not value.startswith(prefix):
        return False
    return name is None or value.removeprefix(prefix) == name
