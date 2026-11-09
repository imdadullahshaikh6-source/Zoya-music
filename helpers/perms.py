# helpers/perms.py
import time
from typing import Set

from pyrogram.enums import ChatMembersFilter, ChatMemberStatus

import config
import database
import state

_admin_cache = {}  # chat_id -> (ts, {ids})
TTL = 120


def is_sudo(uid: int) -> bool:
    return bool(uid) and (uid == config.OWNER_ID or uid in state.SUDOERS)


async def get_admins(client, chat_id: int, fresh: bool = False) -> Set[int]:
    c = _admin_cache.get(chat_id)
    if c and not fresh and time.time() - c[0] < TTL:
        return c[1]
    ids = set()
    try:
        async for m in client.get_chat_members(chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
            if m.user:
                ids.add(m.user.id)
    except Exception:
        if c:
            return c[1]
    _admin_cache[chat_id] = (time.time(), ids)
    return ids


def reload(chat_id: int):
    _admin_cache.pop(chat_id, None)


async def is_admin(client, chat_id: int, uid: int) -> bool:
    return uid in await get_admins(client, chat_id)


async def can_control(client, chat_id: int, uid: int) -> bool:
    if is_sudo(uid):
        return True
    if await is_admin(client, chat_id, uid):
        return True
    return await database.is_auth(chat_id, uid)


async def message_can_control(client, message) -> bool:
    # anonymous admin (group ke naam se message)
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if not message.from_user:
        return False
    return await can_control(client, message.chat.id, message.from_user.id)


async def message_is_admin(client, message) -> bool:
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if not message.from_user:
        return False
    uid = message.from_user.id
    return is_sudo(uid) or await is_admin(client, message.chat.id, uid)
