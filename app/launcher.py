from __future__ import annotations

import sys

from app.utils.runtime import app_root


def _run_ytdlp(args: list[str]) -> int:
    from yt_dlp import main

    sys.argv = ["yt-dlp", *args]
    main()
    return 0


def _run_spotdl(args: list[str]) -> int:
    from spotdl.console.entry_point import console_entry_point

    sys.argv = ["spotdl", *args]
    console_entry_point()
    return 0


def main() -> None:
    import os

    os.chdir(app_root())
    if len(sys.argv) >= 3 and sys.argv[1] == "--aio-tool":
        tool = sys.argv[2]
        args = sys.argv[3:]
        if tool == "yt-dlp":
            raise SystemExit(_run_ytdlp(args))
        if tool == "spotdl":
            raise SystemExit(_run_spotdl(args))
        raise SystemExit(f"Unknown bundled AIO tool: {tool}")

    from app.desktop import main as desktop_main

    desktop_main()


if __name__ == "__main__":
    main()
