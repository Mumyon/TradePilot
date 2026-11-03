#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root/server"
if [ ! -x .venv/bin/python ]; then
  echo "server/.venv가 없습니다. RUN_TEST_GUIDE.md의 서버 환경 설치를 먼저 진행하세요." >&2
  exit 1
fi
PYTHONPATH=. exec .venv/bin/python tool/run_demo.py
