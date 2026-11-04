# helpers/ytdl.py — YouTube / link resolver (yt-dlp, blocking calls thread me chalte hain)
import asyncio
import os
import re
import time
from typing import List, Optional

import yt_dlp

import config
from state import Track

YT_RE = re.compile(r"(youtube\.com|youtu\.be|music\.youtube\.com)", re.I)
URL_RE = re.compile(r"^https?://", re.I)

AUDIO_FMT = "bestaudio[ext=m4a]/bestaudio/best"
VIDEO_FMT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
STALE_AFTER = 1200  # stream url 20 min baad dubara resolve


def _opts(**extra):
    o = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "skip_download": True,
    }
    if config.COOKIES_FILE and os.path.isfile(config.COOKIES_FILE):
        o["cookiefile"] = config.COOKIES_FILE
    o.update(extra)
    return o


def _formats(info: dict, video: bool):
    """(video/main url, audio url, headers)"""
    if video:
        rf = info.get("requested_formats") or []
        vf = next((f for f in rf if f.get("vcodec") not in (None, "none")), None)
        af = next(
            (f for f in rf if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")),
            None,
        )
        if vf and af:
            return vf["url"], af["url"], vf.get("http_headers")
    return info.get("url"), None, info.get("http_headers")


def _fill(track: Track, info: dict, video: bool) -> Track:
    url, audio, headers = _formats(info, video)
    if not url:
        raise RuntimeError("stream url nahi mila")
    track.title = info.get("title") or track.title
    track.duration = int(info.get("duration") or track.duration or 0)
    track.thumb = info.get("thumbnail") or track.thumb
    track.webpage = info.get("webpage_url") or track.webpage
    track.vid = info.get("id") or track.vid
    track.channel = info.get("uploader") or info.get("channel") or track.channel
    track.stream_url, track.audio_url, track.headers = url, audio, headers
    track.video = video
    track.resolved_at = time.time()
    return track


def _has_cookies() -> bool:
    return bool(config.COOKIES_FILE and os.path.isfile(config.COOKIES_FILE))


def _run(target: str, video: bool, **extra) -> dict:
    with yt_dlp.YoutubeDL(_opts(format=VIDEO_FMT if video else AUDIO_FMT, **extra)) as ydl:
        return ydl.extract_info(target, download=False)


def _extract(target: str, video: bool) -> dict:
    if not URL_RE.match(target):
        target = f"ytsearch1:{target}"
    try:
        info = _run(target, video)
    except Exception as e:
        # cookies na ho aur YouTube bot-check de to dusre clients se ek baar try (pakka nahi chalta)
        if "Sign in" in str(e) and not _has_cookies():
            print("[ytdl] bot-check mila, alternate clients try kar raha hoon (cookies.txt behtar hai)")
            info = _run(target, video, extractor_args={"youtube": {"player_client": ["android_vr", "tv_simply", "mweb"]}})
        else:
            raise
    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise RuntimeError("koi result nahi mila")
        info = entries[0]
    if not info:
        raise RuntimeError("koi result nahi mila")
    return info


async def get_track(query: str, video: bool = False) -> Track:
    info = await asyncio.to_thread(_extract, query, video)
    return _fill(Track(query=query), info, video)


async def ensure_stream(track: Track):
    """Play karne se pehle stream url fresh karo (lazy / expired tracks)."""
    if track.local:
        return
    if track.stream_url and time.time() - track.resolved_at < STALE_AFTER:
        return
    target = track.webpage or track.query or track.title
    info = await asyncio.to_thread(_extract, target, track.video)
    _fill(track, info, track.video)


def _flat_playlist(url: str, limit: int) -> List[dict]:
    with yt_dlp.YoutubeDL(_opts(noplaylist=False, extract_flat="in_playlist", playlistend=limit)) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e for e in (info.get("entries") or []) if e]


async def get_playlist(url: str, video: bool, limit: int) -> List[Track]:
    entries = await asyncio.to_thread(_flat_playlist, url, limit)
    out = []
    for e in entries:
        vid = e.get("id") or ""
        out.append(
            Track(
                title=e.get("title") or "Unknown",
                duration=int(e.get("duration") or 0),
                webpage=e.get("url") if str(e.get("url", "")).startswith("http") else f"https://www.youtube.com/watch?v={vid}",
                vid=vid,
                video=video,
                thumb=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else "",
            )
        )
    return out


def _search_flat(q: str, n: int) -> List[dict]:
    with yt_dlp.YoutubeDL(_opts(extract_flat=True)) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{q}", download=False)
    return [e for e in (info.get("entries") or []) if e]


async def related(track: Track, exclude: set) -> Optional[Track]:
    """Autoplay: current song se milta-julta next track."""
    q = f"{track.channel} {track.title}".strip()
    try:
        entries = await asyncio.to_thread(_search_flat, q, 10)
    except Exception:
        return None
    for e in entries:
        vid = e.get("id")
        if vid and vid not in exclude and vid != track.vid:
            return Track(
                title=e.get("title") or "Unknown",
                duration=int(e.get("duration") or 0),
                webpage=f"https://www.youtube.com/watch?v={vid}",
                vid=vid,
                video=track.video,
                thumb=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            )
    return None
