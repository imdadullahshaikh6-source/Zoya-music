# plugin/vclogger.py — /vclogger: VC join / leave / invite group me announce karo
#
# Kaam kaise karta hai:
#   - "invite": Telegram service message (video_chat_participants_invited) -> bot hook karta hai.
#   - join / leave: Bot ko Telegram raw VC updates bhejta hi nahi, isliye ASSISTANT (userbot)
#     har POLL_EVERY second me phone.GetGroupParticipants se participant list mangta hai
#     aur purani list se compare karke join/leave announce karta hai.
#   - Assistant ka us group me member hona zaruri hai (jab /play chala ho tab hota hai).
#   - Logger on karne ke baad pehli poll silent hoti hai (jo pehle se VC me hain unko announce nahi karta).
import asyncio
import html

from pyrogram import filters
from pyrogram.raw import functions
from pyrogram.raw.types import InputChannel, PeerUser

import database
from core import bot, userbot
from helpers import perms
from helpers.fonts import sc

DELETE_AFTER = 5     # seconds (join/leave messages itne baad apne aap delete)
POLL_EVERY = 5       # seconds
ENABLED_REFRESH = 30 # seconds (DB se enabled chats ki list refresh)

_members: dict = {}   # chat_id -> set(user_id) jo abhi VC me hain
_poll_task = None


def _uname(u) -> str:
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


# ───────────────────────── polling: join / leave ─────────────────────────
async def _enabled_chats() -> list:
    try:
        if database.ok():
            return [d["_id"] async for d in database._db.chats.find({"vclogger": True}, {"_id": 1})]
        return [cid for cid, d in database._mem["chats"].items() if d.get("vclogger")]
    except Exception as e:
        print(f"[vclogger] enabled list error: {e!r}")
        return []


async def _fetch_participants(chat_id: int):
    """(user_ids set, users dict) ya None agar VC chalu nahi / access nahi."""
    peer = await userbot.resolve_peer(chat_id)
    if not hasattr(peer, "channel_id"):
        return None  # sirf supergroup
    ch = InputChannel(channel_id=peer.channel_id, access_hash=peer.access_hash)
    full = await userbot.invoke(functions.channels.GetFullChannel(channel=ch))
    call = getattr(full.full_chat, "call", None)
    if not call:
        return None
    res = await userbot.invoke(
        functions.phone.GetGroupParticipants(call=call, ids=[], sources=[], offset="", limit=200)
    )
    ids = {p.peer.user_id for p in res.participants if isinstance(getattr(p, "peer", None), PeerUser)}
    users = {u.id: u for u in res.users}
    return ids, users


async def _check_chat(chat_id: int, my_id: int):
    try:
        got = await _fetch_participants(chat_id)
    except Exception as e:
        print(f"[vclogger] poll failed chat={chat_id}: {e!r}")
        return
    new, users = got if got else (set(), {})
    new.discard(my_id)  # assistant khud ko announce nahi karna
    old = _members.get(chat_id)
    _members[chat_id] = new
    if old is None:
        return  # pehli poll silent
    for uid in new - old:
        await _announce(chat_id, f"{_mention(uid, users.get(uid))} {sc('voice chat joined')}", True)
    for uid in old - new:
        await _announce(chat_id, f"{_mention(uid, users.get(uid))} {sc('voice chat left')}", True)


async def _poll_loop():
    print("[vclogger] poller started")
    enabled, last_refresh = [], 0.0
    loop = asyncio.get_event_loop()
    while True:
        try:
            if loop.time() - last_refresh > ENABLED_REFRESH:
                enabled = await _enabled_chats()
                last_refresh = loop.time()
                for cid in list(_members):
                    if cid not in enabled:
                        _members.pop(cid, None)  # off hua to state bhool jao
            my_id = getattr(userbot.me, "id", 0)
            for cid in enabled:
                await _check_chat(cid, my_id)
        except Exception as e:
            print(f"[vclogger] poll loop error: {e!r}")
        await asyncio.sleep(POLL_EVERY)


def start_poller():
    """main.py me userbot.start() ke baad ek baar call karo."""
    global _poll_task
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.ensure_future(_poll_loop())


# ───────────────────────── service message: invite ─────────────────────────
def _has_invite(_, __, m):
    return bool(getattr(m, "video_chat_participants_invited", None))


_invite_filter = filters.create(_has_invite)


@bot.on_message(_invite_filter & filters.group, group=-1)
async def _on_vc_invite(client, message):
    chat_id = message.chat.id
    if not await _logger_on(chat_id):
        return
    invited = (message.video_chat_participants_invited.users or [])
    names = ", ".join(mention_user(u) for u in invited) or sc("someone")
    text = f"{mention_user(message.from_user)} {sc('invited')} {names} {sc('to the video chat')}"
    await _announce(chat_id, text, False)  # invite record rehta hai, delete nahi hota


# ───────────────────────── /vclogger on|off ─────────────────────────
@bot.on_message(filters.command("vclogger") & filters.group, group=-1)
async def _vclogger_cmd(client, message):
    print(f"[vclogger] /vclogger command received chat={message.chat.id} from={message.from_user.id if message.from_user else None}")
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
        _members.pop(chat_id, None)
        start_poller()
        return await message.reply_text(
            sc("vc logger turned on.") + " " + sc("voice chat join, leave and invites will now be announced here.")
        )
    if val in ("off", "disable", "false", "0"):
        await database.set_chat(chat_id, vclogger=False)
        return await message.reply_text(sc("vc logger turned off."))
    return await message.reply_text(sc("usage:") + " <code>/vclogger on</code> / <code>/vclogger off</code>")
