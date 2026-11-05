# plugin/controls.py — pause/resume/skip/stop/seek/seekback/loop/shuffle/autoplay + player buttons
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup

import state
from core import userbot
from helpers import assistant, panel, perms, player
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import fmt_time, sc
from helpers.strings import t


async def _guard(client, message) -> bool:
    if not await perms.message_can_control(client, message):
        await message.reply_text(await t(message.chat.id, "admins_only"), reply_markup=player.CLOSE_KB)
        return False
    return True


async def _reply_key(message, key, **kw):
    await message.reply_text(await t(message.chat.id, key, **kw), reply_markup=player.CLOSE_KB)


@Client.on_message(cmd("pause") & filters.group)
async def pause_cmd(client, message):
    if not await _guard(client, message):
        return
    k = await player.do_pause(message.chat.id)
    await _reply_key(message, "paused" if k == "ok" else k, user=player.mention(message.from_user))


@Client.on_message(cmd("resume") & filters.group)
async def resume_cmd(client, message):
    if not await _guard(client, message):
        return
    k = await player.do_resume(message.chat.id)
    await _reply_key(message, "resumed" if k == "ok" else k, user=player.mention(message.from_user))


@Client.on_message(cmd(["skip", "next"]) & filters.group)
async def skip_cmd(client, message):
    if not await _guard(client, message):
        return
    k = await player.do_skip(message.chat.id)
    if k != "ok":
        await _reply_key(message, k)


@Client.on_message(cmd(["stop", "end"]) & filters.group)
async def stop_cmd(client, message):
    if not await _guard(client, message):
        return
    k = await player.do_stop(message.chat.id, player.mention(message.from_user))
    if k != "ok":
        await _reply_key(message, k)


async def _seek(client, message, sign):
    if not await _guard(client, message):
        return
    name = message.command[0].lower()
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await _reply_key(message, "seek_usage", cmd=name)
    k, pos = await player.do_seek(message.chat.id, sign * int(message.command[1]))
    if k == "ok":
        return await _reply_key(message, "seek_ok", pos=fmt_time(pos), user=player.mention(message.from_user))
    st = state.get(message.chat.id)
    await _reply_key(message, k, dur=fmt_time(st.current.duration) if st.current else "")


@Client.on_message(cmd("seek") & filters.group)
async def seek_cmd(client, message):
    await _seek(client, message, 1)


@Client.on_message(cmd("seekback") & filters.group)
async def seekback_cmd(client, message):
    await _seek(client, message, -1)


@Client.on_message(cmd("loop") & filters.group)
async def loop_cmd(client, message):
    if not await _guard(client, message):
        return
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await _reply_key(message, "loop_usage")
    n = int(message.command[1])
    if n > 10:
        return await _reply_key(message, "loop_usage")
    k = player.do_loop(message.chat.id, n)
    await _reply_key(message, k, n=n)


@Client.on_message(cmd("shuffle") & filters.group)
async def shuffle_cmd(client, message):
    if not await _guard(client, message):
        return
    await _reply_key(message, player.do_shuffle(message.chat.id))


@Client.on_message(cmd("autoplay") & filters.group)
async def autoplay_cmd(client, message):
    if not await _guard(client, message):
        return
    st = state.get(message.chat.id)
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("on", "enable", "yes"):
        st.autoplay = True
        return await _reply_key(message, "autoplay_on")
    if arg in ("off", "disable", "no"):
        st.autoplay = False
        return await _reply_key(message, "autoplay_off")
    text, kb = _ap_panel(message.chat.id)
    await message.reply_text(text, reply_markup=kb)


def _ap_panel(chat_id: int):
    """/autoplay ka settings panel (thumbnail settings jaisa): enable / disable."""
    on = bool(state.get(chat_id).autoplay)
    text = (
        f"<u>{sc('autoplay settings')}</u>\n\n"
        f"{sc('automatically play a related track when the queue ends.')}\n\n"
        f"<i>{sc('current status')}:</i> <b>{sc('enabled') if on else sc('disabled')}</b>"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                btn("enable", "apm:on", style="success" if on else None),
                btn("disable", "apm:off", style="danger" if not on else None),
            ],
            [btn("close", "x", style="danger")],
        ]
    )
    return text, kb


@Client.on_callback_query(filters.regex(r"^apm:(on|off)$"))
async def autoplay_panel_cb(client, cq):
    chat_id = cq.message.chat.id
    if not await perms.can_control(client, chat_id, cq.from_user.id):
        return await cq.answer("Only admins / authorized users can use these buttons.", show_alert=True)
    state.get(chat_id).autoplay = cq.matches[0].group(1) == "on"
    text, kb = _ap_panel(chat_id)
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass  # message not modified (same button dobara dabaya)
    await cq.answer("Autoplay enabled" if state.get(chat_id).autoplay else "Autoplay disabled")


# ── inline player buttons ──
async def _refresh(cq, chat_id):
    try:
        await cq.message.edit_reply_markup(panel.player_keyboard(chat_id))
    except Exception:
        pass  # message not modified / deleted
    # panel khula hai -> 10s ka timer dobara shuru (koi use na ho to wapas "controls ?"); band hai -> timer hata do
    if panel.is_open(chat_id):
        panel.arm_collapse(chat_id, cq.message)
    else:
        panel.cancel_collapse(chat_id)


@Client.on_callback_query(filters.regex(r"^pl:noop$"))
async def progress_row_cb(client, cq):
    await cq.answer()  # progress row sirf dikhne ke liye hai


@Client.on_callback_query(filters.regex(r"^pl:(pr|skip|stop|loop|shuffle|close|ctl|back|ap|apon|apoff):(-?\d+)$"))
async def player_buttons(client, cq):
    action, chat_id = cq.matches[0].group(1), int(cq.matches[0].group(2))

    # panel kholna / band karna sab ke liye allowed (sirf dikhata hai), actions neeche guard hote hain
    if action == "ctl":
        panel.open_panel(chat_id)
        await _refresh(cq, chat_id)
        return await cq.answer()
    if action == "back":
        panel.close_panel(chat_id)
        await _refresh(cq, chat_id)
        return await cq.answer()

    if not await perms.can_control(client, chat_id, cq.from_user.id):
        return await cq.answer("Only admins / authorized users can use these buttons.", show_alert=True)
    who = player.mention(cq.from_user)
    if action == "close":
        panel.close_panel(chat_id)
        panel.cancel_collapse(chat_id)
        try:
            await cq.message.delete()
        except Exception:
            pass
        return
    st = state.get(chat_id)
    if action == "pr":
        k = await (player.do_resume(chat_id) if st.paused else player.do_pause(chat_id))
        await _refresh(cq, chat_id)
        return await cq.answer("Resumed" if (k == "ok" and not st.paused) else "Paused" if k == "ok" else "Nothing is playing.")
    if action == "skip":
        # turant answer do, warna button pe spinner ghoomta rehta hai jab tak next track download ho
        await cq.answer("Picking a next track...")
        panel.cancel_collapse(chat_id)
        k = await player.do_skip(chat_id)
        if k != "ok":
            await client.send_message(chat_id, await t(chat_id, k), reply_markup=player.CLOSE_KB)
        return
    if action == "stop":
        k = await player.do_stop(chat_id, who)
        panel.close_panel(chat_id)
        panel.cancel_collapse(chat_id)
        return await cq.answer("Stopped" if k == "ok" else "Nothing is playing.")
    if action == "loop":
        k = player.do_loop(chat_id, 0 if st.loop else 1)
        await _refresh(cq, chat_id)
        return await cq.answer("Repeat once more" if k == "loop_set" else "Loop off")
    if action == "shuffle":
        k = player.do_shuffle(chat_id)
        if panel.is_open(chat_id):
            panel.arm_collapse(chat_id, cq.message)  # shuffle bhi "use" hai -> timer dobara
        return await cq.answer("Shuffled" if k == "shuffled" else "Need at least 2 songs in queue.", show_alert=(k != "shuffled"))
    if action == "ap":  # player me "autoplay" button -> enable / disable menu
        panel.open_panel(chat_id, "autoplay")
        await _refresh(cq, chat_id)
        return await cq.answer()
    if action in ("apon", "apoff"):
        st.autoplay = action == "apon"
        panel.open_panel(chat_id, "main")  # choose karte hi wapas controls panel
        await _refresh(cq, chat_id)
        return await cq.answer("Autoplay enabled" if st.autoplay else "Autoplay disabled")


@Client.on_callback_query(filters.regex(r"^pl:now:(-?\d+):(\d+)$"))
async def play_now_button(client, cq):
    chat_id, tok = int(cq.matches[0].group(1)), int(cq.matches[0].group(2))
    tr = player._qtok.get(tok)
    uid = cq.from_user.id
    # admin / authorized, ya jisne ye song queue me lagaya wo khud
    allowed = await perms.can_control(client, chat_id, uid) or (tr is not None and getattr(tr, "requester_id", None) == uid)
    if not allowed:
        return await cq.answer("Only admins or the person who requested this song can use this.", show_alert=True)
    if tr is None or not player.in_queue(chat_id, tr):
        try:
            await cq.message.edit_reply_markup()
        except Exception:
            pass
        return await cq.answer("This song is no longer in the queue.", show_alert=True)
    await cq.answer("Picking a next track...")
    k = await player.play_now(chat_id, tr)
    if k == "ok":
        try:
            await cq.message.edit_reply_markup()
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^unban_assistant$"))
async def unban_assistant_cb(client, cq):
    chat_id = cq.message.chat.id
    if not await perms.is_admin(client, chat_id, cq.from_user.id) and not perms.is_sudo(cq.from_user.id):
        return await cq.answer("Only admins can unban the assistant.", show_alert=True)
    try:
        await client.unban_chat_member(chat_id, userbot.me.id)
        assistant.forget(chat_id)
        await cq.message.edit_text("✅ Assistant has been unbanned. Please try playing again.")
    except Exception as e:
        await cq.answer(f"Failed to unban: {e}", show_alert=True)
