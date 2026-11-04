from pyrogram import filters

PREFIXES = ["/", "."]


def cmd(names):
    """Har command / aur . dono se chalega."""
    if isinstance(names, str):
        names = [names]
    return filters.command(names, prefixes=PREFIXES)
