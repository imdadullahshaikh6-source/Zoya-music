from pyrogram import Client, filters

from helpers.filters import cmd
from helpers.player import handle_play


@Client.on_message(cmd(["playforce", "vplayforce"]) & filters.group)
async def playforce_cmd(client, message):
    await handle_play(client, message, video=message.command[0].lower() == "vplayforce", force=True)
