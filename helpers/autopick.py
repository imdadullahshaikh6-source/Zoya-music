# helpers/autopick.py — autoplay ke liye agla gaana chunna
#
# Pehle problem:  "Tu Hai Kahan by AUR (Official)" ke baad usi gaane ka "feat. ZAYN" / "(Lyrics)" upload bajta tha.
# Ab:
#   1) YouTube "Mix" (list=RD<video id>) se us gaane jaise gaane lete hain (same vibe / artists / language)
#   2) Jo gaana pehle baj chuka (ya queue me hai) uska koi bhi doosra upload / remix / lyrics / slowed => skip
#   3) Jukebox, mashup, 1 hour, shorts, interview jaisa junk => skip
#   4) Current gaana calm/sad/romantic hai to party/dj wale se bachna, aur party hai to sad wale se (mood match)
#   5) Kuch na mile to purana ytdl.related() (usme bhi duplicate skip hota hai)
import asyncio
import os
import random
import re
from collections import defaultdict, deque

import config
from helpers import ytdl

# ───────────────────────── title ko "gaane ke naam" me badalna ─────────────────────────
_BRACKETS = re.compile(r"[\(\[\{【（][^\)\]\}】）]*[\)\]\}】）]")
_FEAT = re.compile(r"\b(?:feat|ft|featuring)\b.*$")
_SPLIT = re.compile(r"[^\w]+", re.UNICODE)

_NOISE = set(
    """official video music audio lyrics lyrical lyric full song songs hd 4k 8k new latest version remix remixed
    remastered slowed reverb sped up lofi lo fi acoustic cover live unplugged visualizer visualiser studio original
    soundtrack ost from the movie film mv teaser out now with by feat ft featuring prod produced presents presented
    and x vs hq best top hit hits mix edit extended bass boosted 8d 3d reprise""".split()
)


def tokens(title: str, channel: str = "") -> list:
    t = _BRACKETS.sub(" ", (title or "").lower())
    t = _FEAT.sub(" ", t)
    words = [w for w in _SPLIT.split(t) if w]
    chan = {w for w in _SPLIT.split((channel or "").lower()) if w} - _NOISE
    out = [w for w in words if w not in _NOISE]
    base = [w for w in out if w not in chan] or out
    ascii_only = [w for w in base if re.search(r"[a-z0-9]", w)]
    return ascii_only or base


def same_song(a: list, b: list) -> bool:
    A, B = set(a), set(b)
    if not A or not B:
        return False
    inter = len(A & B)
    if min(len(A), len(B)) <= 2:  # chhote naam: lagbhag barabar hone chahiye
        return inter / len(A | B) >= 0.75
    return inter / min(len(A), len(B)) >= 0.7


# ───────────────────────── junk + mood ─────────────────────────
_JUNK = re.compile(
    r"jukebox|non[- ]?stop|mashup|megamix|\b\d+\s*(?:hour|hours|hr|hrs)\b|full album|playlist|reaction|interview|"
    r"trailer|teaser|behind the scenes|\bbts\b|making of|podcast|#shorts|\bshorts\b|ringtone|karaoke|tutorial|"
    r"\bnews\b|vlog|24/7|live ?stream",
    re.I,
)

_CALM = set(
    """sad dard bewafa bewafai judai judaai tanha tanhai yaad yaadein yaadon aansu rona broken heartbreak heartbroken
    emotional breakup alvida gham intezaar intezar lofi lo fi slowed reverb acoustic unplugged sufi ghazal soulful
    romantic ishq mohabbat pyaar pyar love sukoon chill""".split()
)
_ENERGY = set(
    """party dance club dj bass bhangra rap drill gym workout edm trap masti dhol banger hype remix item dhamaka
    anthem swag""".split()
)


def mood(title: str, channel: str = ""):
    words = set(_SPLIT.split(f"{title} {channel}".lower()))
    calm, energy = len(words & _CALM), len(words & _ENERGY)
    if calm > energy:
        return "calm"
    if energy > calm:
        return "energy"
    return None


# ───────────────────────── chat-wise yaad (kya baj chuka) ─────────────────────────
_played = defaultdict(lambda: deque(maxlen=40))  # chat_id -> [token lists]


def note_played(chat_id: int, track):
    _played[chat_id].append(tokens(getattr(track, "title", ""), getattr(track, "channel", "")))


def forget(chat_id: int):
    _played.pop(chat_id, None)


def _is_repeat(chat_id: int, extra: list, title: str, channel: str) -> bool:
    tk = tokens(title, channel)
    return any(same_song(tk, old) for old in list(_played[chat_id]) + extra)


def _bad_length(duration) -> bool:
    if not duration:
        return False  # pata nahi -> baad me asli Track se dobara check hoga
    limit = min(getattr(config, "DURATION_LIMIT_MIN", 10) * 60, 12 * 60)
    return duration < 80 or duration > limit


def _ok(chat_id, extra, title, channel, duration) -> bool:
    return not (_JUNK.search(title or "") or _bad_length(duration) or _is_repeat(chat_id, extra, title, channel))


# ───────────────────────── candidates (YouTube Mix) ─────────────────────────
def _flat(url: str, limit: int) -> list:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": False,
        "playlistend": limit,
        "ignoreerrors": True,
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:github"],
    }
    if os.path.isfile("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []
    for e in (info or {}).get("entries") or []:
        if e and e.get("id"):
            out.append(
                {
                    "id": e["id"],
                    "title": e.get("title") or "",
                    "duration": e.get("duration"),
                    "channel": e.get("channel") or e.get("uploader") or "",
                }
            )
    return out


async def _candidates(current) -> list:
    vid = getattr(current, "vid", None)
    urls = []
    if vid:
        urls += [f"https://www.youtube.com/watch?v={vid}&list=RD{vid}", f"https://www.youtube.com/playlist?list=RD{vid}"]
    chan = getattr(current, "channel", "") or ""
    if chan:
        urls.append(f"ytsearch20:{chan} songs")
    for u in urls:
        try:
            got = await asyncio.wait_for(asyncio.to_thread(_flat, u, 40), 15)
        except Exception as e:
            print(f"[autopick] candidates failed ({u[:60]}): {e!r}")
            continue
        if len(got) >= 3:
            return got
    return []


def _score(i: int, cur_mood, cur_channel: str, c: dict) -> float:
    s = -0.1 * i + random.uniform(0, 0.4)  # YouTube ka order + thoda variety
    m = mood(c["title"], c["channel"])
    if cur_mood and m:
        s += 3 if m == cur_mood else -4
    if cur_channel and c["channel"] and c["channel"].lower() == cur_channel.lower():
        s += 0.5  # same artist ka doosra gaana thoda pasand
    return s


# ───────────────────────── main entry ─────────────────────────
async def pick(chat_id: int, current, history, queue_titles=()):
    """Agla autoplay Track (ya None). current = abhi baj raha/baja hua track."""
    extra = [tokens(t) for t in queue_titles]
    cur_title = getattr(current, "title", "")
    cur_chan = getattr(current, "channel", "") or ""
    cur_mood = mood(cur_title, cur_chan)
    tried = set(history or ())

    try:
        cands = await _candidates(current)
    except Exception as e:
        print(f"[autopick] {e!r}")
        cands = []

    pool = [c for c in cands if c["id"] not in tried and _ok(chat_id, extra, c["title"], c["channel"], c["duration"])]
    pool.sort(key=lambda c: -_score(cands.index(c), cur_mood, cur_chan, c))
    print(f"[autopick] chat={chat_id} mood={cur_mood} candidates={len(cands)} usable={len(pool)}")

    for c in pool[:3]:
        try:
            tr = await asyncio.wait_for(ytdl.get_track(f"https://www.youtube.com/watch?v={c['id']}", False), 20)
        except Exception as e:
            print(f"[autopick] get_track failed: {e!r}")
            continue
        if tr and _ok(chat_id, extra, tr.title, getattr(tr, "channel", ""), getattr(tr, "duration", 0)):
            print(f"[autopick] picked: {tr.title!r}")
            return tr
        tried.add(c["id"])

    # fallback: purana related(), duplicate nikle to agla maango
    last = None
    hist = set(tried)
    for _ in range(4):
        try:
            tr = await asyncio.wait_for(ytdl.related(current, hist), 30)
        except Exception as e:
            print(f"[autopick] related failed: {e!r}")
            break
        if not tr:
            break
        last = tr
        if _ok(chat_id, extra, tr.title, getattr(tr, "channel", ""), getattr(tr, "duration", 0)):
            return tr
        if tr.vid:
            hist.add(tr.vid)
    return last  # sab duplicate nikle to bhi kuch to bajao (music band nahi hona chahiye)
