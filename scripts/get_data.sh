#!/usr/bin/env bash
# Runs get_data.py, which does the work.
set -euo pipefail
exec python3 "$(dirname "$0")/get_data.py" "$@"
