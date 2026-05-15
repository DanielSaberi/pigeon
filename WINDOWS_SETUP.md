# Windows 10 Setup

This is the deployment path for running the detector on a Windows 10 machine
with LM Studio running locally on that same Windows machine.

## Prerequisites

- Windows 10 on the detector machine.
- Python 3 installed and available through the Python launcher `py`.
- FFmpeg installed and available on `PATH`.
- LM Studio installed, model loaded, and the local OpenAI-compatible server enabled.
- The Tapo camera reachable from Windows at `192.168.178.34`.
- The Tapo app closed while detection is running, because the camera only supports one RTSP session.
- Optional but recommended: Android phone alert receiver reachable at `192.168.178.22:8765`.

## Install Tools

Open PowerShell in the repo root.

Install FFmpeg:

```powershell
winget install -e --id Gyan.FFmpeg
```

Close and reopen PowerShell, then verify:

```powershell
py -3 --version
ffmpeg -version
```

Create the Python virtual environment and install detector dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r benchmark\requirements-live.txt
```

## LM Studio

In LM Studio:

1. Load the VLM model.
2. Enable the local server.
3. Use port `1234`.

Check from PowerShell:

```powershell
curl.exe http://localhost:1234/v1/models
```

The restart script defaults to:

```text
http://localhost:1234/v1
qwen3.6-35b-a3b@q4_k_xl
```

If LM Studio exposes a different model id, pass it with `-Model`.

## Phone Alert Receiver

If the Android phone is already prepared, start Termux on the phone and run:

```sh
sh /sdcard/a
```

Then test from Windows:

```powershell
curl.exe http://192.168.178.22:8765/health
curl.exe -X POST http://192.168.178.22:8765/bird
```

To deploy or refresh phone files from Windows over USB ADB:

```powershell
powershell -ExecutionPolicy Bypass -File .\android_alert\deploy_adb.ps1
```

After deploying, open Termux on the phone and run:

```sh
sh /sdcard/a
```

The phone plays through Android's current media output. Pair/select the intended
Bluetooth speaker on the phone before testing alerts.

## Start Detection

Recommended background run:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart_detection.ps1 `
  -PhoneIp "192.168.178.22" `
  -Model "qwen3.6-35b-a3b@q4_k_xl"
```

If your LM Studio server URL or camera URL differs:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart_detection.ps1 `
  -LmStudioBaseUrl "http://localhost:1234/v1" `
  -Model "qwen3.6-35b-a3b@q4_k_xl" `
  -RtspUrl "rtsp://Daniel:Webdev20!@192.168.178.34/stream1" `
  -PhoneIp "192.168.178.22"
```

The script starts `benchmark\live_detect.py` minimized, writes logs, and stops
any previous detector process first.

Deterrence mode is enabled by default. After a bird-positive result, the camera
stays on the current preset, preset switching and motion gating pause, alerts
repeat, and VLM checks run back-to-back until two consecutive no-bird results.
The scare-away period is recorded as a video-only `deterrence_*.mp4` from the
active detection stream. The separate `postbird_av_*.mp4` with audio is still
recorded after deterrence clears. Tune with `--deterrence-clear-count`,
`--deterrence-alert-interval`, and `--deterrence-record-fps` in a foreground run,
or disable it with `--deterrence-mode off`.

## Logs And Status

Watch the main log:

```powershell
Get-Content -Wait .\benchmark\live_detect.log
```

Watch the error log:

```powershell
Get-Content -Wait .\benchmark\live_detect.err.log
```

Check whether detection is running:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'benchmark[\\/]+live_detect\.py' }
```

Stop detection:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'benchmark[\\/]+live_detect\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Connectivity Checks

Camera RTSP port:

```powershell
Test-NetConnection 192.168.178.34 -Port 554
```

Camera HTTPS/PTZ port:

```powershell
Test-NetConnection 192.168.178.34 -Port 443
```

Phone alert receiver:

```powershell
Test-NetConnection 192.168.178.22 -Port 8765
```

LM Studio:

```powershell
curl.exe http://localhost:1234/v1/models
```

## Notes

`restart_detection.ps1` uses these current defaults:

```text
PhoneIp:         192.168.178.22
LmStudioBaseUrl: http://localhost:1234/v1
Model:           qwen3.6-35b-a3b@q4_k_xl
Camera RTSP:     rtsp://Daniel:Webdev20!@192.168.178.34/stream1
Preset cycle:    1,2
Preset dwell:    55 seconds
VLM image size:  1440x810
Follow-up AV:    90 seconds after bird detection
```

The AV follow-up recording uses FFmpeg and temporarily pauses frame detection
while recording, because the Tapo camera only supports one RTSP client.
