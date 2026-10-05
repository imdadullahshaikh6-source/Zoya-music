import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Credentials
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8923638580:AAFefaYcgPOo9MycixwbD_KoJjTzRk2xXJk")
API_ID = os.environ.get("API_ID", "") # Add your API_ID from my.telegram.org
API_HASH = os.environ.get("API_HASH", "") # Add your API_HASH from my.telegram.org

# Assistant Userbot (String Session) - Required for VC
STRING_SESSION = os.environ.get("STRING_SESSION", "") 

# Database
MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")

# Owner & Branding
OWNER_ID = os.environ.get("OWNER_ID", "@Ownerbackk")
BOT_LINK = os.environ.get("BOT_LINK", "http://t.me/Zoyahumusicbot")

# Music API Keys
YT_API_KEY = os.environ.get("YT_API_KEY", "AIzaSyCRlUmap-YG69wvj8H4Fm41F1Fnq35zeUk")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "beb77e138e364a7eba4ba6ded1a59373")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "5602c01fbc444866a094b54e73c783ad")

# Render Port
PORT = int(os.environ.get("PORT", 8080))
