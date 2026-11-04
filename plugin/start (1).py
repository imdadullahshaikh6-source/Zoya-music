# plugin/start.py — /start, /help (Zoya font + blockquote), help categories
import html

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import database
import state
from core import bot
from helpers.filters import cmd
from helpers.fonts import fmt_uptime, sc
import time


def C(c, args="", desc=""):
    a = f" <code>{html.escape(args)}</code>" if args else ""
    return f"• <code>{c}</code>{a} — {sc(desc)}"


PAGES = {
    "play": (
        "▶️",
        "playback commands",
        [
            C("/play", "[song name / url]", "play and stream audio in group voice chat."),
            C("/vplay", "[video name / url]", "play and stream hd video in group video chat."),
            C("/playforce", "[song name / url]", "play audio immediately, bypassing the queue."),
            C("/vplayforce", "[video name / url]", "play video immediately, bypassing the queue."),
            C("/autoplay", "", "automatically find and play related tracks when queue ends."),
        ],
        "tip: reply directly to any audio or video file with /play!",
    ),
    "ctl": (
        "⏭",
        "playback controls",
        [
            C("/pause", "", "pause the current playing stream in voice chat."),
            C("/resume", "", "resume the paused stream in voice chat."),
            C("/skip", "", "skip the currently playing track to the next queued song."),
            C("/stop", "", "stop playing music completely and clear the queue."),
            C("/seek", "[seconds]", "jump forward in the ongoing stream by seconds."),
            C("/seekback", "[seconds]", "rewind backward in the ongoing stream by seconds."),
            C("/loop", "[1-10]", "repeat the currently playing song multiple times."),
            C("/shuffle", "", "randomly shuffle the order of all queued songs."),
        ],
        "",
    ),
    "pl": (
        "🎼",
        "playlist & queue",
        [
            C("/player", "", "show interactive music player controls in chat (also /np)."),
            C("/queue", "", "display the currently playing song and all upcoming tracks."),
            C("/myplaylists", "", "view all your personal saved playlists."),
            C("/createplaylist", "[name]", "create a brand new personal playlist."),
            C("/addtoplaylist", "[id]", "save the currently playing song to a playlist."),
            C("/deleteplaylist", "[id]", "permanently delete a saved playlist."),
            C("/play", "playlist-[id]", "play all songs from your playlist sequentially."),
        ],
        "",
    ),
    "adm": (
        "🛡",
        "admin commands",
        [
            C("/settings", "", "open group settings to configure playback mode and permissions."),
            C("/auth", "[username / id]", "allow a member to use admin music controls without admin rights."),
            C("/unauth", "[username / id]", "remove authorized member status from a user."),
            C("/authlist", "", "view the complete list of authorized members in this group."),
            C("/reload", "", "refresh admin list and bot permissions cache."),
        ],
        "",
    ),
    "gen": (
        "🧭",
        "general commands",
        [
            C("/ping", "", "check bot response speed, ping latency, and server uptime."),
            C("/stats", "", "view bot system status, cpu and ram usage, and active streams."),
            C("/start", "", "start the bot or check if the bot is active and working."),
            C("/help", "", "open this interactive help and commands menu."),
        ],
        "",
    ),
}


def page_text(key: str) -> str:
    icon, title, lines, tip = PAGES[key]
    out = f"{icon} <u>{sc(title)}:</u>\n\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>"
    if tip:
        out += f"\n\nℹ️ <i>{sc(tip)}</i>"
    return out


def help_main_text() -> str:
    return (
        f"❔ <u>{sc('help and commands')}:</u>\n\n"
        f"{sc('tap any category below to explore available commands and features.')}\n\n"
        f"ℹ️ <i>{sc('all commands can be used with / or .')}</i>"
    )


def help_main_kb(back_to_start: bool = True):
    rows = [
        [InlineKeyboardButton("▶️ Playback", callback_data="help:play"), InlineKeyboardButton("⏭ Controls", callback_data="help:ctl")],
        [InlineKeyboardButton("🎼 Playlists", callback_data="help:pl"), InlineKeyboardButton("🛡 Admins", callback_data="help:adm")],
        [InlineKeyboardButton("🧭 General", callback_data="help:gen")],
    ]
    if back_to_start:
        rows.append([InlineKeyboardButton("‹", callback_data="start:back")])
    else:
        rows.append([InlineKeyboardButton("✖", callback_data="x")])
    return InlineKeyboardMarkup(rows)


def start_text(name_html: str) -> str:
    return (
        f"<blockquote expandable>✦ <b>{sc('hey')}</b> {name_html} !\n\n"
        f"{sc('i am')} <b><i>Zoya</i></b> — {sc('a powerful music bot.')}\n"
        f"➤ {sc('play high-quality music & video in group voice chats')}\n"
        f"➤ {sc('supports youtube, spotify and direct links')}\n"
        f"➤ {sc('queue, loop, shuffle, seek and autoplay')}\n"
        f"➤ {sc('personal playlists you can save and play anytime')}\n"
        f"➤ {sc('every command works with / or . in groups')}\n\n"
        f"{sc('tap')} <b>{sc('help and commands')}</b> {sc('below to see everything i can do.')}</blockquote>"
    )


def start_kb():
    me = bot.me.username
    rows = [
        [InlineKeyboardButton("➕ Add me to your group", url=f"https://t.me/{me}?startgroup=true&admin=invite_users+delete_messages+manage_video_chats")],
        [InlineKeyboardButton("❔ Help and Commands?", callback_data="help:main")],
    ]
    r = []
    if config.SUPPORT_CHAT:
        r.append(InlineKeyboardButton("💬 Support", url=config.SUPPORT_CHAT))
    r.append(InlineKeyboardButton("</> Developer", url=f"https://t.me/{config.OWNER_USERNAME}"))
    rows.append(r)
    return InlineKeyboardMarkup(rows)


async def _edit(cq, text, kb):
    m = cq.message
    try:
        if m.photo:
            await m.edit_caption(text, reply_markup=kb)
        else:
            await m.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@Client.on_message(cmd("start"))
async def start_cmd(client, message):
    user = message.from_user
    if message.chat.type.name == "PRIVATE":
        if user:
            await database.add_served_user(user.id)
        name = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>' if user else ""
        try:
            await message.reply_photo(config.START_IMG, caption=start_text(name), reply_markup=start_kb())
        except Exception:
            await message.reply_text(start_text(name), reply_markup=start_kb())
    else:
        await database.add_served_chat(message.chat.id)
        up = fmt_uptime(time.time() - state.START_TIME)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❔ Help", url=f"https://t.me/{bot.me.username}?start=help")]])
        await message.reply_text(
            f"✦ <b><i>Zoya</i></b> {sc('is alive and ready to play music!')}\n⏱ {sc('uptime')}: <code>{up}</code>",
            reply_markup=kb,
        )


@Client.on_message(cmd("help"))
async def help_cmd(client, message):
    if message.chat.type.name == "PRIVATE" and message.from_user:
        await database.add_served_user(message.from_user.id)
    back = message.chat.type.name == "PRIVATE"
    try:
        await message.reply_photo(config.START_IMG, caption=help_main_text(), reply_markup=help_main_kb(back))
    except Exception:
        await message.reply_text(help_main_text(), reply_markup=help_main_kb(back))


@Client.on_callback_query(filters.regex(r"^help:(\w+)$"))
async def help_cb(client, cq):
    key = cq.matches[0].group(1)
    back = cq.message.chat.type.name == "PRIVATE"
    if key == "main":
        await _edit(cq, help_main_text(), help_main_kb(back))
    elif key in PAGES:
        await _edit(cq, page_text(key), InlineKeyboardMarkup([[InlineKeyboardButton("‹", callback_data="help:main")]]))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^start:back$"))
async def start_back(client, cq):
    u = cq.from_user
    name = f'<a href="tg://user?id={u.id}">{html.escape(u.first_name or "User")}</a>'
    await _edit(cq, start_text(name), start_kb())
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^x$"))
async def close_cb(client, cq):
    try:
        await cq.message.delete()
    except Exception:
        await cq.answer()
