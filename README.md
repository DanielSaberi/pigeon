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

After a bird detection, the detector saves a continuous RTSP audio/video clip
for 5 minutes by default as `postbird_av_*.mp4`. Configure the duration with
`--post-detect-save-seconds`; use `0` or `--post-detect-mode off` to disable it.
The AV mode temporarily stops frame-based detection, records one ffmpeg clip
from the current preset, then reconnects detection. Use the older sampled-frame
modes with `--post-detect-mode video`, `frames`, or `both`.
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
android_alert/README.md         Android phone alert setup and reproduction guide
android_alert/sounds/           normalized random alert sound set
TODO.md                         follow-up implementation notes
```

## Notes

The Tapo camera supports only one RTSP session. Close the Tapo app before
starting live detection.

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
