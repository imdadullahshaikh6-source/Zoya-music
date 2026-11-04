# helpers/assistant.py — assistant (userbot) ko group me bulana
import asyncio
import html

from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import (
    ChatAdminRequired,
    InviteHashExpired,
    InviteRequestSent,
    UserAlreadyParticipant,
    UserNotParticipant,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import bot, userbot
from helpers.fonts import sc
from helpers.strings import t

_joined = set()


def forget(chat_id: int):
    _joined.discard(chat_id)


async def ensure(client, chat, status_msg):
    """(ok, text, markup) return karta hai. status_msg par 'Inviting assistant' dikhata hai."""
    chat_id = chat.id
    if chat_id in _joined:
        return True, "", None
    me = userbot.me
    try:
        member = await client.get_chat_member(chat_id, me.id)
        if member.status == ChatMemberStatus.BANNED:
            return False, banned_text(me), banned_markup()
        if member.status != ChatMemberStatus.LEFT:
            _joined.add(chat_id)
            return True, "", None
    except UserNotParticipant:
        pass
    except Exception:
        pass

    try:
        await status_msg.edit_text(await t(chat_id, "hold_on", bot=bot.me.first_name))
    except Exception:
        pass

    try:
        if chat.username:
            target = chat.username
        else:
            target = await client.export_chat_invite_link(chat_id)
        try:
            await userbot.join_chat(target)
        except InviteRequestSent:
            await client.approve_chat_join_request(chat_id, me.id)
        except UserAlreadyParticipant:
            pass
        _joined.add(chat_id)
        await asyncio.sleep(1)
        return True, "", None
    except ChatAdminRequired:
        return False, sc("make me admin with 'invite users via link' permission, or add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None
    except InviteHashExpired:
        return False, sc("invite link expired. please try again."), None
    except Exception as e:
        return False, sc("failed to add assistant:") + f" <code>{html.escape(str(e))}</code>\n" + sc("add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None


def banned_text(me) -> str:
    return (
        f"{sc('assistant is banned in this chat.')}\n"
        f"{sc('id')}: <code>{me.id}</code>\n"
        f"{sc('name')}: <code>{html.escape(me.first_name or '')}</code>\n"
        f"{sc('please unban the assistant and try again.')}"
    )


def banned_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Unban Assistant", callback_data="unban_assistant")]])
