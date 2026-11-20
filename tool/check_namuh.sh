#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root/server"
PYTHONPATH=. exec .venv/bin/python tool/check_namuh.py
