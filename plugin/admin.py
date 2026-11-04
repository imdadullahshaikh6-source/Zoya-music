# plugin/admin.py — /settings /auth /unauth /authlist /reload
import html
import traceback

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup

import database
from helpers import assistant, perms
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import sc
from helpers.strings import t


async def _admin_only(client, message) -> bool:
    if not await perms.message_is_admin(client, message):
        await message.reply_text(await t(message.chat.id, "admins_only"))
        return False
    return True


async def _target(client, message):
    r = message.reply_to_message
    if r and r.from_user:
        return r.from_user
    if len(message.command) > 1:
        arg = message.command[1].lstrip("@")
        try:
            return await client.get_users(int(arg) if arg.lstrip("-").isdigit() else arg)
        except Exception:
            return None
    return None


# ───────── auth ─────────
@Client.on_message(cmd("auth") & filters.group)
async def auth_cmd(client, message):
    if not await _admin_only(client, message):
        return
    u = await _target(client, message)
    if not u:
        return await message.reply_text(sc("reply to a user, or give a username / id."))
    await database.auth_add(message.chat.id, u.id)
    await message.reply_text(f"✅ {player_mention(u)} {sc('is now authorized.')}")


@Client.on_message(cmd("unauth") & filters.group)
async def unauth_cmd(client, message):
    if not await _admin_only(client, message):
        return
    u = await _target(client, message)
    if not u:
        return await message.reply_text(sc("reply to a user, or give a username / id."))
    ok = await database.auth_remove(message.chat.id, u.id)
    await message.reply_text(f"✅ {player_mention(u)} {sc('is no longer authorized.')}" if ok else sc("that user is not authorized."))


@Client.on_message(cmd("authlist") & filters.group)
async def authlist_cmd(client, message):
    ids = await database.auth_list(message.chat.id)
    if not ids:
        return await message.reply_text(sc("no authorized members in this group."))
    lines = [f"🛡 <u>{sc('authorized members')}</u>\n"]
    for i, uid in enumerate(ids, 1):
        try:
            u = await client.get_users(uid)
            lines.append(f"{i}. {player_mention(u)} (<code>{uid}</code>)")
        except Exception:
            lines.append(f"{i}. <code>{uid}</code>")
    await message.reply_text("\n".join(lines))


def player_mention(u) -> str:
    return f'<a href="tg://user?id={u.id}">{html.escape(u.first_name or "User")}</a>'


# ───────── reload ─────────
@Client.on_message(cmd("reload") & filters.group)
async def reload_cmd(client, message):
    if not await _admin_only(client, message):
        return
    perms.reload(message.chat.id)
    assistant.forget(message.chat.id)
    await perms.get_admins(client, message.chat.id, fresh=True)
    await message.reply_text("✅ " + sc("admin list and permissions cache refreshed."))


# ───────── settings panel (Alexa jaisa) ─────────
BACK = [btn("back", "set:main")]


async def _panel(chat):
    text = (
        f"⚙️ <u><b>Zoya</b> {sc('settings panel')}:</u>\n\n"
        f"<b>{sc('chat id')}:</b> <code>{chat.id}</code>\n"
        f"<b>{sc('chat title')}:</b> {html.escape(chat.title or '')}\n\n"
        f"{sc('click on the buttons below to change settings.')}"
    )
    kb = InlineKeyboardMarkup(
        [
            [btn("play mode", "set:pm", style="primary"), btn("clean commands", "set:cl", style="primary")],
            [btn("thumbnail", "set:th", style="primary")],
            [btn("close", "x", style="danger")],
        ]
    )
    return text, kb


async def _sub(chat_id: int, which: str):
    c = await database.get_chat(chat_id)
    if which == "pm":
        cur = c["play_mode"]
        text = (
            f"🔒 <u>{sc('play mode settings')}</u>\n\n"
            f"{sc('choose who can play music in this group.')}\n\n"
            f"• <b>{sc('everyone')}:</b> {sc('anyone can play music.')}\n"
            f"• <b>{sc('admin only')}:</b> {sc('only admins can play music.')}\n\n"
            f"<i>{sc('current selection')}:</i> <b>{sc('everyone') if cur == 'everyone' else sc('admin only')}</b>"
        )
        kb = [
            [
                btn("everyone", "set:pm:everyone", style="success" if cur == "everyone" else None),
                btn("admin only", "set:pm:admins", style="success" if cur == "admins" else None),
            ]
        ]
    else:
        key, icon, title, desc = {
            "cl": ("clean", "🧹", "clean commands settings", "automatically delete bot commands after execution to keep the chat clean."),
            "th": ("thumb", "🖼", "thumbnail settings", "show track thumbnail while playing music in voice chat."),
        }[which]
        on = bool(c.get(key, key == "thumb"))
        text = (
            f"{icon} <u>{sc(title)}</u>\n\n{sc(desc)}\n\n"
            f"<i>{sc('current status')}:</i> <b>{sc('enabled') if on else sc('disabled')}</b>"
        )
        kb = [
            [
                btn("enable", f"set:{which}:on", style="success" if on else None),
                btn("disable", f"set:{which}:off", style="danger" if not on else None),
            ]
        ]
    kb.append(BACK)
    return text, InlineKeyboardMarkup(kb)


@Client.on_message(cmd(["settings", "setting", "playmode"]) & filters.group)
async def settings_cmd(client, message):
    try:
        if not await _admin_only(client, message):
            return
        text, kb = await _panel(message.chat)
        await message.reply_text(text, reply_markup=kb)
    except Exception:
        # pehle ye error chup-chap nigal jata tha, isliye command "sunta hi nahi" lagta tha
        traceback.print_exc()
        await message.reply_text(sc("could not open settings. please try /reload and try again."))


@Client.on_callback_query(filters.regex(r"^set:(main|pm|cl|th)(?::(\w+))?$"))
async def settings_cb(client, cq):
    chat = cq.message.chat
    if not (perms.is_sudo(cq.from_user.id) or await perms.is_admin(client, chat.id, cq.from_user.id)):
        return await cq.answer("Only admins can change settings.", show_alert=True)
    which, val = cq.matches[0].group(1), cq.matches[0].group(2)
    if val:
        try:
            if which == "pm" and val in ("everyone", "admins"):
                await database.set_chat(chat.id, play_mode=val)
            elif which == "cl" and val in ("on", "off"):
                await database.set_chat(chat.id, clean=(val == "on"))
            elif which == "th" and val in ("on", "off"):
                await database.set_chat(chat.id, thumb=(val == "on"))
        except Exception:
            traceback.print_exc()
            return await cq.answer("Could not save this setting.", show_alert=True)
    text, kb = await (_panel(chat) if which == "main" else _sub(chat.id, which))
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await cq.answer("Saved" if val else None)
