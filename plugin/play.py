import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberBanned
from pyrogram.errors import UserNotParticipant
from pytgcalls.types import MediaStream
# ✅ CHANGED: main ki jagah core se import kiya
from core import call_py, userbot

# --- Helper: Extract Stream URL ---
def get_stream_url(query: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            return info.get('url'), info.get('title', 'Unknown Title'), info.get('duration', 0)
        except Exception as e:
            print(f"yt-dlp error: {e}")
            return None, None, 0

# --- Play Command ---
@Client.on_message(filters.command(["play", "vplay"]) & filters.group)
async def play_cmd(client: Client, message: Message):
    # 1. Initial UI
    msg = await message.reply_text("🔍 Picking the right track...")
    
    # Extract query
    if len(message.command) < 2:
        return await msg.edit_text("❌ Please provide a song name or URL.")
    
    query = " ".join(message.command[1:])
    chat_id = message.chat.id

    # 2. Assistant Auto-Invite Logic
    try:
        member = await client.get_chat_member(chat_id, userbot.me.id)
        if isinstance(member, ChatMemberBanned):
            raise Exception("Banned")
    except UserNotParticipant:
        try:
            await client.add_chat_members(chat_id, userbot.me.id)
            await msg.edit_text("➕ Assistant added to the group. Picking the right track...")
        except Exception as e:
            return await msg.edit_text(f"❌ Failed to add assistant: {e}")
    except Exception as e:
        if "Banned" in str(e):
            # Exact Ban Exception Message
            text = (
                f"Assistant is banned in this chat.\n"
                f"ID: `{userbot.me.id}`\n"
                f"Name: `{userbot.me.first_name}`\n"
                f"Please unban the assistant and try again."
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unban Assistant", callback_data="unban_assistant")]])
            return await msg.edit_text(text, reply_markup=kb)
        return await msg.edit_text(f"❌ Error: {e}")

    # 3. Fetch stream URL
    url, title, duration = get_stream_url(query)
    if not url:
        return await msg.edit_text("❌ Could not find the track. Try another query.")

    # 4. Join VC and Stream
    try:
        await call_py.join_group_call(
            chat_id,
            MediaStream(url)
        )
        
        # Format duration
        mins, secs = divmod(duration, 60)
        duration_str = f"{mins}:{secs:02d}"

        await msg.edit_text(
            f"▶️ **Now Streaming**\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {duration_str}\n"
            f"**Requested by:** {message.from_user.mention}"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Playback Error: {e}")

# --- Unban Assistant Callback ---
@Client.on_callback_query(filters.regex("^unban_assistant$"))
async def unban_assistant_cb(client: Client, callback_query):
    chat_id = callback_query.message.chat.id
    try:
        await client.unban_chat_member(chat_id, userbot.me.id)
        await callback_query.message.edit_text("✅ Assistant has been unbanned. Please try playing again.")
    except Exception as e:
        await callback_query.answer(f"Failed to unban: {e}", show_alert=True)
