# helpers/player.py — poora playback engine (queue, controls, player card, stream end)
import asyncio
import html
import inspect
import re
import itertools
import traceback
import os
import random
import time
from typing import List, Optional

import yt_dlp
from pyrogram.types import InlineKeyboardMarkup
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

import config
import database
import state
from core import bot, call_py
from helpers import assistant, autopick, panel, perms, spotify, thumb, ytdl
from helpers.buttons import btn
from helpers.fonts import fmt_played, fmt_time, sc
from helpers.strings import t
from state import Track

# ───────────────────────── link preview off ─────────────────────────
# Title ek hyperlink hai, isliye Telegram neeche YouTube ka preview card bana deta tha.
# Ye kwargs har text message/edit me lagte hain (pyrogram ke dono versions ke liye).


def _preview_off() -> dict:
    try:
        from pyrogram import Client as _C
        for cls in (type(bot), _C):
            params = inspect.signature(cls.send_message).parameters
            if "link_preview_options" in params:
                from pyrogram.types import LinkPreviewOptions
                return {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
            if "disable_web_page_preview" in params:
                return {"disable_web_page_preview": True}
    except Exception as e:
        print(f"[player] preview-off setup failed: {e!r}")
    return {}


NOPREV = _preview_off()

# ───────────────────────── small utils ─────────────────────────


def mention(user) -> str:
    if not user:
        return sc("anonymous")
    return f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'


def esc(s) -> str:
    return html.escape(str(s or ""))


_TITLE_BRACKETS = re.compile(r"[\(\[\{【（][^\)\]\}】）]*[\)\]\}】）]")
_TITLE_FEAT = re.compile(r"\s+(?:feat|ft|featuring)\b.*$", re.I)
_TITLE_TAIL = re.compile(
    r"[\s\-–—:,]*\b(?:official|video|music|audio|lyrical|lyrics|lyric|full song|full video|new song|hd|4k)\b[\s\-–—:,]*$", re.I
)
TITLE_MAX = 45


def short_title(title: str) -> str:
    """'Jhol | Coke Studio Pakistan | Season 15 | Maanu x Annural Khalid' -> 'Jhol'
    (brackets, '|' ke baad ka hissa, official/lyrics jaise shabd aur feat. hata ke chhota naam)."""
    raw = (title or "").strip()
    t = _TITLE_BRACKETS.sub(" ", raw)
    parts = [x.strip() for x in t.split("|") if x.strip()]
    t = parts[0] if parts else t
    t = _TITLE_FEAT.sub("", t)
    for _ in range(3):  # "Song Official Video" jaise piche ke ek se zyada shabd
        t2 = _TITLE_TAIL.sub("", t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\s+", " ", t).strip(" -–—:,")
    if not t:
        t = raw
    if len(t) > TITLE_MAX:
        t = t[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" -–—:,") + "…"
    return t


def link_title(track: Track) -> str:
    """Ab link nahi banta: sirf chhota, saaf naam dikhta hai (naam purana hai taaki baaki code na badalna pade)."""
    return esc(short_title(track.title))


def err_kind(e: Exception) -> str:
    n = type(e).__name__
    if n in ("NoActiveGroupCall", "GroupcallForbidden", "GroupCallNotFound"):
        return "no_vc"
    if n in ("UnMuteNeeded",):
        return "muted"
    if "GROUPCALL" in str(e).upper() or "NoActiveGroupCall" in str(e):
        return "no_vc"
    return "other"


def _transport_err(e: Exception) -> bool:
    return type(e).__name__ == "TransportParseException" or "Transport not found" in str(e)


async def _play_err_text(chat_id: int, e: Exception) -> str:
    """Asli wajah batao, galat 'no voice chat' nahi."""
    kind = err_kind(e)
    if kind != "other":
        return await t(chat_id, kind)
    if _transport_err(e):
        return sc(
            "assistant could not connect to the voice chat. make sure the assistant is in this group (not banned or restricted), "
            "the voice chat is running, then try again."
        )
    err = f"{type(e).__name__}: {e}"
    if len(err) > 300:  # lambe googlevideo URL wale errors chat me na bhar jaayen
        err = err[:300] + "…"
    return await t(chat_id, "play_err", err=esc(err))


# ───────────────────────── captions & keyboard ─────────────────────────


def now_caption(track: Track) -> str:
    return (
        f"<u>{sc('now streaming')}</u>\n\n"
        f"<b>{sc('title')}:</b> {link_title(track)}\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_time(track.duration) if track.duration else 'LIVE'}</code>\n"
        f"<b>{sc('requested by')}:</b> {track.requester or sc('unknown')}"
    )


def ended_caption(track: Track, played: int, reason: str) -> str:
    total = fmt_time(track.duration) if track.duration else "LIVE"
    return (
        f"<u>{sc('stream ended')}</u>\n\n"
        f"<b>{sc('title')}:</b> {link_title(track)}\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_played(played)} / {total}</code>\n"
        f"• <b>{sc('reason')}:</b> <i>{reason}</i>"
    )


def player_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Pehle sirf 'controls ?' button; click par poora panel (helpers/panel.py)."""
    return panel.player_keyboard(chat_id)


CLOSE_KB = InlineKeyboardMarkup([[btn("close", "x", style="danger")]])


async def _fail(msg, text):
    return await msg.edit_text(text, reply_markup=CLOSE_KB)

# ───────────────────────── low-level playback ─────────────────────────


def _mk_stream(track: Track, kw: dict):
    if track.video:
        extra = {}
        if track.audio_url:
            extra["audio_path"] = track.audio_url
        return MediaStream(
            track.stream_url,
            audio_parameters=AudioQuality.HIGH,
            video_parameters=VideoQuality.HD_720p,
            video_flags=MediaStream.Flags.REQUIRED,
            **extra,
            **kw,
        )
    return MediaStream(
        track.stream_url,
        audio_parameters=AudioQuality.HIGH,
        video_flags=MediaStream.Flags.IGNORE,
        **kw,
    )


def build_stream(track: Track, seek: int = 0):
    kw = {}
    if seek:
        kw["ffmpeg_parameters"] = f"-ss {int(seek)}"
    if track.headers and not track.local:
        kw["headers"] = track.headers
    try:
        return _mk_stream(track, kw)
    except TypeError:  # purane py-tgcalls me headers param nahi hota
        kw.pop("headers", None)
        return _mk_stream(track, kw)


def _dl_sync(track: Track) -> str:
    """yt-dlp se audio file download karo (cookies ke saath). Cache bhi karta hai."""
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    key = track.vid or str(abs(hash(track.webpage or track.title)))
    # pehle se download hai to wahi use karo
    for f in os.listdir(config.DOWNLOAD_DIR):
        if f.startswith(key + ".") and not f.endswith((".part", ".ytdl")):
            return os.path.join(config.DOWNLOAD_DIR, f)
    opts = {
        "format": "bestaudio",
        "outtmpl": os.path.join(config.DOWNLOAD_DIR, f"{key}.%(ext)s"),
        "cookiefile": "cookies.txt",
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:github"],
        "quiet": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(track.webpage, download=True)
        return ydl.prepare_filename(info)


# Video (/vplay): VC ka ffmpeg AV1 (itag 398/399...) decode nahi kar pata -> "NoVideoSourceFound".
# Isliye H.264 (avc1) video + m4a audio chunte hain, 720p tak. Na mile to VP9, phir kuch bhi.
_VFMT = (
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/"
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
    "best[vcodec^=avc1][height<=720]/"
    "bestvideo[vcodec^=vp9][height<=720]+bestaudio/"
    "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
)
_vres: dict = {}  # id(track) -> track (jinka video format already resolve ho chuka)


def _resolve_video_sync(track: Track):
    opts = {
        "format": _VFMT,
        "cookiefile": "cookies.txt",
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:github"],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(track.webpage, download=False)
    fmts = info.get("requested_formats") or [info]
    v = next((f for f in fmts if f.get("vcodec") not in (None, "none")), fmts[0])
    a = next((f for f in fmts if f is not v and f.get("acodec") not in (None, "none")), None)
    track.stream_url = v["url"]
    track.audio_url = a["url"] if a else None
    track.headers = v.get("http_headers") or track.headers
    return v.get("format_id"), v.get("vcodec")


def _video_to_audio(track: Track):
    """Video play na ho paye to usi gaane ko audio-only bana do."""
    track.video = False
    track.local = False
    track.stream_url = None
    track.audio_url = None
    _prepared.pop(id(track), None)
    _vres.pop(id(track), None)


# ───────────────────────── prefetch (agla song pehle se ready) ─────────────────────────
# Current song khatam hone se PREFETCH_SECONDS pehle agla song (queue ka pehla, ya autoplay ka related)
# dhoondh ke download kar liya jata hai, taaki switch turant ho.
# NOTICE_SECONDS pehle "playing next track..." message aata hai, jo switch hote hi song ke card me badal jata hai.
# config.py me badal sakte ho:  PREFETCH_SECONDS = 10
PREFETCH_SECONDS = int(getattr(config, "PREFETCH_SECONDS", 10))
NOTICE_SECONDS = 2
SWITCH_GRACE = 0.5    # song khatam hone ke itne second baad bhi stream-end event na aaye to bot khud agla chala deta hai

_prepared: dict = {}   # id(track) -> track   (stream_url + local file ready; start_track use karke hata deta hai)
_prep_tasks: dict = {}  # id(track) -> Task    (ek hi track do baar parallel download na ho)
_pre: dict = {}        # chat_id -> {"for", "task", "track", "auto", "card"}
_ph: dict = {}         # chat_id -> {"msg", "track"}  ("playing next track..." / "picking a next track..." message)
_sched: dict = {}      # chat_id -> Task (har chat ka timer)


def _rm(path):
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _discard_rec(rec):
    if rec:
        _rm(rec.get("card"))
        rec["card"] = None


async def _prepare_impl(track: Track):
    await ytdl.ensure_stream(track)
    if track.video and track.webpage and str(track.webpage).startswith("http") and not track.local and id(track) not in _vres:
        try:
            fid, vc = await asyncio.wait_for(asyncio.to_thread(_resolve_video_sync, track), 45)
            _vres[id(track)] = track
            while len(_vres) > 30:
                _vres.pop(next(iter(_vres)))
            print(f"[play] video format {fid} ({vc})")
        except Exception as e:
            print(f"[play] h264 video resolve failed, using default format: {e!r}")
    # FIX: remote URL ki jagah local file se play karo (silent audio issue)
    if not track.local and not track.video and track.webpage:
        try:
            path = await asyncio.to_thread(_dl_sync, track)
            track.stream_url = path
            track.local = True
            track.headers = None
            print(f"[play] downloaded: {path}")
        except Exception as e:
            print(f"[play] download failed, using direct url: {e!r}")
    _prepared[id(track)] = track
    while len(_prepared) > 30:
        _prepared.pop(next(iter(_prepared)))


async def prepare(track: Track):
    """Stream URL + download. Pehle se ho chuka ho to turant return; chal raha ho to usi ka wait."""
    k = id(track)
    if k in _prepared:
        return
    task = _prep_tasks.get(k)
    if task is None:
        task = asyncio.ensure_future(_prepare_impl(track))
        _prep_tasks[k] = task
        task.add_done_callback(lambda _t, k=k: _prep_tasks.pop(k, None))
    await asyncio.shield(task)


async def start_track(chat_id: int, track: Track, seek: int = 0):
    st = state.get(chat_id)
    await prepare(track)
    _prepared.pop(id(track), None)
    await call_py.play(chat_id, build_stream(track, seek))
    st.current = track
    st.started = time.time() - seek
    st.paused = False
    st.paused_at = 0.0
    if track.vid:
        st.history.add(track.vid)
        if len(st.history) > 200:
            st.history.clear()
    if not seek:
        autopick.note_played(chat_id, track)  # autoplay isse milta-julta gaana dobara nahi chunega
    _arm(chat_id, track, seek)


async def _prefetch_job(chat_id: int, current: Track, rec: dict):
    st = state.get(chat_id)
    try:
        if st.queue:
            tr = st.queue[0]
        elif st.autoplay:
            tr = await asyncio.wait_for(autopick.pick(chat_id, current, st.history, [q.title for q in st.queue]), 75)
            if not tr:
                return
            tr.requester = sc("autoplay")
            rec["auto"] = True
        else:
            return
        rec["track"] = tr
        await prepare(tr)
        # placeholder ke liye thumbnail card pehle se bana ke rakho (2s me bhejna hai)
        try:
            if (await database.get_chat(chat_id)).get("thumb", True):
                rec["card"] = await thumb.make_card(tr.thumb, tr.title, tr.channel, 0, tr.duration)
                if _pre.get(chat_id) is not rec:  # tab tak skip/stop ho chuka -> card ki zarurat nahi
                    _discard_rec(rec)
        except Exception as e:
            print(f"[prefetch] card failed: {e!r}")
        print(f"[prefetch] chat={chat_id} ready: {tr.title!r}")
    except Exception as e:
        print(f"[prefetch] chat={chat_id} failed: {e!r}")


def _start_prefetch(chat_id: int, current: Track):
    st = state.get(chat_id)
    if st.loop:
        return
    old = _pre.get(chat_id)
    if old and old["for"] is current:
        return  # is track ke liye already chal raha / ho chuka
    _discard_rec(old)
    rec = {"for": current, "task": None, "track": None, "auto": False, "card": None}
    rec["task"] = asyncio.ensure_future(_prefetch_job(chat_id, current, rec))
    _pre[chat_id] = rec


async def _drop_ph(chat_id: int):
    ph = _ph.pop(chat_id, None)
    if ph:
        try:
            await ph["msg"].delete()
        except Exception:
            pass


async def _send_placeholder(chat_id: int):
    """Switch se ~2s pehle: 'playing next track...' (thumbnail ho to uske saath)."""
    st = state.get(chat_id)
    if st.loop or chat_id in _ph:
        return
    rec = _pre.get(chat_id)
    nxt = rec["track"] if rec else None
    if nxt is None:
        if not (st.queue or st.autoplay):
            return  # kuch aane wala nahi -> assistant VC chhodega, message nahi
        if rec and rec["task"].done():
            return  # autoplay ko related track mila hi nahi
    text = f"<i>{sc('playing next track...')}</i>"
    path = rec["card"] if (rec and rec["card"] and os.path.isfile(rec["card"])) else None
    msg = None
    try:
        if path:
            msg = await bot.send_photo(chat_id, path, caption=text, has_spoiler=True)
        else:
            msg = await bot.send_message(chat_id, text)
    except Exception as e:
        print(f"[placeholder] send failed: {e!r}")
    finally:
        if path:
            _rm(path)
            rec["card"] = None
    if msg:
        _ph[chat_id] = {"msg": msg, "track": nxt if path else None}


async def _safe_stream_end(chat_id: int, track: Track):
    try:
        await on_stream_end(chat_id, expect=track)
    except Exception as e:
        print(f"[timer] on_stream_end error: {e!r}")
        traceback.print_exc()


async def _watch(chat_id: int, track: Track, seek: int = 0):
    """Har chal rahe song ka apna timer (state.played() pe bharosa nahi, khud ki clock):
    prefetch -> 'playing next track...' -> end hote hi agla track (event na aaye to bhi)."""
    st = state.get(chat_id)
    prefetched = noticed = False
    elapsed = float(seek)
    last = time.monotonic()
    try:
        while st.current is track and st.active:
            now = time.monotonic()
            if not st.paused:
                elapsed += now - last
            last = now
            if st.paused:
                await asyncio.sleep(0.5)
                continue
            remaining = track.duration - elapsed
            if not prefetched and remaining <= PREFETCH_SECONDS:
                prefetched = True
                print(f"[timer] chat={chat_id} {remaining:.0f}s left -> prefetch next")
                _start_prefetch(chat_id, track)
            if not noticed and remaining <= NOTICE_SECONDS:
                noticed = True
                await _send_placeholder(chat_id)
            elif not noticed and chat_id in _ph and remaining > NOTICE_SECONDS + 3:
                await _drop_ph(chat_id)  # user ne peeche seek kiya -> purana notice hata do
            if remaining <= -SWITCH_GRACE:
                print(f"[timer] chat={chat_id} song ended, switching to next track")
                asyncio.ensure_future(_safe_stream_end(chat_id, track))
                return
            await asyncio.sleep(1.0 if remaining > NOTICE_SECONDS + 1.5 else 0.2)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[timer] chat={chat_id} error: {e!r}")
        traceback.print_exc()


def _arm(chat_id: int, track: Track, seek: int = 0):
    _disarm(chat_id)
    if track.duration:  # live stream ka end nahi hota
        _sched[chat_id] = asyncio.ensure_future(_watch(chat_id, track, seek))


def _disarm(chat_id: int):
    task = _sched.pop(chat_id, None)
    if task and task is not asyncio.current_task():
        task.cancel()


async def _delete_old(st):
    if st.msg:
        try:
            await st.msg.delete()
        except Exception:
            pass
        st.msg = None


async def send_player(chat_id: int, track: Track, message=None, ph=None):
    """Player card group me SPOILER ke saath bhejta hai.
    ph = 'playing next track...' wala message: usi ko edit karke card bana deta hai."""
    st = state.get(chat_id)
    await _delete_old(st)
    caption = now_caption(track)
    kb = player_keyboard(chat_id)
    cdata = await database.get_chat(chat_id)
    want_photo = bool(cdata.get("thumb", True))
    if ph is not None:
        m = ph["msg"]
        try:
            if m.photo and want_photo and ph.get("track") is track:
                await m.edit_caption(caption, reply_markup=kb)
                st.msg = m
                return
            if not m.photo and not want_photo:
                await m.edit_text(caption, reply_markup=kb, **NOPREV)
                st.msg = m
                return
        except Exception as e:
            print(f"[send_player] placeholder edit failed: {e!r}")
        # text <-> photo me edit nahi ho sakta: purana hata ke naya card bhejo
        try:
            await m.delete()
        except Exception:
            pass
    path = None
    if want_photo:
        path = await thumb.make_card(track.thumb, track.title, track.channel, 0, track.duration)
    sent = None
    try:
        if path:
            if message is not None:
                sent = await message.reply_photo(path, caption=caption, reply_markup=kb, has_spoiler=True)
            else:
                sent = await bot.send_photo(chat_id, path, caption=caption, reply_markup=kb, has_spoiler=True)
        else:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb, **NOPREV)
    except Exception as e:
        print(f"send_player error: {e}")
        try:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb, **NOPREV)
        except Exception:
            pass
    finally:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass
    st.msg = sent


async def refresh_keyboard(chat_id: int):
    st = state.get(chat_id)
    if st.msg:
        try:
            await st.msg.edit_reply_markup(player_keyboard(chat_id))
        except Exception:
            pass


async def finish(chat_id: int, reason: str):
    """Call chhodo, state saaf karo, last player message ko 'Stream Ended' bana do."""
    st = state.get(chat_id)
    assistant.touch(chat_id)  # idle-clock yahin se shuru (10 min baad assistant leave)
    _disarm(chat_id)
    _discard_rec(_pre.pop(chat_id, None))
    autopick.forget(chat_id)
    await _drop_ph(chat_id)
    track, played, msg = st.current, st.played(), st.msg
    try:
        await asyncio.wait_for(call_py.leave_call(chat_id), 15)
    except Exception:
        pass
    st.current, st.msg = None, None
    st.queue.clear()
    st.loop = 0
    st.paused = False
    if not track:
        return
    cap = ended_caption(track, played, reason)
    try:
        if msg:
            await msg.edit_caption(cap, reply_markup=CLOSE_KB) if msg.photo else await msg.edit_text(cap, reply_markup=CLOSE_KB, **NOPREV)
        else:
            await bot.send_message(chat_id, cap, reply_markup=CLOSE_KB, **NOPREV)
    except Exception:
        try:
            await bot.send_message(chat_id, cap, reply_markup=CLOSE_KB, **NOPREV)
        except Exception:
            pass


async def _pick_next(chat_id: int, st, rec) -> Optional[Track]:
    """Pehle queue, phir autoplay (prefetch hua ho to wahi), warna None."""
    if st.queue:
        return st.queue.pop(0)
    if st.autoplay and st.current:
        if rec and rec["task"] is not None and (rec["auto"] or rec["track"] is None):
            try:  # prefetch abhi chal raha ho to uska intezaar (download wahi share hoga)
                await asyncio.wait_for(asyncio.shield(rec["task"]), 120)
            except Exception:
                pass
            if rec["auto"] and rec["track"] is not None:
                return rec["track"]
        try:
            tr = await asyncio.wait_for(autopick.pick(chat_id, st.current, st.history, [q.title for q in st.queue]), 75)
        except Exception as e:
            print(f"[autoplay] related failed: {e!r}")
            return None
        if tr:
            tr.requester = sc("autoplay")
        return tr
    return None


async def _play_next(chat_id: int) -> bool:
    """Queue (ya autoplay) se agla track chalao. False = kuch bacha nahi / fatal error."""
    st = state.get(chat_id)
    rec = _pre.pop(chat_id, None)   # prefetch hua track (agar hua ho)
    ph = _ph.pop(chat_id, None)     # auto-switch ka "playing next track..." message (agar bheja ho)
    if ph is None and (st.queue or (st.autoplay and st.current)):
        ready = bool(rec and rec["track"] is not None and rec["task"].done() and id(rec["track"]) in _prepared)
        if not ready:
            # skip / download me time lagega -> turant batao, track start hote hi isi message ko card bana do
            try:
                m = await asyncio.wait_for(bot.send_message(chat_id, f"<i>{sc('picking a next track...')}</i>"), 10)
                ph = {"msg": m, "track": None}
            except Exception:
                ph = None
    try:
        while True:
            nxt: Optional[Track] = await _pick_next(chat_id, st, rec)
            rec = None
            if nxt is None:
                return False
            try:
                await asyncio.wait_for(start_track(chat_id, nxt), 90)
            except Exception as e:
                print(f"[play_next] start_track failed: {type(e).__name__}: {e!r}")
                if type(e).__name__ == "NoVideoSourceFound" and nxt.video:
                    _video_to_audio(nxt)
                    st.queue.insert(0, nxt)
                    try:
                        await bot.send_message(chat_id, f"<i>{sc('this video could not be streamed, playing audio only.')}</i>")
                    except Exception:
                        pass
                    continue
                kind = err_kind(e)
                if kind in ("no_vc", "muted"):
                    st.queue.clear()
                    await bot.send_message(chat_id, await t(chat_id, kind))
                    return False
                try:
                    await bot.send_message(chat_id, await t(chat_id, "play_err", err=esc(f"{nxt.title}: {type(e).__name__}: {e}")))
                except Exception:
                    pass
                continue
            try:
                await asyncio.wait_for(send_player(chat_id, nxt, ph=ph), 30)
            except Exception as e:
                print(f"[play_next] send_player failed: {e!r}")
            ph = None
            return True
    finally:
        if ph:  # use nahi hua (kuch bacha nahi) -> hata do
            try:
                await ph["msg"].delete()
            except Exception:
                pass
        _discard_rec(rec)


# ───────────────────────── events ─────────────────────────


async def on_stream_end(chat_id: int, expect: Optional[Track] = None):
    st = state.get(chat_id)
    print(f"[stream_end] chat={chat_id} src={'timer' if expect is not None else 'event'} queue={len(st.queue)} autoplay={st.autoplay} loop={st.loop}")
    async with st.lock:
        if not st.active:
            return
        if expect is not None and st.current is not expect:
            return  # timer aur asli event ek saath aaye: dobara skip nahi karna
        if st.loop > 0:
            st.loop -= 1
            try:
                await start_track(chat_id, st.current)
                return
            except Exception:
                pass
        if not await _play_next(chat_id):
            await finish(chat_id, esc(await t(chat_id, "ended_queue")))


async def on_call_closed(chat_id: int, key: str):
    st = state.get(chat_id)
    async with st.lock:
        if not st.active:
            return
        await finish(chat_id, esc(await t(chat_id, key)))


# ───────────────────────── controls ─────────────────────────
# har function ek key return karta hai (strings.py ki) — "ok" ya error key


async def do_pause(chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    if st.paused:
        return "already_paused"
    await call_py.pause(chat_id)
    st.paused, st.paused_at = True, time.time()
    await refresh_keyboard(chat_id)
    return "ok"


async def do_resume(chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    if not st.paused:
        return "not_paused"
    await call_py.resume(chat_id)
    st.started += time.time() - st.paused_at
    st.paused = False
    await refresh_keyboard(chat_id)
    return "ok"


async def do_skip(chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    async with st.lock:
        st.loop = 0
        if not await _play_next(chat_id):
            await finish(chat_id, esc(await t(chat_id, "ended_queue")))
    return "ok"


async def do_stop(chat_id: int, user_html: str) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    async with st.lock:
        await finish(chat_id, await t(chat_id, "ended_stop", user=user_html))
    return "ok"


# "play now" button (queue me add hone wale message ke saath)
_qtok: dict = {}
_qctr = itertools.count(1)


def register_queued(track: Track) -> int:
    tok = next(_qctr)
    _qtok[tok] = track
    while len(_qtok) > 500:
        _qtok.pop(next(iter(_qtok)))
    return tok


def in_queue(chat_id: int, track: Track) -> bool:
    st = state.get(chat_id)
    return st.active and any(q is track for q in st.queue)


async def play_now(chat_id: int, track: Track) -> str:
    """Queue ke is track ko sabse aage laga ke turant chalao."""
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    async with st.lock:
        idx = next((i for i, q in enumerate(st.queue) if q is track), None)
        if idx is None:
            return "gone"
        st.queue.insert(0, st.queue.pop(idx))
        st.loop = 0
        if not await _play_next(chat_id):
            await finish(chat_id, esc(await t(chat_id, "ended_queue")))
    return "ok"


async def do_seek(chat_id: int, delta: int) -> (str, int):
    st = state.get(chat_id)
    if not st.active:
        return "nothing", 0
    tr = st.current
    if not tr.duration:
        return "seek_bad", 0
    new = max(st.played() + delta, 0)
    if new >= tr.duration - 3:
        return "seek_bad", 0
    async with st.lock:
        await start_track(chat_id, tr, seek=new)
    return "ok", new


def do_loop(chat_id: int, n: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    st.loop = max(0, min(n, 10))
    return "loop_set" if st.loop else "loop_off"


def do_shuffle(chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    if len(st.queue) < 2:
        return "shuffle_need"
    random.shuffle(st.queue)
    return "shuffled"


# ───────────────────────── queue text ─────────────────────────


def queue_text(chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return ""
    c = st.current
    out = [
        f"<u>{sc('now playing')}</u>",
        f"<b>{link_title(c)}</b>",
        f"<code>{fmt_played(st.played())} / {fmt_time(c.duration) if c.duration else 'LIVE'}</code> • {c.requester}",
    ]
    if st.queue:
        out.append(f"\n<u>{sc('up next')}</u> ({len(st.queue)})")
        for i, q in enumerate(st.queue[:10], 1):
            out.append(f"<b>{i}.</b> {esc(q.title)} <code>{fmt_time(q.duration) if q.duration else '--'}</code>")
        if len(st.queue) > 10:
            out.append(f"+{len(st.queue) - 10} {sc('more')}")
    return "\n".join(out)


# ───────────────────────── /play handler ─────────────────────────


async def _from_file(message, video: bool) -> Optional[Track]:
    r = message.reply_to_message
    if not r:
        return None
    media = r.audio or r.video or r.voice or r.video_note
    is_vid = bool(r.video or r.video_note)
    if not media and r.document and (r.document.mime_type or "").startswith(("audio/", "video/")):
        media = r.document
        is_vid = r.document.mime_type.startswith("video/")
    if not media:
        return None
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    path = await r.download(file_name=os.path.join(config.DOWNLOAD_DIR, ""))
    title = getattr(media, "title", None) or getattr(media, "file_name", None) or "Telegram file"
    return Track(
        title=title,
        duration=int(getattr(media, "duration", 0) or 0),
        stream_url=path,
        local=True,
        video=bool(video and is_vid),
        resolved_at=time.time(),
    )


async def _resolve(message, video: bool, uid: int) -> List[Track]:
    chat_id = message.chat.id
    args = " ".join(message.command[1:]).strip()
    r = message.reply_to_message

    if not args:
        ft = await _from_file(message, video)
        if ft:
            return [ft]
        if r and (r.text or r.caption):
            args = (r.text or r.caption).strip()
    if not args:
        raise ValueError("usage_play")

    if args.lower().startswith("playlist-"):
        doc = await database.pl_get(args[9:].strip())
        if not doc or doc["user_id"] != uid:
            raise ValueError("pl_missing")
        if not doc["tracks"]:
            raise ValueError("pl_empty")
        return [
            Track(title=x["title"], duration=x.get("duration", 0), webpage=x["webpage"], video=video)
            for x in doc["tracks"]
        ]

    if spotify.is_spotify(args):
        queries = await spotify.resolve(args, limit=min(25, config.QUEUE_LIMIT))
        first = await ytdl.get_track(queries[0], video)
        return [first] + [Track(title=q, query=q, video=video) for q in queries[1:]]

    if ytdl.YT_RE.search(args) and "/playlist" in args:
        tracks = await ytdl.get_playlist(args, video, config.QUEUE_LIMIT)
        if not tracks:
            raise ValueError("not_found")
        return tracks

    return [await ytdl.get_track(args, video)]


async def handle_play(client, message, video: bool = False, force: bool = False):
    chat_id = message.chat.id
    user = message.from_user
    uid = user.id if user else 0
    await database.add_served_chat(chat_id)
    cdata = await database.get_chat(chat_id)

    if (force or cdata["play_mode"] == "admins") and not await perms.message_can_control(client, message):
        return await message.reply_text(await t(chat_id, "admins_only"), reply_markup=CLOSE_KB)

    msg = await message.reply_text(await t(chat_id, "searching"))

    ok, err, markup = await assistant.ensure(client, message.chat, msg)
    if not ok:
        return await msg.edit_text(err, reply_markup=markup)

    print(f"[play] chat={chat_id} assistant ok, resolving...")
    try:
        tracks = await asyncio.wait_for(_resolve(message, video, uid), timeout=90)
        print(f"[play] resolved: {tracks[0].title!r} dur={tracks[0].duration}")
    except asyncio.TimeoutError:
        print("[play] RESOLVE TIMEOUT (yt-dlp 90s me nahi nikla)")
        return await _fail(msg, sc("search timed out. youtube is too slow or blocking this server. try again."))
    except ValueError as e:
        key = str(e)
        if key == "pl_missing":
            return await _fail(msg, sc("playlist not found, or it is not yours."))
        if key == "pl_empty":
            return await _fail(msg, sc("this playlist is empty."))
        return await _fail(msg, await t(chat_id, key))
    except Exception as e:
        print(f"resolve error: {e!r}")
        traceback.print_exc()
        if "Sign in" in str(e):
            return await _fail(msg, sc("youtube is blocking this server (bot check). the owner needs to add a cookies.txt file."))
        return await _fail(msg, await t(chat_id, "not_found"))

    who = mention(user)
    limit = config.DURATION_LIMIT_MIN * 60
    for tr in tracks:
        tr.requester, tr.requester_id = who, uid
        if not tr.local:
            tr.video = video
    if tracks[0].duration and tracks[0].duration > limit:
        return await _fail(msg, await t(chat_id, "too_long", mins=config.DURATION_LIMIT_MIN))

    st = state.get(chat_id)
    async with st.lock:
        if force or not st.active:
            first, rest = tracks[0], tracks[1:]
            room = config.QUEUE_LIMIT
            rest = rest[:room]
            if force:
                st.queue[0:0] = rest
            else:
                st.queue.extend(rest)
            for attempt in (1, 2):
                try:
                    print(f"[play] joining voice chat / starting stream... (try {attempt})")
                    await asyncio.wait_for(start_track(chat_id, first), timeout=75)
                    print("[play] stream started")
                    break
                except Exception as e:
                    print(f"start_track error: {type(e).__name__}: {e!r}")
                    traceback.print_exc()
                    if not st.active:
                        try:
                            await call_py.leave_call(chat_id)
                        except Exception:
                            pass
                    if attempt == 1:
                        if type(e).__name__ == "NoVideoSourceFound" and first.video:
                            _video_to_audio(first)
                            try:
                                await bot.send_message(chat_id, f"<i>{sc('this video could not be streamed, playing audio only.')}</i>")
                            except Exception:
                                pass
                            continue
                        # assistant group se nikal gaya/nikala gaya ho to pehle invite karo, phir dobara play
                        if await assistant.membership(chat_id) is False:
                            assistant.forget(chat_id)
                            ok, err, markup = await assistant.ensure(client, message.chat, msg)
                            if not ok:
                                st.queue.clear()
                                return await msg.edit_text(err, reply_markup=markup or CLOSE_KB)
                            continue
                        if _transport_err(e):
                            await asyncio.sleep(2)
                            continue
                    if not st.active:
                        st.queue.clear()
                    return await _fail(msg, await _play_err_text(chat_id, e))
            try:
                await msg.delete()
            except Exception:
                pass
            await send_player(chat_id, first, message)
            return

        room = config.QUEUE_LIMIT - len(st.queue)
        if room <= 0:
            return await _fail(msg, await t(chat_id, "queue_full", limit=config.QUEUE_LIMIT))
        added = tracks[:room]
        st.queue.extend(added)
        if len(added) == 1:
            tr = added[0]
            play_now_kb = InlineKeyboardMarkup([[btn("play now", f"pl:now:{chat_id}:{register_queued(tr)}", style="primary")]])
            await msg.edit_text(
                await t(
                    chat_id,
                    "added",
                    pos=len(st.queue),
                    title=link_title(tr),
                    dur=fmt_time(tr.duration) if tr.duration else "--",
                    user=who,
                ),
                reply_markup=play_now_kb,
                **NOPREV,
            )
        else:
            await msg.edit_text(await t(chat_id, "added_many", n=len(added)))
