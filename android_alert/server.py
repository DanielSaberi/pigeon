"""HTTP alert receiver for an Android phone running Termux.

The phone should be paired to the alert speaker. A POST to /bird randomly
plays one sound from ALERT_DIR through Android's current media output.
"""
import mimetypes
import os
import random
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, abort, request


app = Flask(__name__)

TOKEN = os.environ.get("BIRD_ALERT_TOKEN", "")
ALERT_DIR = os.environ.get(
    "BIRD_ALERT_DIR",
    "/sdcard/Download/pigeon-setup/sounds",
)
ALERT_FILE = os.environ.get(
    "BIRD_ALERT_FILE",
    "/sdcard/Download/pigeon-setup/alert.mp3",
)
MIN_SECONDS_BETWEEN_ALERTS = float(os.environ.get("BIRD_ALERT_COOLDOWN", "2"))
SUPPORTED_SUFFIXES = {".mp3", ".m4a", ".ogg", ".wav"}

last_played = 0.0
last_alert_file = ""
last_alert_record = None
alert_lock = threading.Lock()


def list_alert_files():
    alert_dir = Path(ALERT_DIR)
    if not alert_dir.is_dir():
        return []

    return sorted(
        str(path)
        for path in alert_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def choose_alert_file():
    global last_alert_file

    files = list_alert_files()
    if not files:
        return ALERT_FILE

    with alert_lock:
        choices = [path for path in files if path != last_alert_file] or files
        last_alert_file = random.choice(choices)
        return last_alert_file


def mime_type_for(path):
    if path.lower().endswith(".mp3"):
        return "audio/mpeg"
    return mimetypes.guess_type(path)[0] or "audio/*"


def play_alert(alert_file):
    subprocess.run(
        [
            "am",
            "start",
            "-S",
            "-a",
            "android.intent.action.VIEW",
            "-n",
            "org.videolan.vlc/.StartActivity",
            "-d",
            f"file://{alert_file}",
            "-t",
            mime_type_for(alert_file),
        ],
        check=False,
    )


@app.post("/bird")
def bird():
    global last_played, last_alert_record

    if TOKEN and request.headers.get("X-Alert-Token") != TOKEN:
        abort(403)

    now = time.time()
    if now - last_played < MIN_SECONDS_BETWEEN_ALERTS:
        return {"ok": True, "skipped": "rate_limited", "last_alert": last_alert_record}

    alert_file = choose_alert_file()
    last_alert_record = {
        "file": Path(alert_file).name,
        "path": alert_file,
        "timestamp": now,
    }
    last_played = now
    print(f"Playing alert: {alert_file}", flush=True)
    threading.Thread(target=play_alert, args=(alert_file,), daemon=True).start()
    return {"ok": True, "alert": last_alert_record}


@app.get("/health")
def health():
    files = list_alert_files()
    return {"ok": True, "sounds": len(files), "alert_dir": ALERT_DIR}


@app.get("/last")
def last():
    return {"ok": True, "last_alert": last_alert_record}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
