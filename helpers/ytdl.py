# helpers/ytdl.py — YouTube / link resolver (yt-dlp, blocking calls thread me chalte hain)
import asyncio
import os
import re
import shutil
import time
from typing import List, Optional

import yt_dlp

import config
from state import Track

YT_RE = re.compile(r"(youtube\.com|youtu\.be|music\.youtube\.com)", re.I)
URL_RE = re.compile(r"^https?://", re.I)

AUDIO_FMT = "bestaudio/best"
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
    # naya yt-dlp YouTube ke liye JS runtime (deno/node) maangta hai, warna formats nahi milte
    for rt in ("deno", "node", "bun"):
        if shutil.which(rt):
            o["js_runtimes"] = {rt: {}}
            o["remote_components"] = ["ejs:github"]
            break
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


def _run(target: str, video: bool, fmt: Optional[str] = None, **extra) -> dict:
    fmt = fmt or (VIDEO_FMT if video else AUDIO_FMT)
    with yt_dlp.YoutubeDL(_opts(format=fmt, **extra)) as ydl:
        return ydl.extract_info(target, download=False)


# (extractor_args, format) combos — ek fail ho to agla try hota hai
def _attempts(video: bool):
    main = VIDEO_FMT if video else AUDIO_FMT
    loose = "best[height<=720]/best" if video else "bestaudio/best"
    yt = lambda *c: {"youtube": {"player_client": list(c)}}
    return [
        ({}, main),
        ({"extractor_args": yt("tv", "web_safari")}, main),
        ({"extractor_args": yt("android_vr")}, main),
        ({"extractor_args": yt("mweb", "ios")}, loose),
        ({}, loose),
    ]


def _search_url(q: str) -> str:
    """Search ko ek hi baar karo, phir seedha video URL pe retry chalao."""
    with yt_dlp.YoutubeDL(_opts(extract_flat=True)) as ydl:
        info = ydl.extract_info(f"ytsearch1:{q}", download=False)
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        raise RuntimeError("koi result nahi mila")
    e = entries[0]
    u = e.get("url") or ""
    if u.startswith("http"):
        return u
    return f"https://www.youtube.com/watch?v={e.get('id')}"


def _extract(target: str, video: bool) -> dict:
    if not URL_RE.match(target):
        target = _search_url(target)

    last = None
    for i, (extra, fmt) in enumerate(_attempts(video)):
        try:
            info = _run(target, video, fmt=fmt, **extra)
            break
        except Exception as e:
            last = e
            print(f"[ytdl] attempt {i + 1} fail: {str(e)[:150]}")
    else:
        if last and "Sign in" in str(last) and not _has_cookies():
            print("[ytdl] bot-check: cookies.txt daalo (COOKIES_FILE)")
        raise last

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
