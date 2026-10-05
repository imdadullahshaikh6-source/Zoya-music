# core.py
import pyrogram.errors
import pyrogram.raw.types

# --- MONKEY PATCH: Pyrogram + PyTgCalls Compatibility Fix ---
# Yeh patch pytgcalls ko chlane ke liye zaroori hai
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    pyrogram.errors.GroupcallForbidden = type("GroupcallForbidden", (Exception,), {})
if not hasattr(pyrogram.errors, "GroupcallInvalid"):
    pyrogram.errors.GroupcallInvalid = type("GroupcallInvalid", (Exception,), {})
if not hasattr(pyrogram.raw.types, "InputGroupCallSlug"):
    class InputGroupCallSlug:
        def __init__(self, slug=None):
            self.slug = slug
    pyrogram.raw.types.InputGroupCallSlug = InputGroupCallSlug
if not hasattr(pyrogram.raw.types, "PhoneCallDiscardReasonMigrateConferenceCall"):
    class PhoneCallDiscardReasonMigrateConferenceCall:
        pass
    pyrogram.raw.types.PhoneCallDiscardReasonMigrateConferenceCall = PhoneCallDiscardReasonMigrateConferenceCall
# --- END MONKEY PATCH ---

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
