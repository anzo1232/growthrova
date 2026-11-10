#!/bin/sh
# Dev-only real FFmpeg pilot. Never starts production or handles live credentials.
set -eu
cd "$(dirname "$0")/.."
PY="${CLIPPR_PILOT_PYTHON:-$HOME/.clippr-business-pilot-runtime/venv/bin/python}"
if ! "$PY" -c 'from PIL import Image; import sys; assert sys.version_info >= (3,10)' >/dev/null 2>&1; then
  echo "Local pilot requires Python 3.10+ with Pillow installed." >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Local pilot requires FFmpeg and FFprobe." >&2
  exit 1
fi
export CLIPPR_LOCAL_PILOT=1
export CLIPPR_LOCAL_PILOT_PORT="${CLIPPR_LOCAL_PILOT_PORT:-4192}"
# User testing is separate from generated smoke-test fixtures.
export CLIPPR_LOCAL_PILOT_ROOT="${CLIPPR_LOCAL_PILOT_ROOT:-$HOME/.clippr-business-testing-workspace}"
exec "$PY" -u business_local_pilot.py
