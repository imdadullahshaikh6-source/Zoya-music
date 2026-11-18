# plugin/vclogger.py — /vclogger: VC join / leave / invite group me announce karo
#
# Kaam kaise karta hai:
#   - "invite" (X ne Y ko VC me invite kiya) Telegram khud ek service message bhejta hai
#     (message.video_chat_participants_invited) — usi ko hook karke reply karte hain.
#   - Plain "join" / "leave" (bina invite ke, seedha "Join VC" button se) ka koi normal
#     chat-message event Telegram nahi deta. Ye data sirf raw MTProto update
#     (UpdateGroupCallParticipant) me milta hai, aur ye update Telegram supergroup ki
#     apni update-stream ka hissa hota hai — isliye BOT sirf group ka MEMBER hoke bhi
#     ye updates pakad sakta hai, assistant ko VC me baithane ki zarurat nahi.
#   - Har update me sirf current participant state hoti hai (join/mute/unmute sab isi
#     se aate hain), isliye khud track karna padta hai "ye naya join hai ya purana wala
#     bas mute/unmute hua" — _call_members set isi ke liye hai.
#
# NOTE: Ye Telegram ka undocumented/internal mechanism hai (raw update), official Bot
# API ka hissa nahi. Agar kisi Telegram update ke baad format badal jaye to yahi file
# dekhni padegi — print() statements isliye lagaye hain taaki journalctl me pata chale.
import asyncio
import html

import pyrogram.utils as putils
from pyrogram import filters
from pyrogram.raw.types import PeerUser, UpdateGroupCall, UpdateGroupCallParticipant

import database
from core import bot
from helpers import perms
from helpers.fonts import sc

DELETE_AFTER = 5  # seconds (join/leave messages isके baad apne aap delete)

_call_chat: dict = {}     # raw call id -> pyrogram chat_id (-100...)
_call_members: dict = {}  # raw call id -> set(user_id) jo "andar" hain (dedupe ke liye)


def _uname(u) -> str:
    """Raw User object (ya None) se display naam (username pref, warna first_name)."""
    if not u:
        return "User"
    username = getattr(u, "username", None)
    if not username:
        usernames = getattr(u, "usernames", None) or []
        username = usernames[0].username if usernames else None
    if username:
        return f"@{username}"
    return getattr(u, "first_name", None) or "User"


def _mention(user_id: int, u=None) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(_uname(u))}</a>'


def mention_user(u) -> str:
    """pyrogram.types.User (normal message.from_user) ke liye."""
    if not u:
        return sc("someone")
    name = f"@{u.username}" if u.username else (u.first_name or "User")
    return f'<a href="tg://user?id={u.id}">{html.escape(name)}</a>'


async def _logger_on(chat_id: int) -> bool:
    try:
        data = await database.get_chat(chat_id)
        return bool(data.get("vclogger"))
    except Exception:
        return False


async def _announce(chat_id: int, text: str, auto_delete: bool):
    try:
        m = await bot.send_message(chat_id, f"<blockquote>{text}</blockquote>")
    except Exception as e:
        print(f"[vclogger] send failed chat={chat_id}: {e!r}")
        return
    if not auto_delete:
        return

    async def _del():
        await asyncio.sleep(DELETE_AFTER)
        try:
            await m.delete()
        except Exception:
            pass

    asyncio.ensure_future(_del())


# ───────────────────────── raw update: join / leave ─────────────────────────
@bot.on_raw_update()
async def _on_raw_update(client, update, users, chats):
    try:
        if isinstance(update, UpdateGroupCall):
            call = update.call
            call_id = getattr(call, "id", None)
            if call_id is None:
                return
            if type(call).__name__ == "GroupCallDiscarded":
                _call_chat.pop(call_id, None)
                _call_members.pop(call_id, None)
                return
            try:
                chat_id = putils.get_channel_id(update.chat_id)
            except Exception:
                chat_id = -update.chat_id  # basic group fallback
            _call_chat[call_id] = chat_id
            return

        if isinstance(update, UpdateGroupCallParticipant):
            p = update.participant
            call_id = getattr(update.call, "id", None)
            chat_id = _call_chat.get(call_id)
            if chat_id is None or not isinstance(getattr(p, "peer", None), PeerUser):
                return
            if not await _logger_on(chat_id):
                return
            user_id = p.peer.user_id
            members = _call_members.setdefault(call_id, set())
            left = bool(getattr(p, "left", False))
            u = users.get(user_id)
            if left:
                if user_id in members:
                    members.discard(user_id)
                    await _announce(chat_id, f"{_mention(user_id, u)} {sc('voice chat left')}", True)
            else:
                if user_id not in members:
                    members.add(user_id)
                    await _announce(chat_id, f"{_mention(user_id, u)} {sc('voice chat joined')}", True)
    except Exception as e:
        print(f"[vclogger] raw update error: {e!r}")


# ───────────────────────── service message: invite ─────────────────────────
def _has_invite(_, __, m):
    return bool(getattr(m, "video_chat_participants_invited", None))


_invite_filter = filters.create(_has_invite)


@bot.on_message(_invite_filter & filters.group)
async def _on_vc_invite(client, message):
    chat_id = message.chat.id
    if not await _logger_on(chat_id):
        return
    invited = (message.video_chat_participants_invited.users or [])
    names = ", ".join(mention_user(u) for u in invited) or sc("someone")
    text = f"{mention_user(message.from_user)} {sc('invited')} {names} {sc('to the video chat')}"
    await _announce(chat_id, text, False)  # invite record rehta hai, delete nahi hota


# ───────────────────────── /vclogger on|off ─────────────────────────
@bot.on_message(filters.command("vclogger") & filters.group)
async def _vclogger_cmd(client, message):
    chat_id = message.chat.id
    if not await perms.message_can_control(client, message):
        return await message.reply_text(sc("only admins can use this command."))
    args = message.command[1:]
    data = await database.get_chat(chat_id)
    if not args:
        cur = sc("on") if data.get("vclogger") else sc("off")
        return await message.reply_text(
            sc("vc logger is currently:") + f" <b>{cur}</b>\n" + sc("usage:") + " <code>/vclogger on</code> / <code>/vclogger off</code>"
        )
    val = args[0].strip().lower()
    if val in ("on", "enable", "true", "1"):
        await database.set_chat(chat_id, vclogger=True)
        return await message.reply_text(
            sc("vc logger turned on.") + " " + sc("voice chat join, leave and invites will now be announced here.")
        )
    if val in ("off", "disable", "false", "0"):
        await database.set_chat(chat_id, vclogger=False)
        return await message.reply_text(sc("vc logger turned off."))
    return await message.reply_text(sc("usage:") + " <code>/vclogger on</code> / <code>/vclogger off</code>")
