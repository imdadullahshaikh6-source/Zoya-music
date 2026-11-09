# plugin/playlist.py — personal playlists
import html

from pyrogram import Client, filters

import database
import state
from helpers import player
from helpers.filters import cmd
from helpers.fonts import fmt_time, sc


@Client.on_message(cmd("myplaylists"))
async def my_playlists(client, message):
    if not message.from_user:
        return
    pls = await database.pl_list(message.from_user.id)
    if not pls:
        return await message.reply_text(sc("you have no playlists. create one with") + " <code>/createplaylist [name]</code>")
    lines = [f"🎼 <u>{sc('your playlists')}</u>\n"]
    for p in pls:
        lines.append(f"• <b>{html.escape(p['name'])}</b> — <code>{p['_id']}</code> ({len(p['tracks'])} {sc('songs')})")
    lines.append(f"\n{sc('play one with')} <code>/play playlist-[id]</code>")
    await message.reply_text("\n".join(lines))


@Client.on_message(cmd("createplaylist"))
async def create_playlist(client, message):
    if not message.from_user:
        return
    name = " ".join(message.command[1:]).strip()
    if not name:
        return await message.reply_text(sc("usage:") + " <code>/createplaylist [name]</code>")
    doc = await database.pl_create(message.from_user.id, name)
    if not doc:
        return await message.reply_text(sc(f"you can only have {database.MAX_PLAYLISTS} playlists. delete one first."))
    await message.reply_text(
        f"✅ {sc('playlist created')}: <b>{html.escape(doc['name'])}</b>\n{sc('id')}: <code>{doc['_id']}</code>\n"
        f"{sc('add the current song with')} <code>/addtoplaylist {doc['_id']}</code>"
    )


@Client.on_message(cmd("deleteplaylist"))
async def delete_playlist(client, message):
    if not message.from_user or len(message.command) < 2:
        return await message.reply_text(sc("usage:") + " <code>/deleteplaylist [id]</code>")
    ok = await database.pl_delete(message.command[1].strip(), message.from_user.id)
    await message.reply_text("✅ " + sc("playlist deleted.") if ok else "❌ " + sc("playlist not found, or it is not yours."))


async def _save(user_id: int, pid: str, chat_id: int) -> str:
    st = state.get(chat_id)
    if not st.active:
        return "nothing"
    tr = st.current
    if tr.local or not tr.webpage:
        return "local"
    return await database.pl_add_track(
        pid, user_id, {"title": tr.title, "webpage": tr.webpage, "duration": tr.duration}
    )


MSG = {
    "ok": "✅ Added to playlist.",
    "dup": "This song is already in that playlist.",
    "full": "That playlist is full.",
    "notfound": "Playlist not found, or it is not yours.",
    "nothing": "Nothing is playing right now.",
    "local": "Telegram files can't be saved to playlists.",
}


@Client.on_message(cmd("addtoplaylist") & filters.group)
async def add_to_playlist(client, message):
    if not message.from_user or len(message.command) < 2:
        return await message.reply_text(sc("usage:") + " <code>/addtoplaylist [id]</code>")
    k = await _save(message.from_user.id, message.command[1].strip(), message.chat.id)
    await message.reply_text(MSG[k])


@Client.on_callback_query(filters.regex(r"^pl:save:(-?\d+)$"))
async def save_button(client, cq):
    chat_id = int(cq.matches[0].group(1))
    pls = await database.pl_list(cq.from_user.id)
    if not pls:
        return await cq.answer("You have no playlist. Create one: /createplaylist [name]", show_alert=True)
    k = await _save(cq.from_user.id, pls[0]["_id"], chat_id)
    extra = f" ({pls[0]['name']})" if k == "ok" else ""
    await cq.answer(MSG[k] + extra, show_alert=(k != "ok"))
