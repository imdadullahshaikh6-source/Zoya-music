import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client
from motor.motor_asyncio import AsyncIOMotorClient
from pytgcalls import PyTgCalls

import config

# --- Flask Web Server (Keep Alive for UptimeRobot) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Zoya Music Bot is running! 🎵"

def run_flask():
    app.run(host="0.0.0.0", port=config.PORT)

# --- Bot & Assistant Clients ---
bot = Client(
    "ZoyaMusicBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    plugins=dict(root="plugins")
)

userbot = Client(
    "ZoyaUserbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.STRING_SESSION
)

# --- PyTgCalls Instance ---
call_py = PyTgCalls(userbot)

# --- Database ---
db = None

async def start_bot():
    global db
    # Start Flask in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"🌐 Flask server running on port {config.PORT}")

    # Connect to MongoDB
    if config.MONGO_DB_URI:
        db = AsyncIOMotorClient(config.MONGO_DB_URI).ZoyaMusic
        print("✅ Connected to MongoDB")

    # Start Pyrogram Clients
    await bot.start()
    await userbot.start()
    await call_py.start()
    print("🤖 Bot and Assistant started successfully!")
    print("🎵 PyTgCalls is ready to stream!")

    # Keep the main loop running
    from pyrogram import idle
    await idle()

    await bot.stop()
    await userbot.stop()

if __name__ == "__main__":
    asyncio.run(start_bot())
