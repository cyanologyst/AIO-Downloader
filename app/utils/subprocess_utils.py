from __future__ import annotations

import asyncio
import subprocess
import shutil
import sys
from typing import Any


def require_executable(name: str, friendly_name: str | None = None) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"{friendly_name or name} executable not found: {name}")
    return resolved


def subprocess_window_options() -> dict[str, object]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


async def terminate_process(process: asyncio.subprocess.Process | None) -> None:
    if not process or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


async def terminate_process_any(process: Any | None) -> None:
    if not process:
        return
    if isinstance(process, asyncio.subprocess.Process):
        await terminate_process(process)
        return
    if getattr(process, "poll", lambda: None)() is not None:
        return
    process.terminate()
    try:
        await asyncio.to_thread(process.wait, timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        await asyncio.to_thread(process.wait)
