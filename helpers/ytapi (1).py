# helpers/ytapi.py — apni InnerTube Media API (https://truemorningxd.up.railway.app) se audio / video
#
#   GET  /stream/{audio|video}/{video_id}    -> media (pehli baar API khud download karti hai, baad me cache se turant)
#   POST /prefetch/{audio|video}/{video_id}  -> pehle se garam kar do (202)
#   GET  /resolve/..  /health                -> abhi use nahi hote
#
# .env (server pe) me:
#   INNERTUBE_URL=https://truemorningxd.up.railway.app   # khaali = API band, sirf yt-dlp
#   INNERTUBE_KEY=                                        # (optional) sirf agar TUMHARI InnerTube API key maangti ho
#   INNERTUBE_KEY_HEADER=X-API-Key                        # (optional) key kis header me bhejni hai
#   INNERTUBE_DIRECT=1   # 1 = API ka URL seedha VC ko (download nahi)  |  0 = API se local file download karke play
# NOTE: purani YT_API_KEY (Google YouTube Data key) se is file ka koi lena-dena nahi, wo kabhi nayi API ko nahi bheji jati.
#
# API fail ho to player.py apne aap purane yt-dlp tareeke pe chala jata hai.
import asyncio
import os
import shutil
import time
import urllib.request

import config
from helpers.lowprio import vid_lock


def _cfg(name: str, default=""):
    v = getattr(config, name, None)
    return v if v not in (None, "") else os.getenv(name, default)


BASE = str(_cfg("INNERTUBE_URL") or _cfg("YT_API_URL")).strip().rstrip("/")  # YT_API_URL: pehle wala naam, chalta rahega
KEY = str(_cfg("INNERTUBE_KEY")).strip()  # jaan-boojh ke YT_API_KEY nahi: wo Google ki key hai
KEY_HEADER = str(_cfg("INNERTUBE_KEY_HEADER", "X-API-Key")).strip() or "X-API-Key"
DIRECT = str(_cfg("INNERTUBE_DIRECT") or _cfg("YT_API_DIRECT", "1")).strip().lower() not in ("0", "false", "no", "off")
# --- Doosri API: AloneMusic (api.riteshyt.in) ---------------------------------
#   .env:  RITESH_URL=https://api.riteshyt.in   RITESH_KEY=riteshfree...   API_FIRST=ritesh   (API_FIRST optional)
#   GET /download?query={vid}&dl_type=audio|video&quality=720&api_key=KEY  (key URL me jaati hai, header me nahi)
R_BASE = str(_cfg("RITESH_URL")).strip().rstrip("/")
R_KEY = str(_cfg("RITESH_KEY")).strip()
FIRST = str(_cfg("API_FIRST", "innertube")).strip().lower()  # "ritesh" likho to wo pehle try hogi
PROBE_TIMEOUT = 60  # pehli baar API download karke deti hai, isliye intezaar

# URL se chalte stream ke liye ffmpeg: connection tute to khud wapas jud jaye
FFMPEG_NET = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

_EXT = {
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "video/webm": "webm",
    "video/mp4": "mp4",
}


def _providers() -> list:
    """Jo APIs set hain, unki list (jise pehle try karna ho wo aage)."""
    ps = []
    if BASE:
        ps.append({"name": "innertube", "base": BASE, "key": KEY})
    if R_BASE and R_KEY:
        ps.append({"name": "ritesh", "base": R_BASE, "key": R_KEY})
    if FIRST == "ritesh":
        ps.sort(key=lambda p: p["name"] != "ritesh")
    return ps


def total_timeout() -> int:
    return (PROBE_TIMEOUT + 10) * max(1, len(_providers())) + 15


def enabled() -> bool:
    return bool(_providers())


def is_api_url(url) -> bool:
    u = str(url or "")
    return any(u.startswith(p["base"]) for p in _providers())


def headers(p=None) -> dict:
    h = {"User-Agent": "ZoyaMusic/1.0"}
    if KEY and (p is None or p["name"] == "innertube"):
        h[KEY_HEADER] = KEY
    return h


def ffmpeg_headers(url=None):
    """ffmpeg ko header sirf tab bhejo jab URL innertube API ka ho aur key lagti ho (ritesh me key URL me hoti hai)."""
    if url and not str(url).startswith(BASE or "\0"):
        return None
    return {KEY_HEADER: KEY} if (KEY and BASE) else None


def stream_url(kind: str, vid: str, p=None) -> str:
    p = p or (_providers() or [{"name": "innertube", "base": BASE, "key": KEY}])[0]
    if p["name"] == "ritesh":
        u = f"{p['base']}/download?query={vid}&dl_type={kind}&api_key={p['key']}"
        return u + "&quality=720" if kind == "video" else u
    return f"{p['base']}/stream/{kind}/{vid}"


def is_video_id(vid) -> bool:
    v = str(vid or "")
    return len(v) == 11 and all(c.isalnum() or c in "-_" for c in v)


def _probe_sync(kind: str, vid: str, timeout: int, p=None) -> str:
    """Stream sach me khulta hai? (pehle 2KB padh ke dekhte hain)."""
    req = urllib.request.Request(stream_url(kind, vid, p), headers={**headers(p), "Range": "bytes=0-2047"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status = r.status
        ctype = (r.headers.get("Content-Type") or "").lower()
        head = r.read(2048)
    if status not in (200, 206):
        raise RuntimeError(f"HTTP {status}")
    if any(x in ctype for x in ("json", "html", "text")):
        raise RuntimeError(f"media nahi mila (content-type {ctype}): {head[:120]!r}")
    if not head:
        raise RuntimeError("empty response")
    return ctype


async def ready(kind: str, vid: str) -> str:
    """URL return karta hai jab stream khulne layak ho. Har API ko 3 baar tak try karta hai (pehli baar API gaana
    garam kar rahi hoti hai to connection beech me tut jata hai), phir agli API / yt-dlp."""
    last = None
    provs = _providers()
    for i, p in enumerate(provs):
        t0 = time.monotonic()
        for attempt in range(3):
            try:
                await asyncio.to_thread(_probe_sync, kind, vid, PROBE_TIMEOUT, p)
                if attempt:
                    print(f"[ytapi] {p['name']} {kind}/{vid} {attempt + 1}vi koshish me khula")
                return stream_url(kind, vid, p)
            except Exception as e:
                last = e
                if attempt == 2 or time.monotonic() - t0 > PROBE_TIMEOUT:
                    break
                await asyncio.sleep(2.5)  # API ko gaana garam karne ka mauka
        nxt = " -> agli API" if i < len(provs) - 1 else ""
        print(f"[ytapi] {p['name']} {kind}/{vid} failed ({type(last).__name__}: {last}){nxt}")
    raise last or RuntimeError("koi API set nahi")


def _cached(dest_dir: str, key: str):
    try:
        for f in os.listdir(dest_dir):
            if f.startswith(key + ".") and not f.endswith((".part", ".ytdl")) and ".temp." not in f:
                fp = os.path.join(dest_dir, f)
                if os.path.isfile(fp) and os.path.getsize(fp) > 4096:
                    os.utime(fp, None)
                    return fp
    except OSError:
        pass
    return None


def _download_one(kind: str, vid: str, dest_dir: str, timeout: int, key: str, p) -> str:
    req = urllib.request.Request(stream_url(kind, vid, p), headers=headers(p))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if any(x in ctype for x in ("json", "html", "text")):
            raise RuntimeError(f"media nahi mila (content-type {ctype})")
        ext = _EXT.get(ctype, "m4a" if kind == "audio" else "mp4")
        tmp = os.path.join(dest_dir, f"{key}.{ext}.part")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    if os.path.getsize(tmp) < 4096:
        os.remove(tmp)
        raise RuntimeError("downloaded file bahut chhoti hai")
    final = os.path.join(dest_dir, f"{key}.{ext}")
    os.replace(tmp, final)
    return final


def _download_sync(kind: str, vid: str, dest_dir: str, timeout: int) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    key = ("v_" if kind == "video" else "") + vid
    with vid_lock(key):
        hit = _cached(dest_dir, key)
        if hit:
            return hit
        last = None
        for p in _providers():
            try:
                return _download_one(kind, vid, dest_dir, timeout, key, p)
            except Exception as e:
                last = e
                print(f"[ytapi] {p['name']} {kind}/{vid} download failed ({type(e).__name__}: {e}) -> agli API")
        raise last or RuntimeError("koi API set nahi")


async def download(kind: str, vid: str, dest_dir: str) -> str:
    return await asyncio.to_thread(_download_sync, kind, vid, dest_dir, 300)


def _prefetch_sync(kind: str, vid: str):
    if not BASE:  # ritesh API me prefetch endpoint nahi hai
        return
    req = urllib.request.Request(f"{BASE}/prefetch/{kind}/{vid}", data=b"", method="POST", headers=headers())
    with urllib.request.urlopen(req, timeout=8) as r:
        r.read(256)


def prefetch_bg(kind: str, vid: str):
    """Queue me lage gaane ko API me pehle se garam karo (fire-and-forget, kabhi error nahi deta)."""
    if not (enabled() and is_video_id(vid)):
        return

    async def _run():
        try:
            await asyncio.to_thread(_prefetch_sync, kind, vid)
        except Exception as e:
            print(f"[ytapi] prefetch {kind}/{vid} failed: {e!r}")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass
