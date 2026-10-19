import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Credentials (Blank rakhein, Railway se aayega)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", 0)) 
API_HASH = os.environ.get("API_HASH", "")

# Assistant Userbot (String Session) 
# DHYAN RAKHEIN: Railway mein variable ka naam STRING_SESSION hi hona chahiye
STRING_SESSION = os.environ.get("STRING_SESSION", "") 

# Database
MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")

# Owner & Branding
# OWNER_ID hamesha ek NUMBER hota hai (@username nahi). 
# Telegram par @userinfobot se apni ID nikal kar yahan dalein ya Railway me variable set karein
OWNER_ID = int(os.environ.get("OWNER_ID", 0)) 
BOT_LINK = os.environ.get("BOT_LINK", "https://t.me/Zoyahumusicbot")

# Music API Keys (Blank rakhein, Railway se aayega)
YT_API_KEY = os.environ.get("YT_API_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Render Port
PORT = int(os.environ.get("PORT", 8080))
