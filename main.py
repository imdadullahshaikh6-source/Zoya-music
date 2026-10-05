# main.py
import os
import asyncio
import threading
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import idle
import config

# Import from core
from core import bot, userbot, call_py
import core

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

# --- Start Bot Function ---
async def start_bot():
    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()

    # Connect to Database
    if config.MONGO_DB_URI:
        core.db = AsyncIOMotorClient(config.MONGO_DB_URI).ZoyaMusic
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
    await idle()

    await bot.stop()
    await userbot.stop()

if __name__ == "__main__":
    asyncio.run(start_bot())
