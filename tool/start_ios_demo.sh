#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! curl --fail --silent http://127.0.0.1:18081/health/ready >/dev/null; then
  echo "먼저 다른 터미널에서 ./tool/start_demo_server.sh 를 실행하세요." >&2
  exit 1
fi
open -a Simulator
# Without an ID Flutter offers available devices rather than guessing a simulator.
if [ "$#" -gt 0 ]; then
  exec "$project_root/client/tool/flutterw" run -d "$1" --dart-define=DEMO_MODE=false --dart-define=LOCAL_DEMO=true --dart-define=API_BASE_URL=http://127.0.0.1:18081
fi
exec "$project_root/client/tool/flutterw" run --dart-define=DEMO_MODE=false --dart-define=LOCAL_DEMO=true --dart-define=API_BASE_URL=http://127.0.0.1:18081
