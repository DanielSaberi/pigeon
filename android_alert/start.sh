#!/data/data/com.termux/files/usr/bin/sh
set -eu

cd "$HOME/bird-alert"
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi
python server.py
