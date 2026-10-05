from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
import config

@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    # Blockquote formatting using HTML or Markdown. Pyrogram supports Markdown '>'
    text = (
        f"> **Hey {message.from_user.mention} !**\n\n"
        f"> I am **Zoya** — a powerful music bot.\n"
        f"> ➤ Play high-quality music in your groups.\n"
        f"> ➤ Supports YouTube, Spotify, and direct links.\n"
        f"> ➤ Fast, lag-free, and 24/7 online.\n\n"
        f"> Tap **Command** below to see everything I can do."
    )

    # Requested Button Layout
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Command", callback_data="help")],
        [
            InlineKeyboardButton("👑 Owner", url=f"https://t.me/{config.OWNER_ID.replace('@', '')}"),
            InlineKeyboardButton("🔔 Channel", url="https://t.me/Zoyahumusicbot")
        ],
        [InlineKeyboardButton("➕ Add Me", url=f"http://t.me/Zoyahumusicbot?startgroup=true")]
    ])

    await message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)

@Client.on_callback_query(filters.regex("^help$"))
async def help_callback(client: Client, callback_query):
    await callback_query.answer("Commands: /play, /vplay, /playforce, /vplayforce", show_alert=True)
