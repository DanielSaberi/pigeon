# Pigeon

Bird detection for a balcony camera. The live detector watches an RTSP stream,
uses motion/blob filtering to reduce VLM calls, classifies changed frames with a
VLM, and can trigger an Android-phone alert speaker when a bird is detected.

## Key Commands

Live detection with two PTZ presets and phone alert:

```sh
python benchmark/live_detect.py \
  --backend mac \
  --no-think \
  --preset-cycle 1,2 \
  --preset-dwell 55 \
  --vlm-max-size 1440x810 \
  --alert-url http://PHONE_IP:8765/bird \
  --alert-cooldown 60
```

Windows 10 with LM Studio running locally:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r benchmark\requirements-live.txt
.\restart_detection.ps1
```

If PowerShell blocks local scripts, run the same command with a one-time
execution-policy bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart_detection.ps1
```

The Windows restart script uses the local LM Studio API at
`http://localhost:1234/v1` with the `windows` backend preset. Override the
model id if LM Studio exposes a different one:

```powershell
.\restart_detection.ps1 -Model "qwen3.6-35b-a3b@q4_k_xl"
```

For a one-off foreground run on Windows:

```powershell
.\.venv\Scripts\python benchmark\live_detect.py `
  --backend windows `
  --no-think `
  --preset-cycle 1,2 `
  --preset-dwell 55 `
  --vlm-max-size 1440x810 `
  --alert-url http://PHONE_IP:8765/bird `
  --alert-cooldown 60
```

After a bird detection, the detector saves a continuous RTSP audio/video clip
for 1.5 minutes by default as `postbird_av_*.mp4`. Configure the duration with
`--post-detect-save-seconds`; use `0` or `--post-detect-mode off` to disable it.
By default, bird detections first enter deterrence mode: the camera stays on the
current preset, motion gating and preset switching pause, VLM checks run
back-to-back, and alerts repeat until two consecutive no-bird results. Tune this
with `--deterrence-clear-count` and `--deterrence-alert-interval`, or disable it
with `--deterrence-mode off`. With AV follow-up enabled, the ffmpeg recording is
deferred until deterrence mode clears so it does not interrupt the repeated
checks and alerts. Use the older sampled-frame modes with
`--post-detect-mode video`, `frames`, or `both`.
`--post-detect-video-fps` only affects sampled-frame MP4s; AV clips keep the
camera stream's native FPS.

Offline benchmark:

```sh
python benchmark/benchmark_vlm.py --backend mac --dataset balcony --no-think
```

## Important Files

```text
benchmark/live_detect.py        live RTSP detector, PTZ cycling, motion gating, alerts
benchmark/benchmark_vlm.py      offline VLM benchmark
benchmark/ptz_control.py        Tapo PTZ helper
restart_detection.ps1           Windows PowerShell restart helper
restart_detection.sh            macOS/Linux restart helper
WINDOWS_SETUP.md                Windows 10 setup and run guide
android_alert/README.md         Android phone alert setup and reproduction guide
android_alert/sounds/           normalized random alert sound set
TODO.md                         follow-up implementation notes
```

## Notes

The Tapo camera supports only one RTSP session. Close the Tapo app before
starting live detection.

Windows 10 requirements: Python 3, FFmpeg on `PATH`, local LM Studio with an
OpenAI-compatible server enabled, and network access to the camera and Android
phone receiver. The Android phone setup still runs inside Termux on the phone;
Windows can deploy the files with `android_alert\deploy_adb.ps1` if ADB is
installed. See `WINDOWS_SETUP.md` for the full Windows setup and runbook.

The RTSP stream exposes audio. The default AV follow-up mode releases the
OpenCV detector stream before starting ffmpeg, because the Tapo camera appears
to support only one RTSP client at a time. This avoids concurrent RTSP sessions
but means detection and preset cycling are paused while the follow-up clip is
being recorded.

Detection output is intentionally ignored by git:

```text
detections/
benchmark/detections/
benchmark/ptz_snaps/
benchmark/*.log
```
