# core.py
import pyrogram.errors
import pyrogram.raw.types
import pyrogram.raw.functions.phone

# --- MONKEY PATCH: Pyrogram + PyTgCalls Compatibility Fix ---
# 1. Fix GroupcallForbidden
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    pyrogram.errors.GroupcallForbidden = type("GroupcallForbidden", (Exception,), {})
if not hasattr(pyrogram.errors, "GroupcallInvalid"):
    pyrogram.errors.GroupcallInvalid = type("GroupcallInvalid", (Exception,), {})

# 2. Fix Raw Types
if not hasattr(pyrogram.raw.types, "InputGroupCallSlug"):
    class InputGroupCallSlug:
        def __init__(self, slug=None):
            self.slug = slug
    pyrogram.raw.types.InputGroupCallSlug = InputGroupCallSlug

if not hasattr(pyrogram.raw.types, "PhoneCallDiscardReasonMigrateConferenceCall"):
    class PhoneCallDiscardReasonMigrateConferenceCall:
        pass
    pyrogram.raw.types.PhoneCallDiscardReasonMigrateConferenceCall = PhoneCallDiscardReasonMigrateConferenceCall

# 3. Fix CreateConferenceCall (Yeh naya fix hai)
if not hasattr(pyrogram.raw.functions.phone, "CreateConferenceCall"):
    class CreateConferenceCall:
        def __init__(self, call=None, join_as=None, invite_hash=None, public_key=None):
            self.call = call
            self.join_as = join_as
            self.invite_hash = invite_hash
            self.public_key = public_key
    pyrogram.raw.functions.phone.CreateConferenceCall = CreateConferenceCall
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
