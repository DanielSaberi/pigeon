"""Live bird detection from Tapo RTSP camera stream.

Captures frames from an RTSP stream, detects scene changes via frame
differencing, and sends changed frames to a VLM for bird classification.

Usage:
    python live_detect.py --backend mac --no-think
    python live_detect.py --backend windows --no-think
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
import threading
import time
from collections import deque
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
    "windows": {
        "base_url": "http://localhost:1234/v1",
        "model": "qwen3.6-35b-a3b@q4_k_xl",
        "no_think_method": "prefill",
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


def parse_frame_size(value):
    """Parse fixed WIDTHxHEIGHT for ffmpeg raw-frame output."""
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            "must be WIDTHxHEIGHT (for example 1440x810)"
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
        if os.name == "nt":
            completed_command = command
            use_shell = True
        else:
            completed_command = shlex.split(command)
            use_shell = False

        result = subprocess.run(
            completed_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=use_shell,
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


def trigger_configured_alert(alert_url=None, alert_token=None, alert_command=None, timeout=1.0):
    """Trigger all configured alert outputs once."""
    result = {}
    if alert_url:
        result["http"] = trigger_alert(
            alert_url,
            token=alert_token,
            timeout=timeout,
        )
    if alert_command:
        result["command"] = trigger_command_alert(
            alert_command,
            timeout=timeout,
        )
    return result


def alert_result_ok(alert_result):
    """Return true when any configured alert backend succeeded."""
    if not alert_result:
        return False
    return any(result.get("ok") for result in alert_result.values())


class AlertRepeater:
    """Repeatedly trigger alerts in the background during deterrence mode."""

    def __init__(self, alert_url=None, alert_token=None, alert_command=None,
                 timeout=1.0, interval=4.0):
        self.alert_url = alert_url
        self.alert_token = alert_token
        self.alert_command = alert_command
        self.timeout = timeout
        self.interval = max(0.1, float(interval))
        self._stop = threading.Event()
        self._thread = None

    def configured(self):
        return bool(self.alert_url or self.alert_command)

    def trigger_once(self):
        return trigger_configured_alert(
            alert_url=self.alert_url,
            alert_token=self.alert_token,
            alert_command=self.alert_command,
            timeout=self.timeout,
        )

    def start(self):
        """Start repeating alerts and return the immediate first alert result."""
        if not self.configured():
            return None
        if self._thread is not None and self._thread.is_alive():
            return None

        self._stop.clear()
        first_result = self.trigger_once()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return first_result

    def _run(self):
        while not self._stop.wait(self.interval):
            result = self.trigger_once()
            if alert_result_ok(result):
                print("    Deterrence alert triggered")
            else:
                print(f"    Deterrence alert failed: {result}")

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._thread = None


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


class DeterrenceCapture:
    """Record deterrence AV with ffmpeg and expose decoded frames to detection."""

    def __init__(self, rtsp_url, save_dir, preset_id, initial_frame,
                 frame_size=(1440, 810), frame_fps=1.0):
        self.rtsp_url = rtsp_url
        self.frame_size = frame_size
        self.frame_fps = max(0.1, float(frame_fps))
        suffix = preset_suffix(preset_id)
        self.fname = f"deterrence_av{suffix}_{frame_timestamp()}.mp4"
        self.save_path = os.path.join(save_dir, self.fname)

        self.lock = threading.Lock()
        self.process = None
        self.frame_thread = None
        self.stderr_thread = None
        self.stderr_lines = deque(maxlen=40)
        self.latest = initial_frame.copy()
        self.latest_seq = 1
        self.pipe_frame_count = 0
        self.error = None
        self.started_at = time.time()
        self.ended_at = None

    def start(self):
        cmd = self._build_command()
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as e:
            raise RuntimeError(f"Could not start ffmpeg: {e}") from e

        self.frame_thread = threading.Thread(target=self._read_frames, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.frame_thread.start()
        self.stderr_thread.start()
        return self

    def _build_command(self):
        width, height = self.frame_size
        frame_filter = f"fps={self.frame_fps:g},scale={width}:{height}:flags=area"
        return [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            self.rtsp_url,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            self.save_path,
            "-map",
            "0:v:0",
            "-vf",
            frame_filter,
            "-pix_fmt",
            "bgr24",
            "-an",
            "-f",
            "rawvideo",
            "pipe:1",
        ]

    def _read_frames(self):
        if self.process is None or self.process.stdout is None:
            return

        width, height = self.frame_size
        frame_bytes = width * height * 3
        while True:
            raw = self._read_exact(self.process.stdout, frame_bytes)
            if raw is None:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
            with self.lock:
                self.latest = frame
                self.latest_seq += 1
                self.pipe_frame_count += 1

        if self.process is not None:
            returncode = self.process.poll()
            if returncode not in (None, 0) and self.error is None:
                self.error = f"ffmpeg exited with code {returncode}"

    @staticmethod
    def _read_exact(pipe, byte_count):
        chunks = []
        remaining = byte_count
        while remaining > 0:
            chunk = pipe.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_stderr(self):
        if self.process is None or self.process.stderr is None:
            return
        for raw_line in iter(self.process.stderr.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self.stderr_lines.append(line)

    def latest_frame(self, after_seq=None, timeout=2.0):
        """Return the newest frame, preferably newer than after_seq."""
        deadline = time.time() + max(0.0, timeout)
        while True:
            with self.lock:
                if after_seq is None or self.latest_seq != after_seq or time.time() >= deadline:
                    return self.latest.copy(), self.latest_seq

            if self.process is not None and self.process.poll() is not None:
                with self.lock:
                    return self.latest.copy(), self.latest_seq
            time.sleep(0.02)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self._request_ffmpeg_quit()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3.0)

        if self.frame_thread is not None:
            self.frame_thread.join(timeout=2.0)
            self.frame_thread = None
        if self.stderr_thread is not None:
            self.stderr_thread.join(timeout=1.0)
            self.stderr_thread = None

        returncode = self.process.returncode if self.process is not None else None
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            self.process = None

        self.ended_at = time.time()
        file_size = os.path.getsize(self.save_path) if os.path.exists(self.save_path) else 0
        stderr_tail = "\n".join(self.stderr_lines)[-1000:]
        ok = file_size > 0 and returncode == 0 and self.error is None
        return {
            "ok": ok,
            "file": self.fname,
            "frame_count": self.pipe_frame_count,
            "frame_fps": self.frame_fps,
            "frame_size": [self.frame_size[0], self.frame_size[1]],
            "elapsed_s": round(self.ended_at - self.started_at, 2),
            "returncode": returncode,
            "file_size_bytes": file_size,
            "stderr": stderr_tail,
            "error": self.error,
        }

    def _request_ffmpeg_quit(self):
        if self.process is None or self.process.stdin is None:
            return
        try:
            self.process.stdin.write(b"q")
            self.process.stdin.flush()
            self.process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def record_av_clip(rtsp_url, save_dir, prefix, preset_id, duration_seconds):
    """Record a continuous RTSP audio/video clip with ffmpeg."""
    suffix = preset_suffix(preset_id)
    fname = f"{prefix}{suffix}_{frame_timestamp()}.mp4"
    save_path = os.path.join(save_dir, fname)
    duration = max(0.001, float(duration_seconds))
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        rtsp_url,
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        save_path,
    ]

    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:
        return {
            "ok": False,
            "file": fname,
            "duration_requested_s": round(duration, 3),
            "elapsed_s": round(time.time() - started, 2),
            "returncode": None,
            "error": str(e)[:500],
        }

    elapsed = time.time() - started
    file_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
    ok = result.returncode == 0 and file_size > 0
    return {
        "ok": ok,
        "file": fname,
        "duration_requested_s": round(duration, 3),
        "elapsed_s": round(elapsed, 2),
        "returncode": result.returncode,
        "file_size_bytes": file_size,
        "stderr": result.stderr[-1000:].strip(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Live bird detection from RTSP camera",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--backend", choices=sorted(BACKENDS), default="mac",
                        help="VLM backend preset")
    parser.add_argument("--base-url",
                        help="OpenAI-compatible API base URL; overrides --backend")
    parser.add_argument("--model",
                        help="Model name/slug; overrides --backend")
    parser.add_argument("--api-key", default="no-key",
                        help="API key for the VLM server")
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
    parser.add_argument("--deterrence-mode", choices=["on", "off"], default="on",
                        help="After a bird detection, stay on the current preset, "
                             "run continuous VLM checks, and repeat alerts until clear")
    parser.add_argument("--deterrence-clear-count", type=int, default=2,
                        help="Consecutive no-bird VLM results required to leave deterrence mode")
    parser.add_argument("--deterrence-alert-interval", type=float, default=4.0,
                        help="Seconds between repeated alerts while deterrence mode is active")
    parser.add_argument("--deterrence-record-video", choices=["on", "off"], default="on",
                        help="Record an audio/video MP4 while deterrence mode is active")
    parser.add_argument("--deterrence-frame-fps", type=float, default=1.0,
                        help="FPS of frames piped from ffmpeg to VLM checks during deterrence; "
                             "the saved AV MP4 keeps the camera stream's native FPS")
    parser.add_argument("--deterrence-frame-size", type=parse_frame_size, default=(1440, 810),
                        help="Frame size piped from ffmpeg to VLM checks during deterrence")
    parser.add_argument("--deterrence-record-fps", type=float,
                        help="Deprecated alias for --deterrence-frame-fps")
    parser.add_argument("--post-detect-save-seconds", type=float, default=90.0,
                        help="Seconds after a bird detection to save follow-up media; 0 disables")
    parser.add_argument("--post-detect-mode", choices=["av", "video", "frames", "both", "off"], default="av",
                        help="Follow-up media saved after bird detections")
    parser.add_argument("--post-detect-video-fps", type=float, default=1.0,
                        help="FPS for post-detection sampled-frame MP4 clips; ignored by --post-detect-mode av")
    args = parser.parse_args()
    post_detect_enabled = args.post_detect_save_seconds > 0 and args.post_detect_mode != "off"
    save_post_detect_av = args.post_detect_mode == "av"
    save_post_detect_frames = args.post_detect_mode in {"frames", "both"}
    save_post_detect_video = args.post_detect_mode in {"video", "both"}
    sampled_post_detect_enabled = (
        post_detect_enabled and (save_post_detect_frames or save_post_detect_video)
    )
    if save_post_detect_video and args.post_detect_video_fps <= 0:
        parser.error("--post-detect-video-fps must be positive")
    if args.deterrence_clear_count < 1:
        parser.error("--deterrence-clear-count must be at least 1")
    if args.deterrence_alert_interval <= 0:
        parser.error("--deterrence-alert-interval must be positive")
    if args.deterrence_record_fps is not None:
        args.deterrence_frame_fps = args.deterrence_record_fps
    if args.deterrence_frame_fps <= 0:
        parser.error("--deterrence-frame-fps must be positive")
    deterrence_enabled = args.deterrence_mode == "on"
    deterrence_record_enabled = deterrence_enabled and args.deterrence_record_video == "on"

    # Apply backend preset
    preset = BACKENDS[args.backend]
    base_url = args.base_url or preset["base_url"]
    model = args.model or preset["model"]
    no_think_method = preset["no_think_method"]

    # Adjust RTSP URL stream number
    rtsp_url = args.rtsp_url.replace("/stream1", f"/stream{args.stream}")
    preset_cycle = parse_preset_cycle(args.preset_cycle) if args.preset_cycle else []

    os.makedirs(args.save_detections, exist_ok=True)
    log_dir = os.path.dirname(args.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    client = OpenAI(base_url=base_url, api_key=args.api_key)

    print(f"Live bird detection")
    print(f"  Camera:    {rtsp_url.split('@')[1]}")
    print(f"  Backend:   {args.backend} ({model})")
    print(f"  API:       {base_url}")
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
    if deterrence_enabled:
        print(f"  Deterrence: stay on bird preset, continuous checks until "
              f"{args.deterrence_clear_count} consecutive no-bird result(s), "
              f"alerts every {args.deterrence_alert_interval:g}s")
        if deterrence_record_enabled:
            print(f"  Deterrence AV: audio/video MP4, VLM frame pipe "
                  f"{args.deterrence_frame_size[0]}x{args.deterrence_frame_size[1]} "
                  f"at {args.deterrence_frame_fps:g} fps")
    if post_detect_enabled:
        detail = []
        if save_post_detect_av:
            detail.append("continuous AV MP4 with audio")
        if save_post_detect_video:
            detail.append(f"MP4 at {args.post_detect_video_fps:g} fps")
        if save_post_detect_frames:
            detail.append("JPEG frames")
        if deterrence_enabled and save_post_detect_av:
            print("  Follow-up: AV after-clear recording disabled while deterrence is on; "
                  "deterrence AV records the scare-away period instead")
        else:
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
    deterrence_active = False
    deterrence_session = 0
    deterrence_clear_count = 0
    deterrence_started_at = None
    deterrence_capture = None
    deterrence_capture_seq = None
    alert_repeater = AlertRepeater(
        alert_url=args.alert_url,
        alert_token=args.alert_token,
        alert_command=args.alert_command,
        timeout=args.alert_timeout,
        interval=args.deterrence_alert_interval,
    )

    try:
        while True:
            now = time.time()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if preset_cycle and not deterrence_active and now >= next_preset_switch:
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
            if not deterrence_active and elapsed < args.interval:
                time.sleep(0.1)
                continue

            if deterrence_active and deterrence_capture is not None:
                frame, deterrence_capture_seq = deterrence_capture.latest_frame(
                    after_seq=deterrence_capture_seq,
                    timeout=max(0.5, min(args.alert_timeout, 2.0)),
                )
                if deterrence_capture.error:
                    print(f"  Deterrence recording warning: {deterrence_capture.error}")
            else:
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
            if deterrence_active:
                reference_motion = None
                motion = {"prepared": prepare_motion_frame(frame)}
                print(f"  [{timestamp}] Deterrence mode #{deterrence_session}: "
                      f"continuous inference "
                      f"(clear {deterrence_clear_count}/{args.deterrence_clear_count})...")
            elif reference_motion is not None:
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
            post_detect_av_result = None
            deterrence_record_result = None
            stop_after_log = False
            deterrence_entered = False
            deterrence_exited = False
            deterrence_duration_s = None

            print(f"  [{timestamp}] Inference #{inference_count}{preset_note}: {status} "
                  f"(conf={conf:.2f}, {inference_time:.1f}s)")

            # Save frame for every inference (bird or not)
            if bird:
                detection_count += 1
                fname, save_path = save_frame(args.save_detections, "bird", current_preset, frame)
                if sampled_post_detect_enabled:
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

            if deterrence_enabled:
                if bird:
                    deterrence_clear_count = 0
                    if not deterrence_active:
                        deterrence_active = True
                        deterrence_entered = True
                        deterrence_session += 1
                        deterrence_started_at = time.time()
                        if deterrence_record_enabled:
                            if cap is not None:
                                cap.release()
                                cap = None
                            try:
                                deterrence_capture = DeterrenceCapture(
                                    rtsp_url,
                                    args.save_detections,
                                    current_preset,
                                    frame,
                                    frame_size=args.deterrence_frame_size,
                                    frame_fps=args.deterrence_frame_fps,
                                ).start()
                                deterrence_capture_seq = 1
                                print(f"    Deterrence AV recording started: "
                                      f"{deterrence_capture.save_path}")
                            except RuntimeError as e:
                                deterrence_capture = None
                                deterrence_capture_seq = None
                                print(f"    Deterrence AV recording failed to start: {e}")
                                cap = open_stream(rtsp_url)
                                if cap is None:
                                    print("ERROR: Could not reopen RTSP stream after "
                                          "deterrence AV start failure", file=sys.stderr)
                                    stop_after_log = True
                        alert_result = alert_repeater.start()
                        print(f"    Deterrence mode #{deterrence_session} started; "
                              "holding current view and repeating alerts")
                        if alert_result is not None:
                            if alert_result_ok(alert_result):
                                print("    Deterrence alert triggered")
                            else:
                                print(f"    Deterrence alert failed: {alert_result}")
                elif deterrence_active:
                    deterrence_clear_count += 1
                    if deterrence_clear_count >= args.deterrence_clear_count:
                        deterrence_exited = True
                        deterrence_active = False
                        alert_repeater.stop()
                        if deterrence_started_at is not None:
                            deterrence_duration_s = time.time() - deterrence_started_at
                        print(f"    Deterrence mode #{deterrence_session} cleared after "
                              f"{deterrence_clear_count} consecutive no-bird result(s)")
                        deterrence_clear_count = 0
                        deterrence_started_at = None
                        if preset_cycle:
                            next_preset_switch = time.time() + args.preset_dwell
                    else:
                        print(f"    Deterrence clear check "
                              f"{deterrence_clear_count}/{args.deterrence_clear_count}; "
                              "staying in continuous mode")

            if bird and not deterrence_enabled and (args.alert_url or args.alert_command):
                since_alert = time.time() - last_alert_time
                if since_alert >= args.alert_cooldown:
                    alert_result = trigger_configured_alert(
                        alert_url=args.alert_url,
                        alert_token=args.alert_token,
                        alert_command=args.alert_command,
                        timeout=args.alert_timeout,
                    )

                    if alert_result_ok(alert_result):
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

            should_record_av = (
                post_detect_enabled and save_post_detect_av and (
                    bird and not deterrence_enabled
                )
            )
            if deterrence_exited and deterrence_capture is not None:
                deterrence_record_result = deterrence_capture.stop()
                if deterrence_record_result.get("ok"):
                    print(f"    Deterrence AV recording saved: "
                          f"{os.path.join(args.save_detections, deterrence_record_result['file'])}")
                else:
                    print(f"    Deterrence AV recording failed: {deterrence_record_result}")
                deterrence_capture = None
                deterrence_capture_seq = None
                if cap is None and not should_record_av:
                    print("    Reconnecting detection stream...")
                    cap = open_stream(rtsp_url)
                    if cap is None:
                        print("ERROR: Could not reopen RTSP stream after deterrence AV",
                              file=sys.stderr)
                        stop_after_log = True
                    else:
                        motion_references.pop(motion_key, None)
                        last_capture_time = 0
                        if preset_cycle:
                            next_preset_switch = time.time() + args.preset_dwell

            if should_record_av:
                print(f"    Recording AV follow-up for {args.post_detect_save_seconds:g}s...")
                if post_detect_video_writer is not None:
                    post_detect_video_writer.release()
                    post_detect_video_writer = None
                if cap is not None:
                    cap.release()
                post_detect_av_result = record_av_clip(
                    rtsp_url,
                    args.save_detections,
                    "postbird_av",
                    current_preset,
                    args.post_detect_save_seconds,
                )
                if post_detect_av_result.get("ok"):
                    print(f"    AV follow-up saved: "
                          f"{os.path.join(args.save_detections, post_detect_av_result['file'])}")
                else:
                    print(f"    AV follow-up failed: {post_detect_av_result}")

                print("    Reconnecting detection stream...")
                cap = open_stream(rtsp_url)
                if cap is None:
                    print("ERROR: Could not reopen RTSP stream after AV follow-up", file=sys.stderr)
                    stop_after_log = True
                else:
                    motion_references.pop(motion_key, None)
                    last_capture_time = 0
                    if preset_cycle:
                        next_preset_switch = time.time() + args.preset_dwell

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
            if deterrence_enabled:
                log_entry["deterrence_active"] = deterrence_active
                if deterrence_session:
                    log_entry["deterrence_session"] = deterrence_session
                if deterrence_entered:
                    log_entry["deterrence_event"] = "entered"
                elif deterrence_exited:
                    log_entry["deterrence_event"] = "cleared"
                if deterrence_duration_s is not None:
                    log_entry["deterrence_duration_s"] = round(deterrence_duration_s, 2)
                if deterrence_active:
                    log_entry["deterrence_clear_count"] = deterrence_clear_count
                if deterrence_record_result is not None:
                    log_entry["deterrence_av"] = deterrence_record_result
            if bird:
                log_entry["saved_frame"] = fname
                if sampled_post_detect_enabled:
                    log_entry["post_detect_save_until"] = round(post_detect_save_until, 3)
                    log_entry["post_detect_mode"] = args.post_detect_mode
                    if post_detect_video_fname:
                        log_entry["post_detect_video"] = post_detect_video_fname
            if post_detect_av_result is not None:
                log_entry["post_detect_mode"] = args.post_detect_mode
                log_entry["post_detect_video"] = post_detect_av_result.get("file")
                log_entry["post_detect_av"] = post_detect_av_result
            if alert_result is not None:
                log_entry["alert"] = alert_result
            with open(args.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            if stop_after_log:
                break

    except KeyboardInterrupt:
        print(f"\n\nStopped.")
        print(f"  Total inferences: {inference_count}")
        print(f"  Bird detections:  {detection_count}")
        print(f"  Frames skipped:   {skipped_count}")
        print(f"  Log: {args.log_file}")

    finally:
        alert_repeater.stop()
        if deterrence_capture is not None:
            deterrence_capture.stop()
        if post_detect_video_writer is not None:
            post_detect_video_writer.release()
        if cap is not None:
            cap.release()


if __name__ == "__main__":
    main()
