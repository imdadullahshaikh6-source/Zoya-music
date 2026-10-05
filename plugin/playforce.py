from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls.types import MediaStream
# ✅ CHANGED: main ki jagah core se import kiya
from core import call_py, userbot
from plugins.play import get_stream_url

@Client.on_message(filters.command(["playforce", "vplayforce"]) & filters.group)
async def playforce_cmd(client: Client, message: Message):
    msg = await message.reply_text("🔍 Force streaming...")
    
    if len(message.command) < 2:
        return await msg.edit_text("❌ Please provide a song name or URL.")
    
    query = " ".join(message.command[1:])
    chat_id = message.chat.id

    url, title, duration = get_stream_url(query)
    if not url:
        return await msg.edit_text("❌ Could not find the track.")

    try:
        # Leave current call to force a new one
        try:
            await call_py.leave_group_call(chat_id)
        except:
            pass
            
        await call_py.join_group_call(chat_id, MediaStream(url))
        
        mins, secs = divmod(duration, 60)
        await msg.edit_text(
            f"⚡ **Force Streaming**\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {mins}:{secs:02d}\n"
            f"**Requested by:** {message.from_user.mention}"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Playback Error: {e}")
