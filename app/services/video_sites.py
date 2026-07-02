from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

GENERAL_VIDEO_SITES = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "twitter.com": "X / Twitter",
    "x.com": "X / Twitter",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "twitch.tv": "Twitch",
}

ADULT_VIDEO_SITES = {
    "alphaporno.com": "AlphaPorno",
    "camsoda.com": "CamSoda",
    "drtuber.com": "DrTuber",
    "empflix.com": "Empflix",
    "eporner.com": "Eporner",
    "hellporno.com": "HellPorno",
    "hellporno.net": "HellPorno",
    "hqporner.com": "HQPorner",
    "javhdporn.net": "JavHDPorn",
    "javtiful.com": "Javtiful",
    "lovehomeporn.com": "LoveHomePorn",
    "missav.com": "MissAV",
    "missav.live": "MissAV",
    "missav.ws": "MissAV",
    "missav123.com": "MissAV",
    "motherless.com": "Motherless",
    "njavtv.com": "NJAV",
    "nonktube.com": "NonkTube",
    "pornhub.com": "PornHub",
    "porntop.com": "PornTop",
    "porntrex.com": "Porntrex",
    "redtube.com": "RedTube",
    "rule34video.com": "Rule34Video",
    "sexu.com": "Sexu",
    "spankbang.com": "SpankBang",
    "sunporno.com": "SunPorno",
    "thothub.to": "Thothub",
    "thisvid.com": "ThisVid",
    "tnaflix.com": "TNAFlix",
    "tube8.com": "Tube8",
    "txxx.com": "Txxx",
    "webcamera.pl": "WebCamera.pl",
    "xhamster.com": "XHamster",
    "xnxx.com": "XNXX",
    "xvideos.com": "XVideos",
    "youjizz.com": "YouJizz",
    "youporn.com": "YouPorn",
    "zenporn.com": "ZenPorn",
}

HENTAI_VIDEO_SITES = {
    "hanime.tv": "Hanime",
    "hstream.moe": "HStream",
    "hentaihaven.com": "HentaiHaven",
    "hentaimama.io": "HentaiMama",
    "hanime.red": "HanimeRed",
}

GENERIC_IMPERSONATION_SITES = frozenset({"javhdporn.net"})
SUPPORTED_VIDEO_SITES = {**GENERAL_VIDEO_SITES, **ADULT_VIDEO_SITES, **HENTAI_VIDEO_SITES}


@dataclass(frozen=True, slots=True)
class SocialProfileInfo:
    username: str
    platform: str


def host(url: str) -> str:
    value = (urlparse(url.strip()).hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value


def matches_domain(value: str, domain: str) -> bool:
    return value == domain or value.endswith(f".{domain}")


def is_adult_video_url(url: str) -> bool:
    value = host(url)
    return any(matches_domain(value, domain) for domain in ADULT_VIDEO_SITES)


def is_hentai_video_url(url: str) -> bool:
    value = host(url)
    return any(matches_domain(value, domain) for domain in HENTAI_VIDEO_SITES)


def requires_deno_runtime(url: str) -> bool:
    return matches_domain(host(url), "hanime.tv")


def requires_generic_impersonation(url: str) -> bool:
    value = host(url)
    return any(matches_domain(value, domain) for domain in GENERIC_IMPERSONATION_SITES)


def platform_label(url: str) -> str:
    value = host(url)
    for domain, label in SUPPORTED_VIDEO_SITES.items():
        if matches_domain(value, domain):
            return label
    return "Video"


def platform_slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", platform_label(url)).strip("-") or "Video"


def social_profile_info(url: str) -> SocialProfileInfo | None:
    parsed = urlparse(url.strip())
    value = host(url)
    path = parsed.path.strip("/")
    if not path:
        return None

    parts = [part for part in path.split("/") if part]
    if not parts:
        return None

    if matches_domain(value, "tiktok.com"):
        first = parts[0]
        if first.startswith("@") and len(first) > 1:
            return SocialProfileInfo(first.removeprefix("@"), "TikTok")
        return None

    if matches_domain(value, "instagram.com"):
        username = parts[0]
        reserved = {
            "accounts",
            "api",
            "direct",
            "explore",
            "graphql",
            "p",
            "reel",
            "reels",
            "stories",
            "tv",
        }
        if username.lower() not in reserved and re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            return SocialProfileInfo(username, "Instagram")
        return None

    if matches_domain(value, "x.com") or matches_domain(value, "twitter.com"):
        username = parts[0]
        reserved = {
            "compose",
            "explore",
            "hashtag",
            "home",
            "i",
            "intent",
            "messages",
            "notifications",
            "search",
            "settings",
            "share",
            "status",
        }
        if username.lower() not in reserved and re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
            if len(parts) == 1 or parts[1].lower() in {"media", "with_replies", "highlights"}:
                return SocialProfileInfo(username, "X")
        return None

    return None


def is_social_profile_url(url: str) -> bool:
    return social_profile_info(url) is not None
