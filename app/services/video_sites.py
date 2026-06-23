from __future__ import annotations

import re
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
