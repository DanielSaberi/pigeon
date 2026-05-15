#!/data/data/com.termux/files/usr/bin/sh
set -eu

cd "$HOME/bird-alert"
export BIRD_ALERT_KIND="${BIRD_ALERT_KIND:-startle_combo}"
export BIRD_ALERT_MIN_DURATION="${BIRD_ALERT_MIN_DURATION:-0}"
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi
if ! command -v termux-media-player >/dev/null 2>&1; then
  echo "Warning: termux-media-player not found; install termux-api and the Termux:API app to avoid foreground VLC playback." >&2
fi
if ! command -v mpv >/dev/null 2>&1; then
  echo "Warning: mpv not found; install mpv if Termux:API playback is unavailable." >&2
fi
python server.py
