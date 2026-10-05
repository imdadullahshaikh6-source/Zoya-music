import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client
from motor.motor_asyncio import AsyncIOMotorClient
from pytgcalls import PyTgCalls  # PyPI package is py-tgcalls, but import is pytgcalls
import config

print("🚀 [DEBUG] main.py started...")

# --- Flask Web Server ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Zoya Music Bot is running! 🎵"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    print(f"🌐 [DEBUG] Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port)

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

    print("💾 [DEBUG] Connecting to MongoDB...")
    if config.MONGO_DB_URI:
        db = AsyncIOMotorClient(config.MONGO_DB_URI).ZoyaMusic
        print("✅ [DEBUG] Connected to MongoDB")
    else:
        print("⚠️ [DEBUG] MONGO_DB_URI is missing! Database will not work.")

    print("🤖 [DEBUG] Starting Pyrogram Bot Client...")
    try:
        await bot.start()
        print("✅ [DEBUG] Bot Client started successfully!")
    except Exception as e:
        print(f"❌ [DEBUG] Bot Client Error: {e}")
        return

    print("👤 [DEBUG] Starting Userbot Client...")
    try:
        await userbot.start()
        print("✅ [DEBUG] Userbot Client started successfully!")
    except Exception as e:
        print(f"❌ [DEBUG] Userbot Client Error: {e}")
        return

    print("📞 [DEBUG] Starting PyTgCalls...")
    try:
        await call_py.start()
        print("✅ [DEBUG] PyTgCalls started successfully!")
    except Exception as e:
        print(f"❌ [DEBUG] PyTgCalls Error: {e}")
        return

    print("🎵 [DEBUG] Zoya Music Bot is fully operational!")
    from pyrogram import idle
    await idle()

    await bot.stop()
    await userbot.stop()

if __name__ == "__main__":
    print("🚀 [DEBUG] Entering main block...")
    asyncio.run(start_bot())
