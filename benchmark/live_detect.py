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
import sys
import time
from datetime import datetime

from openai import OpenAI

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


def compute_change(frame_a, frame_b):
    """Compute mean absolute difference between two frames as a percentage (0-100).

    Both frames are downscaled and converted to grayscale for speed.
    """
    small_a = cv2.resize(frame_a, (320, 180))
    small_b = cv2.resize(frame_b, (320, 180))
    gray_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)
    # Blur to suppress sensor noise and compression artifacts
    gray_a = cv2.GaussianBlur(gray_a, (21, 21), 0)
    gray_b = cv2.GaussianBlur(gray_b, (21, 21), 0)
    diff = cv2.absdiff(gray_a, gray_b)
    return (diff.mean() / 255.0) * 100.0


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
    parser.add_argument("--no-think", action="store_true",
                        help="Disable thinking mode")
    parser.add_argument("--save-detections", default="detections",
                        help="Directory to save frames where birds are detected")
    parser.add_argument("--log-file", default="detections/log.jsonl",
                        help="JSONL log of all inferences")
    parser.add_argument("--stream", choices=["1", "2"], default="1",
                        help="RTSP stream number (1=high quality, 2=low quality)")
    args = parser.parse_args()

    # Apply backend preset
    preset = BACKENDS[args.backend]
    base_url = preset["base_url"]
    model = preset["model"]
    no_think_method = preset["no_think_method"]

    # Adjust RTSP URL stream number
    rtsp_url = args.rtsp_url.replace("/stream1", f"/stream{args.stream}")

    os.makedirs(args.save_detections, exist_ok=True)
    log_dir = os.path.dirname(args.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    client = OpenAI(base_url=base_url, api_key="no-key")

    print(f"Live bird detection")
    print(f"  Camera:    {rtsp_url.split('@')[1]}")
    print(f"  Backend:   {args.backend} ({model})")
    print(f"  Interval:  {args.interval}s min between captures")
    print(f"  Change:    {args.change_threshold}% threshold to trigger inference")
    if args.no_think:
        print(f"  No-think:  {no_think_method}")
    print()

    print("Connecting to camera...")
    cap = open_stream(rtsp_url)
    if cap is None:
        print("ERROR: Could not open RTSP stream", file=sys.stderr)
        sys.exit(1)
    print("Connected. Watching for birds...\n")

    reference_frame = None
    last_capture_time = 0
    inference_count = 0
    detection_count = 0
    skipped_count = 0

    try:
        while True:
            now = time.time()

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
                reference_frame = None
                continue

            ret, frame = cap.retrieve()
            if not ret:
                continue

            last_capture_time = now
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Check scene change
            if reference_frame is not None:
                change = compute_change(reference_frame, frame)
                if change < args.change_threshold:
                    skipped_count += 1
                    if skipped_count % 20 == 0:
                        print(f"  [{timestamp}] ... scene stable ({skipped_count} frames skipped, "
                              f"last change: {change:.2f}%)")
                    continue

                print(f"  [{timestamp}] Scene change: {change:.2f}% — running inference...")
            else:
                print(f"  [{timestamp}] First frame — running inference...")

            reference_frame = frame.copy()

            # Run VLM inference
            t0 = time.time()
            result = classify_frame(client, model, frame,
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

            print(f"  [{timestamp}] Inference #{inference_count}: {status} "
                  f"(conf={conf:.2f}, {inference_time:.1f}s)")

            # Save frame for every inference (bird or not)
            if bird:
                detection_count += 1
                fname = datetime.now().strftime("bird_%Y%m%d_%H%M%S.jpg")
            else:
                fname = datetime.now().strftime("nobird_%Y%m%d_%H%M%S.jpg")
            save_path = os.path.join(args.save_detections, fname)
            cv2.imwrite(save_path, frame)
            print(f"    Saved: {save_path}")

            # Log to JSONL
            log_entry = {
                "timestamp": timestamp,
                "bird": bird,
                "confidence": conf,
                "inference_time_s": round(inference_time, 2),
                "inference_num": inference_count,
            }
            if bird:
                log_entry["saved_frame"] = fname
            with open(args.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

    except KeyboardInterrupt:
        print(f"\n\nStopped.")
        print(f"  Total inferences: {inference_count}")
        print(f"  Bird detections:  {detection_count}")
        print(f"  Frames skipped:   {skipped_count}")
        print(f"  Log: {args.log_file}")

    finally:
        cap.release()


if __name__ == "__main__":
    main()
