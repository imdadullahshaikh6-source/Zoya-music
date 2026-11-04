# helpers/player.py — poora playback engine (queue, controls, player card, stream end)
import asyncio
import html
import traceback
import os
import random
import time
from typing import List, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

import config
import database
import state
from core import bot, call_py
from helpers import assistant, perms, spotify, thumb, ytdl
from helpers.fonts import fmt_played, fmt_time, sc
from helpers.strings import t
from state import Track

# ───────────────────────── small utils ─────────────────────────


def mention(user) -> str:
    if not user:
        return sc("anonymous")
    return f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'


def esc(s) -> str:
    return html.escape(str(s or ""))


def link_title(track: Track) -> str:
    if track.webpage and track.webpage.startswith("http"):
        return f'<a href="{html.escape(track.webpage, quote=True)}">{esc(track.title)}</a>'
    return esc(track.title)


def err_kind(e: Exception) -> str:
    n = type(e).__name__
    if n in ("NoActiveGroupCall", "GroupcallForbidden", "GroupCallNotFound"):
        return "no_vc"
    if n in ("UnMuteNeeded",):
        return "muted"
    if "GROUPCALL" in str(e).upper() or "NoActiveGroupCall" in str(e):
        return "no_vc"
    return "other"


# ───────────────────────── captions & keyboard ─────────────────────────


def now_caption(track: Track) -> str:
    return (
        f"▶️ <u>{sc('now streaming')}</u>\n\n"
        f"<b>{sc('title')}:</b> {link_title(track)}\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_time(track.duration) if track.duration else 'LIVE'}</code>\n"
        f"<b>{sc('requested by')}:</b> {track.requester or sc('unknown')}"
    )


def ended_caption(track: Track, played: int, reason: str) -> str:
    total = fmt_time(track.duration) if track.duration else "LIVE"
    return (
        f"⬜ <u>{sc('stream ended')}</u>\n\n"
        f"<b>{sc('title')}:</b> {link_title(track)}\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_played(played)} / {total}</code>\n"
        f"• <b>{sc('reason')}:</b> <i>{reason}</i>"
    )


def player_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    st = state.get(chat_id)
    pr = ("▶️", "pr") if st.paused else ("⏸", "pr")
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(pr[0], callback_data=f"pl:{pr[1]}:{chat_id}"),
                InlineKeyboardButton("⏭", callback_data=f"pl:skip:{chat_id}"),
                InlineKeyboardButton("⏹", callback_data=f"pl:stop:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔁", callback_data=f"pl:loop:{chat_id}"),
                InlineKeyboardButton("🔀", callback_data=f"pl:shuffle:{chat_id}"),
                InlineKeyboardButton("⭐", callback_data=f"pl:save:{chat_id}"),
            ],
            [InlineKeyboardButton("✖", callback_data=f"pl:close:{chat_id}")],
        ]
    )


CLOSE_KB = InlineKeyboardMarkup([[InlineKeyboardButton("✖", callback_data="x")]])


async def _fail(msg, text):
    return await msg.edit_text(text, reply_markup=CLOSE_KB, disable_web_page_preview=True)

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


async def start_track(chat_id: int, track: Track, seek: int = 0):
    st = state.get(chat_id)
    await ytdl.ensure_stream(track)
    await call_py.play(chat_id, build_stream(track, seek))
    st.current = track
    st.started = time.time() - seek
    st.paused = False
    st.paused_at = 0.0
    if track.vid:
        st.history.add(track.vid)
        if len(st.history) > 200:
            st.history.clear()


async def _delete_old(st):
    if st.msg:
        try:
            await st.msg.delete()
        except Exception:
            pass
        st.msg = None


async def send_player(chat_id: int, track: Track, message=None):
    """Player card group me SPOILER ke saath bhejta hai."""
    st = state.get(chat_id)
    await _delete_old(st)
    caption = now_caption(track)
    kb = player_keyboard(chat_id)
    cdata = await database.get_chat(chat_id)
    path = None
    if cdata.get("thumb", True):
        path = await thumb.make_card(track.thumb, track.title, track.channel, 0, track.duration)
    sent = None
    try:
        if path:
            if message is not None:
                sent = await message.reply_photo(path, caption=caption, reply_markup=kb, has_spoiler=True)
            else:
                sent = await bot.send_photo(chat_id, path, caption=caption, reply_markup=kb, has_spoiler=True)
        else:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        print(f"send_player error: {e}")
        try:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb, disable_web_page_preview=True)
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
    track, played, msg = st.current, st.played(), st.msg
    try:
        await call_py.leave_call(chat_id)
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
            await msg.edit_caption(cap, reply_markup=CLOSE_KB) if msg.photo else await msg.edit_text(cap, reply_markup=CLOSE_KB, disable_web_page_preview=True)
        else:
            await bot.send_message(chat_id, cap, reply_markup=CLOSE_KB, disable_web_page_preview=True)
    except Exception:
        try:
            await bot.send_message(chat_id, cap, reply_markup=CLOSE_KB, disable_web_page_preview=True)
        except Exception:
            pass


async def _play_next(chat_id: int) -> bool:
    """Queue (ya autoplay) se agla track chalao. False = kuch bacha nahi / fatal error."""
    st = state.get(chat_id)
    while True:
        nxt: Optional[Track] = st.queue.pop(0) if st.queue else None
        if nxt is None and st.autoplay and st.current:
            nxt = await ytdl.related(st.current, st.history)
            if nxt:
                nxt.requester = sc("autoplay")
        if nxt is None:
            return False
        try:
            await start_track(chat_id, nxt)
        except Exception as e:
            kind = err_kind(e)
            if kind in ("no_vc", "muted"):
                st.queue.clear()
                await bot.send_message(chat_id, await t(chat_id, kind))
                return False
            try:
                await bot.send_message(chat_id, await t(chat_id, "play_err", err=esc(f"{nxt.title}: {e}")))
            except Exception:
                pass
            continue
        await send_player(chat_id, nxt)
        return True


# ───────────────────────── events ─────────────────────────


async def on_stream_end(chat_id: int):
    st = state.get(chat_id)
    async with st.lock:
        if not st.active:
            return
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
        f"🎧 <u>{sc('now playing')}</u>",
        f"<b>{link_title(c)}</b>",
        f"<code>{fmt_played(st.played())} / {fmt_time(c.duration) if c.duration else 'LIVE'}</code> • {c.requester}",
    ]
    if st.queue:
        out.append(f"\n📜 <u>{sc('up next')}</u> ({len(st.queue)})")
        for i, q in enumerate(st.queue[:10], 1):
            out.append(f"<b>{i}.</b> {esc(q.title)} <code>{fmt_time(q.duration) if q.duration else '--'}</code>")
        if len(st.queue) > 10:
            out.append(f"… +{len(st.queue) - 10} {sc('more')}")
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
        return await _fail(msg, "❌ " + sc("search timed out. youtube is too slow or blocking this server. try again."))
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
            try:
                print("[play] joining voice chat / starting stream...")
                await asyncio.wait_for(start_track(chat_id, first), timeout=75)
                print("[play] stream started")
            except Exception as e:
                print(f"start_track error: {type(e).__name__}: {e!r}")
                traceback.print_exc()
                kind = err_kind(e)
                if not st.active:
                    st.queue.clear()
                    try:
                        await call_py.leave_call(chat_id)
                    except Exception:
                        pass
                text = await t(chat_id, kind) if kind != "other" else await t(chat_id, "play_err", err=esc(f"{type(e).__name__}: {e}"))
                return await _fail(msg, text)
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
            await msg.edit_text(
                await t(
                    chat_id,
                    "added",
                    pos=len(st.queue),
                    title=link_title(tr),
                    dur=fmt_time(tr.duration) if tr.duration else "--",
                    user=who,
                ),
                disable_web_page_preview=True,
            )
        else:
            await msg.edit_text(await t(chat_id, "added_many", n=len(added)))
