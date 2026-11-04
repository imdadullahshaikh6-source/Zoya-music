# helpers/assistant.py — assistant (userbot) ko group me bulana
import asyncio
import html
import traceback
from datetime import datetime, timedelta

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


async def _assistant_is_member(chat_id: int) -> bool:
    """Assistant ki taraf se check (zyada bharosemand)."""
    try:
        m = await userbot.get_chat_member(chat_id, "me")
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except Exception:
        return False


async def _make_link(client, chat_id: int) -> str:
    """Naya single-use link (primary link revoke nahi hota, join-request group me bhi seedha join)."""
    try:
        link = await client.create_chat_invite_link(
            chat_id,
            name="Zoya assistant",
            expire_date=datetime.utcnow() + timedelta(minutes=10),
            member_limit=1,
        )
        return link.invite_link
    except ChatAdminRequired:
        raise
    except Exception as e:
        print(f"[assistant] create_chat_invite_link failed: {e!r} — export_chat_invite_link try kar raha hoon")
        return await client.export_chat_invite_link(chat_id)


async def ensure(client, chat, status_msg):
    """(ok, text, markup). status_msg par 'Inviting assistant' dikhata hai."""
    chat_id = chat.id
    if chat_id in _joined:
        return True, "", None
    me = userbot.me

    # 1) banned?  (bot admin ho to status dikhta hai)
    try:
        member = await client.get_chat_member(chat_id, me.id)
        if member.status == ChatMemberStatus.BANNED:
            return False, banned_text(me), banned_markup()
    except Exception:
        pass

    # 2) pehle se member?
    if await _assistant_is_member(chat_id):
        _joined.add(chat_id)
        return True, "", None

    try:
        await status_msg.edit_text(await t(chat_id, "hold_on", bot=bot.me.first_name))
    except Exception:
        pass

    # 3) join
    last_err = None
    for attempt in range(2):
        link = None
        try:
            target = chat.username if chat.username else (link := await _make_link(client, chat_id))
            try:
                await userbot.join_chat(target)
            except InviteRequestSent:
                await client.approve_chat_join_request(chat_id, me.id)
            except UserAlreadyParticipant:
                pass
            _joined.add(chat_id)
            await asyncio.sleep(1)
            if link:
                try:
                    await client.revoke_chat_invite_link(chat_id, link)
                except Exception:
                    pass
            return True, "", None
        except ChatAdminRequired:
            return False, sc("make me admin with 'invite users via link' permission, or add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None
        except InviteHashExpired as e:
            last_err = e
            print(f"[assistant] invite hash expired (attempt {attempt + 1}), retrying")
            await asyncio.sleep(1)
            continue
        except Exception as e:
            traceback.print_exc()
            return False, sc("failed to add assistant:") + f" <code>{html.escape(str(e))}</code>\n" + sc("add the assistant manually:") + f" @{html.escape(me.username or str(me.id))}", None

    print(f"[assistant] join failed: {last_err!r}")
    return False, sc("could not add the assistant automatically. please add it to the group manually:") + f" @{html.escape(me.username or str(me.id))}", None


def banned_text(me) -> str:
    return (
        f"{sc('assistant is banned in this chat.')}\n"
        f"{sc('id')}: <code>{me.id}</code>\n"
        f"{sc('name')}: <code>{html.escape(me.first_name or '')}</code>\n"
        f"{sc('please unban the assistant and try again.')}"
    )


def banned_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Unban Assistant", callback_data="unban_assistant")]])
