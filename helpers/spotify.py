# helpers/spotify.py — Spotify link -> search queries (YouTube par play hoga)
import base64
import re
import time
from typing import List

import aiohttp

import config

SP_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([A-Za-z0-9]+)")
_tok = {"v": "", "exp": 0.0}


def is_spotify(text: str) -> bool:
    return bool(SP_RE.search(text or ""))


async def _token(session) -> str:
    if _tok["v"] and time.time() < _tok["exp"]:
        return _tok["v"]
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        raise RuntimeError("Spotify keys set nahi hain")
    basic = base64.b64encode(f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}".encode()).decode()
    async with session.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {basic}"},
    ) as r:
        data = await r.json()
    if "access_token" not in data:
        raise RuntimeError("Spotify token error")
    _tok["v"] = data["access_token"]
    _tok["exp"] = time.time() + data.get("expires_in", 3600) - 60
    return _tok["v"]


def _q(item: dict) -> str:
    artists = ", ".join(a["name"] for a in item.get("artists", [])[:2])
    return f"{item['name']} {artists}".strip()


async def resolve(url: str, limit: int = 25) -> List[str]:
    m = SP_RE.search(url)
    if not m:
        raise RuntimeError("Invalid Spotify link")
    kind, sid = m.groups()
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {await _token(s)}"}
        if kind == "track":
            async with s.get(f"https://api.spotify.com/v1/tracks/{sid}", headers=h) as r:
                d = await r.json()
            if "name" not in d:
                raise RuntimeError("Spotify track nahi mila")
            return [_q(d)]
        if kind == "album":
            async with s.get(f"https://api.spotify.com/v1/albums/{sid}/tracks?limit={limit}", headers=h) as r:
                d = await r.json()
            return [_q(i) for i in d.get("items", [])]
        async with s.get(f"https://api.spotify.com/v1/playlists/{sid}/tracks?limit={limit}", headers=h) as r:
            d = await r.json()
        out = []
        for i in d.get("items", []):
            t = i.get("track")
            if t and t.get("name"):
                out.append(_q(t))
        if not out:
            raise RuntimeError("Spotify playlist khali ya private hai")
        return out
