#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
client_root="$project_root/client"

case $# in
  0)
    set -- --dart-define=WEB_SAME_ORIGIN=true
    ;;
  1)
    if ! printf '%s\n' "$1" | LC_ALL=C grep -Eq '^https://[[:alnum:].-]+(:[0-9]+)?/?$'; then
      printf '%s\n' '경로 없는 HTTPS API 주소를 입력하세요. 예: https://api.example.com' >&2
      exit 2
    fi
    set -- "--dart-define=API_BASE_URL=$1"
    ;;
  *)
    printf '사용법: %s [https://api.example.com]\n' "$0" >&2
    exit 2
    ;;
esac

flutter="$client_root/tool/flutterw"
"$flutter" pub get --offline || "$flutter" pub get
"$flutter" build web --release --no-pub --dart-define=DEMO_MODE=false "$@"

archive="$client_root/build/tradepilot-web.tar.gz"
archive_tmp=$(mktemp "$archive.XXXXXX")
trap 'rm -f "$archive_tmp"' EXIT
tar -czf "$archive_tmp" -C "$client_root/build/web" .
mv -f "$archive_tmp" "$archive"
printf '웹 배포 파일: %s\n' "$archive"
