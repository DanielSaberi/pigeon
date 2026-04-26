#!/data/data/com.termux/files/usr/bin/sh
set -eu

pkg update -y
pkg install -y python
python -m pip install --no-cache-dir flask

mkdir -p "$HOME/bird-alert"
cp "/sdcard/Download/pigeon-setup/server.py" "$HOME/bird-alert/server.py"
cp "/sdcard/Download/pigeon-setup/start.sh" "$HOME/bird-alert/start.sh"
cp "/sdcard/Download/pigeon-setup/restart_receiver.sh" "$HOME/bird-alert/restart_receiver.sh" 2>/dev/null || true
chmod +x "$HOME/bird-alert/start.sh"
chmod +x "$HOME/bird-alert/restart_receiver.sh" 2>/dev/null || true

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
fi

cat <<'EOF'

Termux receiver files are installed in ~/bird-alert.

Before starting:
1. Pair this phone to the alert Bluetooth speaker.
2. Make sure phone media output is the alert Bluetooth speaker.
3. Start the receiver:

   export BIRD_ALERT_TOKEN='change-this-to-a-long-random-string'  # optional but recommended
   ~/bird-alert/start.sh

EOF
