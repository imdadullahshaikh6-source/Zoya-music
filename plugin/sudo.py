# plugin/sudo.py — /addsudo /delsudo /sudolist /broadcast /restart
import asyncio
import html
import os
import sys

from pyrogram import Client
from pyrogram.errors import FloodWait

import config
import database
import state
from helpers import perms
from helpers.filters import cmd
from helpers.fonts import sc


def _owner(message) -> bool:
    return bool(message.from_user) and message.from_user.id == config.OWNER_ID


def _sudo(message) -> bool:
    return bool(message.from_user) and perms.is_sudo(message.from_user.id)


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


@Client.on_message(cmd("addsudo"))
async def addsudo(client, message):
    if not _owner(message):
        return await message.reply_text("❌ " + sc("owner only."))
    u = await _target(client, message)
    if not u:
        return await message.reply_text(sc("reply to a user, or give a username / id."))
    state.SUDOERS.add(u.id)
    await database.sudo_add(u.id)
    await message.reply_text(f"✅ <a href='tg://user?id={u.id}'>{html.escape(u.first_name or 'User')}</a> {sc('added to sudo users.')}")


@Client.on_message(cmd("delsudo"))
async def delsudo(client, message):
    if not _owner(message):
        return await message.reply_text("❌ " + sc("owner only."))
    u = await _target(client, message)
    if not u:
        return await message.reply_text(sc("reply to a user, or give a username / id."))
    state.SUDOERS.discard(u.id)
    await database.sudo_del(u.id)
    await message.reply_text(f"✅ <a href='tg://user?id={u.id}'>{html.escape(u.first_name or 'User')}</a> {sc('removed from sudo users.')}")


@Client.on_message(cmd("sudolist"))
async def sudolist(client, message):
    if not _sudo(message):
        return await message.reply_text("❌ " + sc("sudo users only."))
    lines = [f"⚙️ <u>{sc('sudo users')}</u>\n", f"👑 {sc('owner')}: <code>{config.OWNER_ID}</code>"]
    for i, uid in enumerate(state.SUDOERS, 1):
        lines.append(f"{i}. <code>{uid}</code>")
    await message.reply_text("\n".join(lines))


@Client.on_message(cmd("broadcast"))
async def broadcast(client, message):
    if not _sudo(message):
        return await message.reply_text("❌ " + sc("sudo users only."))
    args = message.command[1:]
    mode = "all"
    if args and args[0] in ("-users", "-chats", "-all"):
        mode = args[0][1:]
        args = args[1:]
    r = message.reply_to_message
    text = " ".join(args).strip()
    if not r and not text:
        return await message.reply_text(sc("usage:") + " <code>/broadcast [-users / -chats / -all] [text]</code> " + sc("or reply to a message."))
    targets = []
    if mode in ("users", "all"):
        targets += await database.all_users()
    if mode in ("chats", "all"):
        targets += await database.all_chats()
    status = await message.reply_text(f"📣 {sc('broadcasting to')} {len(targets)} {sc('chats...')}")
    ok = fail = 0
    for cid in targets:
        try:
            if r:
                await r.copy(cid)
            else:
                await client.send_message(cid, text, disable_web_page_preview=True)
            ok += 1
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await (r.copy(cid) if r else client.send_message(cid, text))
                ok += 1
            except Exception:
                fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ {sc('broadcast done')}\n\n{sc('sent')}: <code>{ok}</code>\n{sc('failed')}: <code>{fail}</code>")


@Client.on_message(cmd("restart"))
async def restart(client, message):
    if not _owner(message):
        return await message.reply_text("❌ " + sc("owner only."))
    await message.reply_text("♻️ " + sc("restarting..."))
    os.execv(sys.executable, [sys.executable] + sys.argv)
