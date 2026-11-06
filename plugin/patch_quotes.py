# Usage: python3 patch_quotes.py helpers/player.py
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()

new = '''def now_caption(track: Track) -> str:
    return (
        f"<blockquote><u>{sc('now streaming')}</u></blockquote>\\n"
        f"<blockquote>"
        f"<b>{sc('title')}:</b> {link_title(track)}\\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_time(track.duration) if track.duration else 'LIVE'}</code>\\n"
        f"<b>{sc('requested by')}:</b> {track.requester or sc('unknown')}"
        f"</blockquote>"
    )


def ended_caption(track: Track, played: int, reason: str) -> str:
    total = fmt_time(track.duration) if track.duration else "LIVE"
    return (
        f"<blockquote><u>{sc('stream completed')}</u></blockquote>\\n"
        f"<blockquote>"
        f"<b>{sc('title')}:</b> {link_title(track)}\\n"
        f"<b>{sc('duration')}:</b> <code>{fmt_played(played)} / {total}</code>\\n"
        f"• <b>{sc('reason')}:</b> <i>{reason}</i>"
        f"</blockquote>"
    )


'''
pat = re.compile(r"def now_caption\(track: Track\) -> str:.*?(?=def player_keyboard)", re.S)
assert pat.search(s), "now_caption/ended_caption nahi mila"
s = pat.sub(lambda m: new, s, count=1)
open(p, "w", encoding="utf-8").write(s)
print("done")
