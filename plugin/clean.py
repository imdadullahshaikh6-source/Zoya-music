# plugin/clean.py — "Clean Commands" setting: command execute hone ke baad user ka command message delete
import re

from pyrogram import Client, filters

import database
from core import bot

CMDS = (
    "play|vplay|playforce|vplayforce|autoplay|pause|resume|skip|next|stop|end|seek|seekback|loop|shuffle|"
    "player|np|queue|myplaylists|createplaylist|deleteplaylist|addtoplaylist|settings|setting|playmode|auth|unauth|"
    "authlist|reload|ping|stats|start|help"
)
_RE = re.compile(rf"^[/.]({CMDS})(?:@(\w+))?(?:\s|$)", re.I)


@Client.on_message(filters.group & filters.text, group=1)
async def clean_commands(client, message):
    m = _RE.match(message.text or "")
    if not m:
        return
    if m.group(2) and m.group(2).lower() != (bot.me.username or "").lower():
        return  # kisi aur bot ka command
    if (await database.get_chat(message.chat.id)).get("clean"):
        try:
            await message.delete()
        except Exception:
            pass
          
