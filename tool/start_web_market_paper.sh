#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
origin=http://localhost:18083
api_url=http://127.0.0.1:18084

if ! curl --fail --silent --max-time 3 "$api_url/health/ready" >/dev/null; then
  printf '%s\n' "다른 터미널에서 ALLOWED_ORIGINS='[\"$origin\"]' ./tool/start_market_paper.sh --provider toss --ai-profile web --port 18084 --data-dir .demo/web-preview 를 먼저 실행하세요." >&2
  exit 1
fi

printf 'TradePilot 앱 연결 웹 화면은 %s 에서 열 수 있습니다.\n' "$origin"
exec "$project_root/client/tool/flutterw" run -d web-server \
  --no-pub \
  --web-hostname localhost --web-port 18083 \
  --dart-define=DEMO_MODE=false \
  --dart-define=LOCAL_DEMO=true \
  --dart-define=API_BASE_URL="$api_url" \
  "$@"
