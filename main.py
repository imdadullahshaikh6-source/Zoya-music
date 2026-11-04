# main.py
import asyncio
import os
import threading

from flask import Flask
from pyrogram import idle

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
