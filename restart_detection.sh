#!/usr/bin/env sh
set -eu

# Restart the balcony bird detector in a detached screen session.
#
# What this script does:
# 1) Stops any previous detector process/session.
# 2) Starts live_detect.py with the current "known good" arguments.
# 3) Writes logs to benchmark/live_detect.log.
#
# Run from anywhere:
#   sh /Users/danielsaberi/Documents/code/pigeon/restart_detection.sh
#
# Optional override:
#   PHONE_IP=192.168.178.22 sh restart_detection.sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

SESSION_NAME="pigeon-detect"
LOG_FILE="benchmark/live_detect.log"
PHONE_IP="${PHONE_IP:-192.168.178.22}"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv/bin/python in $SCRIPT_DIR" >&2
  echo "Create/activate the venv first." >&2
  exit 1
fi

if ! command -v screen >/dev/null 2>&1; then
  echo "screen is not installed." >&2
  exit 1
fi

# Stop existing screen session (if present) and any stray detector process.
screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
pkill -f "benchmark/live_detect.py" >/dev/null 2>&1 || true

# Start detector:
# --preset-cycle 1,2 and --preset-dwell 55 alternate balcony views.
# --alert-url triggers phone playback receiver on bird detections.
# Deterrence mode records the scare-away period as AV until the bird is gone.
screen -dmS "$SESSION_NAME" zsh -lc "
  cd '$SCRIPT_DIR' && \
  .venv/bin/python -u benchmark/live_detect.py \
    --backend mac \
    --no-think \
    --preset-cycle 1,2 \
    --preset-dwell 55 \
    --vlm-max-size 1440x810 \
    --alert-url http://$PHONE_IP:8765/bird \
    --alert-cooldown 60 \
    --deterrence-record-video on \
    --deterrence-frame-size 1440x810 \
    --deterrence-frame-fps 1 \
    --post-detect-mode off \
    --save-detections benchmark/detections \
    --log-file benchmark/detections/log.jsonl \
    > '$LOG_FILE' 2>&1
"

sleep 1
echo "Started session: $SESSION_NAME"
echo "Log file: $SCRIPT_DIR/$LOG_FILE"
echo "Check status: screen -ls"
echo "Attach logs:  tail -f $SCRIPT_DIR/$LOG_FILE"
