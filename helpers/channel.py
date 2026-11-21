# helpers/channel.py — Storage channel cache.
# Gaana ek baar YouTube se download hota hai -> background me storage channel me upload ho jata hai
# aur database me record (video id -> channel message id) save hota hai.
# Agli baar wahi gaana aaye to YouTube/yt-dlp ki jagah channel se utha liya jata hai (cookies bachti hain).
# Koi bhi gadbad ho (channel, upload, download) to bot pehle jaisa normal download kar leta hai.
import asyncio
import html
import os
import re
import shutil
from typing import Optional

import config
import database
from core import bot, userbot

# Storage channel ki ID (-100 ke saath). config.py me STORAGE_CHANNEL_ID dalo to wo use hogi.
CHANNEL_ID = int(getattr(config, "STORAGE_CHANNEL_ID", 0) or -1004323292886)

MAX_BYTES = 150 * 1024 * 1024  # isse bada gaana channel me nahi daalte
BIG_BYTES = 15 * 1024 * 1024   # isse bada ya wav/flac ho to pehle chhota (AAC) banate hain
LOSSLESS = {"wav", "flac", "aif", "aiff", "alac"}
COMPRESS_TIMEOUT = 180
UPLOAD_DELAY = 8               # gaana chalne ke itne sec baad upload shuru (playback ko lag na ho)
FETCH_TIMEOUT = 90

_VID = re.compile(r"^[\w-]{11}$")
_TEMP = re.compile(r"\.(?:temp|part|ytdl|frag\d*)(?:\.|$)|\.f\d+\.")

_clients: list = []      # jo clients channel tak pahunch sake (bot pehle, phir assistant)
_uploading: set = set()  # abhi upload ho rahe video ids
_sem_up: Optional[asyncio.Semaphore] = None
_sem_dl: Optional[asyncio.Semaphore] = None


def enabled() -> bool:
    return bool(_clients)


def _sems():
    global _sem_up, _sem_dl
    if _sem_up is None:
        _sem_up = asyncio.Semaphore(1)  # ek samay me ek hi upload
        _sem_dl = asyncio.Semaphore(2)
    return _sem_up, _sem_dl


async def init():
    """Startup par ek baar: channel tak pahunch check karo. Fail ho to cache band, bot normal chalega."""
    _clients.clear()
    for name, c in (("bot", bot), ("assistant", userbot)):
        try:
            chat = await c.get_chat(CHANNEL_ID)
            _clients.append(c)
            print(f"✅ Storage channel OK via {name}: {getattr(chat, 'title', CHANNEL_ID)}")
        except Exception as e:
            print(f"⚠️ Storage channel via {name} nahi khula: {e!r}")
    if not _clients:
        print("⚠️ Storage cache band hai (channel nahi mila) — bot normal download se chalega")


# ───────────────────────── helpers ─────────────────────────
def _vid_of(track) -> Optional[str]:
    """Sirf YouTube ke audio gaane cache hote hain (video/vplay nahi)."""
    if getattr(track, "video", False):
        return None
    vid = str(getattr(track, "vid", "") or "")
    w = str(getattr(track, "webpage", "") or "")
    if not _VID.match(vid) or ("youtube.com" not in w and "youtu.be" not in w):
        return None
    return vid


def _local_file(vid: str) -> Optional[str]:
    """Download folder me pehle se poori file ho to wahi."""
    try:
        for f in os.listdir(config.DOWNLOAD_DIR):
            if f.startswith(vid + ".") and not _TEMP.search(f):
                fp = os.path.join(config.DOWNLOAD_DIR, f)
                if os.path.isfile(fp) and os.path.getsize(fp) > 4096:
                    os.utime(fp, None)
                    return fp
    except OSError:
        pass
    return None


def _apply(track, path: str):
    track.stream_url, track.local, track.headers = path, True, None
    track.audio_url = None


# ───────────────────────── cache se lena ─────────────────────────
async def try_cache(track) -> bool:
    """True = gaana ready (local file set ho gayi). False = normal download karo."""
    try:
        vid = _vid_of(track)
        if not vid:
            return False
        hit = _local_file(vid)
        if hit:
            _apply(track, hit)
            return True
        if not enabled():
            return False
        rec = await database.song_get(vid)
        if not rec:
            return False
        _, dl = _sems()
        async with dl:
            path = await asyncio.wait_for(_fetch(rec, vid), FETCH_TIMEOUT)
        if not path:
            return False
        _apply(track, path)
        print(f"[cache] {vid} storage channel se mila (YouTube download nahi hua)")
        return True
    except Exception as e:
        print(f"[cache] {getattr(track, 'vid', '?')} cache se nahi mila ({e!r}) -> normal download")
        return False


async def _fetch(rec: dict, vid: str) -> Optional[str]:
    mid = rec.get("msg_id")
    if not mid:
        return None
    last = None
    for c in _clients:
        try:
            msg = await c.get_messages(CHANNEL_ID, int(mid))
            if not msg or getattr(msg, "empty", False) or not (msg.document or msg.audio):
                # channel se message hat gaya -> record hatao, agli baar fir upload ho jayega
                await database.song_del(vid)
                return None
            ext = (rec.get("ext") or "m4a").lstrip(".")
            os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
            final = os.path.join(config.DOWNLOAD_DIR, f"{vid}.{ext}")
            tmp = final + ".part"  # .part -> adhoori file kabhi play nahi hoti
            path = await c.download_media(msg, file_name=tmp)
            if not path or not os.path.isfile(path) or os.path.getsize(path) < 4096:
                raise RuntimeError("download adhoora")
            os.replace(path, final)
            return final
        except Exception as e:
            last = e
    if last:
        raise last
    return None


# ───────────────────────── channel me daalna ─────────────────────────
def schedule_upload(track):
    """Download hui local file ko background me channel me daalo. Kabhi block/raise nahi karta."""
    try:
        if not enabled():
            return
        vid = _vid_of(track)
        path = str(getattr(track, "stream_url", "") or "")
        if not vid or not getattr(track, "local", False) or not os.path.isfile(path):
            return
        if vid in _uploading:
            return
        _uploading.add(vid)
        asyncio.ensure_future(_upload(vid, path, str(getattr(track, "title", "") or vid), getattr(track, "duration", 0)))
    except Exception as e:
        print(f"[cache] schedule error: {e!r}")


async def _compress(vid: str, path: str) -> Optional[str]:
    """Bade/lossless gaane (jaise 51 MB wav) ko AAC 128k m4a (~4 MB) banao. Low priority, 1 thread -> bot ko lag nahi.
    Fail ho to None."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    out = os.path.join(os.path.dirname(path) or ".", f"{vid}.up.m4a.part")  # .part -> cache me kabhi nahi ginti
    cmd = [ff, "-y", "-v", "error", "-threads", "1", "-i", path, "-vn", "-map_metadata", "-1",
           "-c:a", "aac", "-b:a", "128k", "-f", "ipod", out]
    nice = shutil.which("nice")
    if nice:
        cmd = [nice, "-n", "19"] + cmd
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), COMPRESS_TIMEOUT)
        if proc.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 4096:
            return out
        print(f"[cache] compress fail ({vid}): {(err or b'')[-200:]!r}")
    except Exception as e:
        print(f"[cache] compress error ({vid}): {e!r}")
    try:
        os.remove(out)
    except OSError:
        pass
    return None


async def _upload(vid: str, path: str, title: str, duration):
    try:
        await asyncio.sleep(UPLOAD_DELAY)
        up, _ = _sems()
        async with up:
            if await database.song_get(vid):
                return  # pehle se channel me hai
            if not os.path.isfile(path):
                return
            size = os.path.getsize(path)
            if size < 4096:
                return
            ext = os.path.splitext(path)[1].lstrip(".").lower() or "m4a"
            tmp = None
            if ext in LOSSLESS or size > BIG_BYTES:
                tmp = await _compress(vid, path)
                if tmp:
                    path, ext, size = tmp, "m4a", os.path.getsize(tmp)
                    print(f"[cache] {vid} compress hua -> {size // 1024} KB")
                elif size > BIG_BYTES:
                    return  # compress nahi hua aur bahut bada hai -> channel nahi bharte
            if size > MAX_BYTES:
                return
            msg = None
            for c in _clients:
                try:
                    msg = await c.send_document(
                        CHANNEL_ID,
                        path,
                        file_name=f"{vid}.{ext}",
                        caption=f"{html.escape(title)}\n<code>{vid}</code>",
                        force_document=True,
                    )
                    break
                except Exception as e:
                    print(f"[cache] upload fail ({vid}): {e!r}")
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if msg:
                await database.song_put(
                    vid, msg_id=msg.id, title=title, duration=duration or 0, ext=ext, size=size
                )
                print(f"[cache] {vid} storage channel me save ({size // 1024} KB)")
    except Exception as e:
        print(f"[cache] upload error ({vid}): {e!r}")
    finally:
        _uploading.discard(vid)
