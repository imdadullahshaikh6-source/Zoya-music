import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Credentials
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", 0)) 
API_HASH = os.environ.get("API_HASH", "")

# Assistant Userbot (String Session) - Required for VC
STRING_SESSION = os.environ.get("STRING_SESSION", "") # Dhyan rahe Railway me bhi yahi naam ho

# Database
MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")

# Owner & Branding
# Yahan apna Telegram User ID dalein (jaise 123456789), username nahi chalega
OWNER_ID = int(os.environ.get("OWNER_ID", 0)) 
BOT_LINK = os.environ.get("BOT_LINK", "https://t.me/Zoyahumusicbot")

# Music API Keys (Ise Railway Variables me dalein, yahan blank rakhein)
YT_API_KEY = os.environ.get("YT_API_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Render Port
PORT = int(os.environ.get("PORT", 8080))
