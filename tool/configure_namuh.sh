#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$project_root/server/.venv/bin/python" "$project_root/server/tool/configure_namuh.py" "$@"
