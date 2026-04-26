#!/bin/sh
set -eu

SERIAL="${1:-${ANDROID_ALERT_ADB_SERIAL:-}}"
ALERT_FILE="${2:-/sdcard/Download/pigeon-setup/alert.mp3}"
ALERT_DIR="${ANDROID_ALERT_REMOTE_DIR:-/sdcard/Download/pigeon-setup/sounds}"

if [ -z "$SERIAL" ]; then
  SERIAL="$(adb devices | awk '/^[0-9.]+:5555[[:space:]]+device$/ {print $1; exit}')"
fi

if [ -z "$SERIAL" ]; then
  echo "No connected Wi-Fi ADB device found. Run: adb connect PHONE_IP:5555" >&2
  exit 1
fi

if [ $# -lt 2 ]; then
  SELECTED_FILE="$(adb -s "$SERIAL" shell "ls -1 '$ALERT_DIR'/*.mp3 2>/dev/null" | tr -d '\r' | awk 'BEGIN {srand()} {files[++n]=$0} END {if (n) print files[int(rand()*n)+1]}')"
  if [ -n "$SELECTED_FILE" ]; then
    ALERT_FILE="$SELECTED_FILE"
  fi
fi

echo "Playing $ALERT_FILE on $SERIAL"
adb -s "$SERIAL" shell am start -S \
  -a android.intent.action.VIEW \
  -n org.videolan.vlc/.StartActivity \
  -d "file://${ALERT_FILE}" \
  -t audio/mpeg >/dev/null
