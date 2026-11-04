# plugin/nowplaying.py — /player /np /queue
from pyrogram import Client, filters

import state
from helpers import player, thumb
from helpers.filters import cmd
from helpers.strings import t


@Client.on_message(cmd(["player", "np"]) & filters.group)
async def np_cmd(client, message):
    chat_id = message.chat.id
    st = state.get(chat_id)
    if not st.active:
        return await message.reply_text(await t(chat_id, "nothing"), reply_markup=player.CLOSE_KB)
    tr = st.current
    from database import get_chat
    path = None
    if (await get_chat(chat_id)).get("thumb", True):
        path = await thumb.make_card(tr.thumb, tr.title, tr.channel, st.played(), tr.duration, st.paused)
    cap = player.now_caption(tr)
    kb = player.player_keyboard(chat_id)
    try:
        if path:
            await message.reply_photo(path, caption=cap, reply_markup=kb, has_spoiler=True)
        else:
            await message.reply_text(cap, reply_markup=kb)
    finally:
        if path:
            import os
            try:
                os.remove(path)
            except Exception:
                pass


@Client.on_message(cmd("queue") & filters.group)
async def queue_cmd(client, message):
    chat_id = message.chat.id
    text = player.queue_text(chat_id)
    if not text:
        return await message.reply_text(await t(chat_id, "nothing"), reply_markup=player.CLOSE_KB)
    await message.reply_text(text)
