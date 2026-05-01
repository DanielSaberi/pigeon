#!/data/data/com.termux/files/usr/bin/sh
set -eu

cd "$HOME/bird-alert"
export BIRD_ALERT_KIND="${BIRD_ALERT_KIND:-startle_burst}"
export BIRD_ALERT_MIN_DURATION="${BIRD_ALERT_MIN_DURATION:-0}"
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi
python server.py
