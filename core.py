# core.py
from pyrogram import Client
from pytgcalls import PyTgCalls
import config

# Bot Client
bot = Client(
    "ZoyaMusicBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    plugins=dict(root="plugins") # Note: 'plugins' plural
)

# Assistant Userbot Client
userbot = Client(
    "ZoyaUserbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.STRING_SESSION
)

# PyTgCalls Instance
call_py = PyTgCalls(userbot)

# Database Variable
db = None
