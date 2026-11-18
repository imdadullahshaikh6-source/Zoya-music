# database.py — MongoDB (motor). Mongo na ho to in-memory fallback (restart par data jayega).
import time
import secrets
from typing import List, Optional

import config

_client = None
_db = None

# in-memory fallback
_mem = {"chats": {}, "users": {}, "sudo": set(), "playlists": {}}
_chat_cache = {}


def connect():
    global _client, _db
    if not config.MONGO_DB_URI:
        print("⚠️ MONGO_DB_URI missing — in-memory DB use ho raha hai")
        return False
    from motor.motor_asyncio import AsyncIOMotorClient
    _client = AsyncIOMotorClient(config.MONGO_DB_URI, serverSelectionTimeoutMS=8000)
    _db = _client.ZoyaMusic
    return True


def ok() -> bool:
    return _db is not None


async def ping_ms() -> Optional[float]:
    if not ok():
        return None
    t = time.perf_counter()
    try:
        await _client.admin.command("ping")
    except Exception:
        return None
    return (time.perf_counter() - t) * 1000


# ───────────────────────── chats ─────────────────────────
DEFAULT_CHAT = {"play_mode": "everyone", "auth": [], "clean": False, "thumb": True}


async def get_chat(chat_id: int) -> dict:
    if chat_id in _chat_cache:
        return _chat_cache[chat_id]
    doc = None
    if ok():
        doc = await _db.chats.find_one({"_id": chat_id})
    else:
        doc = _mem["chats"].get(chat_id)
    data = dict(DEFAULT_CHAT)
    data["auth"] = []
    if doc:
        data.update({k: v for k, v in doc.items() if k != "_id"})
    _chat_cache[chat_id] = data
    return data


async def set_chat(chat_id: int, **kw):
    data = await get_chat(chat_id)
    data.update(kw)
    if ok():
        await _db.chats.update_one({"_id": chat_id}, {"$set": kw}, upsert=True)
    else:
        _mem["chats"][chat_id] = data


async def add_served_chat(chat_id: int):
    if chat_id in _chat_cache:
        return
    await get_chat(chat_id)
    if ok():
        await _db.chats.update_one({"_id": chat_id}, {"$setOnInsert": {"served": True}}, upsert=True)
    else:
        _mem["chats"].setdefault(chat_id, dict(_chat_cache[chat_id]))


async def add_served_user(user_id: int):
    if ok():
        await _db.users.update_one({"_id": user_id}, {"$setOnInsert": {"t": time.time()}}, upsert=True)
    else:
        _mem["users"][user_id] = True


async def all_chats() -> List[int]:
    if ok():
        return [d["_id"] async for d in _db.chats.find({}, {"_id": 1}) if d["_id"] < 0]
    return [c for c in _mem["chats"] if c < 0]


async def all_users() -> List[int]:
    if ok():
        return [d["_id"] async for d in _db.users.find({}, {"_id": 1})]
    return list(_mem["users"])


async def counts():
    if ok():
        chats = await _db.chats.count_documents({"_id": {"$lt": 0}})
        users = await _db.users.count_documents({})
        return chats, users
    return len([c for c in _mem["chats"] if c < 0]), len(_mem["users"])


# ───────────────────────── auth users ─────────────────────────
async def auth_add(chat_id: int, user_id: int):
    data = await get_chat(chat_id)
    if user_id not in data["auth"]:
        data["auth"].append(user_id)
        await set_chat(chat_id, auth=data["auth"])


async def auth_remove(chat_id: int, user_id: int) -> bool:
    data = await get_chat(chat_id)
    if user_id in data["auth"]:
        data["auth"].remove(user_id)
        await set_chat(chat_id, auth=data["auth"])
        return True
    return False


async def auth_list(chat_id: int) -> List[int]:
    return list((await get_chat(chat_id))["auth"])


async def is_auth(chat_id: int, user_id: int) -> bool:
    return user_id in (await get_chat(chat_id))["auth"]


# ───────────────────────── sudo ─────────────────────────
async def sudo_load() -> List[int]:
    if ok():
        return [d["_id"] async for d in _db.sudo.find({})]
    return list(_mem["sudo"])


async def sudo_add(uid: int):
    if ok():
        await _db.sudo.update_one({"_id": uid}, {"$set": {"t": time.time()}}, upsert=True)
    else:
        _mem["sudo"].add(uid)


async def sudo_del(uid: int):
    if ok():
        await _db.sudo.delete_one({"_id": uid})
    else:
        _mem["sudo"].discard(uid)


# ───────────────────────── playlists ─────────────────────────
MAX_PLAYLISTS = 10
MAX_PL_TRACKS = 100


async def pl_list(user_id: int) -> List[dict]:
    if ok():
        return [d async for d in _db.playlists.find({"user_id": user_id})]
    return [p for p in _mem["playlists"].values() if p["user_id"] == user_id]


async def pl_create(user_id: int, name: str) -> Optional[dict]:
    if len(await pl_list(user_id)) >= MAX_PLAYLISTS:
        return None
    pid = secrets.token_hex(3)
    doc = {"_id": pid, "user_id": user_id, "name": name[:40], "tracks": []}
    if ok():
        await _db.playlists.insert_one(doc)
    else:
        _mem["playlists"][pid] = doc
    return doc


async def pl_get(pid: str) -> Optional[dict]:
    if ok():
        return await _db.playlists.find_one({"_id": pid})
    return _mem["playlists"].get(pid)


async def pl_delete(pid: str, user_id: int) -> bool:
    doc = await pl_get(pid)
    if not doc or doc["user_id"] != user_id:
        return False
    if ok():
        await _db.playlists.delete_one({"_id": pid})
    else:
        _mem["playlists"].pop(pid, None)
    return True


async def pl_add_track(pid: str, user_id: int, track: dict) -> str:
    doc = await pl_get(pid)
    if not doc or doc["user_id"] != user_id:
        return "notfound"
    if len(doc["tracks"]) >= MAX_PL_TRACKS:
        return "full"
    if any(t["webpage"] == track["webpage"] for t in doc["tracks"]):
        return "dup"
    if ok():
        await _db.playlists.update_one({"_id": pid}, {"$push": {"tracks": track}})
    else:
        doc["tracks"].append(track)
    return "ok"
