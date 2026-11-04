# helpers/nopreview.py — bot ke messages me link preview (YouTube card) band.
# Title ka hyperlink waisa hi rahega, bas neeche wala YouTube preview card nahi banega.
# Pyrogram ke dono versions ke liye kaam karta hai:
#   naye forks  -> link_preview_options=LinkPreviewOptions(is_disabled=True)
#   purane      -> disable_web_page_preview=True
import functools
import inspect

from pyrogram import Client


def _wrap(name: str) -> None:
    orig = getattr(Client, name, None)
    if orig is None:
        return
    try:
        params = list(inspect.signature(orig).parameters)
    except (TypeError, ValueError):
        return
    if "link_preview_options" in params:
        try:
            from pyrogram.types import LinkPreviewOptions
        except Exception:
            return
        key, val = "link_preview_options", LinkPreviewOptions(is_disabled=True)
    elif "disable_web_page_preview" in params:
        key, val = "disable_web_page_preview", True
    else:
        return
    pos = params.index(key) - 1  # self hata ke position (agar kisi ne positional pass kiya ho)

    @functools.wraps(orig)
    async def wrapper(self, *args, **kwargs):
        if len(args) <= pos and kwargs.get(key) is None:
            kwargs[key] = val
        return await orig(self, *args, **kwargs)

    setattr(Client, name, wrapper)


for _n in ("send_message", "edit_message_text"):
    _wrap(_n)
