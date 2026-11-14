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
# --- Teesri API ("dump"): dost ki API (JSON poll + Telegram dump channel) --------------------------------
#   .env:  DUMP_API_URL=http://HOST:PORT/api/youtube/song   DUMP_VIDEO_API_URL=http://HOST:PORT/api/youtube/video
#          DUMP_API_KEY=...   DUMP_CHANNEL_ID=-100...   DUMP_CHANNEL_INVITE=https://t.me/+xxxx   (API_FIRST=dump to sabse pehle)
#   GET {DUMP_API_URL}/{vid}?api=KEY -> 202 (abhi ban rahi hai) ... 200 {"status":"done","link":"dump:<msg_id>" | "http://..."}
#   "dump:<msg_id>" => file Telegram ke dump channel me hai, assistant (userbot) usse download karta hai. Ye provider
#   seedha stream nahi deta, local FILE deta hai (ready() ab URL ya file path dono return kar sakta hai).
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
FIRST = str(_cfg("API_FIRST", "innertube")).strip().lower()  # "ritesh" / "dump" likho to wo pehle try hogi
PROBE_TIMEOUT = 60  # pehli baar API download karke deti hai, isliye intezaar

# --- "dump" API (dost ki) ---
D_AUDIO = str(_cfg("DUMP_API_URL")).strip().rstrip("/")
D_VIDEO = str(_cfg("DUMP_VIDEO_API_URL")).strip().rstrip("/")
D_KEY = str(_cfg("DUMP_API_KEY")).strip()


def _int_cfg(name: str, default: int) -> int:
    try:
        return int(str(_cfg(name, default)).strip())
    except (TypeError, ValueError):
        return default


# --- "local" API (apna, isi server pe — free, koi proxy/3rd-party backend nahi) ---
L_URL = str(_cfg("LOCAL_API_URL", "http://127.0.0.1:8787")).strip().rstrip("/")
L_KEY = str(_cfg("LOCAL_API_KEY")).strip()
L_ENABLED = str(_cfg("LOCAL_API_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off") and bool(L_URL)
LOCAL_TIMEOUT = _int_cfg("LOCAL_API_TIMEOUT", 180)

D_CHAT = _int_cfg("DUMP_CHANNEL_ID", 0)
D_INVITE = str(_cfg("DUMP_CHANNEL_INVITE")).strip()
DUMP_POLL_MAX = _int_cfg("DUMP_POLL_MAX", 150)      # API ko download karke dene ke liye max intezaar (sec)
DUMP_DL_TIMEOUT = _int_cfg("DUMP_DL_TIMEOUT", 180)  # dump channel / direct link se file utarne ka max time (sec)
DUMP_MIN_BYTES = 4096

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
# ritesh/dump) sirf iske fallback hain. FIRST sirf un fallback APIs ka aapas me order badalta hai.
_DEFAULT_ORDER = ["innertube", "ritesh", "dump"]


def _providers() -> list:
    """Jo APIs set hain, unki list (jise pehle try karna ho wo aage). 'local' hamesha sabse upar (agar on ho)."""
    pool = {}
    if BASE:
        pool["innertube"] = {"name": "innertube", "base": BASE, "key": KEY}
    if R_BASE and R_KEY:
        pool["ritesh"] = {"name": "ritesh", "base": R_BASE, "key": R_KEY}
    if (D_AUDIO or D_VIDEO) and D_KEY:
        pool["dump"] = {"name": "dump", "base": D_AUDIO or D_VIDEO, "key": D_KEY}
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


def total_timeout() -> int:
    t = 15
    for p in _providers():
        if p["name"] == "dump":
            t += DUMP_POLL_MAX + DUMP_DL_TIMEOUT + 20
        elif p["name"] == "local":
            t += LOCAL_TIMEOUT + 10
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


def _fkey(kind: str, vid: str) -> str:
    return ("v_" if kind == "video" else "") + vid


async def ready(kind: str, vid: str) -> str:
    """URL ya local FILE PATH return karta hai jab stream khulne layak ho.
    Har HTTP API ko 3 baar tak try karta hai (pehli baar API gaana garam kar rahi hoti hai to connection beech me
    tut jata hai). "dump" API file deti hai (path). Sab fail hon to yt-dlp race (agar on ho), phir player.py
    purane yt-dlp tareeke pe chala jata hai."""
    last = None
    provs = _providers()
    for i, p in enumerate(provs):
        nxt = " -> agli API" if i < len(provs) - 1 else ""
        if p["name"] in ("dump", "local"):
            fetch = dump_fetch if p["name"] == "dump" else _local_fetch
            try:
                return await fetch(kind, vid)
            except Exception as e:
                last = e
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
        print(f"[ytapi] {p['name']} {kind}/{vid} failed ({type(last).__name__}: {last}){nxt}")
    if provs and race_enabled():
        try:
            return await race_download(kind, vid, config.DOWNLOAD_DIR)
        except Exception as e:
            last = e
            print(f"[ytapi] race {kind}/{vid} failed ({type(e).__name__}: {e})")
    raise last or RuntimeError("koi API set nahi")


_TEMP_SUFFIX = (".part", ".ytdl", ".temp")


def _cached(dest_dir: str, key: str):
    try:
        for f in os.listdir(dest_dir):
            if f.startswith(key + ".") and not f.endswith(_TEMP_SUFFIX) and ".temp." not in f:
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
        for p in (provs if provs is not None else [x for x in _providers() if x["name"] != "dump"]):
            try:
                return _download_one(kind, vid, dest_dir, timeout, key, p)
            except Exception as e:
                last = e
                print(f"[ytapi] {p['name']} {kind}/{vid} download failed ({type(e).__name__}: {e}) -> agli API")
        raise last or RuntimeError("koi API set nahi")


async def download(kind: str, vid: str, dest_dir: str) -> str:
    """INNERTUBE_DIRECT=0 mode: API se local file. Order = _providers() ka order (dump bhi isi me), phir race."""
    os.makedirs(dest_dir, exist_ok=True)
    hit = _cached(dest_dir, _fkey(kind, vid))
    if hit:
        return hit
    last = None
    provs = _providers()
    for p in provs:
        try:
            if p["name"] in ("dump", "local"):
                fetch = dump_fetch if p["name"] == "dump" else _local_fetch
                return await fetch(kind, vid, dest_dir)
            return await asyncio.to_thread(_download_sync, kind, vid, dest_dir, 300, [p])
        except Exception as e:
            last = e
            print(f"[ytapi] {p['name']} {kind}/{vid} download failed ({type(e).__name__}: {e}) -> agli API")
    if provs and race_enabled():
        try:
            return await race_download(kind, vid, dest_dir)
        except Exception as e:
            last = e
            print(f"[ytapi] race {kind}/{vid} failed ({type(e).__name__}: {e})")
    raise last or RuntimeError("koi API set nahi")


# ═════════════════════════ "local" API (apna, isi server pe — koi proxy/3rd-party nahi) ═════════════════════════
def _local_get_sync(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ZoyaMusic/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


async def _local_fetch(kind: str, vid: str, dest_dir: str = "") -> str:
    """Apne local_api/server.py se file. Wahi process already bot ke cookies se download karke downloads/ me rakhta
    hai, isliye seedha wahi path use hota hai (copy/move ki zarurat nahi)."""
    dest_dir = dest_dir or config.DOWNLOAD_DIR
    key = _fkey(kind, vid)
    hit = _cached(dest_dir, key)
    if hit:
        return hit
    qkey = f"&key={urllib.parse.quote(L_KEY, safe='')}" if L_KEY else ""
    url = f"{L_URL}/resolve?vid={urllib.parse.quote(vid, safe='')}&kind={kind}{qkey}"
    data = await asyncio.to_thread(_local_get_sync, url, LOCAL_TIMEOUT)
    if data.get("status") != "done" or not data.get("path"):
        raise RuntimeError(f"local API error: {data.get('error') or data}")
    path = str(data["path"])
    if not os.path.isfile(path):
        raise RuntimeError("local API: diya hua path exist nahi karta")
    return path


# ═════════════════════════ "dump" API (JSON poll -> Telegram dump channel) ═════════════════════════
def _parse_dump_id(link) -> str:
    """"dump:31295" / "31295" / "/c/123/31295" -> "31295".  "dump:True" / khaali -> ""."""
    raw = str(link or "").strip()
    if raw.lower().startswith("dump:"):
        raw = raw[5:].strip()
    if not raw or raw.lower() in ("true", "false", "none", "null"):
        return ""
    if raw.startswith("http"):
        return ""
    m = re.search(r"(\d{4,})$", raw)
    return m.group(1) if m else ""


def _dump_base(kind: str) -> str:
    return D_VIDEO if kind == "video" else D_AUDIO


def _dump_get_sync(url: str, timeout: int = 30):
    """(status_code, json_dict). HTTP error codes exception nahi, normal return hote hain."""
    req = urllib.request.Request(url, headers={"User-Agent": "ZoyaMusic/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read(1 << 20)
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read(1 << 16)
    try:
        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        body = {}
    return code, body if isinstance(body, dict) else {}


async def _dump_poll(kind: str, vid: str) -> dict:
    """API ko tab tak poll karo jab tak status=done na ho. 2s pe 30s tak, phir 5s pe DUMP_POLL_MAX tak."""
    base = _dump_base(kind)
    if not (base and D_KEY):
        raise RuntimeError(f"dump API ({kind}) set nahi")
    url = f"{base}/{urllib.parse.quote(vid, safe='')}?api={urllib.parse.quote(D_KEY, safe='')}"
    t0 = time.monotonic()
    polls = fails5xx = 0
    last = "no response"
    while True:
        el = time.monotonic() - t0
        if el >= DUMP_POLL_MAX:
            raise RuntimeError(f"dump API timeout {el:.0f}s, {polls} polls (last: {last})")
        polls += 1
        wait = 2 if el < 30 else 5
        try:
            code, body = await asyncio.to_thread(_dump_get_sync, url)
        except Exception as e:  # network error / timeout -> dobara
            last = f"{type(e).__name__}: {e}"
            await asyncio.sleep(wait)
            continue
        if code == 202:
            last, fails5xx = "downloading", 0
            await asyncio.sleep(wait)
            continue
        if code in (400, 401, 403, 404):
            raise RuntimeError(f"dump API HTTP {code}: {body.get('error') or body.get('detail') or 'error'}")
        if code != 200:
            last = f"HTTP {code}"
            fails5xx += 1
            if fails5xx >= 6:
                raise RuntimeError(f"dump API baar-baar HTTP {code}")
            await asyncio.sleep(wait)
            continue
        fails5xx = 0
        status = str(body.get("status") or "").lower()
        if status in ("done", "success"):
            if polls > 1:
                print(f"[ytapi] dump {kind}/{vid} {el:.0f}s / {polls} polls me ready")
            return body
        if status in ("error", "failed", "fail"):
            raise RuntimeError(f"dump API error: {body.get('error') or body.get('message') or status}")
        last = f"status={status or '?'}"  # downloading / processing / pending / kuch aur -> intezaar
        await asyncio.sleep(wait)


_dump_locks: dict = {}   # key -> asyncio.Lock (ek video ek hi baar utare)
_DUMP_SEM = asyncio.Semaphore(3)


def _is_bot_client(client) -> bool:
    me = getattr(client, "me", None)
    return bool(getattr(me, "is_bot", False))


async def _fix_dump_peer(client, tag: str):
    """Assistant string-session se aata hai (peer cache khaali) -> dump channel ka peer cache me laao / join karo."""
    steps = []
    if not _is_bot_client(client):
        if D_INVITE:
            steps.append(("get_chat(invite)", lambda: client.get_chat(D_INVITE)))
            steps.append(("join_chat", lambda: client.join_chat(D_INVITE)))

        async def _dialogs():
            async for _ in client.get_dialogs(limit=300):
                pass

        steps.append(("get_dialogs", _dialogs))
    for name, fn in steps:
        try:
            await asyncio.wait_for(fn(), 25)
            print(f"[ytapi] dump channel peer ({tag}) {name} ok")
            yield name
        except Exception as e:
            low = str(e).lower()
            if "already" in low or "participant" in low:
                yield name
            else:
                print(f"[ytapi] dump channel peer ({tag}) {name}: {type(e).__name__}: {str(e)[:100]}")


async def _get_dump_message(client, tag: str, mid: int):
    async def fetch():
        return await asyncio.wait_for(client.get_messages(D_CHAT, mid), 20)

    try:
        return await fetch()
    except Exception as first:
        err = first
    async for _ in _fix_dump_peer(client, tag):
        try:
            return await fetch()
        except Exception as e:
            err = e
    raise err


def _pick_media(msg, kind: str):
    """(media_obj, ext) ya (None, None)."""
    def _ext(obj, default):
        name = getattr(obj, "file_name", None) or ""
        e = os.path.splitext(name)[1].lower()
        return e if re.fullmatch(r"\.[a-z0-9]{2,5}", e or "") else default

    doc = getattr(msg, "document", None)
    dmime = (getattr(doc, "mime_type", None) or "").lower() if doc else ""
    if kind == "video":
        if getattr(msg, "video", None):
            return msg.video, _ext(msg.video, ".mp4")
        if doc and dmime.startswith("video/"):
            return doc, _ext(doc, ".mp4")
        return None, None
    if getattr(msg, "audio", None):
        return msg.audio, _ext(msg.audio, ".mp3")
    if getattr(msg, "voice", None):
        return msg.voice, ".ogg"
    if doc and dmime.startswith("audio/"):
        return doc, _ext(doc, ".mp3")
    if getattr(msg, "video", None):  # kuch dump me audio bhi mp4 container me hota hai
        return msg.video, _ext(msg.video, ".mp4")
    return None, None


async def _dump_tg_download(mid: str, key: str, kind: str, dest_dir: str) -> str:
    if not D_CHAT:
        raise RuntimeError("DUMP_CHANNEL_ID set nahi")
    from core import bot, userbot  # lazy: circular import se bachne ke liye

    errs = []
    async with _DUMP_SEM:
        for tag, client in (("assistant", userbot), ("bot", bot)):
            if not getattr(client, "is_connected", True):
                errs.append(f"{tag}: connected nahi")
                continue
            try:
                msg = await _get_dump_message(client, tag, int(mid))
            except Exception as e:
                errs.append(f"{tag}: {type(e).__name__}: {str(e)[:80]}")
                continue
            if not msg or getattr(msg, "empty", False):
                errs.append(f"{tag}: message {mid} nahi mila (delete?)")
                continue
            media, ext = _pick_media(msg, kind)
            if not media:
                errs.append(f"{tag}: message {mid} me {kind} media nahi")
                continue
            dest = os.path.join(dest_dir, f"{key}{ext}")
            try:
                got = await asyncio.wait_for(client.download_media(msg, file_name=dest), DUMP_DL_TIMEOUT)
            except asyncio.TimeoutError:
                errs.append(f"{tag}: download timeout {DUMP_DL_TIMEOUT}s")
                continue
            except Exception as e:
                errs.append(f"{tag}: download {type(e).__name__}: {str(e)[:80]}")
                continue
            got = str(got) if got else ""
            if got and os.path.isfile(got) and os.path.getsize(got) >= DUMP_MIN_BYTES:
                return got
            if got and os.path.isfile(got):
                os.remove(got)
            errs.append(f"{tag}: file chhoti/adhoori")
    raise RuntimeError("dump channel: " + "; ".join(errs))


def _direct_download(url: str, fmt, key: str, kind: str, dest_dir: str) -> str:
    ext = re.sub(r"[^a-z0-9]", "", str(fmt or "").lower()) or ("mp3" if kind == "audio" else "mp4")
    tmp = os.path.join(dest_dir, f"{key}.{ext}.part")
    last = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZoyaMusic/1.0"})
            with urllib.request.urlopen(req, timeout=DUMP_DL_TIMEOUT) as r, open(tmp, "wb") as f:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if any(x in ctype for x in ("json", "html")):
                    raise RuntimeError(f"media nahi mila (content-type {ctype})")
                shutil.copyfileobj(r, f, 1 << 20)
            if os.path.getsize(tmp) < DUMP_MIN_BYTES:
                raise RuntimeError("downloaded file bahut chhoti hai")
            final = os.path.join(dest_dir, f"{key}.{ext}")
            os.replace(tmp, final)
            return final
        except Exception as e:
            last = e
            time.sleep(1)
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last or RuntimeError("direct download fail")


async def dump_fetch(kind: str, vid: str, dest_dir: str = "") -> str:
    """Dost ki API se file (local path). Cache -> API poll -> dump channel -> direct link."""
    dest_dir = dest_dir or config.DOWNLOAD_DIR
    os.makedirs(dest_dir, exist_ok=True)
    key = _fkey(kind, vid)
    if len(_dump_locks) > 200:
        for k in [k for k, v in _dump_locks.items() if not v.locked()]:
            _dump_locks.pop(k, None)
    lock = _dump_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cached(dest_dir, key)
        if hit:
            return hit
        data = await _dump_poll(kind, vid)
        link = str(data.get("link") or "").strip()
        errs = []
        mid = _parse_dump_id(link)
        if mid:
            try:
                return await _dump_tg_download(mid, key, kind, dest_dir)
            except Exception as e:
                errs.append(str(e))
                print(f"[ytapi] dump {kind}/{vid} channel se nahi utri ({e}) -> direct link try")
        if link.startswith("http"):
            try:
                return await asyncio.to_thread(_direct_download, link, data.get("format"), key, kind, dest_dir)
            except Exception as e:
                errs.append(f"direct: {type(e).__name__}: {e}")
        raise RuntimeError("; ".join(errs) or f"API ne usable link nahi diya (link={link[:40]!r})")


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
def _prefetch_sync(kind: str, vid: str):
    if L_ENABLED:
        # apna local API: isi call se pehle se download shuru/poora ho jata hai, baad me turant cache-hit milega
        qkey = f"&key={urllib.parse.quote(L_KEY, safe='')}" if L_KEY else ""
        try:
            _local_get_sync(f"{L_URL}/resolve?vid={urllib.parse.quote(vid, safe='')}&kind={kind}{qkey}", LOCAL_TIMEOUT)
            return  # local se mil gaya -> baaki APIs ko faltu warm karne ki zarurat nahi
        except Exception as e:
            print(f"[ytapi] local prefetch {kind}/{vid} failed: {type(e).__name__}: {e}")
    if BASE:
        req = urllib.request.Request(f"{BASE}/prefetch/{kind}/{vid}", data=b"", method="POST", headers=headers())
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(256)
    # dost ki API: ek GET se wo download shuru kar deti hai (202) -> baad me turant ready. Sirf tab jab wo pehli
    # (ya akeli) API ho, warna uske server pe faltu bojh.
    ps = _providers()
    if any(p["name"] == "dump" for p in ps) and (FIRST == "dump" or len(ps) == 1) and _dump_base(kind) and D_KEY:
        _dump_get_sync(f"{_dump_base(kind)}/{urllib.parse.quote(vid, safe='')}?api={urllib.parse.quote(D_KEY, safe='')}", 10)


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
