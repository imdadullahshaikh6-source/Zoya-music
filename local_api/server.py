#!/usr/bin/env python3
# local_api/server.py — apna YouTube resolver API, sirf isi server ke andar (127.0.0.1 pe, bahar se access nahi)
#
# Kya hai: ek chhota HTTP server jo bot ke apne cookies + yt-dlp use karke audio/video download karta hai aur
# local file ka path deta hai. Koi proxy nahi, koi third-party backend nahi.
#
# NAYA (bade video / movie ke liye):
#   1. Download JOB banke background me chalta hai. Bot har ~25s "kya hua?" poochta rehta hai (long-poll),
#      isliye 75s ka timeout khatam: movie jitna bhi time le, bot wahi ek download ka intezaar karta hai
#      (pehle bot timeout karke doosra download shuru kar deta tha -> 2 download ek saath -> slow + awaaz atakti thi).
#   2. File pehle .tmp folder me banti hai, poori hone par hi downloads/ me aati hai. Pehle adhoori file
#      (sirf video ya sirf audio wali .f137.mp4 / .f140.m4a) cache samajh li jati thi -> "awaaz hi nahi aati".
#   3. Video ki quality lambai ke hisaab se: <=90 min 720p, usse lamba (movie) 480p. Hamesha H.264 (avc1)
#      + fps<=30 -> file chhoti (download tez) aur VC me decode halka (CPU kam -> awaaz nahi atakti).
#   4. Strong server: nice band (LOCAL_API_NICE=10 se chhote server pe on kar sakte ho), parallel downloads zyada.
#   5. Video download ka alag slot (ek movie ke download se gaane ke download nahi ruko).
#   6. Purani v_ video files 6 ghante baad aur disk kam padne par apne aap hat jati hain.
#
# .env me (optional):
#   LOCAL_API_PORT=8787
#   LOCAL_API_KEY=kuch-bhi-secret-string
#   LOCAL_API_PARALLEL=6          # audio downloads ek saath
#   LOCAL_API_VIDEO_PARALLEL=2    # video downloads ek saath
#   LOCAL_API_NICE=0              # chhota server ho to 10
#   VIDEO_MAX_H=720               # video quality ki upar limit
#   VIDEO_KEEP_HOURS=6
#   MIN_FREE_GB=2
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root import ke liye

import config  # noqa: E402
from helpers import ytdl  # noqa: E402  (cookies wala yt-dlp wrapper, pehle se bana hua)

try:  # strong server: default me priority normal. Chhote server pe LOCAL_API_NICE=10 kar do
    _n = int(os.getenv("LOCAL_API_NICE", "0") or 0)
    if _n:
        os.nice(_n)
except (AttributeError, OSError, ValueError):
    pass

PORT = int(os.getenv("LOCAL_API_PORT", "8787"))
API_KEY = os.getenv("LOCAL_API_KEY", "").strip()
DEST_DIR = config.DOWNLOAD_DIR
TMP_ROOT = os.path.join(DEST_DIR, ".tmp")
os.makedirs(TMP_ROOT, exist_ok=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


MAX_PARALLEL = _env_int("LOCAL_API_PARALLEL", 6)
VIDEO_PARALLEL = _env_int("LOCAL_API_VIDEO_PARALLEL", 2)
MAX_H = _env_int("VIDEO_MAX_H", 720)
KEEP_HOURS = _env_int("VIDEO_KEEP_HOURS", 6)
MIN_FREE_GB = _env_int("MIN_FREE_GB", 2)
ERR_TTL = 20  # ek fail hua job itne second tak wahi error deta hai (bar-bar hathauda nahi)

_audio_slots = threading.BoundedSemaphore(MAX_PARALLEL)
_video_slots = threading.BoundedSemaphore(max(1, VIDEO_PARALLEL))
_VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TEMP_NAME = re.compile(r"\.(?:part|ytdl|temp|frag\d*)$|\.temp\.|\.f\d+\.")


def _js_opts() -> dict:
    """JS challenge solver ke liye runtimes. node pehle, deno backup."""
    rts = {}
    node = shutil.which("node") or "/usr/bin/node"
    if os.path.exists(node):
        rts["node"] = {"path": node}
    deno = shutil.which("deno") or "/root/.deno/bin/deno"
    if os.path.exists(deno):
        rts["deno"] = {"path": deno}
    out = {"remote_components": ["ejs:github"]}
    if rts:
        out["js_runtimes"] = rts
    return out


def _yt_args(existing=None, **extra) -> dict:
    ea = dict(existing or {})
    yt = dict(ea.get("youtube") or {})
    yt["player_js_variant"] = ["tv"]
    yt.update(extra)
    ea["youtube"] = yt
    return ea


def video_height(dur: int) -> int:
    """Lambai ke hisaab se quality (player.py ke VideoQuality se match karti hai)."""
    d = int(dur or 0)
    if d <= 0:
        h = 480
    elif d <= 90 * 60:
        h = 720   # strong server: 90 min tak (zyada tar movies ke trailer/episodes/songs) 720p
    else:
        h = 480   # poori movie: 480p (720p se ~2x chhoti file, download tez, quality theek)
    return min(h, MAX_H)


def video_fmt(h: int) -> str:
    # H.264 (avc1) hi: VP9/AV1 VC me bhaari decode hote hain (CPU -> awaaz atakti) ya khulte hi nahi.
    return (
        f"bestvideo[vcodec^=avc1][height<={h}][fps<=?30]+bestaudio[ext=m4a]/"
        f"bestvideo[vcodec^=avc1][height<={h}]+bestaudio[ext=m4a]/"
        f"best[vcodec^=avc1][acodec!=none][height<={h}]/"
        f"bestvideo[height<={h}][fps<=?30]+bestaudio/best[height<={h}]/best"
    )


AUDIO_FMT = "bestaudio[abr<=96]/bestaudio[filesize<10M]/bestaudio/best"


def _cached(key: str):
    """Sirf POORI file (downloads/ me sirf poori file hi aati hai, fir bhi temp naam filter rakha hai)."""
    try:
        for f in os.listdir(DEST_DIR):
            if f.startswith(key + ".") and not _TEMP_NAME.search(f):
                fp = os.path.join(DEST_DIR, f)
                if os.path.isfile(fp) and os.path.getsize(fp) > 4096:
                    os.utime(fp, None)
                    return fp
    except OSError:
        pass
    return None


def _housekeeping():
    now = time.time()
    try:
        vids = []
        for f in os.listdir(DEST_DIR):
            fp = os.path.join(DEST_DIR, f)
            if f.startswith("v_") and os.path.isfile(fp):
                if now - os.path.getmtime(fp) > KEEP_HOURS * 3600:
                    os.remove(fp)
                else:
                    vids.append(fp)
        for d in os.listdir(TMP_ROOT):  # adhoore/mare hue downloads ka kachra
            dp = os.path.join(TMP_ROOT, d)
            if os.path.isdir(dp) and now - os.path.getmtime(dp) > 3 * 3600:
                shutil.rmtree(dp, ignore_errors=True)
        vids.sort(key=os.path.getmtime)
        while vids and shutil.disk_usage(DEST_DIR).free < MIN_FREE_GB * 1024 ** 3:
            os.remove(vids.pop(0))  # sabse purani video pehle
    except Exception as e:
        print(f"[local-api] housekeeping: {type(e).__name__}: {e}")


def _download(key: str, vid: str, video: bool, dur: int) -> str:
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={vid}"
    work = os.path.join(TMP_ROOT, f"{key}-{uuid.uuid4().hex[:8]}")  # DEST_DIR ke andar -> os.replace atomic
    os.makedirs(work, exist_ok=True)
    try:
        h = video_height(dur) if video else 0
        fmt = video_fmt(h) if video else AUDIO_FMT
        opts = ytdl._opts(
            format=fmt, outtmpl=os.path.join(work, "out.%(ext)s"), skip_download=False,
            http_chunk_size=10 * 1024 * 1024,
            socket_timeout=15, retries=3, fragment_retries=3, extractor_retries=2,
            concurrent_fragment_downloads=8, noprogress=True,
        )
        opts.update(_js_opts())
        opts["extractor_args"] = _yt_args(opts.get("extractor_args"))
        if video:
            opts["merge_output_format"] = "mp4"
            if shutil.which("aria2c"):
                opts["external_downloader"] = "aria2c"
                opts["external_downloader_args"] = {
                    "aria2c": ["-x", "8", "-s", "8", "-k", "1M", "--summary-interval=0",
                               "--connect-timeout=10", "--timeout=15", "--max-tries=3", "--retry-wait=1"]
                }
        slot = _video_slots if video else _audio_slots
        with slot:  # line me lag ke apni baari
            hit = _cached(key)
            if hit:
                return hit
            t0 = time.monotonic()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                if "format is not available" not in str(e):
                    raise
                print(f"[local-api] {key}: format nahi mila, alternate clients se dobara try")
                opts2 = dict(opts)
                opts2["extractor_args"] = _yt_args(opts.get("extractor_args"), player_client=["tv", "web_embedded"])
                with yt_dlp.YoutubeDL(opts2) as ydl:
                    ydl.download([url])
            print(f"[local-api] {key} download {time.monotonic() - t0:.1f}s ({h or 'audio'}p, dur={dur}s)")
        best, size = None, 0
        for f in os.listdir(work):
            fp = os.path.join(work, f)
            if f.startswith("out.") and not _TEMP_NAME.search(f) and os.path.isfile(fp) and os.path.getsize(fp) > size:
                best, size = fp, os.path.getsize(fp)
        if not best or size < 4096:
            raise RuntimeError("download ke baad poori file nahi mili (merge fail?)")
        dest = os.path.join(DEST_DIR, key + os.path.splitext(best)[1])
        os.replace(best, dest)  # ab jaake file 'poori' ke roop me dikhti hai
        print(f"[local-api] {key} ready: {size // 1048576} MB")
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ───────────────────────── jobs ─────────────────────────
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _run_job(key: str, vid: str, video: bool, dur: int, job: dict):
    try:
        job["path"] = _cached(key) or _download(key, vid, video, dur)
        job["state"] = "done"
    except Exception as e:
        job["error"] = f"{type(e).__name__}: {e}"[:200]
        job["state"] = "error"
        print(f"[local-api] {key} failed: {job['error']}")
    finally:
        job["t_end"] = time.time()
        job["event"].set()


def _get_job(vid: str, video: bool, dur: int) -> dict:
    key = ("v_" if video else "") + vid
    with _jobs_lock:
        now = time.time()
        for k in [k for k, j in _jobs.items() if j["state"] != "working" and now - j["t_end"] > 60]:
            _jobs.pop(k, None)
        job = _jobs.get(key)
        if job and (job["state"] == "working" or (job["state"] == "error" and now - job["t_end"] < ERR_TTL)):
            return job
        job = {"state": "working", "event": threading.Event(), "path": "", "error": "", "t_end": 0.0}
        _jobs[key] = job
    if video:
        _housekeeping()
    threading.Thread(target=_run_job, args=(key, vid, video, dur, job), daemon=True).start()
    return job


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[local-api] {self.address_string()} " + (fmt % args))

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"status": "ok", "jobs": sum(1 for j in _jobs.values() if j["state"] == "working")})
        if u.path != "/resolve":
            return self._send(404, {"status": "error", "error": "not found"})
        q = parse_qs(u.query)
        if API_KEY and q.get("key", [""])[0] != API_KEY:
            return self._send(401, {"status": "error", "error": "bad key"})
        vid = q.get("vid", [""])[0].strip()
        kind = q.get("kind", ["audio"])[0].strip().lower()
        if not _VID_RE.match(vid):
            return self._send(400, {"status": "error", "error": "vid galat/missing"})
        try:
            dur = int(q.get("dur", ["0"])[0] or 0)
            wait = max(0, min(int(q.get("wait", ["25"])[0] or 0), 50))
        except ValueError:
            dur, wait = 0, 25
        video = kind == "video"
        key = ("v_" if video else "") + vid
        hit = _cached(key)
        if hit:
            return self._send(200, {"status": "done", "path": hit})
        job = _get_job(vid, video, dur)
        job["event"].wait(wait)
        if job["state"] == "working":
            return self._send(200, {"status": "working"})
        if job["state"] == "done" and job["path"] and os.path.isfile(job["path"]):
            return self._send(200, {"status": "done", "path": job["path"]})
        return self._send(500, {"status": "error", "error": job["error"] or "file gayab ho gayi, dobara try karo"})


def main():
    _housekeeping()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[local-api] listening on 127.0.0.1:{PORT} (key set: {bool(API_KEY)}, downloads: {DEST_DIR}, "
          f"audio slots {MAX_PARALLEL}, video slots {VIDEO_PARALLEL}, max {MAX_H}p)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
