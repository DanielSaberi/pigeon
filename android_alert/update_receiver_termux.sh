#!/data/data/com.termux/files/usr/bin/sh
set -eu

REMOTE_DIR="/sdcard/Download/pigeon-setup"
APP_DIR="$HOME/bird-alert"

# Keep package installation best-effort. Some older Termux installs have a
# broken ffmpeg/mpv dependency chain; that must not prevent updating/starting
# the receiver.
pkg install -y python termux-api || true
python -m pip install --no-cache-dir flask || true

pkill -f '[p]ython.*server.py' 2>/dev/null || true
mkdir -p "$APP_DIR"
cp "$REMOTE_DIR/server.py" "$APP_DIR/server.py"
cp "$REMOTE_DIR/start.sh" "$APP_DIR/start.sh"
chmod +x "$APP_DIR/start.sh"

exec env BIRD_ALERT_PLAYER=auto "$APP_DIR/start.sh"
