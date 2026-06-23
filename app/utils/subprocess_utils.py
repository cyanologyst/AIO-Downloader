from __future__ import annotations

import asyncio
import shutil


def require_executable(name: str, friendly_name: str | None = None) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"{friendly_name or name} executable not found: {name}")
    return resolved


async def terminate_process(process: asyncio.subprocess.Process | None) -> None:
    if not process or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
