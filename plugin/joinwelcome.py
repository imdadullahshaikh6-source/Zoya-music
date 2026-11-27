# plugin/joinwelcome.py — group me join request aaye to user ko bot ki taraf se DM (welcome + "start the bot" button)
#
# Kaise kaam karta hai:
#   * Bot jis group me admin hai (Invite Users power ke saath), wahan koi join request bheje to Telegram bot ko
#     update deta hai. Bot us user ko DM karta hai: "request mili, admin dekhenge, tab tak mujhse milo" + start button.
#   * Button dabate hi /start chalta hai -> start_cmd user ko database me jod deta hai (bot ke users badhte hain),
#     aur ye greeting wala message turant delete ho jata hai (phir normal start screen aati hai).
#   * Group ki request ko bot touch NAHI karta (na accept, na decline) — wo admins ka kaam hai.
#   * Sirf unko DM jo bot ko pehle se nahi jaante, aur ek user ko 24 ghante me ek hi baar (spam nahi).
#
# .env (optional):
#   JOIN_WELCOME=0               # band karna ho to
#   JOIN_WELCOME_COOLDOWN_H=24   # ek user ko dobara kitne ghante baad
#   JOIN_WELCOME_PER_MIN=15      # ek minute me max itne DM (Telegram flood se bachne ke liye)
import html
import os
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardMarkup

import database
from core import bot
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import sc


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


ENABLED = os.getenv("JOIN_WELCOME", "1").strip() != "0"
COOLDOWN = max(1, _int_env("JOIN_WELCOME_COOLDOWN_H", 24)) * 3600
MAX_PER_MIN = max(1, _int_env("JOIN_WELCOME_PER_MIN", 15))

_sent: dict = {}     # user_id -> last DM time
_window: list = []   # pichle 60 second ke DM ke time
_notice: dict = {}   # user_id -> greeting message_id (Mongo na ho / restart ke baad bhi chale isliye Mongo me bhi rakhte hain)


async def _save_notice(uid: int, mid: int) -> None:
    _notice[uid] = mid
    if len(_notice) > 20000:
        _notice.clear()
    try:
        if database.ok():
            await database._db.joinwelcome.update_one({"_id": uid}, {"$set": {"mid": mid, "t": time.time()}}, upsert=True)
    except Exception as e:
        print(f"[joinwelcome] save notice: {type(e).__name__}")


async def _pop_notice(uid: int):
    mid = _notice.pop(uid, None)
    try:
        if database.ok():
            doc = await database._db.joinwelcome.find_one_and_delete({"_id": uid})
            if mid is None and doc:
                mid = doc.get("mid")
    except Exception as e:
        print(f"[joinwelcome] pop notice: {type(e).__name__}")
    return mid


def _allow_now() -> bool:
    now = time.time()
    while _window and now - _window[0] > 60:
        _window.pop(0)
    if len(_window) >= MAX_PER_MIN:
        return False
    _window.append(now)
    return True


async def _is_known(uid: int) -> bool:
    """Bot ke users me pehle se hai (yani /start kar chuka) to DM ki zarurat nahi."""
    try:
        if database.ok():
            return await database._db.users.find_one({"_id": uid}, {"_id": 1}) is not None
        return uid in database._mem["users"]
    except Exception:
        return False


def _bot_name() -> str:
    try:
        return (bot.me.first_name or "Zoya").strip()
    except Exception:
        return "Zoya"


def _text(name: str, group: str) -> str:
    return (
        f"<blockquote>✦ <b>{sc('hey')}</b> {html.escape(name)} !\n\n"
        f"{sc('thanks for requesting to join')} <b>{html.escape(group)}</b>. "
        f"{sc('an admin will review your request soon.')}\n\n"
        f"{sc('while you wait, meet')} <b>{html.escape(_bot_name())}</b> — "
        f"{sc('a music bot that plays songs and videos in group voice chats.')}</blockquote>"
    )


@Client.on_chat_join_request()
async def on_join_request(client, req):
    if not ENABLED:
        return
    user = req.from_user
    if not user or user.is_bot:
        return
    now = time.time()
    if now - _sent.get(user.id, 0) < COOLDOWN:
        return
    if await _is_known(user.id):
        return
    if not _allow_now():
        return
    if len(_sent) > 20000:
        _sent.clear()
    _sent[user.id] = now

    # Telegram join request ke saath user_chat_id deta hai: user ne bot start na kiya ho tab bhi DM jaa sakta hai
    target = getattr(req, "user_chat_id", None) or user.id
    group = getattr(req.chat, "title", None) or "the group"
    try:
        kb = InlineKeyboardMarkup([[btn("start the bot", url=f"https://t.me/{bot.me.username}?start=welcome", style="success")]])
        sent = await client.send_message(target, _text(user.first_name or "there", group), reply_markup=kb)
        await _save_notice(user.id, sent.id)
        print(f"[joinwelcome] DM sent user={user.id} group={req.chat.id}")
    except FloodWait as e:
        print(f"[joinwelcome] FloodWait {e.value}s, DM skip user={user.id}")
    except RPCError as e:  # user ne bot block kiya / DM band / request purani
        print(f"[joinwelcome] DM failed user={user.id}: {type(e).__name__}")
    except Exception as e:
        print(f"[joinwelcome] error user={user.id}: {type(e).__name__}: {e}")


@Client.on_message(cmd("start") & filters.private, group=-2)
async def delete_greeting_on_start(client, message):
    """User bot ko start kare (button se ya khud /start likhe) -> greeting turant delete. Isse start_cmd (group 0)
    nahi rukta, wo apne aap normal start screen bhejta hai."""
    user = message.from_user
    if not user:
        return
    mid = await _pop_notice(user.id)
    if not mid:
        return
    try:
        await client.delete_messages(message.chat.id, mid)
    except Exception as e:
        print(f"[joinwelcome] greeting delete failed user={user.id}: {type(e).__name__}")
