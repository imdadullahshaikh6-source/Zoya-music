#!/bin/bash
# Naye VPS pe ek baar chalao:  bash setup-vps.sh
# Docker install karta hai, phir bot build + start.
set -e
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

mkdir -p data downloads cache
[ -f .env ] || { cp .env.example .env; echo ">> .env bana di. Pehle usme values bharo (nano .env), phir ye script dobara chalao."; exit 0; }
[ -f data/cookies.txt ] || echo ">> WARNING: data/cookies.txt nahi hai. YouTube cookies yahan rakho."

docker compose up -d --build
docker compose logs --tail 30
