from pyrogram import Client, filters

from helpers.filters import cmd
from helpers.player import handle_play


@Client.on_message(cmd(["play", "vplay"]) & filters.group)
async def play_cmd(client, message):
    await handle_play(client, message, video=message.command[0].lower() == "vplay", force=False)
