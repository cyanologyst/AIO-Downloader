from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock
from typing import Any

from dotenv import load_dotenv

from app.utils.runtime import (
    apply_managed_tool_path,
    bundled_binary,
    bundled_tool,
    config_dir,
    default_download_dir,
    managed_binary,
)


def _bool(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    download_dir: str = str(default_download_dir())
    web_host: str = "127.0.0.1"
    web_port: int = 5000
    ytdlp_cookies_file: str = ""
    ytdlp_proxy: str = ""
    default_video_quality: str = "best"
    default_audio_format: str = "mp3"
    max_concurrent_downloads: int = 2
    manga_auto_convert_pdf: bool = True
    manga_remove_images_after_pdf: bool = False
    aria2_bin: str = "aria2c"
    aria2_rpc_host: str = "127.0.0.1"
    aria2_rpc_port: int = 6800
    aria2_rpc_secret: str = ""
    ytdlp_bin: str = "yt-dlp"
    ffmpeg_bin: str = "ffmpeg"
    spotdl_bin: str = "spotdl"
    deno_bin: str = ""
    tpb_api_url: str = "https://apibay.org"
    rarbg_base_url: str = "https://rargb.to"
    prowlarr_url: str = "http://127.0.0.1:9696"
    prowlarr_api_key: str = ""
    prowlarr_search_limit: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        apply_managed_tool_path()
        bundled_aria2 = bundled_binary("aria2c.exe") or bundled_binary("aria2c")
        bundled_ffmpeg = bundled_binary("ffmpeg.exe") or bundled_binary("ffmpeg")
        bundled_deno = bundled_binary("deno.exe") or bundled_binary("deno")
        managed_aria2 = managed_binary("aria2c")
        managed_ytdlp = managed_binary("yt-dlp")
        managed_ffmpeg = managed_binary("ffmpeg")
        managed_spotdl = managed_binary("spotdl")
        managed_deno = managed_binary("deno")
        default_download = str(default_download_dir())
        return cls(
            download_dir=os.getenv("DOWNLOAD_DIR", default_download),
            web_host=os.getenv("WEB_HOST", "127.0.0.1"),
            web_port=int(os.getenv("WEB_PORT", "5000")),
            ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE", ""),
            ytdlp_proxy=os.getenv("YTDLP_PROXY", ""),
            default_video_quality=os.getenv("DEFAULT_VIDEO_QUALITY", "best"),
            default_audio_format=os.getenv("DEFAULT_AUDIO_FORMAT", "mp3"),
            max_concurrent_downloads=max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))),
            manga_auto_convert_pdf=_bool(os.getenv("MANGA_AUTO_CONVERT_PDF"), True),
            manga_remove_images_after_pdf=_bool(
                os.getenv("MANGA_REMOVE_IMAGES_AFTER_PDF"), False
            ),
            aria2_bin=os.getenv("ARIA2_BIN") or managed_aria2 or bundled_aria2 or "aria2c",
            aria2_rpc_host=os.getenv("ARIA2_RPC_HOST", "127.0.0.1"),
            aria2_rpc_port=int(os.getenv("ARIA2_RPC_PORT", "6800")),
            aria2_rpc_secret=os.getenv("ARIA2_RPC_SECRET", ""),
            ytdlp_bin=os.getenv("YTDLP_BIN") or managed_ytdlp or bundled_tool("yt-dlp") or "yt-dlp",
            ffmpeg_bin=os.getenv("FFMPEG_BIN") or managed_ffmpeg or bundled_ffmpeg or "ffmpeg",
            spotdl_bin=os.getenv("SPOTDL_BIN") or managed_spotdl or bundled_tool("spotdl") or "spotdl",
            deno_bin=os.getenv("DENO_BIN") or managed_deno or bundled_deno or shutil.which("deno") or "",
            tpb_api_url=os.getenv("TPB_API_URL", "https://apibay.org"),
            rarbg_base_url=os.getenv("RARBG_BASE_URL", "https://rargb.to"),
            prowlarr_url=os.getenv("PROWLARR_URL", "http://127.0.0.1:9696"),
            prowlarr_api_key=os.getenv("PROWLARR_API_KEY", ""),
            prowlarr_search_limit=max(1, min(100, int(os.getenv("PROWLARR_SEARCH_LIMIT", "20")))),
        )

    @property
    def download_path(self) -> Path:
        return Path(self.download_dir).expanduser().resolve()

    def public_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key
            in {
                "download_dir",
                "ytdlp_cookies_file",
                "ytdlp_proxy",
                "default_video_quality",
                "default_audio_format",
                "max_concurrent_downloads",
                "manga_auto_convert_pdf",
                "manga_remove_images_after_pdf",
                "tpb_api_url",
                "rarbg_base_url",
                "prowlarr_url",
                "prowlarr_api_key",
                "prowlarr_search_limit",
                "aria2_bin",
                "ytdlp_bin",
                "ffmpeg_bin",
                "spotdl_bin",
                "deno_bin",
            }
        }


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "settings.json"
        self._lock = RLock()
        self._settings = Settings.from_env()
        self._load_file()

    def _load_file(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        valid = {field.name for field in fields(Settings)}
        merged = asdict(self._settings)
        merged.update({key: value for key, value in data.items() if key in valid})
        self._settings = Settings(**merged)

    def get(self) -> Settings:
        with self._lock:
            return Settings(**asdict(self._settings))

    def update(self, data: dict[str, Any]) -> Settings:
        with self._lock:
            allowed = set(self._settings.public_dict())
            unknown = set(data) - allowed
            if unknown:
                raise ValueError(f"unsupported settings: {', '.join(sorted(unknown))}")
            merged = asdict(self._settings)
            merged.update(data)
            merged["max_concurrent_downloads"] = max(
                1, min(16, int(merged["max_concurrent_downloads"]))
            )
            merged["prowlarr_search_limit"] = max(
                1, min(100, int(merged["prowlarr_search_limit"]))
            )
            if merged["default_video_quality"] not in {"best", "1080p", "720p", "480p"}:
                raise ValueError("invalid default video quality")
            if merged["default_audio_format"] not in {"mp3", "m4a", "opus"}:
                raise ValueError("invalid default audio format")
            self._settings = Settings(**merged)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._settings.public_dict(), indent=2),
                encoding="utf-8",
            )
            return self.get()
