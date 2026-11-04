# plugin/general.py — /ping /stats
import platform
import time

import psutil
from pyrogram import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from core import call_py

import database
import state
from helpers.filters import cmd
from helpers.fonts import fmt_uptime, sc


@Client.on_message(cmd("ping"))
async def ping_cmd(client, message):
    t0 = time.perf_counter()
    m = await message.reply_text("🏓")
    lat = (time.perf_counter() - t0) * 1000
    try:
        await m.delete()
    except Exception:
        pass
    try:
        tg = float(call_py.ping)
    except Exception:
        tg = 0.0
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    text = (
        f"🏓 <u>{sc('pong')}:</u> <code>{lat:.2f} ms</code>\n\n"
        f"<b>{sc('uptime')}:</b> <code>{fmt_uptime(time.time() - state.START_TIME)}</code>\n"
        f"<b>{sc('ram')}:</b> <code>{vm.percent}%</code>\n"
        f"<b>{sc('cpu')}:</b> <code>{psutil.cpu_percent(interval=0.3)}%</code>\n"
        f"<b>{sc('disk')}:</b> <code>{disk.percent}%</code>\n"
        f"<b>{sc('py-tgcalls')}:</b> <code>{tg:.1f} ms</code>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Support", url=config.SUPPORT_CHAT)]]) if config.SUPPORT_CHAT else None
    try:
        await message.reply_photo(config.START_IMG, caption=text, reply_markup=kb)
    except Exception:
        await message.reply_text(text, reply_markup=kb)


@Client.on_message(cmd("stats"))
async def stats_cmd(client, message):
    chats, users = await database.counts()
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    text = (
        f"📊 <u>{sc('system status')}</u>\n\n"
        f"• <b>{sc('active streams')}:</b> <code>{len(state.active_chats())}</code>\n"
        f"• <b>{sc('served chats')}:</b> <code>{chats}</code>\n"
        f"• <b>{sc('served users')}:</b> <code>{users}</code>\n"
        f"• <b>{sc('cpu')}:</b> <code>{psutil.cpu_percent(interval=0.5)}%</code>\n"
        f"• <b>{sc('ram')}:</b> <code>{vm.percent}% ({vm.used // 2**20} / {vm.total // 2**20} MB)</code>\n"
        f"• <b>{sc('disk')}:</b> <code>{disk.percent}%</code>\n"
        f"• <b>{sc('uptime')}:</b> <code>{fmt_uptime(time.time() - state.START_TIME)}</code>\n"
        f"• <b>python:</b> <code>{platform.python_version()}</code>"
    )
    await message.reply_text(text)
