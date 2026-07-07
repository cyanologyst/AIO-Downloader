from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
import yt_dlp

logger = logging.getLogger(__name__)

SPOTIFY_URL_RE = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[a-z]{2,}/)?|spotify:)"
    r"(?P<kind>playlist|album|track)[/:](?P<id>[A-Za-z0-9]+)",
    re.I,
)

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>')
RESERVED_FILENAME_CHARS = '<>:"/\\|?*\x00-\x1f'
RESERVED_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SpotifyFallbackError(RuntimeError):
    """Raised when the public Spotify fallback cannot resolve or download."""


@dataclass(slots=True)
class SpotifyTrack:
    id: str
    title: str
    artists: str
    album: str
    release_date: str
    cover_url: str
    duration_ms: int | None = None
    position: int | None = None


@dataclass(slots=True)
class SpotifyCollection:
    kind: str
    id: str
    title: str
    owner: str
    cover_url: str
    tracks: list[SpotifyTrack]


def parse_spotify_url(url: str) -> tuple[str, str]:
    match = SPOTIFY_URL_RE.search(url or "")
    if not match:
        raise SpotifyFallbackError("Invalid Spotify track, album, or playlist URL.")
    return match.group("kind").lower(), match.group("id")


def sanitize_filename(value: str, fallback: str = "Unknown") -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    cleaned = "".join(ch for ch in normalized if ch not in RESERVED_FILENAME_CHARS)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".", 1)[0].upper() in RESERVED_DEVICE_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def cap_filename(name: str, max_bytes: int = 245) -> str:
    if len(name.encode("utf-8")) <= max_bytes:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 10 or " " in ext:
        stem, ext = name, ""
    suffix = f".{ext}" if ext else ""
    budget = max(1, max_bytes - len(suffix.encode("utf-8")))
    stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore").rstrip(" .")
    return f"{stem}{suffix}" if stem else f"file{suffix}"


def _resolve_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _deep_find_entity(data: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 8:
        return None
    if isinstance(data, dict):
        if "trackList" in data or data.get("type") in {"playlist", "album", "track"}:
            return data
        for value in data.values():
            found = _deep_find_entity(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _deep_find_entity(value, depth + 1)
            if found is not None:
                return found
    return None


def _largest_image_url(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    sources = value.get("sources")
    if isinstance(sources, list) and sources:
        for item in reversed(sources):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    images = value.get("image")
    if isinstance(images, list) and images:
        for item in reversed(images):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return ""


class SpotifyPublicClient:
    """Spotify public/embed metadata client inspired by Sunnify's approach.

    It intentionally avoids spotDL's anonymous client-token path. Public embed
    pages carry enough metadata for personal-use track/album/playlist fallback.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        self._token: str = ""
        self._token_expires_at = 0.0

    def close(self) -> None:
        self._client.close()

    def resolve(self, url: str) -> SpotifyCollection:
        kind, spotify_id = parse_spotify_url(url)
        if kind == "track":
            track = self.get_track(spotify_id)
            return SpotifyCollection(
                kind=kind,
                id=spotify_id,
                title=track.title,
                owner=track.artists,
                cover_url=track.cover_url,
                tracks=[track],
            )
        return self.get_collection(kind, spotify_id)

    def get_collection(self, kind: str, spotify_id: str) -> SpotifyCollection:
        data = self._fetch_embed(kind, spotify_id)
        entity = self._extract_entity(data)
        title = str(entity.get("name") or entity.get("title") or "Spotify collection")
        owner = str(entity.get("subtitle") or "")
        cover_url = _largest_image_url(entity.get("coverArt")) or _largest_image_url(
            entity.get("visualIdentity")
        )
        album_name = title if kind == "album" else ""
        tracks = list(self._tracks_from_entity(entity, album_name=album_name))
        if kind == "playlist":
            tracks.extend(self._spclient_remaining_tracks(spotify_id, {track.id for track in tracks}))
        return SpotifyCollection(kind, spotify_id, title, owner, cover_url, tracks)

    def get_track(self, track_id: str) -> SpotifyTrack:
        data = self._fetch_embed("track", track_id)
        entity = self._extract_entity(data)
        title = str(entity.get("name") or entity.get("title") or "Unknown Track")
        artists = self._artists_from_value(entity.get("artists")) or str(entity.get("subtitle") or "")
        cover_url = _largest_image_url(entity.get("visualIdentity")) or _largest_image_url(
            entity.get("coverArt")
        )
        release_date = self._release_date(entity.get("releaseDate"))
        return SpotifyTrack(
            id=track_id,
            title=title,
            artists=artists,
            album=self._track_album_from_page(track_id),
            release_date=release_date,
            cover_url=cover_url,
            duration_ms=self._duration_ms(entity.get("duration")),
        )

    def _fetch_embed(self, kind: str, spotify_id: str) -> dict[str, Any]:
        url = f"https://open.spotify.com/embed/{kind}/{spotify_id}"
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self._client.get(url)
                if response.status_code == 429:
                    raise SpotifyFallbackError("Spotify public metadata rate limited the request.")
                if response.status_code in {401, 403, 404}:
                    raise SpotifyFallbackError(
                        f"Spotify public metadata is unavailable for this {kind}."
                    )
                response.raise_for_status()
                match = NEXT_DATA_RE.search(response.text)
                if not match:
                    raise SpotifyFallbackError("Spotify embed page did not include metadata.")
                data = json.loads(match.group(1))
                self._cache_token(data)
                return data
            except (httpx.HTTPError, json.JSONDecodeError, SpotifyFallbackError) as exc:
                last_error = exc
                if isinstance(exc, SpotifyFallbackError) and "unavailable" in str(exc):
                    break
                time.sleep(1.25 * (2**attempt))
        raise SpotifyFallbackError(str(last_error or "Spotify metadata fetch failed."))

    def _cache_token(self, data: dict[str, Any]) -> None:
        paths = (
            ("props", "pageProps", "state", "settings", "session"),
            ("props", "pageProps", "settings", "session"),
            ("props", "pageProps", "session"),
        )
        for path in paths:
            session = _resolve_path(data, path)
            if isinstance(session, dict) and session.get("accessToken"):
                self._token = str(session["accessToken"])
                expiry_ms = session.get("accessTokenExpirationTimestampMs") or 0
                self._token_expires_at = float(expiry_ms) / 1000 if expiry_ms else 0
                return

    def _extract_entity(self, data: dict[str, Any]) -> dict[str, Any]:
        paths = (
            ("props", "pageProps", "state", "data", "entity"),
            ("props", "pageProps", "data", "entity"),
            ("props", "pageProps", "entity"),
        )
        for path in paths:
            entity = _resolve_path(data, path)
            if isinstance(entity, dict):
                return entity
        entity = _deep_find_entity(data)
        if isinstance(entity, dict):
            return entity
        raise SpotifyFallbackError("Could not find Spotify metadata entity.")

    def _tracks_from_entity(
        self, entity: dict[str, Any], *, album_name: str = ""
    ) -> Iterable[SpotifyTrack]:
        track_list = entity.get("trackList")
        if not isinstance(track_list, list):
            return
        for position, item in enumerate(track_list, start=1):
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "")
            track_id = uri.rsplit(":", 1)[-1] if uri.startswith("spotify:track:") else ""
            if not track_id:
                continue
            title = str(item.get("title") or item.get("name") or "Unknown Track")
            artists = self._artists_from_value(item.get("artists")) or str(item.get("subtitle") or "")
            yield SpotifyTrack(
                id=track_id,
                title=title,
                artists=artists,
                album=album_name,
                release_date=self._release_date(item.get("releaseDate")),
                cover_url="",
                duration_ms=self._duration_ms(item.get("duration")),
                position=position,
            )

    def _spclient_remaining_tracks(
        self, playlist_id: str, known_ids: set[str]
    ) -> list[SpotifyTrack]:
        if not self._token or (self._token_expires_at and time.time() > self._token_expires_at - 60):
            try:
                self._fetch_embed("playlist", playlist_id)
            except SpotifyFallbackError:
                return []
        if not self._token:
            return []
        try:
            response = self._client.get(
                f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=30,
            )
            if response.status_code != 200:
                return []
            data = response.json()
        except Exception:
            return []
        items = (((data.get("contents") or {}).get("items")) or [])
        tracks: list[SpotifyTrack] = []
        for position, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "")
            if not uri.startswith("spotify:track:"):
                continue
            track_id = uri.rsplit(":", 1)[-1]
            if track_id in known_ids:
                continue
            try:
                track = self.get_track(track_id)
            except SpotifyFallbackError:
                track = SpotifyTrack(
                    id=track_id,
                    title=f"Track {track_id}",
                    artists="Unknown Artist",
                    album="",
                    release_date="",
                    cover_url="",
                )
            track.position = position
            tracks.append(track)
        return tracks

    def _track_album_from_page(self, track_id: str) -> str:
        try:
            response = self._client.get(
                f"https://open.spotify.com/track/{track_id}",
                headers={"User-Agent": "facebookexternalhit/1.1"},
                timeout=15,
            )
            if response.status_code != 200:
                return ""
        except httpx.HTTPError:
            return ""
        match = re.search(
            r'<meta\s+(?=[^>]*\bproperty="og:description")[^>]*\bcontent="([^"]*)"',
            response.text,
            re.I,
        )
        if not match:
            return ""
        parts = html.unescape(match.group(1)).split(" · ")
        return parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _artists_from_value(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(
                str(item.get("name") or "") for item in value if isinstance(item, dict)
            ).strip(", ")
        return str(value or "")

    @staticmethod
    def _release_date(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("isoString") or "")[:10]
        return str(value or "")[:10]

    @staticmethod
    def _duration_ms(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _normalize(value: str) -> str:
    value = "".join(
        ch for ch in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(ch)
    )
    value = value.casefold()
    value = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", value)
    value = re.sub(r"\b(?:feat\.?|ft\.?)\s+.*$", "", value)
    value = value.replace("'", "").replace("’", "")
    value = "".join(ch if ch.isalnum() else " " for ch in value)
    return re.sub(r"\s+", " ", value).strip()


def _title_core(value: str) -> str:
    return (value or "").split(" - ", 1)[0]


def _title_matches(candidate: str, expected: str) -> bool:
    candidate_norm = _normalize(candidate)
    expected_norm = _normalize(_title_core(expected))
    if not candidate_norm or not expected_norm:
        return False
    if len(expected_norm) >= 4:
        return expected_norm in candidate_norm
    return expected_norm in candidate_norm.split()


def _artist_matches(candidate: str, artists: str) -> bool:
    candidate_norm = _normalize(candidate)
    for token in re.split(r"[,&]+|\s+(?:feat\.?|ft\.?)\s+", artists or "", flags=re.I):
        artist = _normalize(token)
        if artist and artist in candidate_norm:
            return True
    return False


class SpotifyPublicAudioDownloader:
    def __init__(self, *, ffmpeg: str = "", cookies_file: str = "") -> None:
        self.ffmpeg = ffmpeg
        self.cookies_file = cookies_file

    def download_track(
        self,
        track: SpotifyTrack,
        destination: Path,
        audio_format: str,
        *,
        progress_hook: Any | None = None,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        audio_format = audio_format if audio_format in {"mp3", "m4a", "opus"} else "mp3"
        expected_path = destination.with_suffix(f".{audio_format}")
        output_template = str(destination.with_suffix(".%(ext)s"))
        query = f"ytsearch5:{track.title} {track.artists} audio"
        video_url = self._select_video(query, track)
        if not video_url:
            simplified = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", f"{track.title} {track.artists} audio")
            video_url = self._select_video(f"ytsearch5:{simplified}", track)
        if not video_url:
            raise SpotifyFallbackError(f"No confident YouTube match for {track.title}.")

        ydl_base: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "retries": 5,
            "socket_timeout": 20,
            "concurrent_fragment_downloads": 4,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": audio_format}
            ],
        }
        if audio_format in {"mp3", "m4a", "opus"}:
            ydl_base["postprocessors"][0]["preferredquality"] = "192"
        if self.ffmpeg:
            ydl_base["ffmpeg_location"] = self.ffmpeg
        if self.cookies_file:
            ydl_base["cookiefile"] = self.cookies_file
        if progress_hook:
            ydl_base["progress_hooks"] = [progress_hook]

        attempts = [
            ydl_base,
            {
                **ydl_base,
                "extractor_args": {
                    "youtube": {"player_client": ["android", "ios", "tv", "web_safari"]}
                },
            },
        ]
        last_error: Exception | None = None
        for options in attempts:
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.extract_info(video_url, download=True)
                if expected_path.exists():
                    return expected_path
            except Exception as exc:
                last_error = exc
        raise SpotifyFallbackError(
            f"yt-dlp did not create audio for {track.title}: {last_error or 'unknown error'}"
        )

    def _select_video(self, query: str, track: SpotifyTrack) -> str:
        options = {
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
            "socket_timeout": 15,
            "retries": 3,
        }
        if self.cookies_file:
            options["cookiefile"] = self.cookies_file
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(query, download=False) or {}
        except Exception as exc:
            logger.warning("Spotify fallback YouTube search failed: %s", exc)
            return ""
        entries = [entry for entry in (info.get("entries") or []) if entry and entry.get("id")]
        if not entries:
            return ""
        title_pool = [entry for entry in entries if _title_matches(str(entry.get("title") or ""), track.title)]
        if not title_pool:
            return ""
        artist_pool = [
            entry
            for entry in title_pool
            if _artist_matches(str(entry.get("title") or ""), track.artists)
        ] or title_pool
        chosen = artist_pool[0]
        expected_seconds = (track.duration_ms / 1000) if track.duration_ms else None
        timed = [entry for entry in artist_pool if entry.get("duration") and expected_seconds]
        if timed and expected_seconds:
            chosen = min(timed, key=lambda entry: abs(float(entry["duration"]) - expected_seconds))
            if abs(float(chosen["duration"]) - expected_seconds) > 30:
                return ""
        return f"https://www.youtube.com/watch?v={chosen['id']}"


def write_audio_tags(path: Path, track: SpotifyTrack) -> None:
    try:
        if path.suffix.lower() == ".mp3":
            _write_mp3_tags(path, track)
        elif path.suffix.lower() == ".m4a":
            _write_m4a_tags(path, track)
        else:
            _write_generic_tags(path, track)
    except Exception as exc:
        logger.warning("Could not write Spotify fallback tags for %s: %s", path, exc)


def _cover_bytes(url: str) -> tuple[bytes, str]:
    if not url:
        return b"", "image/jpeg"
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
        data = response.content
    except Exception:
        return b"", "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return data, "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    return data, response.headers.get("content-type", "image/jpeg").split(";", 1)[0]


def _write_mp3_tags(path: Path, track: SpotifyTrack) -> None:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import APIC, ID3

    try:
        tags = EasyID3(path)
    except Exception:
        tags = EasyID3()
    tags["title"] = track.title
    tags["artist"] = track.artists
    if track.album:
        tags["album"] = track.album
    if track.release_date:
        tags["date"] = track.release_date[:4]
    if track.position:
        tags["tracknumber"] = str(track.position)
    tags.save(path, v2_version=3)
    cover, mime = _cover_bytes(track.cover_url)
    if cover:
        id3 = ID3(path)
        id3.delall("APIC")
        id3.add(APIC(encoding=1, mime=mime, type=3, desc="Cover", data=cover))
        id3.update_to_v23()
        id3.save(path, v2_version=3)


def _write_m4a_tags(path: Path, track: SpotifyTrack) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    tags = MP4(path)
    tags["\xa9nam"] = [track.title]
    tags["\xa9ART"] = [track.artists]
    if track.album:
        tags["\xa9alb"] = [track.album]
    if track.release_date:
        tags["\xa9day"] = [track.release_date[:4]]
    if track.position:
        tags["trkn"] = [(track.position, 0)]
    cover, mime = _cover_bytes(track.cover_url)
    if cover:
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
    tags.save()


def _write_generic_tags(path: Path, track: SpotifyTrack) -> None:
    from mutagen import File

    tags = File(path, easy=True)
    if tags is None:
        return
    tags["title"] = [track.title]
    tags["artist"] = [track.artists]
    if track.album:
        tags["album"] = [track.album]
    if track.release_date:
        tags["date"] = [track.release_date[:4]]
    if track.position:
        tags["tracknumber"] = [str(track.position)]
    tags.save()
