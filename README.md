# Zoya Music Bot

## VPS (root) setup
```bash
apt update && apt install -y python3 python3-venv python3-pip ffmpeg git nodejs
cd /root/Zoya-music
python3 -m venv venv && source venv/bin/activate
pip install -U pip && pip install -r requirements.txt

cp .env.example .env && nano .env      # BOT_TOKEN, API_ID, API_HASH, MONGO_DB_URI, OWNER_ID ...
python3 gen_session.py                  # assistant account ka NAYA STRING_SESSION -> .env me paste

python3 main.py                         # test
pm2 start "venv/bin/python main.py" --name zoya-music   # 24/7
```
YouTube "Sign in to confirm you're not a bot" aaye to browser se `cookies.txt` export karke bot folder me rakho.

## Files
- plugin/: start(help), play, playforce, controls, nowplaying, playlist, admin, general, sudo, events
- helpers/: player (engine), ytdl, spotify, thumb (player card), perms, assistant, strings (/lang), fonts (small-caps)
- Assistant account ko group me bot khud invite karta hai (bot ko "Invite Users" admin right chahiye).

## Backend (download / stream) order
`helpers/ytapi.py` songs ko is order me try karta hai, jo fail ho aage wala:
1. `INNERTUBE_URL` API (direct stream) → 2. `RITESH_*` API → 3. **dump API** (`DUMP_*`: JSON poll, file Telegram dump channel se assistant utarta hai) → 4. yt-dlp race (`YT_PROXIES` + `cookies.txt`, parallel clients) → 5. purana yt-dlp (`ytdl.py` / `player.py`).
- Dump API pehle chahiye: `.env` me `API_FIRST=dump`.
- Assistant (STRING_SESSION wala account) dump channel me khud join ho jata hai (`DUMP_CHANNEL_INVITE`).
- Cookies: `cookies.txt` (Netscape) bot folder me rakho — race aur yt-dlp dono use karte hain.
