# helpers/assistant.py — assistant (userbot) ko group me bulana
import asyncio
import html
import os
import time
import traceback
from datetime import datetime, timedelta

import pyrogram.errors as _pe
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import (
    ChatAdminRequired,
    InviteHashExpired,
    InviteRequestSent,
    UserAlreadyParticipant,
    UserNotParticipant,
)
from pyrogram.types import InlineKeyboardMarkup

import config
import state
from core import bot, call_py, userbot
from helpers.buttons import btn
from helpers.fonts import sc
from helpers.strings import t

_joined = set()

# ───────────────────────── idle auto-leave ─────────────────────────
# Group me IDLE_MIN minute tak koi song na chale to assistant group chhod deta hai (bot pe load kam).
# Agla /play aate hi ensure() assistant ko wapas invite karke join karwa deta hai.
# Minutes badalne ho to config.py me  ASSISTANT_IDLE_MIN = 10  likh do.
IDLE_SECONDS = 0  # PERMANENT: assistant kisi group se kabhi nahi nikalta (idle auto-leave band). Load badhe to owner ko DM aata hai.
CHECK_EVERY = 30

# VC logger on wale groups (plugin/vclogger.py bharta hai).
# .env me VCLOG_KEEP_ASSISTANT=1 likhoge to in groups se assistant idle me bhi nahi nikalega (logger tabhi chalta hai jab assistant group me ho).
LOGGER_CHATS: set = set()
KEEP_FOR_LOGGER = os.environ.get("VCLOG_KEEP_ASSISTANT", "0").strip() in ("1", "true", "yes")

# ───────────────────────── load alert (owner DM) ─────────────────────────
# Assistant itne groups me ho jaye to owner ko DM aata hai ki naya assistant chahiye.
# Limit badalni ho to .env me ASSISTANT_LOAD_LIMIT=150  (0 = alert band).
LOAD_LIMIT = config._int("ASSISTANT_LOAD_LIMIT", 150)
ALERT_EVERY = 12 * 3600   # limit ke upar rehne par itne seconds baad dobara yaad dilata hai
_alert_on = False
_alert_ts = 0.0

_last_active: dict = {}   # chat_id -> last time music chala / assistant use hua
_locks: dict = {}         # chat_id -> Lock (join aur leave ek saath na ho)
_primary: dict = {}       # chat_id -> admin ka primary (direct) invite link, cache
_watcher = None


def _lock(chat_id: int) -> asyncio.Lock:
    return _locks.setdefault(chat_id, asyncio.Lock())


def touch(chat_id: int):
    """Idle-clock reset (play start / stream end par)."""
    _last_active[chat_id] = time.time()


def forget(chat_id: int):
    _joined.discard(chat_id)
    _last_active.pop(chat_id, None)


async def _leave(chat_id: int):
    async with _lock(chat_id):
        # lock milne tak koi /play aa gaya ho to chhodna nahi hai
        if state.get(chat_id).active or time.time() - _last_active.get(chat_id, 0) < IDLE_SECONDS:
            return
        try:
            await call_py.leave_call(chat_id)
        except Exception:
            pass
        try:
            await userbot.leave_chat(chat_id)
        except UserNotParticipant:
            pass
        except Exception as e:
            print(f"[assistant] idle leave failed in {chat_id}: {e!r} - retry later")
            _last_active[chat_id] = time.time()
            return
        _joined.discard(chat_id)
        _last_active.pop(chat_id, None)
        print(f"[assistant] left idle chat {chat_id}")


async def _sweep_existing():
    """Restart ke baad: assistant jin served groups me pehle se hai, unhe bhi idle-clock par daalo."""
    try:
        import database
        served = set(await database.all_chats())
        async for d in userbot.get_dialogs():
            cid = d.chat.id
            if cid in served and cid not in _joined:
                _joined.add(cid)
                _last_active.setdefault(cid, time.time())
    except Exception as e:
        print(f"[assistant] startup sweep skipped: {e!r}")


async def _check_load():
    """Assistant ka load limit paar kare to owner ke DM me ek note (bot owner ko pehle se DM kiya hona chahiye)."""
    global _alert_on, _alert_ts
    if LOAD_LIMIT <= 0 or not config.OWNER_ID:
        return
    n = len(_joined)
    if n < int(LOAD_LIMIT * 0.9):
        _alert_on = False  # load utar gaya, agli baar phir alert aayega
        return
    if n < LOAD_LIMIT or (_alert_on and time.time() - _alert_ts < ALERT_EVERY):
        return
    streams = sum(1 for c in list(_joined) if state.get(c).active)
    try:
        name = html.escape(userbot.me.first_name or "assistant")
    except Exception:
        name = "assistant"
    text = (
        f"⚠️ <b>{sc('assistant load alert')}</b>\n\n"
        f"{sc('assistant')}: <b>{name}</b>\n"
        f"{sc('groups right now')}: <code>{n}</code> / <code>{LOAD_LIMIT}</code>\n"
        f"{sc('active streams')}: <code>{streams}</code>\n\n"
        f"{sc('the load has increased. one more assistant is needed.')}"
    )
    try:
        await bot.send_message(config.OWNER_ID, text)
        _alert_on = True
        _alert_ts = time.time()
    except Exception as e:
        print(f"[assistant] load alert DM failed: {e!r}")


async def _idle_loop():
    await _sweep_existing()
    while True:
        await asyncio.sleep(CHECK_EVERY)
        now = time.time()
        try:
            await _check_load()
        except Exception as e:
            print(f"[assistant] load check error: {e!r}")
        for chat_id in list(_joined):
            try:
                if KEEP_FOR_LOGGER and chat_id in LOGGER_CHATS:
                    _last_active[chat_id] = now
                    continue
                if state.get(chat_id).active:
                    _last_active[chat_id] = now
                    continue
                if IDLE_SECONDS > 0 and now - _last_active.setdefault(chat_id, now) >= IDLE_SECONDS:
                    await _leave(chat_id)
            except Exception as e:
                print(f"[assistant] idle check error {chat_id}: {e!r}")


def start_watcher():
    """main.py se (ya pehle /play par) ek baar chalta hai, dobara call karne par kuch nahi karta."""
    global _watcher
    if _watcher is not None and not _watcher.done():
        return
    try:
        _watcher = asyncio.get_running_loop().create_task(_idle_loop())
    except RuntimeError:
        pass


# in errors ka matlab: assistant is chat me pakka nahi hai
_NOT_IN = tuple(
    getattr(_pe, n) for n in ("UserNotParticipant", "ChannelPrivate", "ChannelInvalid", "PeerIdInvalid") if hasattr(_pe, n)
)


async def membership(chat_id: int):
    """Assistant ki taraf se asli check. True = member, False = member nahi, None = pata nahi chala (API error)."""
    try:
        m = await userbot.get_chat_member(chat_id, "me")
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except _NOT_IN:
        return False
    except Exception as e:
        print(f"[assistant] membership check inconclusive in {chat_id}: {e!r}")
        return None


async def _primary_link(client, chat_id: int, fresh: bool = False):
    """Bot (admin) ka primary/direct invite link. Naya link NAHI banta, kuch revoke nahi hota.
    (export_chat_invite_link use nahi karte: wo purana primary link revoke kar deta hai.)"""
    if not fresh and chat_id in _primary:
        return _primary[chat_id]
    try:
        chat = await client.get_chat(chat_id)
        link = getattr(chat, "invite_link", None)
        if link:
            _primary[chat_id] = link
            return link
    except Exception as e:
        print(f"[assistant] primary link nahi mila in {chat_id}: {e!r}")
    return None


async def _make_link(client, chat_id: int, fresh: bool = False):
    """Pehle admin ka direct (primary) link; na mile tabhi naya single-use link banata hai.
    Return: (link, temp) — temp=True matlab naya bana tha, join ke baad revoke karna hai."""
    link = await _primary_link(client, chat_id, fresh)
    if link:
        return link, False
    try:
        l = await client.create_chat_invite_link(
            chat_id,
            name="Zoya assistant",
            expire_date=datetime.utcnow() + timedelta(minutes=10),
            member_limit=1,
        )
        return l.invite_link, True
    except ChatAdminRequired:
        raise
    except Exception as e:
        print(f"[assistant] create_chat_invite_link failed: {e!r} — export_chat_invite_link try kar raha hoon")
        return await client.export_chat_invite_link(chat_id), False


async def _approve_pending(client, chat_id: int, user_id: int):
    """Assistant ki pending join request bot se approve karo (bot ko 'invite users' admin haq chahiye).
    Request server pe register hone me 1-2s lag sakte hain, isliye 3 koshish. Return: None = approve ho gayi, warna error text."""
    err = None
    for i in range(3):
        try:
            await client.approve_chat_join_request(chat_id, user_id)
            print(f"[assistant] join request approve ho gayi in {chat_id}")
            return None
        except UserAlreadyParticipant:
            return None
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[assistant] approve attempt {i + 1} failed in {chat_id}: {err}")
            if type(e).__name__ in ("ChatAdminRequired", "UserNotParticipant", "ChannelPrivate", "ChatWriteForbidden"):
                break  # haq hi nahi -> dobara try bekaar
            await asyncio.sleep(1.2)
    return err


def _pending_text(me, err) -> str:
    who = f"@{html.escape(me.username or str(me.id))}"
    txt = sc("the assistant's join request is pending.") + "\n" + sc("approve it manually in 'join requests':") + f" {who}\n"
    txt += sc("or give me admin with 'add members / invite users' permission so i can approve it myself.")
    if err:
        txt += f"\n<code>{html.escape(err)}</code>"
    return txt


def _bg(coro):
    """Fire-and-forget (error kabhi bahar nahi aata, play ko nahi rokta)."""
    async def _run():
        try:
            await coro
        except Exception:
            pass
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        coro.close()


async def ensure(client, chat, status_msg):
    """(ok, text, markup). status_msg par 'Inviting assistant' dikhata hai.
    Assistant group me nahi hai (idle me nikal gaya tha) to wapas invite karke join karwata hai."""
    start_watcher()
    # Tez raasta: abhi is group me gaana/call chal raha hai (assistant pakka andar hai) -> koi API call nahi.
    # (Kicked hua to start_track ka retry membership check karke dobara invite kar deta hai.)
    if chat.id in _joined and state.get(chat.id).active:
        touch(chat.id)
        return True, "", None
    t0 = time.monotonic()
    async with _lock(chat.id):
        res = await _ensure(client, chat, status_msg)
        if res[0]:
            touch(chat.id)
        print(f"[assistant] ensure chat={chat.id} ok={res[0]} {time.monotonic() - t0:.2f}s")
        return res


async def _ensure(client, chat, status_msg):
    chat_id = chat.id
    me = userbot.me

    # 1) pehle se member? (har baar asli check, 1 hi API call; common raasta yahin khatam)
    mem = await membership(chat_id)
    if mem is True:
        _joined.add(chat_id)
        return True, "", None
    if mem is None and chat_id in _joined:
        return True, "", None  # check fail hua (API issue), pehle ka pata hai ki member tha
    _joined.discard(chat_id)  # group me nahi hai -> invite karna padega

    # "hold on" sirf dikhane ke liye hai, uska intezaar nahi karte
    _bg(status_msg.edit_text(await t(chat_id, "hold_on", bot=bot.me.first_name)))

    # 2) banned? + invite link, dono ek saath.
    # Link PUBLIC group me bhi pehle: "approve new members" on ho to username se join sirf *request* banata hai,
    # jabki admin ka banaya link seedha join karata hai (private group wala wahi tareeka).
    ban_task = asyncio.ensure_future(client.get_chat_member(chat_id, me.id))
    link_task = asyncio.ensure_future(_make_link(client, chat_id))
    try:
        member = await ban_task
        if member.status == ChatMemberStatus.BANNED:
            link_task.cancel()
            return False, banned_text(me), banned_markup()
    except Exception:
        pass  # bot admin nahi / status nahi mila -> aage badho

    # 3) join
    last_err = None
    for attempt in range(2):
        link = None
        temp = False
        try:
            try:
                if link_task is not None:
                    link, temp = await link_task  # pehli koshish me already ban chuka hota hai
                    link_task = None
                else:
                    # retry: cached primary link expire/revoke ho gaya ho to fresh lo
                    link, temp = await _make_link(client, chat_id, fresh=True)
                target = link
            except ChatAdminRequired:
                if not chat.username:
                    raise
                target = chat.username  # bot ke paas link banane ka haq nahi -> username se (approval group me request banegi)
                print(f"[assistant] bot link nahi bana sakta in {chat_id} -> username se join")
            pending = False
            try:
                await userbot.join_chat(target)
            except InviteRequestSent:
                pending = True
            except UserAlreadyParticipant:
                pass
            if pending or await membership(chat_id) is False:
                # join request pending hai (ya join ke turant baad abhi dikha nahi) -> bot se approve karne ki koshish
                approve_err = await _approve_pending(client, chat_id, me.id)
                if await membership(chat_id) is False:
                    for _ in range(3):
                        await asyncio.sleep(1)
                        if await membership(chat_id) is not False:
                            break
                    else:
                        if pending or approve_err:
                            return False, _pending_text(me, approve_err), None
                        raise RuntimeError("join went through but the assistant is still not in the group")
            _joined.add(chat_id)
            if link and temp:  # primary link kabhi revoke nahi karna
                _bg(client.revoke_chat_invite_link(chat_id, link))  # revoke ka intezaar nahi
            return True, "", None
        except ChatAdminRequired:
            return False, sc("make me admin with 'invite users via link' permission, or add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None
        except InviteHashExpired as e:
            last_err = e
            _primary.pop(chat_id, None)
            print(f"[assistant] invite hash expired (attempt {attempt + 1}), retrying")
            await asyncio.sleep(1)
            continue
        except Exception as e:
            traceback.print_exc()
            return False, sc("failed to add assistant:") + f" <code>{html.escape(str(e))}</code>\n" + sc("add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None

    print(f"[assistant] join failed: {last_err!r}")
    return False, sc("could not add the assistant automatically. please add it to the group manually:") + f" @{html.escape(me.username or str(me.id))}", None


def banned_text(me) -> str:
    return (
        f"{sc('assistant is banned in this chat.')}\n"
        f"{sc('id')}: <code>{me.id}</code>\n"
        f"{sc('name')}: <code>{html.escape(me.first_name or '')}</code>\n"
        f"{sc('please unban the assistant and try again.')}"
    )


def banned_markup():
    return InlineKeyboardMarkup([[btn("unban assistant", "unban_assistant", style="danger")]])
