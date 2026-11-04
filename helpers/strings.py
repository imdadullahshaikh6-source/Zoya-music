# helpers/strings.py — /lang (English + Hinglish). Static text Zoya small-caps font me aata hai.
import re

import database
from helpers.fonts import sc

S = {
    "en": {
        "searching": "🔍 Picking the right track...",
        "hold_on": "⏳ Hold on a moment...\n\n🤖 Inviting {bot} assistant to your chat.",
        "usage_play": "ℹ️ Usage: <code>/play [song title, artist or link]</code>\n\n🎵 Supported Platforms:\nYouTube • Spotify",
        "not_found": "❌ Could not find the track. Try another query.",
        "too_long": "❌ This track is longer than the allowed limit ({mins} min).",
        "admins_only": "❌ Only admins and authorized users can use this command.",
        "no_vc": "❌ No active voice chat found. Start a voice chat / video chat in this group first.",
        "muted": "❌ The assistant is muted in the voice chat. Unmute it and try again.",
        "play_err": "❌ Playback error: {err}",
        "added": "✅ Added to queue at #{pos}\n\nTitle: {title}\nDuration: {dur}\nRequested by: {user}",
        "added_many": "✅ Added {n} tracks to queue.",
        "queue_full": "❌ Queue is full ({limit} tracks).",
        "nothing": "ℹ️ The bot isn't currently streaming on voice chat.",
        "paused": "⏸ Stream paused by {user}.",
        "resumed": "▶️ Stream resumed by {user}.",
        "already_paused": "❌ Stream is already paused.",
        "not_paused": "❌ Stream is not paused.",
        "skipped": "⏭ Skipped by {user}.",
        "stopped": "⏹ Stopped by {user}.",
        "seek_ok": "⏩ Seeked to {pos} by {user}.",
        "seek_bad": "❌ You can't seek that far. Current track length is {dur}.",
        "seek_usage": "❌ Usage: /{cmd} [seconds]",
        "loop_set": "🔁 Current song will repeat {n} more time(s).",
        "loop_off": "🔁 Loop disabled.",
        "loop_usage": "❌ Usage: /loop [1-10] (0 = off)",
        "shuffled": "🔀 Queue shuffled.",
        "shuffle_need": "❌ Need at least 2 songs in the queue to shuffle.",
        "autoplay_on": "♾ Autoplay enabled — I'll find related tracks when the queue ends.",
        "autoplay_off": "♾ Autoplay disabled.",
        "ended_queue": "Queue finished.",
        "ended_stop": "Stopped by {user}.",
        "ended_kick": "I was removed from the voice chat.",
        "ended_closed": "The voice chat was closed.",
        "ended_left": "I left the voice chat because I was muted.",
        "group_only": "❌ This command works only in groups.",
    },
}

_TOKEN = re.compile(r"(\{\w+\}|<[^>]+>)")


async def get_lang(chat_id: int) -> str:
    return "en"  # language option hata diya — sirf English


def render(lang: str, key: str, **kw) -> str:
    text = S.get(lang, S["en"]).get(key) or S["en"][key]
    out = []
    in_code = False
    for part in _TOKEN.split(text):
        if part.startswith("{") and part.endswith("}"):
            out.append(str(kw.get(part[1:-1], "")))
        elif part.startswith("<"):
            in_code = part == "<code>" or (in_code and part != "</code>")
            out.append(part)
        else:
            out.append(part if in_code else sc(part))
    return "".join(out)


async def t(chat_id: int, key: str, **kw) -> str:
    return render(await get_lang(chat_id), key, **kw)
