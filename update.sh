#!/bin/bash
# Update Night Shift from GitHub (use this instead of git pull), then finish any new setup steps.
set -e
cd "$(dirname "$0")"
python3 tools/nightshift/kit_update.py
./setup.sh "$@"
