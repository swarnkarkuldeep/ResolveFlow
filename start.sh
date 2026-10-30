#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
docker compose up -d --build
API_PORT="$(grep -E '^API_PORT=' .env | cut -d= -f2)"; API_PORT="${API_PORT:-8000}"
python3 scripts/wait_for_health.py "http://localhost:${API_PORT}/api/health/ready" 180
echo "Ready: http://localhost:$(grep -E '^WEB_PORT=' .env | cut -d= -f2 | sed 's/^$/3000/')  (Mailpit: http://localhost:8025)"
echo "Demo login: owner@brightwork.test / resolveflow-demo"
