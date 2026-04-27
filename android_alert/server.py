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
import json
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
MIN_ALERT_DURATION_SECONDS = float(os.environ.get("BIRD_ALERT_MIN_DURATION", "5.0"))
ALERT_KIND = os.environ.get("BIRD_ALERT_KIND", "alert_sequence")
SUPPORTED_SUFFIXES = {".mp3", ".m4a", ".ogg", ".wav"}

last_played = 0.0
last_alert_file = ""
last_alert_record = None
alert_lock = threading.Lock()


def list_all_alert_files():
    alert_dir = Path(ALERT_DIR)
    if not alert_dir.is_dir():
        return []

    return sorted(
        str(path)
        for path in alert_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def manifest_entries():
    manifest_path = Path(ALERT_DIR) / "manifest.json"
    if not manifest_path.is_file():
        return []

    try:
        return json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def manifest_durations(entries=None):
    durations = {}
    for entry in entries if entries is not None else manifest_entries():
        try:
            durations[Path(entry["file"]).name] = float(entry["duration_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
    return durations


def manifest_kinds(entries=None):
    kinds = {}
    for entry in entries if entries is not None else manifest_entries():
        try:
            kinds[Path(entry["file"]).name] = str(entry["kind"])
        except (KeyError, TypeError, ValueError):
            continue
    return kinds


def kind_allowed(kind):
    if ALERT_KIND in {"", "any", "*"}:
        return True
    return kind == ALERT_KIND


def apply_manifest_filters(files):
    entries = manifest_entries()
    if not entries:
        return files

    durations = manifest_durations(entries)
    kinds = manifest_kinds(entries)
    filtered = []
    for path in files:
        name = Path(path).name
        if not kind_allowed(kinds.get(name, "")):
            continue
        if MIN_ALERT_DURATION_SECONDS > 0:
            duration = durations.get(name, MIN_ALERT_DURATION_SECONDS)
            if duration < MIN_ALERT_DURATION_SECONDS:
                continue
        filtered.append(path)
    return filtered


def list_alert_files():
    files = list_all_alert_files()
    filtered = apply_manifest_filters(files)
    if filtered:
        return filtered

    if ALERT_KIND not in {"", "any", "*"}:
        fallback = [
            path for path in files
            if Path(path).stem.startswith(ALERT_KIND)
        ]
        if fallback:
            return fallback

    if MIN_ALERT_DURATION_SECONDS <= 0:
        return files

    durations = manifest_durations()
    if not durations:
        return files

    return [
        path for path in files
        if durations.get(Path(path).name, MIN_ALERT_DURATION_SECONDS) >= MIN_ALERT_DURATION_SECONDS
    ]


def alert_file_counts():
    files = list_all_alert_files()
    entries = manifest_entries()
    if not entries:
        return {"available": len(files), "selected": len(list_alert_files())}

    durations = manifest_durations(entries)
    kinds = manifest_kinds(entries)
    counts = {}
    for path in files:
        name = Path(path).name
        kind = kinds.get(name, "unknown")
        counts[kind] = counts.get(kind, 0) + 1

    return {
        "available": len(files),
        "selected": len(list_alert_files()),
        "by_kind": counts,
        "duration_filtered": sum(
            1 for path in files
            if durations.get(Path(path).name, MIN_ALERT_DURATION_SECONDS) < MIN_ALERT_DURATION_SECONDS
        ),
    }


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
    counts = alert_file_counts()
    return {
        "ok": True,
        "sounds": len(files),
        "available_sounds": counts["available"],
        "sound_counts": counts,
        "alert_kind": ALERT_KIND,
        "min_duration_s": MIN_ALERT_DURATION_SECONDS,
        "alert_dir": ALERT_DIR,
    }


@app.get("/last")
def last():
    return {"ok": True, "last_alert": last_alert_record}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
