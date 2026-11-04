# plugin/controls.py — pause/resume/skip/stop/seek/seekback/loop/shuffle/autoplay + player buttons
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup

import state
from core import userbot
from helpers import assistant, nopreview, panel, perms, player  # noqa: F401  (nopreview = YouTube card band)
from helpers.buttons import btn
from helpers.filters import cmd
from helpers.fonts import fmt_time, sc
from helpers.strings import t

# ── "Controls ?" panel + no-star keyboard ──
# helpers/player.py ke andar ka keyboard yahan se replace hota hai. Jab player.py ko edit karo
# to in 2 lines ko wahi merge kar dena aur yahan se hata dena.
player.player_keyboard = panel.player_keyboard
player.CLOSE_KB = InlineKeyboardMarkup([[btn("close", "x", style="danger")]])


async def skip_with_notice(client, chat_id: int) -> str:
    """Skip karte hi turant 'picking a next track...' dikhao, next song start hone par hata do."""
    if not state.get(chat_id).active:
        return await player.do_skip(chat_id)
    notice = None
    try:
        notice = await client.send_message(chat_id, f"<i>{sc('picking a next track...')}</i>")
    except Exception:
        pass
    try:
        return await player.do_skip(chat_id)
    finally:
        if notice:
            try:
                await notice.delete()
            except Exception:
                pass


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
    k = await skip_with_notice(client, message.chat.id)
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
    now = sc("on") if st.autoplay else sc("off")
    await message.reply_text(
        f"{sc('autoplay is currently')} <b>{now}</b>\n\n"
        f"{sc('usage:')} <code>/autoplay on</code> {sc('or')} <code>/autoplay off</code>",
        reply_markup=player.CLOSE_KB,
    )


# ── inline player buttons ──
async def _refresh(cq, chat_id):
    try:
        await cq.message.edit_reply_markup(panel.player_keyboard(chat_id))
    except Exception:
        pass  # message not modified / deleted


@Client.on_callback_query(filters.regex(r"^pl:(pr|skip|stop|loop|shuffle|close|ctl|back|ap):(-?\d+)$"))
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
        k = await skip_with_notice(client, chat_id)
        if k != "ok":
            await client.send_message(chat_id, await t(chat_id, k), reply_markup=player.CLOSE_KB)
        return
    if action == "stop":
        k = await player.do_stop(chat_id, who)
        panel.close_panel(chat_id)
        return await cq.answer("Stopped" if k == "ok" else "Nothing is playing.")
    if action == "loop":
        k = player.do_loop(chat_id, 0 if st.loop else 1)
        await _refresh(cq, chat_id)
        return await cq.answer("Repeat once more" if k == "loop_set" else "Loop off")
    if action == "shuffle":
        k = player.do_shuffle(chat_id)
        return await cq.answer("Shuffled" if k == "shuffled" else "Need at least 2 songs in queue.", show_alert=(k != "shuffled"))
    if action == "ap":
        st.autoplay = not st.autoplay
        await _refresh(cq, chat_id)
        return await cq.answer("Autoplay on" if st.autoplay else "Autoplay off")


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
