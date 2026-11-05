# helpers/panel.py — "Controls ?" player panel
#
# Pehle sirf ek button aata hai:        [ controls ? ]
# Click karte hi poora panel khulta hai:
#     [ pause | next | end ]
#     [ loop | shuffle | autoplay ]
#     [ back | close ]
# "autoplay" (hamesha blue) dabane par us button ki jagah autoplay ka menu khulta hai:
#     [ enable | disable ]
#     [ back ]
#
# Sabse upar ek progress row hoti hai (click nahi hoti, sirf dikhti hai):
#     -----›--------------        <- chhota arrow, gaana aage badhta hai to arrow bhi aage badhta hai
# Controls kholne ke baad 10s tak kuch na dabao to panel apne aap wapas "controls ?" pe aa jata hai.
#
# Star (save to playlist) button hata diya gaya hai.
import asyncio

import state
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from helpers.buttons import btn

BAR_WIDTH = 20        # progress row me kul kitne characters (arrow samet)
COLLAPSE_AFTER = 10   # controls khulne ke itne second baad (koi use na ho to) wapas band

# chat_id -> {"key": id() of the track whose panel is open, "view": "main" | "autoplay"}
# Track badalte hi (naya now-playing message) panel apne aap collapsed ho jata hai.
_open: dict = {}


def _track_key(st):
    cur = getattr(st, "current", None)
    return id(cur) if cur is not None else None


def is_open(chat_id: int) -> bool:
    rec = _open.get(chat_id)
    return rec is not None and rec["key"] is not None and rec["key"] == _track_key(state.get(chat_id))


def open_panel(chat_id: int, view: str = "main") -> None:
    _open[chat_id] = {"key": _track_key(state.get(chat_id)), "view": view}


def close_panel(chat_id: int) -> None:
    _open.pop(chat_id, None)


def view_of(chat_id: int) -> str:
    rec = _open.get(chat_id)
    return rec["view"] if rec else "main"


# ───────────────────────── progress row ─────────────────────────
_prog: dict = {}  # chat_id -> 0.0..1.0 (gaana kitna ho chuka)


def set_progress(chat_id: int, frac: float) -> None:
    _prog[chat_id] = max(0.0, min(1.0, float(frac)))


def bar_pos(chat_id: int) -> int:
    return int(_prog.get(chat_id, 0.0) * (BAR_WIDTH - 1))


def bar_row(chat_id: int) -> list:
    pos = bar_pos(chat_id)
    text = "-" * pos + "›" + "-" * (BAR_WIDTH - 1 - pos)
    # click nahi hota: pl:noop sirf chupchaap answer deta hai
    return [InlineKeyboardButton(text, callback_data="pl:noop")]


# ───────────────────────── auto-collapse (10s) ─────────────────────────
_timers: dict = {}


def cancel_collapse(chat_id: int) -> None:
    task = _timers.pop(chat_id, None)
    if task and task is not asyncio.current_task():
        task.cancel()


def arm_collapse(chat_id: int, message) -> None:
    """Har click par timer dobara 10s se shuru. 10s koi use nahi -> panel wapas 'controls ?' ban jata hai."""
    cancel_collapse(chat_id)
    _timers[chat_id] = asyncio.ensure_future(_collapse_later(chat_id, message))


async def _collapse_later(chat_id: int, message) -> None:
    try:
        await asyncio.sleep(COLLAPSE_AFTER)
    except asyncio.CancelledError:
        return
    _timers.pop(chat_id, None)
    if not is_open(chat_id):
        return
    close_panel(chat_id)
    try:
        await message.edit_reply_markup(player_keyboard(chat_id))
    except Exception:
        pass  # message delete ho gaya / same markup


# ───────────────────────── keyboards ─────────────────────────
def collapsed_kb(chat_id: int, bar: bool = True) -> InlineKeyboardMarkup:
    rows = [[btn("controls ?", f"pl:ctl:{chat_id}", style="primary")]]
    return InlineKeyboardMarkup(([bar_row(chat_id)] if bar else []) + rows)


def expanded_kb(chat_id: int, bar: bool = True) -> InlineKeyboardMarkup:
    st = state.get(chat_id)
    paused = bool(getattr(st, "paused", False))
    looping = bool(getattr(st, "loop", 0))
    return InlineKeyboardMarkup(
        ([bar_row(chat_id)] if bar else [])
        + [
            [
                btn("resume" if paused else "pause", f"pl:pr:{chat_id}", style="primary"),
                btn("next", f"pl:skip:{chat_id}", style="success"),
                btn("end", f"pl:stop:{chat_id}", style="danger"),
            ],
            [
                btn("loop on" if looping else "loop", f"pl:loop:{chat_id}", style="success" if looping else "primary"),
                btn("shuffle", f"pl:shuffle:{chat_id}", style="primary"),
                btn("autoplay", f"pl:ap:{chat_id}", style="primary"),
            ],
            [
                btn("back", f"pl:back:{chat_id}"),
                btn("close", f"pl:close:{chat_id}", style="danger"),
            ],
        ]
    )


def autoplay_kb(chat_id: int, bar: bool = True) -> InlineKeyboardMarkup:
    on = bool(getattr(state.get(chat_id), "autoplay", False))
    return InlineKeyboardMarkup(
        ([bar_row(chat_id)] if bar else [])
        + [
            [
                btn("enable", f"pl:apon:{chat_id}", style="success" if on else None),
                btn("disable", f"pl:apoff:{chat_id}", style="danger" if not on else None),
            ],
            [btn("back", f"pl:ctl:{chat_id}")],
        ]
    )


def player_keyboard(chat_id: int, *args, bar: bool = True, **kwargs) -> InlineKeyboardMarkup:
    """Drop-in replacement for helpers.player.player_keyboard (bar=False: bina progress row)."""
    if not is_open(chat_id):
        return collapsed_kb(chat_id, bar)
    return autoplay_kb(chat_id, bar) if view_of(chat_id) == "autoplay" else expanded_kb(chat_id, bar)
