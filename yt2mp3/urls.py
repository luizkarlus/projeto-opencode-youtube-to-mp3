"""Detecção de URLs suportadas.

O app original aceitava YouTube, Vimeo, SoundCloud, Facebook, Instagram,
TikTok, Bandcamp e vários outros, com regex por serviço (por exemplo
``youtube.com/watch?v=...``). Como o yt-dlp já cobre centenas de sites,
basta validar de forma genérica e reconhecer os atalhos mais comuns.
"""

from __future__ import annotations

import re

URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$", re.IGNORECASE)

KNOWN_HOSTS = {
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "vimeo.com",
    "soundcloud.com",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "tiktok.com",
    "dailymotion.com",
    "bandcamp.com",
    "mixcloud.com",
    "twitch.tv",
    "twitter.com",
    "x.com",
    "bitchute.com",
    "rumble.com",
    "odysee.com",
    "audius.co",
    "podcasts.apple.com",
}

MEDIA_EXT_RE = re.compile(r"\.(mp3|m4a|webm|mp4|opus|flac|wav|aac|ogg)$", re.IGNORECASE)


def _host(url: str) -> str:
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", url, re.IGNORECASE)
    if not match:
        return ""
    host = match.group(1).lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def is_supported(url: str) -> bool:
    url = url.strip()
    if not URL_RE.match(url):
        return False
    if MEDIA_EXT_RE.search(url):
        return False
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in KNOWN_HOSTS)


def split_entries(text: str) -> list[str]:
    """Extrai URLs de um texto colado (uma por linha ou separadas por espaço)."""
    found: list[str] = []
    for token in re.split(r"[\s,]+", text.strip()):
        token = token.strip()
        if token and URL_RE.match(token) and token not in found:
            found.append(token)
    return found
