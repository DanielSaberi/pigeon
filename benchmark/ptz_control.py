"""PTZ control helper for the Tapo balcony camera.

Examples:
    python ptz_control.py presets
    python ptz_control.py set-preset 1
    python ptz_control.py move-step 90
    python ptz_control.py capture ptz_snaps/corner.jpg --preset 1 --move-step 90

Requires:
    - `pytapo` installed in the active environment
    - `ffmpeg` available on PATH for the `capture` subcommand
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from pytapo import Tapo


DEFAULT_HOST = os.environ.get("PIGEON_TAPO_HOST", "192.168.178.34")
DEFAULT_USER = os.environ.get("PIGEON_TAPO_USER", "Daniel")
DEFAULT_PASSWORD = os.environ.get("PIGEON_TAPO_PASSWORD", "Webdev20!")
DEFAULT_STREAM = os.environ.get("PIGEON_TAPO_STREAM", "1")


def make_camera(args):
    return Tapo(args.host, args.user, args.password, printDebugInformation=False)


def rtsp_url(args):
    return f"rtsp://{args.user}:{args.password}@{args.host}/stream{args.stream}"


def wait_settle(seconds):
    if seconds > 0:
        time.sleep(seconds)


def apply_position(camera, preset=None, move_steps=None, dwell=0.0):
    if preset is not None:
        result = camera.setPreset(str(preset))
        print(f"set_preset={preset} result={result}")
        wait_settle(dwell)

    for move_step in move_steps or []:
        result = camera.moveMotorStep(int(move_step))
        print(f"move_step={move_step} result={result}")
        wait_settle(dwell)


def run_capture(url, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "udp",
        "-i",
        url,
        "-frames:v",
        "1",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Control PTZ presets and capture snapshots from the balcony camera."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Camera host/IP")
    parser.add_argument("--user", default=DEFAULT_USER, help="Camera account username")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Camera account password")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("presets", help="List presets")

    set_preset = subparsers.add_parser("set-preset", help="Move camera to a preset")
    set_preset.add_argument("preset_id", help="Preset ID to activate")
    set_preset.add_argument("--dwell", type=float, default=8.0, help="Seconds to wait after moving")

    save_preset = subparsers.add_parser("save-preset", help="Save current position as a preset")
    save_preset.add_argument("name", help="Preset name")

    delete_preset = subparsers.add_parser("delete-preset", help="Delete a preset")
    delete_preset.add_argument("preset_id", help="Preset ID to delete")

    move_step = subparsers.add_parser("move-step", help="Move one PTZ step in a direction")
    move_step.add_argument("angle", type=int, help="Direction angle, 0 <= angle < 360")
    move_step.add_argument("--dwell", type=float, default=8.0, help="Seconds to wait after moving")

    capture = subparsers.add_parser(
        "capture",
        help="Capture one RTSP frame, optionally after moving to a preset and/or step direction",
    )
    capture.add_argument("output", help="Output image path")
    capture.add_argument("--stream", choices=["1", "2"], default=DEFAULT_STREAM, help="RTSP stream number")
    capture.add_argument("--preset", help="Preset ID to activate before capture")
    capture.add_argument(
        "--move-step",
        type=int,
        action="append",
        default=[],
        help="Step direction to apply before capture; repeat to chain moves",
    )
    capture.add_argument("--dwell", type=float, default=8.0, help="Seconds to wait after each move before capture")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "presets":
        camera = make_camera(args)
        print(json.dumps(camera.getPresets(), indent=2, sort_keys=True))
        return

    if args.command == "set-preset":
        camera = make_camera(args)
        result = camera.setPreset(str(args.preset_id))
        print(json.dumps({"preset_id": str(args.preset_id), "result": result}))
        wait_settle(args.dwell)
        return

    if args.command == "save-preset":
        camera = make_camera(args)
        result = camera.savePreset(args.name)
        print(json.dumps({"name": args.name, "result": result, "presets": camera.getPresets()}))
        return

    if args.command == "delete-preset":
        camera = make_camera(args)
        result = camera.deletePreset(str(args.preset_id))
        print(json.dumps({"preset_id": str(args.preset_id), "result": result, "presets": camera.getPresets()}))
        return

    if args.command == "move-step":
        camera = make_camera(args)
        result = camera.moveMotorStep(args.angle)
        print(json.dumps({"angle": args.angle, "result": result}))
        wait_settle(args.dwell)
        return

    if args.command == "capture":
        camera = make_camera(args)
        apply_position(camera, preset=args.preset, move_steps=args.move_step, dwell=args.dwell)
        output_path = Path(args.output)
        run_capture(rtsp_url(args), output_path)
        print(json.dumps({"output": str(output_path), "rtsp_url": rtsp_url(args)}))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
