from __future__ import annotations

import sys
import traceback

from app.utils.runtime import app_root


def _run_ytdlp(args: list[str]) -> int:
    from yt_dlp import main

    sys.argv = ["yt-dlp", *args]
    main()
    return 0


def _run_spotdl(args: list[str]) -> int:
    try:
        _patch_gettext_missing_translation_fallback()
        from spotdl.console.entry_point import console_entry_point

        sys.argv = ["spotdl", *args]
        console_entry_point()
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1 if exc.code else 0
        return code
    except BaseException:
        traceback.print_exc()
        return 1


def _patch_gettext_missing_translation_fallback() -> None:
    import gettext

    original = gettext.translation

    if getattr(original, "_aio_missing_translation_fallback", False):
        return

    def translation_with_fallback(domain, localedir=None, languages=None, class_=None, fallback=False):
        try:
            return original(domain, localedir=localedir, languages=languages, class_=class_, fallback=fallback)
        except FileNotFoundError:
            return gettext.NullTranslations()

    translation_with_fallback._aio_missing_translation_fallback = True
    gettext.translation = translation_with_fallback


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
