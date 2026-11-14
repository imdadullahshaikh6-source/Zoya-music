#!/usr/bin/env python3
# local_api/server.py — apna YouTube resolver API, sirf isi server ke andar (127.0.0.1 pe, bahar se access nahi)
#
# Kya hai: ek chhota HTTP server jo bot ke apne cookies + yt-dlp use karke audio/video download karta hai aur
# local file ka path deta hai. Koi proxy nahi lagta (free), koi third-party backend pe depend nahi (tension-free).
# Same disk/cache bot ke downloads/ folder me use hota hai, isliye file dobara download nahi hoti.
#
# Chalane ka tareeka: niche README dekho (systemd service "zoya-api" banani hai, is file ko bot se alag chalao).
#
# .env me (optional):
#   LOCAL_API_PORT=8787
#   LOCAL_API_KEY=kuch-bhi-secret-string      # khaali chhodo to bina key ke chalega (localhost pe hi hai, phir bhi key rakhna behtar)
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root import ke liye

import config  # noqa: E402
from helpers import ytdl  # noqa: E402  (cookies wala yt-dlp wrapper, pehle se bana hua)

PORT = int(os.getenv("LOCAL_API_PORT", "8787"))
API_KEY = os.getenv("LOCAL_API_KEY", "").strip()
DEST_DIR = config.DOWNLOAD_DIR
os.makedirs(DEST_DIR, exist_ok=True)

_locks: dict = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _cached(key: str):
    try:
        for f in os.listdir(DEST_DIR):
            if f.startswith(key + ".") and not f.endswith((".part", ".ytdl", ".temp")):
                fp = os.path.join(DEST_DIR, f)
                if os.path.isfile(fp) and os.path.getsize(fp) > 4096:
                    os.utime(fp, None)
                    return fp
    except OSError:
        pass
    return None


def _resolve(vid: str, video: bool) -> str:
    key = ("v_" if video else "") + vid
    with _lock_for(key):
        hit = _cached(key)
        if hit:
            return hit
        import yt_dlp

        url = f"https://www.youtube.com/watch?v={vid}"
        fmt = ytdl.VIDEO_FMT if video else ytdl.AUDIO_FMT
        outtmpl = os.path.join(DEST_DIR, f"{key}.%(ext)s")
        opts = ytdl._opts(format=fmt, outtmpl=outtmpl, skip_download=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        hit = _cached(key)
        if not hit:
            raise RuntimeError("download ke baad file nahi mili")
        return hit


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[local-api] {self.address_string()} " + (fmt % args))

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"status": "ok"})
        if u.path != "/resolve":
            return self._send(404, {"status": "error", "error": "not found"})
        q = parse_qs(u.query)
        if API_KEY and q.get("key", [""])[0] != API_KEY:
            return self._send(401, {"status": "error", "error": "bad key"})
        vid = q.get("vid", [""])[0].strip()
        kind = q.get("kind", ["audio"])[0].strip().lower()
        if not vid:
            return self._send(400, {"status": "error", "error": "vid missing"})
        t0 = time.monotonic()
        try:
            path = _resolve(vid, kind == "video")
            print(f"[local-api] {kind}/{vid} ready ({time.monotonic() - t0:.1f}s)")
            return self._send(200, {"status": "done", "path": path})
        except Exception as e:
            print(f"[local-api] {kind}/{vid} failed ({time.monotonic() - t0:.1f}s): {type(e).__name__}: {e}")
            return self._send(500, {"status": "error", "error": str(e)[:200]})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[local-api] listening on 127.0.0.1:{PORT} (key set: {bool(API_KEY)}, downloads: {DEST_DIR})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
          
