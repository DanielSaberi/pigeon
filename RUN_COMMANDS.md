# Pigeon Run Commands

Quick commands for running the balcony bird detector and Android alert speaker.

## Start Detection On This Mac

Prerequisites:

- Camera is powered and reachable at `192.168.178.34`.
- Tapo app is closed, because the camera only supports one RTSP session.
- LM Studio server is running at `http://192.168.2.2:1234/v1` and a VLM is loaded.
- Phone alert receiver is running if speaker alerts should work.

Start or restart detection:

```sh
cd /Users/danielsaberi/Documents/code/pigeon
sh restart_detection.sh
```

If the phone IP changes:

```sh
cd /Users/danielsaberi/Documents/code/pigeon
PHONE_IP=192.168.178.22 sh restart_detection.sh
```

Check whether detection is running:

```sh
screen -ls
ps aux | rg '[p]ython.*benchmark/live_detect.py|[l]ive_detect.py'
```

Watch the detector log:

```sh
tail -f /Users/danielsaberi/Documents/code/pigeon/benchmark/live_detect.log
```

Deterrence mode is enabled by default. After a bird-positive result, the camera
stays on the current preset, preset switching and motion gating pause, alerts
repeat, and VLM checks run back-to-back until two consecutive no-bird results.
The scare-away period is recorded as `deterrence_av_*.mp4` with audio and video.
That recording starts only after the first positive bird result and stops when
deterrence clears. A single ffmpeg RTSP reader records the MP4 and feeds frames
to Python, so this does not require a second camera session.

Useful knobs:

```sh
--deterrence-clear-count 2
--deterrence-alert-interval 4
--deterrence-record-video on
--deterrence-frame-size 1440x810
--deterrence-frame-fps 1
--deterrence-mode off
```

Stop detection:

```sh
screen -S pigeon-detect -X quit
pkill -f "benchmark/live_detect.py"
```

## Start The Phone Alert Receiver

On the Android phone, open Termux and run:

```sh
sh /data/data/com.termux/files/home/bird-alert/start.sh
```

Preferred playback uses Termux:API via `termux-media-player`, because it plays
without switching the foreground app to VLC. The receiver can also use `mpv`
inside Termux as an optional non-foreground fallback, but older Termux installs
may fail to install `mpv` because of `ffmpeg` package errors. If Termux prints
warnings that Termux:API is missing, install the Termux:API Android app and run:

```sh
pkg install termux-api
sh /data/data/com.termux/files/home/bird-alert/start.sh
```

The phone must be on the same network as the Mac and should usually be reachable
at:

```text
192.168.178.22
```

The Bluetooth speaker is not hardcoded. Android plays through the current media
output, so connect the desired speaker and verify normal phone audio goes to it.

## Update Phone Receiver Over Wi-Fi

From this Mac, start a temporary file server from the repo:

```sh
cd /Users/danielsaberi/Documents/code/pigeon
python3 -m http.server 8766 --bind 0.0.0.0
```

On the phone in Termux, stop the current receiver with `Ctrl+C` if it is running,
then run:

```sh
pkg install -y curl termux-api mpv
mkdir -p /sdcard/Download/pigeon-setup /data/data/com.termux/files/home/bird-alert
curl -fsSL http://192.168.178.44:8766/android_alert/server.py -o /sdcard/Download/pigeon-setup/server.py
curl -fsSL http://192.168.178.44:8766/android_alert/start.sh -o /sdcard/Download/pigeon-setup/start.sh
cp /sdcard/Download/pigeon-setup/server.py /data/data/com.termux/files/home/bird-alert/server.py
cp /sdcard/Download/pigeon-setup/start.sh /data/data/com.termux/files/home/bird-alert/start.sh
chmod +x /data/data/com.termux/files/home/bird-alert/start.sh
pkill -f '[p]ython.*server.py' 2>/dev/null
BIRD_ALERT_PLAYER=auto sh /data/data/com.termux/files/home/bird-alert/start.sh
```

If the files were deployed over USB ADB, this shorter phone command does the
same update/install/start sequence:

```sh
sh /sdcard/a
```

## Test Audio From This Mac

Trigger one alert sound through the phone receiver:

```sh
curl -sS --max-time 5 -X POST http://192.168.178.22:8765/bird
```

Expected response:

```json
{"alert":{"file":"startle_combo_04.mp3","path":"/sdcard/Download/pigeon-setup/sounds/startle_combo_04.mp3","timestamp":1778338861.544335},"ok":true}
```

If the command returns `connection refused`, the Termux receiver is not running.
Start it again on the phone:

```sh
sh /data/data/com.termux/files/home/bird-alert/start.sh
```

If the command returns `ok: true` but no sound is audible, check Android's media
output and speaker volume by playing any normal phone audio, for example a
browser or YouTube video.

Check receiver health and the active playback backend:

```sh
curl -sS --max-time 5 http://192.168.178.22:8765/health
```

`termux_media_player_available` or `mpv_available` should be `true`. If both are
`false`, the receiver will fall back to VLC, which can bring VLC to the
foreground and is less reliable.

## Useful Connectivity Checks

Check camera:

```sh
ping -c 2 192.168.178.34
```

Check LM Studio:

```sh
curl -s http://192.168.2.2:1234/v1/models
```

Check phone receiver port:

```sh
nc -vz 192.168.178.22 8765
```
