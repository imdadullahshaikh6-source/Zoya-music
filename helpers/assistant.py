# helpers/assistant.py — assistant (userbot) ko group me bulana
import asyncio
import html
import time
import traceback
from datetime import datetime, timedelta

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
IDLE_SECONDS = int(getattr(config, "ASSISTANT_IDLE_MIN", 10)) * 60
CHECK_EVERY = 30

_last_active: dict = {}   # chat_id -> last time music chala / assistant use hua
_locks: dict = {}         # chat_id -> Lock (join aur leave ek saath na ho)
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


async def _idle_loop():
    await _sweep_existing()
    while True:
        await asyncio.sleep(CHECK_EVERY)
        now = time.time()
        for chat_id in list(_joined):
            try:
                if state.get(chat_id).active:
                    _last_active[chat_id] = now
                    continue
                if now - _last_active.setdefault(chat_id, now) >= IDLE_SECONDS:
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


async def _assistant_is_member(chat_id: int) -> bool:
    """Assistant ki taraf se check (zyada bharosemand)."""
    try:
        m = await userbot.get_chat_member(chat_id, "me")
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except Exception:
        return False


async def _make_link(client, chat_id: int) -> str:
    """Naya single-use link (primary link revoke nahi hota, join-request group me bhi seedha join)."""
    try:
        link = await client.create_chat_invite_link(
            chat_id,
            name="Zoya assistant",
            expire_date=datetime.utcnow() + timedelta(minutes=10),
            member_limit=1,
        )
        return link.invite_link
    except ChatAdminRequired:
        raise
    except Exception as e:
        print(f"[assistant] create_chat_invite_link failed: {e!r} — export_chat_invite_link try kar raha hoon")
        return await client.export_chat_invite_link(chat_id)


async def ensure(client, chat, status_msg):
    """(ok, text, markup). status_msg par 'Inviting assistant' dikhata hai.
    Assistant group me nahi hai (idle me nikal gaya tha) to wapas invite karke join karwata hai."""
    start_watcher()
    async with _lock(chat.id):
        res = await _ensure(client, chat, status_msg)
        if res[0]:
            touch(chat.id)
        return res


async def _ensure(client, chat, status_msg):
    chat_id = chat.id
    if chat_id in _joined:
        return True, "", None
    me = userbot.me

    # 1) banned?  (bot admin ho to status dikhta hai)
    try:
        member = await client.get_chat_member(chat_id, me.id)
        if member.status == ChatMemberStatus.BANNED:
            return False, banned_text(me), banned_markup()
    except Exception:
        pass

    # 2) pehle se member?
    if await _assistant_is_member(chat_id):
        _joined.add(chat_id)
        return True, "", None

    try:
        await status_msg.edit_text(await t(chat_id, "hold_on", bot=bot.me.first_name))
    except Exception:
        pass

    # 3) join
    last_err = None
    for attempt in range(2):
        link = None
        try:
            target = chat.username if chat.username else (link := await _make_link(client, chat_id))
            try:
                await userbot.join_chat(target)
            except InviteRequestSent:
                await client.approve_chat_join_request(chat_id, me.id)
            except UserAlreadyParticipant:
                pass
            _joined.add(chat_id)
            await asyncio.sleep(1)
            if link:
                try:
                    await client.revoke_chat_invite_link(chat_id, link)
                except Exception:
                    pass
            return True, "", None
        except ChatAdminRequired:
            return False, sc("make me admin with 'invite users via link' permission, or add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None
        except InviteHashExpired as e:
            last_err = e
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
