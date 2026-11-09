# plugin/diag.py — /diag : audio lag ki asli wajah dhundhne ke liye (sirf owner / sudo)
#
# Lag ke dauran (jab awaaz atak rahi ho) group me /diag bhejo. 5 second me ye check karta hai:
#   * host CPU "steal"        -> VPS provider ne CPU throttle kiya hai (RAM/CPU % dikhne me kam, par asli me slow)
#   * bot ka event loop lag   -> bot ka python code atak raha hai
#   * ffmpeg / deno processes -> purane processes leak hokar CPU kha rahe hain
#   * Telegram servers tak TCP connect time / fail -> network slow ya packet loss
#   * pytgcalls ka played time vs bot ki apni clock -> stream real-time se peeche ho raha hai ya nahi
import asyncio
import html
import os
import time

import psutil
from pyrogram import Client

import config
from core import call_py
from helpers import perms, player
from helpers.filters import cmd

# Telegram data centers (TCP 443) — route / packet loss ka andaza
DCS = {"DC2": "149.154.167.51", "DC4": "149.154.167.91", "DC5": "91.108.56.130"}


async def _loop_lag(n: int = 25, step: float = 0.1):
    """Event loop kitna late jaagta hai (ms): (average, worst)."""
    tot = worst = 0.0
    for _ in range(n):
        t = time.perf_counter()
        await asyncio.sleep(step)
        d = max(0.0, (time.perf_counter() - t - step) * 1000)
        tot += d
        worst = max(worst, d)
    return tot / n, worst


async def _tcp(host: str, tries: int = 6):
    ms, fail = [], 0
    for _ in range(tries):
        t = time.perf_counter()
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(host, 443), 2.0)
            ms.append((time.perf_counter() - t) * 1000)
            w.close()
        except Exception:
            fail += 1
        await asyncio.sleep(0.1)
    return ms, fail


def _sample():
    """2 second ka CPU sample (blocking -> thread me chalta hai)."""
    me = psutil.Process()
    kids = []
    try:
        kids = me.children(recursive=True)
    except Exception:
        pass
    for p in kids + [me]:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    cpu = psutil.cpu_times_percent(interval=2.0)
    rows = []
    for p in kids:
        try:
            rows.append((p.name().lower(), p.cpu_percent(None), p.memory_info().rss))
        except Exception:
            pass
    try:
        me_cpu, rss, threads = me.cpu_percent(None), me.memory_info().rss, me.num_threads()
        fds = me.num_fds()
    except Exception:
        me_cpu = rss = threads = fds = 0
    return {"cpu": cpu, "kids": rows, "me_cpu": me_cpu, "rss": rss, "threads": threads, "fds": fds}


async def _call_time(chat_id: int):
    for name in ("played_time", "time"):
        fn = getattr(call_py, name, None)
        if callable(fn):
            try:
                return await fn(chat_id)
            except Exception:
                return None
    return None


def _mb(b) -> str:
    return f"{b / 1048576:.0f}MB"


async def build_report() -> str:
    sample_t = asyncio.create_task(asyncio.to_thread(_sample))
    lag_t = asyncio.create_task(_loop_lag())
    net_t = {k: asyncio.create_task(_tcp(h)) for k, h in DCS.items()}
    smp = await sample_t
    avg_lag, worst_lag = await lag_t
    net = {k: await t for k, t in net_t.items()}

    cpu = smp["cpu"]
    steal = getattr(cpu, "steal", 0.0)
    iowait = getattr(cpu, "iowait", 0.0)
    kids = smp["kids"]
    ffm = [r for r in kids if "ffmpeg" in r[0]]
    deno = [r for r in kids if "deno" in r[0]]
    other = [r for r in kids if r not in ffm and r not in deno]
    active = list(player._sched.keys())

    out = []
    out.append(f"uptime: {int((time.time() - psutil.boot_time()) // 3600)}h (server)  load: {' / '.join(f'{x:.2f}' for x in os.getloadavg())}")
    out.append(f"cpu: user {cpu.user:.0f}%  sys {cpu.system:.0f}%  iowait {iowait:.0f}%  STEAL {steal:.0f}%  idle {cpu.idle:.0f}%")
    out.append(f"bot: cpu {smp['me_cpu']:.0f}%  ram {_mb(smp['rss'])}  threads {smp['threads']}  fds {smp['fds']}")
    out.append(f"event loop lag: avg {avg_lag:.0f}ms  worst {worst_lag:.0f}ms")
    out.append(
        f"ffmpeg: {len(ffm)} (cpu {sum(r[1] for r in ffm):.0f}%)  deno: {len(deno)}  other children: {len(other)}"
    )
    out.append(f"active streams: {len(active)}")
    for cid in active[:5]:
        st_el = player._elapsed.get(cid)
        ct = await _call_time(cid)
        out.append(f"  chat {cid}: bot clock {st_el:.0f}s" + (f" | pytgcalls time {ct}" if ct is not None else ""))
    out.append("telegram tcp (ms):")
    bad_net = False
    for k, (ms, fail) in net.items():
        if ms:
            line = f"  {k}: min {min(ms):.0f}  avg {sum(ms) / len(ms):.0f}  max {max(ms):.0f}  fail {fail}/{len(ms) + fail}"
            if sum(ms) / len(ms) > 250 or fail or max(ms) > 3 * max(min(ms), 20):
                bad_net = True
        else:
            line = f"  {k}: all failed"
            bad_net = True
        out.append(line)

    verdict = []
    if steal >= 5:
        verdict.append(f"WARN: host CPU throttling (steal {steal:.0f}%). VPS slow ho raha hai, RAM/CPU % dikhne me kam hone par bhi.")
    if worst_lag > 300:
        verdict.append(f"WARN: bot ka event loop atak raha hai (worst {worst_lag:.0f}ms).")
    if iowait >= 10:
        verdict.append(f"WARN: disk I/O wait zyada hai ({iowait:.0f}%).")
    if len(ffm) > max(1, len(active)) + 1:
        verdict.append(f"WARN: zaroorat se zyada ffmpeg processes ({len(ffm)}), purane leak ho rahe hain.")
    if len(deno) > 2:
        verdict.append(f"WARN: {len(deno)} deno processes atke hain.")
    if bad_net:
        verdict.append("WARN: Telegram servers tak network slow / unstable hai (packet loss ya jitter).")
    if not verdict:
        verdict.append("OK: server aur bot side sab theek. Lag network (VC ka UDP route) ya listener ke taraf ka lagta hai.")

    return "<b>/diag</b>\n<pre>" + html.escape("\n".join(out)) + "</pre>\n" + html.escape("\n".join(verdict))


def _allowed(message) -> bool:
    u = message.from_user
    return bool(u) and (u.id == config.OWNER_ID or perms.is_sudo(u.id))


@Client.on_message(cmd("diag"))
async def diag_cmd(client, message):
    if not _allowed(message):
        return
    wait = await message.reply_text("<i>checking... (5s)</i>")
    try:
        text = await build_report()
    except Exception as e:
        text = f"diag error: {html.escape(repr(e))}"
    await wait.edit_text(text)
