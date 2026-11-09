# core.py
import pyrogram.errors
import pyrogram.raw.types
import pyrogram.raw.functions.phone

# --- MONKEY PATCH: Pyrogram(kurigram) + PyTgCalls compatibility ---
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

if not hasattr(pyrogram.raw.functions.phone, "CreateConferenceCall"):
    class CreateConferenceCall:
        def __init__(self, call=None, join_as=None, invite_hash=None, public_key=None):
            self.call = call
            self.join_as = join_as
            self.invite_hash = invite_hash
            self.public_key = public_key
    pyrogram.raw.functions.phone.CreateConferenceCall = CreateConferenceCall

if not hasattr(pyrogram.raw.functions.phone, "GetGroupCallChainBlocks"):
    class GetGroupCallChainBlocks:
        def __init__(self, call=None, sub_peer=None, offset=0, limit=1000):
            self.call = call
            self.sub_peer = sub_peer
            self.offset = offset
            self.limit = limit
    pyrogram.raw.functions.phone.GetGroupCallChainBlocks = GetGroupCallChainBlocks
# --- END MONKEY PATCH ---

from pyrogram import Client
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls

import config

# Bot client — saare plugins plugin/ folder se load hote hain
bot = Client(
    "ZoyaMusicBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    parse_mode=ParseMode.HTML,
    plugins=dict(root="plugin"),
)

# Assistant (userbot) — voice chat me yahi stream karta hai
userbot = Client(
    "ZoyaUserbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.STRING_SESSION,
    parse_mode=ParseMode.HTML,
)

call_py = PyTgCalls(userbot)
