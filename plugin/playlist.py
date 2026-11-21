# plugin/playlist.py — personal playlists
import html

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup

import database
import state
from helpers import player
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import fmt_time, sc


PER_PAGE = 10  # ek page me kitne gaane dikhane hain


def _short(text: str, n: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _list_view(pls: list, uid: int):
    """Saari playlists ka message + har playlist ka button."""
    lines = [f"🎼 <u>{sc('your playlists')}</u>\n"]
    rows = []
    for p in pls:
        n = len(p["tracks"])
        lines.append(f"• <b>{html.escape(p['name'])}</b> — <code>{p['_id']}</code> ({n} {sc('songs')})")
        rows.append([btn(f"{_short(p['name'], 28)} ({n})", f"pl:v:{p['_id']}:{uid}:0", style="primary")])
    lines.append(f"\n{sc('play one with')} <code>/play playlist-[id]</code>")
    lines.append(f"👇 {sc('tap a playlist to see its songs')}")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _songs_view(p: dict, uid: int, page: int):
    """Ek playlist ke gaane (page-wise) + back button."""
    tracks = p["tracks"]
    total = len(tracks)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(max(page, 0), pages - 1)
    lines = [f"🎼 <b>{html.escape(p['name'])}</b>", f"{sc('id')}: <code>{p['_id']}</code> • {total} {sc('songs')}\n"]
    if not total:
        lines.append(sc("this playlist is empty.") + f"\n{sc('add songs with')} <code>/addtoplaylist {p['_id']}</code>")
    for i, tr in enumerate(tracks[page * PER_PAGE:(page + 1) * PER_PAGE], start=page * PER_PAGE + 1):
        dur = f" — {fmt_time(tr['duration'])}" if tr.get("duration") else ""
        lines.append(f"{i}. {html.escape(_short(tr.get('title'), 50))}{dur}")
    if total:
        lines.append(f"\n{sc('play it with')} <code>/play playlist-{p['_id']}</code>")
    nav = []
    if page > 0:
        nav.append(btn("prev", f"pl:v:{p['_id']}:{uid}:{page - 1}", style="primary"))
    if pages > 1:
        nav.append(btn(f"{page + 1}/{pages}", "pl:n"))
    if page < pages - 1:
        nav.append(btn("next", f"pl:v:{p['_id']}:{uid}:{page + 1}", style="primary"))
    rows = ([nav] if nav else []) + [[btn("back", f"pl:b:{uid}", style="danger")]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _edit(cq, text, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except Exception as e:  # MessageNotModified waghera
        if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
            print(f"[playlist] edit error: {e!r}")


@Client.on_message(cmd("myplaylists"))
async def my_playlists(client, message):
    if not message.from_user:
        return
    pls = await database.pl_list(message.from_user.id)
    if not pls:
        return await message.reply_text(sc("you have no playlists. create one with") + " <code>/createplaylist [name]</code>")
    text, markup = _list_view(pls, message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^pl:v:([^:]+):(\d+):(\d+)$"))
async def view_playlist(client, cq):
    pid, uid, page = cq.matches[0].group(1), int(cq.matches[0].group(2)), int(cq.matches[0].group(3))
    if cq.from_user.id != uid:
        return await cq.answer("Ye playlist tumhari nahi hai. Apni dekhne ke liye /myplaylists likho.", show_alert=True)
    pls = await database.pl_list(uid)
    p = next((x for x in pls if str(x["_id"]) == pid), None)
    if not p:
        return await cq.answer("Playlist nahi mili (shayad delete ho gayi).", show_alert=True)
    text, markup = _songs_view(p, uid, page)
    await _edit(cq, text, markup)
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^pl:b:(\d+)$"))
async def back_to_playlists(client, cq):
    uid = int(cq.matches[0].group(1))
    if cq.from_user.id != uid:
        return await cq.answer("Ye playlist tumhari nahi hai. Apni dekhne ke liye /myplaylists likho.", show_alert=True)
    pls = await database.pl_list(uid)
    if not pls:
        return await cq.answer("Tumhari koi playlist nahi bachi.", show_alert=True)
    text, markup = _list_view(pls, uid)
    await _edit(cq, text, markup)
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^pl:n$"))
async def page_noop(client, cq):
    await cq.answer()


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
    # YouTube gaana download hone ke baad bhi local=True ho jata hai (silent-audio fix),
    # isliye local nahi, balki http link hai ya nahi wo dekhte hain. Telegram file me link nahi hota.
    if not tr.webpage or not str(tr.webpage).startswith("http"):
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
