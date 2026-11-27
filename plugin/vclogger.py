# plugin/vclogger.py — VC logger: group ke voice chat me koi join kare to group me #JoinedVc log
#
# Kaise kaam karta hai:
#   * Assistant (userbot) ko Telegram se VC participants ke raw updates milte hain (UpdateGroupCallParticipants).
#   * Jis group me /vclogger on hai wahan koi naya banda VC join kare to bot group me log bhejta hai.
#   * Sirf JOIN ka log (leave ka nahi). Assistant group me hoga tabhi update milega.
import asyncio
import html
import time
import traceback

from pyrogram import Client, filters, raw
from pyrogram.errors import FloodWait
from pyrogram.handlers import RawUpdateHandler
from pyrogram.types import InlineKeyboardMarkup

import database
from core import bot, userbot
from helpers import assistant, perms
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import sc

# ek hi premium emoji teeno lines me
EMOJI_ID = 5222108309795908493

_enabled: set = set()      # chats jahan logger on hai
_call_chat: dict = {}      # call_id -> chat_id
_miss: dict = {}           # call_id -> last resolve try (spam se bachne ke liye)
_seen: dict = {}           # (chat_id, user_id) -> time (duplicate update na bheje)
_chat_info: dict = {}      # chat_id -> username (Join VC button ke liye)
DEDUP_SECONDS = 20
DELETE_AFTER = 10          # log itne second baad group se delete ho jata hai (0 = delete nahi)


# ───────────────────────── helpers ─────────────────────────
def _candidates(raw_id: int):
    """UpdateGroupCall ka chat_id bare hota hai: supergroup (-100...) ya basic group (-id) dono try karo."""
    return (-(10 ** 12 + raw_id), -raw_id)


def _emo(fallback: str = "ℹ️") -> str:
    return f'<emoji id="{EMOJI_ID}">{fallback}</emoji>'


def _log_text(uid: int, name: str, auth: str, premium: bool = True) -> str:
    e = _emo() if premium else "ℹ️"
    mention = f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'
    return (
        "<blockquote>#JoinedVc\n"
        f"{e} {sc('user')} - {mention}\n"
        f"{e} {sc('userid')} - {uid}\n"
        f"{e} {sc('auth')} - {sc(auth)}</blockquote>"
    )


async def _join_markup(chat_id: int):
    """'Join VC' button (public group = username link, private = t.me/c link)."""
    try:
        if chat_id not in _chat_info:
            c = await bot.get_chat(chat_id)
            _chat_info[chat_id] = c.username or ""
        uname = _chat_info[chat_id]
        if uname:
            url = f"https://t.me/{uname}?videochat"
        elif str(chat_id).startswith("-100"):
            url = f"https://t.me/c/{str(chat_id)[4:]}/1?videochat"
        else:
            return None
        return InlineKeyboardMarkup([[btn("join vc", url=url, style="success")]])
    except Exception:
        return None


async def _auth_label(chat_id: int, uid: int) -> str:
    try:
        return "admin" if await perms.is_admin(bot, chat_id, uid) else "member"
    except Exception:
        return "member"


async def _delete_later(msg):
    """Log bhejne ke DELETE_AFTER second baad message hata do (bot ko delete messages ka haq chahiye)."""
    if DELETE_AFTER <= 0 or msg is None:
        return
    await asyncio.sleep(DELETE_AFTER)
    try:
        await msg.delete()
    except Exception as e:
        print(f"[vclog] delete failed in {msg.chat.id}: {e!r}")


async def _send_log(chat_id: int, uid: int, name: str):
    auth = await _auth_label(chat_id, uid)
    markup = await _join_markup(chat_id)
    for attempt in range(3):
        try:
            msg = await bot.send_message(chat_id, _log_text(uid, name, auth), reply_markup=markup)
            asyncio.get_event_loop().create_task(_delete_later(msg))
            return
        except FloodWait as e:
            await asyncio.sleep(min(e.value, 30))
        except Exception as e:
            print(f"[vclog] send failed in {chat_id}: {e!r} - plain retry")
            try:  # premium emoji / button ki wajah se fail hua ho to simple version
                msg = await bot.send_message(chat_id, _log_text(uid, name, auth, premium=False))
                asyncio.get_event_loop().create_task(_delete_later(msg))
            except Exception as e2:
                print(f"[vclog] plain send failed in {chat_id}: {e2!r}")
            return


# ───────────────────────── call id -> chat id ─────────────────────────
def _learn(update):
    """UpdateGroupCall se call_id aur chat ka rishta yaad rakho."""
    call = getattr(update, "call", None)
    cid = getattr(update, "chat_id", None)
    call_id = getattr(call, "id", None)
    if not call_id or not cid:
        return
    for cand in _candidates(abs(int(cid))):
        if cand in _enabled:
            _call_chat[call_id] = cand
            return


async def _resolve_call(call_id: int):
    """Cache me nahi mila: logger-on wale groups (jinme assistant hai) ke call id check karo."""
    now = time.time()
    if now - _miss.get(call_id, 0) < 60:
        return None
    _miss[call_id] = now
    for cid in list(_enabled & set(assistant._joined)):
        try:
            peer = await userbot.resolve_peer(cid)
            if isinstance(peer, raw.types.InputPeerChannel):
                full = await userbot.invoke(
                    raw.functions.channels.GetFullChannel(
                        channel=raw.types.InputChannel(channel_id=peer.channel_id, access_hash=peer.access_hash)
                    )
                )
            elif isinstance(peer, raw.types.InputPeerChat):
                full = await userbot.invoke(raw.functions.messages.GetFullChat(chat_id=peer.chat_id))
            else:
                continue
            call = getattr(full.full_chat, "call", None)
            if call is not None:
                _call_chat[call.id] = cid
        except FloodWait:
            break
        except Exception:
            continue
        await asyncio.sleep(0.2)
    return _call_chat.get(call_id)


# ───────────────────────── raw update handler (assistant) ─────────────────────────
def _user_name(users: dict, uid: int) -> str:
    u = (users or {}).get(uid)
    if u is None:
        return "User"
    name = f"{getattr(u, 'first_name', '') or ''} {getattr(u, 'last_name', '') or ''}".strip()
    return name or "User"


async def _on_raw(client, update, users, chats):
    try:
        if not _enabled:
            return
        if isinstance(update, raw.types.UpdateGroupCall):
            _learn(update)
            return
        if not isinstance(update, raw.types.UpdateGroupCallParticipants):
            return

        call_id = getattr(update.call, "id", None)
        chat_id = _call_chat.get(call_id) or await _resolve_call(call_id)
        if not chat_id or chat_id not in _enabled:
            return

        skip = {getattr(userbot.me, "id", 0), getattr(bot.me, "id", 0)}
        now = time.time()
        for p in update.participants:
            if not getattr(p, "just_joined", False) or getattr(p, "left", False):
                continue
            peer = getattr(p, "peer", None)
            if not isinstance(peer, raw.types.PeerUser):
                continue  # channel / anonymous join-as, skip
            uid = peer.user_id
            if uid in skip:
                continue
            if now - _seen.get((chat_id, uid), 0) < DEDUP_SECONDS:
                continue
            _seen[(chat_id, uid)] = now
            asyncio.get_event_loop().create_task(_send_log(chat_id, uid, _user_name(users, uid)))

        if len(_seen) > 5000:  # purani entries saaf
            for k in [k for k, v in _seen.items() if now - v > 300]:
                _seen.pop(k, None)
    except Exception:
        traceback.print_exc()


async def _load_enabled():
    try:
        ids = await database.vclog_chats()
        _enabled.update(ids)
        assistant.LOGGER_CHATS.update(ids)
        print(f"[vclog] logger on in {len(ids)} chats")
    except Exception as e:
        print(f"[vclog] could not load chats: {e!r}")


def _register():
    try:
        userbot.add_handler(RawUpdateHandler(_on_raw), group=77)
        asyncio.get_event_loop().create_task(_load_enabled())
        print("[vclog] raw handler registered on assistant")
    except Exception:
        traceback.print_exc()


_register()


# ───────────────────────── on / off ─────────────────────────
async def _set(chat_id: int, on: bool):
    await database.set_chat(chat_id, vclog=on)
    if on:
        _enabled.add(chat_id)
        assistant.LOGGER_CHATS.add(chat_id)
    else:
        _enabled.discard(chat_id)
        assistant.LOGGER_CHATS.discard(chat_id)


async def _panel(chat_id: int):
    on = chat_id in _enabled
    text = (
        f"🎙 <u>{sc('vc logger settings')}</u>\n\n"
        f"{sc('get a log message in this group whenever someone joins the voice chat.')}\n\n"
        f"<i>{sc('current status')}:</i> <b>{sc('enabled') if on else sc('disabled')}</b>"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                btn("enable", "vcl:on", style="success" if on else None),
                btn("disable", "vcl:off", style="danger" if not on else None),
            ],
            [btn("close", "x", style="danger")],
        ]
    )
    return text, kb


async def _assistant_note(chat_id: int) -> str:
    try:
        if await assistant.membership(chat_id) is False:
            return "\n\nℹ️ <i>" + sc("the assistant is not in this group right now. logs start once it joins (it joins when you play a song).") + "</i>"
    except Exception:
        pass
    return ""


@Client.on_message(cmd(["vclogger", "vclog"]) & filters.group)
async def vclogger_cmd(client, message):
    try:
        if not await perms.message_is_admin(client, message):
            return await message.reply_text(sc("only admins can use this command."))
        chat_id = message.chat.id
        arg = message.command[1].lower() if len(message.command) > 1 else ""
        if arg in ("on", "enable", "enabled"):
            await _set(chat_id, True)
            return await message.reply_text("✅ " + sc("vc logger enabled.") + await _assistant_note(chat_id))
        if arg in ("off", "disable", "disabled"):
            await _set(chat_id, False)
            return await message.reply_text("✅ " + sc("vc logger disabled."))
        text, kb = await _panel(chat_id)
        await message.reply_text(text, reply_markup=kb)
    except Exception:
        traceback.print_exc()
        await message.reply_text(sc("could not open vc logger settings. please try again."))


@Client.on_callback_query(filters.regex(r"^vcl:(on|off)$"))
async def vclogger_cb(client, cq):
    chat = cq.message.chat
    if not (perms.is_sudo(cq.from_user.id) or await perms.is_admin(client, chat.id, cq.from_user.id)):
        return await cq.answer("Only admins can change this.", show_alert=True)
    on = cq.matches[0].group(1) == "on"
    try:
        await _set(chat.id, on)
    except Exception:
        traceback.print_exc()
        return await cq.answer("Could not save this setting.", show_alert=True)
    text, kb = await _panel(chat.id)
    if on:
        text += await _assistant_note(chat.id)
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await cq.answer("Saved")
