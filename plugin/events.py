# plugin/events.py — stream end / voice chat closed / kicked events (py-tgcalls)
from pytgcalls import filters as fl

import state
from core import bot, call_py
from helpers import player
from helpers.fonts import sc

try:
    from pytgcalls.types import ChatUpdate
except Exception:  # pragma: no cover
    ChatUpdate = None


def _stream_end_filter():
    f = fl.stream_end
    try:
        import inspect
        if inspect.isfunction(f) or inspect.isclass(f):
            return f()
    except Exception:
        pass
    return f


@call_py.on_update(_stream_end_filter())
async def _stream_end(_, update):
    chat_id = update.chat_id
    notice = None
    try:
        # autoplay on hai (aur loop nahi) -> related track dhoondhne me time lagta hai, user ko batao
        st = state.get(chat_id)
        if getattr(st, "autoplay", False) and not getattr(st, "loop", 0):
            try:
                notice = await bot.send_message(chat_id, f"<i>{sc('picking a next track...')}</i>")
            except Exception:
                notice = None
        await player.on_stream_end(chat_id)
    except Exception as e:
        print(f"stream_end error: {e}")
    finally:
        if notice:
            try:
                await notice.delete()
            except Exception:
                pass


def _status_mask(names):
    mask = None
    for n in names:
        v = getattr(ChatUpdate.Status, n, None)
        if v is not None:
            mask = v if mask is None else mask | v
    return mask


if ChatUpdate is not None:
    _closed = _status_mask(["CLOSED_VOICE_CHAT", "DISCARDED_CALL"])
    _kicked = _status_mask(["KICKED", "LEFT_KICKED"])
    _left = _status_mask(["LEFT_CALL"])

    if _closed is not None:
        @call_py.on_update(fl.chat_update(_closed))
        async def _closed_vc(_, update):
            await player.on_call_closed(update.chat_id, "ended_closed")

    if _kicked is not None:
        @call_py.on_update(fl.chat_update(_kicked))
        async def _kicked_vc(_, update):
            await player.on_call_closed(update.chat_id, "ended_kick")

    if _left is not None:
        @call_py.on_update(fl.chat_update(_left))
        async def _left_vc(_, update):
            await player.on_call_closed(update.chat_id, "ended_left")
          
