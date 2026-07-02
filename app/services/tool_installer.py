from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.config.settings import Settings
from app.utils.runtime import (
    apply_managed_tool_path,
    is_bundled_tool,
    managed_bin_dir,
    managed_binary,
)
from app.utils.subprocess_utils import subprocess_window_options


TOOL_SETTINGS = {
    "aria2c": "aria2_bin",
    "yt-dlp": "ytdlp_bin",
    "ffmpeg": "ffmpeg_bin",
    "spotdl": "spotdl_bin",
    "deno": "deno_bin",
}

UPDATABLE_TOOLS = ("aria2c", "yt-dlp", "ffmpeg", "deno")

WINDOWS_DIRECT_DOWNLOADS = {
    "yt-dlp": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "deno": "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
    "ffmpeg": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
}


@dataclass(slots=True)
class ToolInstallOutcome:
    name: str
    status: str
    path: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "path": self.path,
            "message": self.message,
        }


def tool_health(settings: Settings) -> dict[str, bool]:
    apply_managed_tool_path()
    return {name: bool(resolve_tool(name, getattr(settings, key, ""))) for name, key in TOOL_SETTINGS.items()}


def resolve_tool(name: str, configured: str = "") -> str:
    apply_managed_tool_path()
    if configured:
        if is_bundled_tool(configured, name):
            return configured
        configured_path = Path(configured).expanduser()
        if configured_path.exists():
            return str(configured_path.resolve())
        resolved = shutil.which(configured)
        if resolved:
            return resolved
    managed = managed_binary(name)
    if managed:
        return managed
    return shutil.which(name) or ""


def install_missing_tools(
    settings: Settings,
    tools: Iterable[str] | None = None,
    force_tools: Iterable[str] | None = None,
) -> tuple[list[ToolInstallOutcome], dict[str, str]]:
    apply_managed_tool_path()
    requested = list(tools or TOOL_SETTINGS)
    unknown = sorted(set(requested) - set(TOOL_SETTINGS))
    if unknown:
        raise ValueError(f"Unsupported tool(s): {', '.join(unknown)}")
    forced = set(force_tools or ())
    unknown_forced = sorted(forced - set(TOOL_SETTINGS))
    if unknown_forced:
        raise ValueError(f"Unsupported forced tool(s): {', '.join(unknown_forced)}")

    outcomes: list[ToolInstallOutcome] = []
    installed_paths: dict[str, str] = {}
    managed_bin_dir().mkdir(parents=True, exist_ok=True)

    for name in requested:
        configured = getattr(settings, TOOL_SETTINGS[name], "")
        existing = resolve_tool(name, configured)
        if existing and name not in forced:
            outcomes.append(ToolInstallOutcome(name, "ready", existing, "Already available"))
            continue
        try:
            installed = _install_tool(name)
            installed_paths[TOOL_SETTINGS[name]] = installed
            outcomes.append(ToolInstallOutcome(name, "installed", installed, "Installed successfully"))
        except Exception as exc:
            outcomes.append(ToolInstallOutcome(name, "failed", "", str(exc)))
    return outcomes, installed_paths


def _install_tool(name: str) -> str:
    if name == "spotdl":
        return _install_spotdl()
    if sys.platform != "win32":
        raise RuntimeError(f"Automatic {name} install is currently packaged for Windows builds.")
    if name == "aria2c":
        return _install_aria2c()
    if name == "yt-dlp":
        return _install_direct_exe(name, WINDOWS_DIRECT_DOWNLOADS[name])
    if name == "deno":
        return _install_zip_member(name, WINDOWS_DIRECT_DOWNLOADS[name], "deno.exe")
    if name == "ffmpeg":
        return _install_ffmpeg()
    raise RuntimeError(f"No installer is registered for {name}.")


def _install_direct_exe(name: str, url: str) -> str:
    destination = managed_bin_dir() / f"{name}.exe"
    with tempfile.TemporaryDirectory(prefix="aio-tool-") as tmp:
        download = Path(tmp) / destination.name
        _download(url, download)
        shutil.move(str(download), destination)
    return str(destination.resolve())


def _install_zip_member(name: str, url: str, member_suffix: str) -> str:
    destination = managed_bin_dir() / member_suffix
    with tempfile.TemporaryDirectory(prefix="aio-tool-") as tmp:
        archive = Path(tmp) / f"{name}.zip"
        _download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            member = _first_zip_member(zf, member_suffix)
            zf.extract(member, tmp)
            shutil.move(str(Path(tmp) / member), destination)
    return str(destination.resolve())


def _install_ffmpeg() -> str:
    ffmpeg_path = managed_bin_dir() / "ffmpeg.exe"
    ffprobe_path = managed_bin_dir() / "ffprobe.exe"
    with tempfile.TemporaryDirectory(prefix="aio-tool-") as tmp:
        archive = Path(tmp) / "ffmpeg.zip"
        _download(WINDOWS_DIRECT_DOWNLOADS["ffmpeg"], archive)
        with zipfile.ZipFile(archive) as zf:
            for exe_name, destination in {"ffmpeg.exe": ffmpeg_path, "ffprobe.exe": ffprobe_path}.items():
                member = _first_zip_member(zf, f"/bin/{exe_name}")
                zf.extract(member, tmp)
                shutil.move(str(Path(tmp) / member), destination)
    return str(ffmpeg_path.resolve())


def _install_aria2c() -> str:
    with urllib.request.urlopen(
        urllib.request.Request(
            "https://api.github.com/repos/aria2/aria2/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "AIO-Downloader"},
        ),
        timeout=30,
    ) as response:
        release = json.loads(response.read().decode("utf-8"))
    assets = release.get("assets") or []
    url = ""
    for asset in assets:
        asset_name = str(asset.get("name") or "").lower()
        if asset_name.endswith(".zip") and "win-64bit" in asset_name:
            url = str(asset.get("browser_download_url") or "")
            break
    if not url:
        raise RuntimeError("Could not find the latest aria2 Windows x64 release asset.")
    return _install_zip_member("aria2c", url, "aria2c.exe")


def _install_spotdl() -> str:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "spotdl>=4.2,<5"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **subprocess_window_options(),
    )
    scripts_dir = Path(sysconfig.get_path("scripts"))
    os.environ["PATH"] = os.pathsep.join([str(scripts_dir), os.environ.get("PATH", "")])
    resolved = shutil.which("spotdl") or shutil.which("spotDL")
    if not resolved:
        raise RuntimeError("spotDL installed, but the spotdl command was not found.")
    return resolved


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "AIO-Downloader"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _first_zip_member(zf: zipfile.ZipFile, suffix: str) -> str:
    normalized = suffix.replace("\\", "/").lower()
    for member in zf.namelist():
        if member.replace("\\", "/").lower().endswith(normalized):
            return member
    raise RuntimeError(f"Archive did not contain {suffix}.")
