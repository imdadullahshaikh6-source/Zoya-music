# helpers/buttons.py — coloured (Bot API 9.4 style) + small-caps text-only buttons
#
#   btn("pause", "pl:pr:123", style="primary")   -> blue
#   btn("next",  "pl:skip:123", style="success") -> green
#   btn("end",   "pl:stop:123", style="danger")  -> red
#   btn("back",  "help:main")                    -> default (grey)
#
# Label is always passed through sc() so every button uses the same font as the rest of the repo.
# No emojis anywhere. If your pyrogram fork is too old to know `style`, the button silently
# falls back to a normal one (nothing crashes).
from pyrogram.types import InlineKeyboardButton

from helpers.fonts import sc

try:  # kurigram / pyrogram forks with enums.ButtonStyle
    from pyrogram.enums import ButtonStyle as _Style
except Exception:  # kittygram / srigram take plain strings: style="success"
    _Style = None


def _style(name):
    if not name:
        return None
    if _Style is not None:
        return getattr(_Style, name.upper(), None)
    return name


def btn(text: str, callback_data: str = None, url: str = None, style: str = None) -> InlineKeyboardButton:
    kw = {"text": sc(text)}
    if callback_data is not None:
        kw["callback_data"] = callback_data
    if url:
        kw["url"] = url
    val = _style(style)
    if val is not None:
        try:
            return InlineKeyboardButton(**kw, style=val)
        except TypeError:  # old fork: no `style` argument
            pass
    return InlineKeyboardButton(**kw)
