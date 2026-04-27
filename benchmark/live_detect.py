"""Live bird detection from Tapo RTSP camera stream.

Captures frames from an RTSP stream, detects scene changes via frame
differencing, and sends changed frames to a VLM for bird classification.

Usage:
    python live_detect.py --backend mac --no-think
    python live_detect.py --backend mac --no-think --interval 5 --change-threshold 2.0
"""
import argparse
import base64
import cv2
import json
import numpy as np
import os
import re
import requests
import shlex
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import unquote, urlparse

from openai import OpenAI

try:
    from pytapo import Tapo
except ImportError:
    Tapo = None

# Reuse backend presets from benchmark
BACKENDS = {
    "mac": {
        "base_url": "http://192.168.2.2:1234/v1",
        "model": "mlx-community/qwen3.5-35b-a3b",
        "no_think_method": "prefill",
    },
    "linux": {
        "base_url": "http://localhost:8080/v1",
        "model": "qwen3.5-35b",
        "no_think_method": "extra_body",
    },
}

RTSP_URL = "rtsp://Daniel:Webdev20!@192.168.178.34/stream1"

PROMPT = """Is there a bird in this image?

Reply with ONLY a JSON object in this exact format, nothing else:
{"bird": true, "confidence": 0.95}

Rules:
- "bird": true if you see one or more birds, false otherwise
- "confidence": how sure you are of your answer (0.0 to 1.0)
- Return ONLY the JSON, no explanation"""

MOTION_SIZE = (320, 180)
DEFAULT_MOTION_PIXEL_THRESHOLD = 18
DEFAULT_MIN_BLOB_AREA = 25

# ROI polygons are defined in the downscaled MOTION_SIZE coordinate space.
# They cover the balcony floor and likely bird perches while excluding the
# street/background that causes irrelevant motion.
MOTION_ROI_POLYGONS = {
    "1": [
        [(75, 0), (319, 0), (319, 170), (70, 170), (50, 140), (45, 110), (50, 80), (60, 50)],
        [(35, 4), (75, 0), (86, 45), (70, 90), (50, 115), (28, 90), (22, 50)],
    ],
    "2": [
        [(0, 55), (260, 50), (290, 55), (310, 80), (319, 179), (0, 179)],
        [(0, 40), (250, 35), (290, 45), (300, 58), (0, 55)],
    ],
}


def parse_response(text):
    """Parse VLM JSON response into {"bird": bool, "confidence": float}."""
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'```json\s*', '', cleaned)
    cleaned = re.sub(r'```\s*', '', cleaned)
    cleaned = cleaned.strip()

    json_match = re.search(r'\{[^{}]*"bird"\s*:.*?\}', cleaned, re.DOTALL)
    if not json_match:
        lower = cleaned.lower()
        if "yes" in lower or '"bird": true' in lower or '"bird":true' in lower:
            return {"bird": True, "confidence": 0.5}
        elif "no" in lower or '"bird": false' in lower or '"bird":false' in lower:
            return {"bird": False, "confidence": 0.5}
        return None

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return None

    bird = bool(data.get("bird", False))
    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    return {"bird": bird, "confidence": confidence}


def parse_vlm_max_size(value):
    """Parse WIDTHxHEIGHT or 'native' for VLM downscaling."""
    if value.lower() == "native":
        return None

    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            "must be WIDTHxHEIGHT (for example 1600x900) or 'native'"
        )

    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return (width, height)


def prepare_vlm_frame(frame, max_size):
    """Downscale a frame to fit within max_size for VLM inference."""
    if max_size is None:
        return frame

    max_width, max_height = max_size
    height, width = frame.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return frame

    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    return cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)


def classify_frame(client, model, frame, no_think=False, no_think_method="extra_body"):
    """Send a cv2 frame to the VLM and return classification result."""
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode("utf-8")

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64}"
            }},
        ],
    }]

    extra = {}
    if no_think:
        if no_think_method == "prefill":
            messages.append({"role": "assistant", "content": "<think>\n\n</think>"})
        else:
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            **extra,
        )
        text = resp.choices[0].message.content.strip()
        return parse_response(text)
    except Exception as e:
        print(f"  API error: {str(e)[:120]}")
        return None


def trigger_alert(url, token=None, timeout=1.0):
    """Send a best-effort HTTP alert trigger."""
    headers = {}
    if token:
        headers["X-Alert-Token"] = token

    try:
        resp = requests.post(url, headers=headers, timeout=timeout)
        try:
            response = resp.json()
        except ValueError:
            response = resp.text[:500]
        return {
            "ok": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response": response,
            "error": None,
        }
    except requests.RequestException as e:
        return {
            "ok": False,
            "status_code": None,
            "error": str(e)[:200],
        }


def trigger_command_alert(command, timeout=5.0):
    """Run a best-effort local alert command."""
    try:
        result = subprocess.run(
            shlex.split(command),
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
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {
            "ok": False,
            "returncode": None,
            "error": str(e)[:200],
        }


def prepare_motion_frame(frame):
    """Downscale, grayscale, and blur a frame for motion analysis."""
    small = cv2.resize(frame, MOTION_SIZE)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    # Blur to suppress sensor noise and compression artifacts
    return cv2.GaussianBlur(gray, (21, 21), 0)


def build_motion_mask(preset_id, shape):
    """Build a binary ROI mask for a preset in motion-analysis space."""
    polygons = MOTION_ROI_POLYGONS.get(str(preset_id))
    mask = np.zeros(shape, dtype=np.uint8)
    if not polygons:
        mask.fill(255)
        return mask

    for polygon in polygons:
        pts = np.array(polygon, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
    return mask


def analyze_motion(reference_motion, frame, preset_id, mask_cache,
                   pixel_threshold=DEFAULT_MOTION_PIXEL_THRESHOLD,
                   min_blob_area=DEFAULT_MIN_BLOB_AREA):
    """Analyze frame-to-frame motion inside the preset ROI."""
    current_motion = prepare_motion_frame(frame)
    mask_key = (str(preset_id) if preset_id is not None else "__default__", current_motion.shape)
    mask = mask_cache.get(mask_key)
    if mask is None:
        mask = build_motion_mask(preset_id, current_motion.shape)
        mask_cache[mask_key] = mask

    diff = cv2.absdiff(reference_motion, current_motion)
    masked_diff = cv2.bitwise_and(diff, diff, mask=mask)

    roi_pixels = max(1, cv2.countNonZero(mask))
    change_pct = (float(masked_diff.sum()) / (255.0 * roi_pixels)) * 100.0

    _, binary = cv2.threshold(masked_diff, pixel_threshold, 255, cv2.THRESH_BINARY)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
    binary = cv2.dilate(binary, np.ones((5, 5), dtype=np.uint8), iterations=1)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blob_areas = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area >= min_blob_area:
            blob_areas.append(int(round(area)))

    largest_blob_area = max(blob_areas, default=0)
    triggered = bool(blob_areas)

    return {
        "prepared": current_motion,
        "change_pct": change_pct,
        "blob_count": len(blob_areas),
        "largest_blob_area": largest_blob_area,
        "triggered": triggered,
    }


def open_stream(url, retries=3):
    """Open RTSP stream with retries."""
    for attempt in range(retries):
        # Use FFMPEG backend with UDP (Tapo cameras prefer UDP over TCP)
        os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            # Read and discard first frame to stabilize
            cap.read()
            return cap
        print(f"  Stream open failed (attempt {attempt + 1}/{retries}), retrying...")
        time.sleep(2)
    return None


def parse_preset_cycle(raw):
    """Parse a comma-separated list of preset IDs."""
    presets = [item.strip() for item in raw.split(",") if item.strip()]
    if len(presets) < 2:
        raise ValueError("--preset-cycle requires at least two preset IDs, e.g. 1,2")
    return presets


def make_ptz_client(rtsp_url):
    """Create a Tapo PTZ client from RTSP URL credentials."""
    if Tapo is None:
        raise RuntimeError("pytapo is required for --preset-cycle")

    parsed = urlparse(rtsp_url)
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise ValueError("RTSP URL must include host, username, and password for --preset-cycle")

    return Tapo(
        parsed.hostname,
        unquote(parsed.username),
        unquote(parsed.password),
        printDebugInformation=False,
    )


def switch_preset(camera, preset_id, settle_seconds):
    """Move the PTZ camera to a preset and wait for motion to finish."""
    result = camera.setPreset(str(preset_id))
    print(f"  Switching to preset {preset_id}: {result}")
    if settle_seconds > 0:
        time.sleep(settle_seconds)


def preset_suffix(preset_id):
    """Return a filename-safe preset suffix."""
    if preset_id is None:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(preset_id))
    return f"_p{cleaned}"


def frame_timestamp():
    """Return a filename-safe timestamp with milliseconds."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def save_frame(save_dir, prefix, preset_id, frame):
    """Save a frame with a consistent preset-aware filename."""
    suffix = preset_suffix(preset_id)
    fname = f"{prefix}{suffix}_{frame_timestamp()}.jpg"
    save_path = os.path.join(save_dir, fname)
    cv2.imwrite(save_path, frame)
    return fname, save_path


def open_video_writer(save_dir, prefix, preset_id, frame, fps):
    """Open an MP4 writer for sampled follow-up frames."""
    suffix = preset_suffix(preset_id)
    fname = f"{prefix}{suffix}_{frame_timestamp()}.mp4"
    save_path = os.path.join(save_dir, fname)
    height, width = frame.shape[:2]
    writer = cv2.VideoWriter(
        save_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {save_path}")
    return writer, fname, save_path, (width, height)


def write_video_frame(writer, frame, size):
    """Write a frame, resizing if the stream dimensions changed."""
    width, height = size
    if frame.shape[1] != width or frame.shape[0] != height:
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    writer.write(frame)


def main():
    parser = argparse.ArgumentParser(
        description="Live bird detection from RTSP camera",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--backend", choices=["mac", "linux"], default="mac",
                        help="VLM backend preset")
    parser.add_argument("--rtsp-url", default=RTSP_URL,
                        help="RTSP stream URL")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Minimum seconds between frame captures")
    parser.add_argument("--change-threshold", type=float, default=1.5,
                        help="Minimum scene change (%%) to trigger VLM inference")
    parser.add_argument("--motion-pixel-threshold", type=int, default=DEFAULT_MOTION_PIXEL_THRESHOLD,
                        help="Per-pixel diff threshold for blob-based motion gating")
    parser.add_argument("--min-blob-area", type=int, default=DEFAULT_MIN_BLOB_AREA,
                        help="Minimum connected motion blob area in motion-analysis pixels")
    parser.add_argument("--no-think", action="store_true",
                        help="Disable thinking mode")
    parser.add_argument("--save-detections", default="detections",
                        help="Directory to save frames where birds are detected")
    parser.add_argument("--log-file", default="detections/log.jsonl",
                        help="JSONL log of all inferences")
    parser.add_argument("--stream", choices=["1", "2"], default="1",
                        help="RTSP stream number (1=high quality, 2=low quality)")
    parser.add_argument("--vlm-max-size", type=parse_vlm_max_size, default=(1600, 900),
                        help="Maximum WIDTHxHEIGHT sent to the VLM, or 'native' to disable downscaling")
    parser.add_argument("--preset-cycle",
                        help="Comma-separated preset IDs to alternate between, e.g. 1,2")
    parser.add_argument("--preset-dwell", type=float, default=120.0,
                        help="Seconds to stay on each preset before switching")
    parser.add_argument("--preset-settle", type=float, default=8.0,
                        help="Seconds to wait after each preset switch before reconnecting RTSP")
    parser.add_argument("--alert-url",
                        help="HTTP endpoint to POST when a bird is detected")
    parser.add_argument("--alert-token",
                        help="Optional token sent as X-Alert-Token to the alert endpoint")
    parser.add_argument("--alert-command",
                        help="Local command to run when a bird is detected")
    parser.add_argument("--alert-cooldown", type=float, default=60.0,
                        help="Minimum seconds between alert triggers")
    parser.add_argument("--alert-timeout", type=float, default=1.0,
                        help="Timeout in seconds for alert triggers")
    parser.add_argument("--post-detect-save-seconds", type=float, default=300.0,
                        help="Seconds after a bird detection to save follow-up media; 0 disables")
    parser.add_argument("--post-detect-mode", choices=["video", "frames", "both", "off"], default="video",
                        help="Follow-up media saved after bird detections")
    parser.add_argument("--post-detect-video-fps", type=float, default=1.0,
                        help="FPS for post-detection sampled-frame MP4 clips")
    args = parser.parse_args()
    post_detect_enabled = args.post_detect_save_seconds > 0 and args.post_detect_mode != "off"
    save_post_detect_frames = args.post_detect_mode in {"frames", "both"}
    save_post_detect_video = args.post_detect_mode in {"video", "both"}
    if args.post_detect_video_fps <= 0:
        parser.error("--post-detect-video-fps must be positive")

    # Apply backend preset
    preset = BACKENDS[args.backend]
    base_url = preset["base_url"]
    model = preset["model"]
    no_think_method = preset["no_think_method"]

    # Adjust RTSP URL stream number
    rtsp_url = args.rtsp_url.replace("/stream1", f"/stream{args.stream}")
    preset_cycle = parse_preset_cycle(args.preset_cycle) if args.preset_cycle else []

    os.makedirs(args.save_detections, exist_ok=True)
    log_dir = os.path.dirname(args.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    client = OpenAI(base_url=base_url, api_key="no-key")

    print(f"Live bird detection")
    print(f"  Camera:    {rtsp_url.split('@')[1]}")
    print(f"  Backend:   {args.backend} ({model})")
    print(f"  Interval:  {args.interval}s min between captures")
    if args.vlm_max_size is None:
        print("  VLM input: native")
    else:
        print(f"  VLM input: max {args.vlm_max_size[0]}x{args.vlm_max_size[1]}")
    print(f"  Motion:    ROI blobs (pixel>{args.motion_pixel_threshold}, "
          f"min area {args.min_blob_area}px)")
    print(f"  Change:    {args.change_threshold}% mean-change threshold")
    if args.no_think:
        print(f"  No-think:  {no_think_method}")
    if preset_cycle:
        print(f"  Presets:   {','.join(preset_cycle)} "
              f"({args.preset_dwell}s dwell, {args.preset_settle}s settle)")
    if args.alert_url:
        print(f"  Alert:     {args.alert_url} ({args.alert_cooldown}s cooldown)")
    if args.alert_command:
        print(f"  Alert cmd: {args.alert_command} ({args.alert_cooldown}s cooldown)")
    if post_detect_enabled:
        detail = []
        if save_post_detect_video:
            detail.append(f"MP4 at {args.post_detect_video_fps:g} fps")
        if save_post_detect_frames:
            detail.append("JPEG frames")
        print(f"  Follow-up: save {' and '.join(detail)} for "
              f"{args.post_detect_save_seconds}s after bird detections")
    print()

    ptz = None
    preset_index = 0
    current_preset = None
    next_preset_switch = None

    if preset_cycle:
        try:
            ptz = make_ptz_client(rtsp_url)
            current_preset = preset_cycle[preset_index]
            switch_preset(ptz, current_preset, args.preset_settle)
            next_preset_switch = time.time() + args.preset_dwell
        except Exception as e:
            print(f"ERROR: Could not initialize preset cycling: {e}", file=sys.stderr)
            sys.exit(1)

    print("Connecting to camera...")
    cap = open_stream(rtsp_url)
    if cap is None:
        print("ERROR: Could not open RTSP stream", file=sys.stderr)
        sys.exit(1)
    print("Connected. Watching for birds...\n")

    motion_references = {}
    mask_cache = {}
    last_capture_time = 0
    inference_count = 0
    detection_count = 0
    skipped_count = 0
    last_alert_time = 0.0
    post_detect_save_until = 0.0
    post_detect_frame_count = 0
    post_detect_video_writer = None
    post_detect_video_path = None
    post_detect_video_fname = None
    post_detect_video_size = None

    try:
        while True:
            now = time.time()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if preset_cycle and now >= next_preset_switch:
                preset_index = (preset_index + 1) % len(preset_cycle)
                current_preset = preset_cycle[preset_index]
                print(f"\n  [{timestamp}] Switching view...")
                try:
                    switch_preset(ptz, current_preset, args.preset_settle)
                except Exception as e:
                    print(f"ERROR: Could not switch to preset {current_preset}: {e}", file=sys.stderr)
                    break

                cap.release()
                cap = open_stream(rtsp_url)
                if cap is None:
                    print("ERROR: Could not reopen RTSP stream after preset switch", file=sys.stderr)
                    break

                last_capture_time = 0
                next_preset_switch = time.time() + args.preset_dwell
                continue

            # Respect minimum interval
            elapsed = now - last_capture_time
            if elapsed < args.interval:
                time.sleep(0.1)
                continue

            # Grab latest frame (discard buffered frames)
            ret = cap.grab()
            if not ret:
                print("  Stream lost, reconnecting...")
                cap.release()
                time.sleep(2)
                cap = open_stream(rtsp_url)
                if cap is None:
                    print("ERROR: Could not reconnect", file=sys.stderr)
                    break
                continue

            ret, frame = cap.retrieve()
            if not ret:
                continue

            last_capture_time = now
            if post_detect_save_until > 0 and now >= post_detect_save_until:
                if post_detect_video_writer is not None:
                    post_detect_video_writer.release()
                    post_detect_video_writer = None
                media_note = f", video: {post_detect_video_path}" if post_detect_video_path else ""
                print(f"  [{timestamp}] Follow-up saving ended "
                      f"({post_detect_frame_count} sampled frames{media_note})")
                post_detect_save_until = 0.0
                post_detect_frame_count = 0
                post_detect_video_path = None
                post_detect_video_fname = None
                post_detect_video_size = None

            if post_detect_save_until > 0:
                post_detect_save_path = None
                if save_post_detect_video and post_detect_video_writer is not None:
                    write_video_frame(post_detect_video_writer, frame, post_detect_video_size)
                if save_post_detect_frames:
                    _, post_detect_save_path = save_frame(
                        args.save_detections,
                        "postbird",
                        current_preset,
                        frame,
                    )
                post_detect_frame_count += 1
                if post_detect_frame_count == 1 or post_detect_frame_count % 20 == 0:
                    remaining = int(round(post_detect_save_until - now))
                    target = post_detect_save_path or post_detect_video_path
                    print(f"  [{timestamp}] Follow-up sampled #{post_detect_frame_count} "
                          f"({remaining}s remaining): {target}")

            motion_key = current_preset if current_preset is not None else "__default__"
            reference_motion = motion_references.get(motion_key)

            # Check scene change
            if reference_motion is not None:
                motion = analyze_motion(
                    reference_motion,
                    frame,
                    current_preset,
                    mask_cache,
                    pixel_threshold=args.motion_pixel_threshold,
                    min_blob_area=args.min_blob_area,
                )
                change = motion["change_pct"]
                blob_count = motion["blob_count"]
                largest_blob_area = motion["largest_blob_area"]
                triggered = motion["triggered"] and (
                    change >= args.change_threshold or
                    largest_blob_area >= args.min_blob_area * 2
                )

                if not triggered:
                    skipped_count += 1
                    if skipped_count % 20 == 0:
                        print(f"  [{timestamp}] ... scene stable ({skipped_count} frames skipped, "
                              f"last change: {change:.2f}%, blobs: {blob_count}, "
                              f"largest: {largest_blob_area}px)")
                    continue

                print(f"  [{timestamp}] Motion: {change:.2f}% mean change, "
                      f"{blob_count} blob(s), largest {largest_blob_area}px — running inference...")
            else:
                motion = {"prepared": prepare_motion_frame(frame)}
                print(f"  [{timestamp}] First frame — running inference...")

            motion_references[motion_key] = motion["prepared"]

            # Run VLM inference
            vlm_frame = prepare_vlm_frame(frame, args.vlm_max_size)
            vlm_height, vlm_width = vlm_frame.shape[:2]
            t0 = time.time()
            result = classify_frame(client, model, vlm_frame,
                                    no_think=args.no_think,
                                    no_think_method=no_think_method)
            inference_time = time.time() - t0
            inference_count += 1

            if result is None:
                print(f"  [{timestamp}] Inference #{inference_count}: parse error ({inference_time:.1f}s)")
                continue

            bird = result["bird"]
            conf = result["confidence"]
            status = "BIRD DETECTED" if bird else "no bird"
            preset_note = f" [preset {current_preset}]" if current_preset is not None else ""
            alert_result = None

            print(f"  [{timestamp}] Inference #{inference_count}{preset_note}: {status} "
                  f"(conf={conf:.2f}, {inference_time:.1f}s)")

            # Save frame for every inference (bird or not)
            if bird:
                detection_count += 1
                fname, save_path = save_frame(args.save_detections, "bird", current_preset, frame)
                if post_detect_enabled:
                    if save_post_detect_video and post_detect_video_writer is None:
                        (
                            post_detect_video_writer,
                            post_detect_video_fname,
                            post_detect_video_path,
                            post_detect_video_size,
                        ) = open_video_writer(
                            args.save_detections,
                            "postbird",
                            current_preset,
                            frame,
                            args.post_detect_video_fps,
                        )
                        write_video_frame(post_detect_video_writer, frame, post_detect_video_size)
                        post_detect_frame_count = 1
                    post_detect_save_until = max(
                        post_detect_save_until,
                        time.time() + args.post_detect_save_seconds,
                    )
                    until_text = datetime.fromtimestamp(post_detect_save_until).strftime("%Y-%m-%d %H:%M:%S")
                    media_note = f" video={post_detect_video_path}" if post_detect_video_path else ""
                    print(f"    Follow-up saving active until {until_text}{media_note}")
            else:
                fname, save_path = save_frame(args.save_detections, "nobird", current_preset, frame)

            if bird and (args.alert_url or args.alert_command):
                since_alert = time.time() - last_alert_time
                if since_alert >= args.alert_cooldown:
                    alert_result = {}
                    if args.alert_url:
                        alert_result["http"] = trigger_alert(
                            args.alert_url,
                            token=args.alert_token,
                            timeout=args.alert_timeout,
                        )
                    if args.alert_command:
                        alert_result["command"] = trigger_command_alert(
                            args.alert_command,
                            timeout=args.alert_timeout,
                        )

                    alert_ok = any(result.get("ok") for result in alert_result.values())
                    if alert_ok:
                        last_alert_time = time.time()
                        print("    Alert triggered")
                    else:
                        print(f"    Alert failed: {alert_result}")
                else:
                    alert_result = {
                        "ok": False,
                        "skipped": "cooldown",
                        "remaining_s": round(args.alert_cooldown - since_alert, 1),
                    }
                    print(f"    Alert skipped: cooldown ({alert_result['remaining_s']}s remaining)")

            print(f"    Saved: {save_path}")

            # Log to JSONL
            log_entry = {
                "timestamp": timestamp,
                "bird": bird,
                "confidence": conf,
                "inference_time_s": round(inference_time, 2),
                "inference_num": inference_count,
                "vlm_frame_size": [vlm_width, vlm_height],
                "motion_change_pct": round(change, 3) if reference_motion is not None else None,
                "motion_blob_count": blob_count if reference_motion is not None else None,
                "largest_blob_area": largest_blob_area if reference_motion is not None else None,
            }
            if current_preset is not None:
                log_entry["preset_id"] = current_preset
            if bird:
                log_entry["saved_frame"] = fname
                if post_detect_enabled:
                    log_entry["post_detect_save_until"] = round(post_detect_save_until, 3)
                    log_entry["post_detect_mode"] = args.post_detect_mode
                    if post_detect_video_fname:
                        log_entry["post_detect_video"] = post_detect_video_fname
            if alert_result is not None:
                log_entry["alert"] = alert_result
            with open(args.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

    except KeyboardInterrupt:
        print(f"\n\nStopped.")
        print(f"  Total inferences: {inference_count}")
        print(f"  Bird detections:  {detection_count}")
        print(f"  Frames skipped:   {skipped_count}")
        print(f"  Log: {args.log_file}")

    finally:
        if post_detect_video_writer is not None:
            post_detect_video_writer.release()
        cap.release()


if __name__ == "__main__":
    main()
