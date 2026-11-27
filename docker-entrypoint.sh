#!/bin/sh
# Bot (main.py) + local YouTube API (local_api/server.py) ek hi container me.
# Dono 127.0.0.1 share karte hain, isliye code me kuch badalna nahi pada (LOCAL_API_URL=http://127.0.0.1:8787).
# Koi ek process mar jaye to container band hota hai -> Docker (restart: unless-stopped) dobara utha deta hai.
set -u
cd /app
mkdir -p /data /app/downloads /app/cache

# Bot ka pyrogram session /data me rakho (rebuild/VPS move pe login dobara na ho)
[ -e /app/ZoyaMusicBot.session ] || ln -s /data/ZoyaMusicBot.session /app/ZoyaMusicBot.session

# Cookies: /data/cookies.txt me rakho (compose COOKIES_FILE=/data/cookies.txt set karta hai)
[ -f /data/cookies.txt ] || echo "[docker] WARNING: /data/cookies.txt nahi mila (YouTube 'not a bot' error aa sakta hai)"

if [ "${LOCAL_API_ENABLED:-1}" != "0" ]; then
  python local_api/server.py &
  API_PID=$!
fi

python main.py &
BOT_PID=$!

term() { kill "$BOT_PID" ${API_PID:-} 2>/dev/null; wait; exit 0; }
trap term TERM INT

# POSIX sh me 'wait -n' nahi hota, isliye poll
while kill -0 "$BOT_PID" 2>/dev/null && { [ -z "${API_PID:-}" ] || kill -0 "$API_PID" 2>/dev/null; }; do
  sleep 5
done
echo "[docker] ek process band ho gaya, container restart hoga"
kill "$BOT_PID" ${API_PID:-} 2>/dev/null
exit 1
