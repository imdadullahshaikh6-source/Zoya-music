# Zoya bot wala font: small-caps (ʜᴇʏ ɪ ᴀᴍ ...)
_SRC = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DST = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ" * 2
_TABLE = str.maketrans(_SRC, _DST)


def sc(text: str) -> str:
    """Plain text ko small-caps me badalta hai (HTML tags par mat chalao)."""
    return str(text).translate(_TABLE)


def fmt_time(sec) -> str:
    """4:39 ya 1:02:03"""
    sec = max(int(sec or 0), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_played(sec) -> str:
    """00:11 (Alexa jaisa zero-padded)"""
    sec = max(int(sec or 0), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_uptime(sec) -> str:
    sec = int(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)
  
