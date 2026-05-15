#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REMOTE_DIR="/sdcard/Download/pigeon-setup"
ADB_SERIAL="${ANDROID_SERIAL:-}"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb is not installed or not on PATH" >&2
  exit 1
fi

if [ -z "$ADB_SERIAL" ]; then
  ADB_SERIAL="$(adb devices | awk '/^[[:alnum:]][^[:space:]]*[[:space:]]+device$/ {print $1; exit}')"
fi

if [ -z "$ADB_SERIAL" ] || ! adb -s "$ADB_SERIAL" get-state >/dev/null 2>&1; then
  echo "No authorized Android device found. Connect the phone, enable USB debugging, and approve the prompt." >&2
  adb devices
  exit 1
fi

adb -s "$ADB_SERIAL" shell "mkdir -p '$REMOTE_DIR'"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/server.py" "$REMOTE_DIR/server.py"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/start.sh" "$REMOTE_DIR/start.sh"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/termux_setup.sh" "$REMOTE_DIR/termux_setup.sh"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/restart_receiver.sh" "$REMOTE_DIR/restart_receiver.sh"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/update_receiver_termux.sh" "$REMOTE_DIR/update_receiver_termux.sh"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/update_receiver_termux.sh" "/sdcard/a"
adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/alert.mp3" "$REMOTE_DIR/alert.mp3"
if [ -d "$SCRIPT_DIR/sounds" ]; then
  adb -s "$ADB_SERIAL" shell "rm -rf '$REMOTE_DIR/sounds'"
  adb -s "$ADB_SERIAL" push "$SCRIPT_DIR/sounds" "$REMOTE_DIR/sounds"
fi

echo
echo "Files copied to $REMOTE_DIR"
echo "Next, open Termux on the phone and run:"
echo "  termux-setup-storage"
echo "  sh ~/storage/downloads/pigeon-setup/termux_setup.sh"
echo
echo "For later receiver restarts after redeploying:"
echo "  sh /sdcard/Download/pigeon-setup/restart_receiver.sh"
echo
echo "For one-command update/install from Termux:"
echo "  sh /sdcard/a"
