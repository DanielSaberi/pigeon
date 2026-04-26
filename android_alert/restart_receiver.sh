#!/data/data/com.termux/files/usr/bin/sh
set -eu

REMOTE_DIR="/sdcard/Download/pigeon-setup"
APP_DIR="$HOME/bird-alert"

pkill -f '[p]ython.*server.py' 2>/dev/null || true
mkdir -p "$APP_DIR"
cp "$REMOTE_DIR/server.py" "$APP_DIR/server.py"
cp "$REMOTE_DIR/start.sh" "$APP_DIR/start.sh"
chmod +x "$APP_DIR/start.sh"

exec "$APP_DIR/start.sh"
