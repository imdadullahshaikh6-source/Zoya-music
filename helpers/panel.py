# helpers/panel.py — "Controls ?" player panel
#
# Pehle sirf ek button aata hai:        [ controls ? ]
# Click karte hi poora panel khulta hai:
#     [ pause | next | end ]
#     [ loop | shuffle | autoplay ]
#     [ back | close ]
#
# Star (save to playlist) button hata diya gaya hai, uski jagah autoplay on/off hai.
import state
from pyrogram.types import InlineKeyboardMarkup

from helpers.buttons import btn

# chat_id -> id() of the track whose panel is currently expanded.
# Track badalte hi (naya now-playing message) panel apne aap collapsed ho jata hai.
_open: dict = {}


def _track_key(st):
    cur = getattr(st, "current", None)
    return id(cur) if cur is not None else None


def is_open(chat_id: int) -> bool:
    key = _open.get(chat_id)
    return key is not None and key == _track_key(state.get(chat_id))


def open_panel(chat_id: int) -> None:
    _open[chat_id] = _track_key(state.get(chat_id))


def close_panel(chat_id: int) -> None:
    _open.pop(chat_id, None)


def collapsed_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("controls ?", f"pl:ctl:{chat_id}", style="primary")]])


def expanded_kb(chat_id: int) -> InlineKeyboardMarkup:
    st = state.get(chat_id)
    paused = bool(getattr(st, "paused", False))
    looping = bool(getattr(st, "loop", 0))
    auto = bool(getattr(st, "autoplay", False))
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
                btn("autoplay on" if auto else "autoplay off", f"pl:ap:{chat_id}", style="success" if auto else "primary"),
            ],
            [
                btn("back", f"pl:back:{chat_id}"),
                btn("close", f"pl:close:{chat_id}", style="danger"),
            ],
        ]
    )


def player_keyboard(chat_id: int, *args, **kwargs) -> InlineKeyboardMarkup:
    """Drop-in replacement for helpers.player.player_keyboard."""
    return expanded_kb(chat_id) if is_open(chat_id) else collapsed_kb(chat_id)
