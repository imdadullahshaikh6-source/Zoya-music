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
# Star (save to playlist) button hata diya gaya hai.
import state
from pyrogram.types import InlineKeyboardMarkup

from helpers.buttons import btn

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


def collapsed_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("controls ?", f"pl:ctl:{chat_id}", style="primary")]])


def expanded_kb(chat_id: int) -> InlineKeyboardMarkup:
    st = state.get(chat_id)
    paused = bool(getattr(st, "paused", False))
    looping = bool(getattr(st, "loop", 0))
    return InlineKeyboardMarkup(
        [
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


def autoplay_kb(chat_id: int) -> InlineKeyboardMarkup:
    on = bool(getattr(state.get(chat_id), "autoplay", False))
    return InlineKeyboardMarkup(
        [
            [
                btn("enable", f"pl:apon:{chat_id}", style="success" if on else None),
                btn("disable", f"pl:apoff:{chat_id}", style="danger" if not on else None),
            ],
            [btn("back", f"pl:ctl:{chat_id}")],
        ]
    )


def player_keyboard(chat_id: int, *args, **kwargs) -> InlineKeyboardMarkup:
    """Drop-in replacement for helpers.player.player_keyboard."""
    if not is_open(chat_id):
        return collapsed_kb(chat_id)
    return autoplay_kb(chat_id) if view_of(chat_id) == "autoplay" else expanded_kb(chat_id)
