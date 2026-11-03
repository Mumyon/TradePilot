#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root/server"
if [ "$#" -eq 0 ]; then
  printf 'TradePilot 앱 로그인 이메일: '
  IFS= read -r app_email
  set -- --email "$app_email"
fi
exec .venv/bin/python -m app.llm.chatgpt_login --demo "$@"
