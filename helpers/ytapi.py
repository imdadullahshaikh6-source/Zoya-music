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
# --- Last layer: yt-dlp "race" (YT_PROXIES / YT_RACE) ---------------------------------------------------
#   Saari APIs fail hon to kuch yt-dlp clients (tv/web_safari/android_vr/mweb/ios) proxies + cookies ke saath
#   parallel chalte hain, jo pehle file de de wahi jeet-ta hai.
#
# API fail ho to player.py apne aap purane yt-dlp tareeke pe chala jata hai.
import asyncio
import json
import os
import random
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
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


def _int_cfg(name: str, default: int) -> int:
    try:
        return int(str(_cfg(name, default)).strip())
    except (TypeError, ValueError):
        return default


# --- "local" API (apna, isi server pe — free, koi proxy/3rd-party backend nahi) ---
L_URL = str(_cfg("LOCAL_API_URL", "http://127.0.0.1:8787")).strip().rstrip("/")
L_KEY = str(_cfg("LOCAL_API_KEY")).strip()
L_ENABLED = str(_cfg("LOCAL_API_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off") and bool(L_URL)
LOCAL_TIMEOUT = _int_cfg("LOCAL_API_TIMEOUT", 75)          # audio: kul kitni der intezaar
LOCAL_VIDEO_TIMEOUT = _int_cfg("LOCAL_VIDEO_TIMEOUT", 800)  # video/movie: bada download, zyada sabr (player START_TIMEOUT_VIDEO se kam rakho)
LOCAL_WAIT = 25  # har "kya hua?" poochne ka chakkar itne second ka (server job chalata rehta hai)


def _local_deadline(kind: str) -> int:
    return LOCAL_VIDEO_TIMEOUT if kind == "video" else LOCAL_TIMEOUT

# --- yt-dlp race (last layer) ---
RACE_CLIENTS = ["tv", "web_safari", "android_vr", "mweb", "ios"]
RACE_PARALLEL = max(1, _int_cfg("YT_RACE_PARALLEL", 3))
RACE_TIMEOUT = _int_cfg("YT_RACE_TIMEOUT", 120)
PROXIES = [x for x in re.split(r"[\s,]+", str(_cfg("YT_PROXIES"))) if x]

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


# "local" (apna, isi server pe, free) hamesha sabse pehle try hota hai jab enabled ho — baaki (innertube/
# ritesh) sirf iske fallback hain. FIRST sirf un fallback APIs ka aapas me order badalta hai.
_DEFAULT_ORDER = ["innertube", "ritesh"]


def _providers() -> list:
    """Jo APIs set hain, unki list (jise pehle try karna ho wo aage). 'local' hamesha sabse upar (agar on ho)."""
    pool = {}
    if BASE:
        pool["innertube"] = {"name": "innertube", "base": BASE, "key": KEY}
    if R_BASE and R_KEY:
        pool["ritesh"] = {"name": "ritesh", "base": R_BASE, "key": R_KEY}
    order = [FIRST] if FIRST in pool else []
    order += [n for n in _DEFAULT_ORDER if n in pool and n not in order]
    ps = [pool[n] for n in order]
    if L_ENABLED:
        ps.insert(0, {"name": "local", "base": L_URL, "key": L_KEY})
    return ps


def race_enabled() -> bool:
    """YT_RACE=1/0 se zabardasti on/off, warna proxies set hon tabhi."""
    v = str(_cfg("YT_RACE")).strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return bool(PROXIES)


def total_timeout(kind: str = "audio") -> int:
    t = 15
    for p in _providers():
        if p["name"] == "local":
            t += _local_deadline(kind) + 10
        else:
            t += PROBE_TIMEOUT + 10
    if race_enabled():
        t += RACE_TIMEOUT + 15
    return max(t, PROBE_TIMEOUT + 25)


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


_ERRS: dict = {}  # vid -> ["local: ...", "innertube: ..."]  (player ke error message me asli wajah dikhane ke liye)


def _note(vid: str, who: str, e) -> None:
    msg = str(e).strip() or type(e).__name__
    lst = _ERRS.setdefault(str(vid), [])
    lst.append(f"{who}: {type(e).__name__}: {msg}"[:160])
    del lst[:-6]
    while len(_ERRS) > 60:
        _ERRS.pop(next(iter(_ERRS)))


def last_errors(vid) -> str:
    return " | ".join(_ERRS.get(str(vid), [])[-4:])


def _fkey(kind: str, vid: str) -> str:
    return ("v_" if kind == "video" else "") + vid


async def ready(kind: str, vid: str, dur: int = 0) -> str:
    """URL ya local FILE PATH return karta hai jab stream khulne layak ho.
    Har HTTP API ko 3 baar tak try karta hai (pehli baar API gaana garam kar rahi hoti hai to connection beech me
    tut jata hai). "local" API file deti hai (path). Sab fail hon to yt-dlp race (agar on ho), phir player.py
    purane yt-dlp tareeke pe chala jata hai."""
    last = None
    provs = _providers()
    for i, p in enumerate(provs):
        nxt = " -> agli API" if i < len(provs) - 1 else ""
        if p["name"] == "local":
            try:
                return await _local_fetch(kind, vid, "", dur)
            except Exception as e:
                last = e
                _note(vid, p["name"], e)
                print(f"[ytapi] {p['name']} {kind}/{vid} failed ({type(e).__name__}: {e}){nxt}")
            continue
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
        _note(vid, p["name"], last)
        print(f"[ytapi] {p['name']} {kind}/{vid} failed ({type(last).__name__}: {last}){nxt}")
    if provs and race_enabled():
        try:
            return await race_download(kind, vid, config.DOWNLOAD_DIR)
        except Exception as e:
            last = e
            _note(vid, "race", e)
            print(f"[ytapi] race {kind}/{vid} failed ({type(e).__name__}: {e})")
    raise last or RuntimeError("koi API set nahi")


_TEMP_SUFFIX = (".part", ".ytdl", ".temp")
# yt-dlp ki beech ki files: v_ID.f137.mp4 (sirf video) / v_ID.f140.m4a (sirf audio) / .fragN — inhe "poori file" mat samjho
# (pehle ye cache ban jati thi -> video chalta tha par awaaz nahi aati thi)
_PARTIAL_RE = re.compile(r"\.f\d+\.|\.frag\d*$")


def _cached(dest_dir: str, key: str):
    try:
        for f in os.listdir(dest_dir):
            if f.startswith(key + ".") and not f.endswith(_TEMP_SUFFIX) and ".temp." not in f and not _PARTIAL_RE.search(f):
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


def _download_sync(kind: str, vid: str, dest_dir: str, timeout: int, provs=None) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    key = _fkey(kind, vid)
    with vid_lock(key):
        hit = _cached(dest_dir, key)
        if hit:
            return hit
        last = None
        for p in (provs if provs is not None else _providers()):
            try:
                return _download_one(kind, vid, dest_dir, timeout, key, p)
            except Exception as e:
                last = e
                print(f"[ytapi] {p['name']} {kind}/{vid} download failed ({type(e).__name__}: {e}) -> agli API")
        raise last or RuntimeError("koi API set nahi")


async def download(kind: str, vid: str, dest_dir: str, dur: int = 0) -> str:
    """INNERTUBE_DIRECT=0 mode: API se local file. Order = _providers() ka order, phir race."""
    os.makedirs(dest_dir, exist_ok=True)
    hit = _cached(dest_dir, _fkey(kind, vid))
    if hit:
        return hit
    last = None
    provs = _providers()
    for p in provs:
        try:
            if p["name"] == "local":
                return await _local_fetch(kind, vid, dest_dir, dur)
            return await asyncio.to_thread(_download_sync, kind, vid, dest_dir, 300, [p])
        except Exception as e:
            last = e
            _note(vid, p["name"], e)
            print(f"[ytapi] {p['name']} {kind}/{vid} download failed ({type(e).__name__}: {e}) -> agli API")
    if provs and race_enabled():
        try:
            return await race_download(kind, vid, dest_dir)
        except Exception as e:
            last = e
            _note(vid, "race", e)
            print(f"[ytapi] race {kind}/{vid} failed ({type(e).__name__}: {e})")
    raise last or RuntimeError("koi API set nahi")


# ═════════════════════════ "local" API (apna, isi server pe — koi proxy/3rd-party nahi) ═════════════════════════
def _local_get_sync(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ZoyaMusic/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:  # server 500 ke saath asli wajah JSON me deta hai
        try:
            return json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            raise e


async def _local_fetch(kind: str, vid: str, dest_dir: str = "", dur: int = 0) -> str:
    """Apne local_api/server.py se file. Server download ko background JOB me chalata hai; hum har ~25s me poochte
    rehte hain jab tak file na aa jaye (ya deadline). Isse movie jaisi badi file ke liye bhi ek hi download chalta hai."""
    dest_dir = dest_dir or config.DOWNLOAD_DIR
    key = _fkey(kind, vid)
    hit = _cached(dest_dir, key)
    if hit:
        return hit
    qkey = f"&key={urllib.parse.quote(L_KEY, safe='')}" if L_KEY else ""
    deadline = time.monotonic() + _local_deadline(kind)
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise RuntimeError(f"local API: {kind} {_local_deadline(kind)}s me taiyar nahi hua")
        wait = int(max(1, min(LOCAL_WAIT, left)))
        url = (f"{L_URL}/resolve?vid={urllib.parse.quote(vid, safe='')}&kind={kind}"
               f"&dur={int(dur or 0)}&wait={wait}{qkey}")
        data = await asyncio.to_thread(_local_get_sync, url, wait + 15)
        st = data.get("status")
        if st == "working":
            continue
        if st != "done" or not data.get("path"):
            raise RuntimeError(f"local API error: {data.get('error') or data}")
        path = str(data["path"])
        if not os.path.isfile(path):
            raise RuntimeError("local API: diya hua path exist nahi karta")
        return path


# ═════════════════════════ yt-dlp race (proxies + cookies) ═════════════════════════
_RACE_TMP = re.compile(r"\.(?:part|ytdl|temp)$|\.f\d+\.|\.frag\d*$")


def _race_sync(kind: str, vid: str, dest_dir: str, timeout: int) -> str:
    import yt_dlp
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from helpers import ytdl  # JS runtime + cookies wale common yt-dlp options
    from helpers.lowprio import LowPrio

    os.makedirs(dest_dir, exist_ok=True)
    key = _fkey(kind, vid)
    with vid_lock(key), LowPrio():
        hit = _cached(dest_dir, key)
        if hit:
            return hit
        url = f"https://www.youtube.com/watch?v={vid}"
        if kind == "video":
            fmt = "bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/best[vcodec^=avc1][height<=720]/best[height<=720]/best"
        else:
            fmt = "bestaudio[ext=m4a]/bestaudio/best"
        proxies = list(PROXIES) or [None]
        random.shuffle(proxies)
        combos = [(c, proxies[i % len(proxies)]) for i, c in enumerate(RACE_CLIENTS[:RACE_PARALLEL])]
        root = tempfile.mkdtemp(prefix=f"race_{key}_", dir=dest_dir)
        stop = threading.Event()

        def hook(_d):
            if stop.is_set():
                raise RuntimeError("race: dusra jeet gaya")

        def run(i: int, client: str, proxy):
            out = os.path.join(root, str(i))
            os.makedirs(out, exist_ok=True)
            opts = ytdl._opts(
                skip_download=False,
                format=fmt,
                outtmpl=os.path.join(out, "out.%(ext)s"),
                extractor_args={"youtube": {"player_client": [client]}},
                socket_timeout=20,
                retries=3,
                fragment_retries=5,
                noprogress=True,
                progress_hooks=[hook],
            )
            ck = opts.get("cookiefile")
            if ck:  # har thread ki apni cookie copy: yt-dlp exit par cookies likhta hai, shared file kharab ho sakti hai
                try:
                    cp = os.path.join(out, "cookies.txt")
                    shutil.copyfile(ck, cp)
                    opts["cookiefile"] = cp
                except OSError:
                    opts.pop("cookiefile", None)
            if proxy:
                opts["proxy"] = proxy
            if kind == "video":
                opts["merge_output_format"] = "mp4"
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            for f in sorted(os.listdir(out)):
                fp = os.path.join(out, f)
                if f.startswith("out.") and not _RACE_TMP.search(f) and os.path.getsize(fp) > 50 * 1024:
                    return fp
            raise RuntimeError("file nahi bani")

        ex = ThreadPoolExecutor(max_workers=len(combos))
        futs = {ex.submit(run, i, c, p): (c, p) for i, (c, p) in enumerate(combos)}
        winner, errs = None, []
        try:
            for f in as_completed(futs, timeout=timeout):
                c, p = futs[f]
                try:
                    winner = f.result()
                    print(f"[ytapi] race jeet: client={c} proxy={'yes' if p else 'no'}")
                    break
                except Exception as e:
                    errs.append(f"{c}: {str(e)[:70]}")
        except Exception as e:  # timeout
            errs.append(f"timeout {timeout}s ({type(e).__name__})")
        finally:
            stop.set()
            ex.shutdown(wait=False, cancel_futures=True)
        try:
            if not winner:
                raise RuntimeError("race fail: " + " | ".join(errs)[:300])
            final = os.path.join(dest_dir, key + os.path.splitext(winner)[1])
            os.replace(winner, final)
            return final
        finally:
            shutil.rmtree(root, ignore_errors=True)


async def race_download(kind: str, vid: str, dest_dir: str) -> str:
    if not is_video_id(vid):
        raise RuntimeError("race sirf YouTube video id ke liye")
    return await asyncio.to_thread(_race_sync, kind, vid, dest_dir, RACE_TIMEOUT)


# ═════════════════════════ prefetch ═════════════════════════
def _prefetch_sync(kind: str, vid: str, dur: int = 0):
    if L_ENABLED:
        # apna local API: isi call se pehle se download shuru/poora ho jata hai, baad me turant cache-hit milega
        qkey = f"&key={urllib.parse.quote(L_KEY, safe='')}" if L_KEY else ""
        try:
            # wait=1: server download job shuru kar deta hai aur turant jawab deta hai (hum rukte nahi)
            _local_get_sync(f"{L_URL}/resolve?vid={urllib.parse.quote(vid, safe='')}&kind={kind}&dur={int(dur or 0)}&wait=1{qkey}", 15)
            return  # local ne job utha liya -> baaki APIs ko faltu warm karne ki zarurat nahi
        except Exception as e:
            print(f"[ytapi] local prefetch {kind}/{vid} failed: {type(e).__name__}: {e}")
    if BASE:
        req = urllib.request.Request(f"{BASE}/prefetch/{kind}/{vid}", data=b"", method="POST", headers=headers())
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(256)


def prefetch_bg(kind: str, vid: str, dur: int = 0):
    """Queue me lage gaane ko API me pehle se garam karo (fire-and-forget, kabhi error nahi deta)."""
    if not (enabled() and is_video_id(vid)):
        return

    async def _run():
        try:
            await asyncio.to_thread(_prefetch_sync, kind, vid, dur)
        except Exception as e:
            print(f"[ytapi] prefetch {kind}/{vid} failed: {e!r}")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass
