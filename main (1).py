# main.py
import asyncio
import os
import threading

from flask import Flask
from pyrogram import idle
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

import config
import database
import state
from core import bot, call_py, userbot
from helpers import assistant

print("🚀 main.py started...")

app = Flask(__name__)


@app.route("/")
def home():
    return "Zoya Music Bot is running! 🎵"


def run_flask():
    port = int(os.environ.get("PORT", config.PORT))
    app.run(host="0.0.0.0", port=port)


# ───────────────────────── Telegram "/" menu ─────────────────────────
# Bot khud se menu nahi banata: BotFather me /setcommands karo ya yahan se set_bot_commands call karo.
DM_COMMANDS = [
    ("start", "Start the bot"),
    ("help", "Show all commands"),
    ("ping", "Check bot speed"),
    ("stats", "Bot statistics"),
    ("myplaylists", "Your saved playlists"),
    ("createplaylist", "Create a new playlist"),
    ("deleteplaylist", "Delete a playlist"),
]

GROUP_COMMANDS = [
    ("play", "Play a song (name / link)"),
    ("vplay", "Play a video"),
    ("playforce", "Play now, skipping the queue"),
    ("vplayforce", "Play a video now, skipping the queue"),
    ("pause", "Pause the stream"),
    ("resume", "Resume the stream"),
    ("skip", "Skip to the next track"),
    ("stop", "Stop and clear the queue"),
    ("seek", "Seek forward"),
    ("seekback", "Seek backward"),
    ("loop", "Repeat the current track"),
    ("shuffle", "Shuffle the queue"),
    ("autoplay", "Autoplay related songs (on / off)"),
    ("queue", "Show the queue"),
    ("player", "Show the player"),
    ("addtoplaylist", "Save the current track to a playlist"),
    ("ping", "Check bot speed"),
    ("help", "Show all commands"),
]

ADMIN_COMMANDS = GROUP_COMMANDS + [
    ("settings", "Group settings (play mode, thumbnail...)"),
    ("auth", "Authorize a user to control playback"),
    ("unauth", "Remove an authorized user"),
    ("authlist", "List authorized users"),
    ("reload", "Refresh admin list and assistant"),
]

OWNER_COMMANDS = DM_COMMANDS + [
    ("addsudo", "Add a sudo user"),
    ("delsudo", "Remove a sudo user"),
    ("sudolist", "List sudo users"),
    ("broadcast", "Broadcast a message"),
    ("restart", "Restart the bot"),
    ("diag", "Lag diagnostics (owner)"),
]


def _cmds(items):
    return [BotCommand(c, d) for c, d in items]


async def setup_commands():
    """Telegram ke '/' menu me commands dikhane ke liye."""
    jobs = [
        ("DM", DM_COMMANDS, BotCommandScopeDefault()),
        ("groups", GROUP_COMMANDS, BotCommandScopeAllGroupChats()),
        ("group admins", ADMIN_COMMANDS, BotCommandScopeAllChatAdministrators()),
    ]
    if config.OWNER_ID:
        jobs.append(("owner DM", OWNER_COMMANDS, BotCommandScopeChat(config.OWNER_ID)))
    for name, items, scope in jobs:
        try:
            await bot.set_bot_commands(_cmds(items), scope=scope)
            print(f"✅ Menu commands set: {name} ({len(items)})")
        except Exception as e:
            print(f"⚠️ Menu commands ({name}) set nahi hue: {e!r}")


async def start_bot():
    threading.Thread(target=run_flask, daemon=True).start()

    database.connect()
    try:
        for uid in await database.sudo_load():
            state.SUDOERS.add(uid)
    except Exception as e:
        print(f"⚠️ sudo load error: {e}")

    await bot.start()
    print(f"✅ Bot started: @{bot.me.username}")

    # OWNER_ID me @username ho to numeric ID resolve karo
    if not config.OWNER_ID and config.OWNER_USERNAME:
        try:
            config.OWNER_ID = (await bot.get_users(config.OWNER_USERNAME)).id
            print(f"✅ Owner resolved: {config.OWNER_ID}")
        except Exception as e:
            print(f"⚠️ Owner resolve nahi hua ({e}) — OWNER_ID numeric dalo")

    await setup_commands()

    await userbot.start()
    print(f"✅ Assistant started: {userbot.me.first_name} ({userbot.me.id})")

    await call_py.start()
    print("✅ PyTgCalls started")
    assistant.start_watcher()  # idle group se assistant ko 10 min baad nikalne wala loop
    print("🎵 Zoya Music Bot fully operational!")

    await idle()
    await bot.stop()
    await userbot.stop()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
