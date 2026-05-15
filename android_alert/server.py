"""HTTP alert receiver for an Android phone running Termux.

The phone should be paired to the alert speaker. A POST to /bird randomly
plays one sound from ALERT_DIR through Android's current media output.
"""
import mimetypes
import os
import random
import shutil
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
ALERT_PLAYER = os.environ.get("BIRD_ALERT_PLAYER", "auto")
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


def run_command(command, timeout=3):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-500:].strip(),
            "stderr": result.stderr[-500:].strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:500]}


def play_with_termux_media_player(alert_file):
    if shutil.which("termux-media-player") is None:
        return {
            "ok": False,
            "backend": "termux-media-player",
            "error": "termux-media-player command not found",
        }

    # Stop any previous clip so repeated alerts restart cleanly. This backend
    # plays through Android media routing without bringing VLC to the foreground.
    run_command(["termux-media-player", "stop"], timeout=1)
    result = run_command(["termux-media-player", "play", alert_file], timeout=3)
    result["backend"] = "termux-media-player"
    return result


def play_with_mpv(alert_file):
    if shutil.which("mpv") is None:
        return {
            "ok": False,
            "backend": "mpv",
            "error": "mpv command not found",
        }

    run_command(["pkill", "-f", "[m]pv .*pigeon-setup"], timeout=1)
    try:
        subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", "--no-terminal", alert_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return {"ok": True, "backend": "mpv"}
    except OSError as exc:
        return {"ok": False, "backend": "mpv", "error": str(exc)[:500]}


def play_with_vlc(alert_file):
    result = run_command(
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
        timeout=3,
    )
    result["backend"] = "vlc"
    return result


def player_order():
    if ALERT_PLAYER == "termux-media-player":
        return [play_with_termux_media_player]
    if ALERT_PLAYER == "mpv":
        return [play_with_mpv]
    if ALERT_PLAYER == "vlc":
        return [play_with_vlc]
    return [play_with_termux_media_player, play_with_mpv, play_with_vlc]


def play_alert(alert_file):
    global last_alert_record

    results = []
    for player in player_order():
        result = player(alert_file)
        results.append(result)
        if result.get("ok"):
            break

    with alert_lock:
        if last_alert_record and last_alert_record.get("path") == alert_file:
            last_alert_record["playback"] = results[-1] if results else None
            if len(results) > 1:
                last_alert_record["playback_attempts"] = results

    return results[-1] if results else {"ok": False, "error": "no playback attempted"}


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
        "alert_player": ALERT_PLAYER,
        "termux_media_player_available": shutil.which("termux-media-player") is not None,
        "mpv_available": shutil.which("mpv") is not None,
    }


@app.get("/status")
def status():
    return health()


@app.get("/last")
def last():
    return {"ok": True, "last_alert": last_alert_record}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
