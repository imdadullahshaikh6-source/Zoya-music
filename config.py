# config.py
import os
from dotenv import load_dotenv

load_dotenv()  # .env (server ki secrets)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend.env"))  # backend defaults (git me)

# Project folder (config.py jahan rakhi hai) — relative paths isi se resolve hote hain,
# isliye bot kisi bhi folder se start ho, cookies.txt mil jaati hai.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _path(value):
    """Relative path ko BASE_DIR ke hisaab se absolute bana do."""
    value = (value or "").strip()
    if not value:
        return ""
    return value if os.path.isabs(value) else os.path.join(BASE_DIR, value)


def _int(name, default=0):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Telegram credentials ────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = _int("API_ID")
API_HASH = os.environ.get("API_HASH", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")   # assistant (userbot)

# ── Database ────────────────────────────────────────────────────────────
MONGO_DB_URI = os.environ.get("MONGO_DB_URI", "")

# ── Owner ───────────────────────────────────────────────────────────────
# OWNER_ID me number ya @username dono chalega (pehle @username dene par bot crash hota tha).
# Username ho to startup par bot khud numeric ID resolve kar leta hai (main.py).
_raw_owner = os.environ.get("OWNER_ID", "").strip()
OWNER_ID = int(_raw_owner) if _raw_owner.lstrip("-").isdigit() else 0
OWNER_USERNAME = (os.environ.get("OWNER_USERNAME") or ("" if OWNER_ID else _raw_owner) or "Ownerbackk").lstrip("@")

# ── Branding / links ────────────────────────────────────────────────────
BOT_NAME = os.environ.get("BOT_NAME", "𝘇𝗼𝘆𝗮")
BOT_LINK = os.environ.get("BOT_LINK", "https://t.me/Zoyahumusicbot")
START_IMG = os.environ.get(
    "START_IMG",
    "https://i.ibb.co/LX6d0jnG/AND-THE-NEWS-THAT-THE-WORLD-ME-WAS-WAITING-FOR-F4-CK-21-ST-CENTURY-DELUXE-EDITION-Official-cove.jpg",
)
SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "")        # e.g. https://t.me/yourgroup
UPDATES_CHANNEL = os.environ.get("UPDATES_CHANNEL", "")  # e.g. https://t.me/yourchannel

# ── Music APIs ──────────────────────────────────────────────────────────
YT_API_KEY = os.environ.get("YT_API_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
COOKIES_FILE = _path(os.environ.get("COOKIES_FILE", "cookies.txt"))  # YouTube cookies (Netscape format)

# ── Backend: dost ki "dump" API (helpers/ytapi.py) ───────────────────────
# JSON API poll hoti hai, file Telegram ke dump channel se assistant (userbot) utarta hai.
DUMP_API_URL = os.environ.get("DUMP_API_URL", "")              # http://HOST:PORT/api/youtube/song
DUMP_VIDEO_API_URL = os.environ.get("DUMP_VIDEO_API_URL", "")  # http://HOST:PORT/api/youtube/video
DUMP_API_KEY = os.environ.get("DUMP_API_KEY", "")
DUMP_CHANNEL_ID = _int("DUMP_CHANNEL_ID")                      # -100xxxxxxxxxx
DUMP_CHANNEL_INVITE = os.environ.get("DUMP_CHANNEL_INVITE", "")  # https://t.me/+xxxx (assistant isse join karta hai)
API_FIRST = os.environ.get("API_FIRST", "innertube")           # innertube | ritesh | dump  (pehle kaun try ho)
# Last layer: sab API fail hon to yt-dlp (cookies + proxies) parallel. Proxies: comma / space / newline se alag.
YT_PROXIES = os.environ.get("YT_PROXIES", "")
YT_RACE = os.environ.get("YT_RACE", "")                        # 1 = hamesha on, 0 = off, khaali = proxies ho to on
# Assistant group me kitni der idle rehne ke baad nikal jaye (minutes). 0 = kabhi nahi nikalega (invite ka time bachta hai).
ASSISTANT_IDLE_MIN = _int("ASSISTANT_IDLE_MIN", 10)

# ── Limits ──────────────────────────────────────────────────────────────
QUEUE_LIMIT = _int("QUEUE_LIMIT", 30)
DURATION_LIMIT_MIN = _int("DURATION_LIMIT_MIN", 300)

# ── Misc ────────────────────────────────────────────────────────────────
PORT = _int("PORT", 8080)
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
