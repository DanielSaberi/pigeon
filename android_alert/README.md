# Android Alert Receiver

This turns an Android phone into a local Wi-Fi alert player. The Mac detector
sends `POST /bird` to the phone, and the phone plays a random deterrent sound
through whatever Android currently uses as media output, typically a Bluetooth
speaker near the balcony.

This avoids macOS Bluetooth routing limits: normal Mac audio can stay on other
devices while bird alerts are handled by the phone.

## Requirements

Mac:

```sh
brew install android-platform-tools ffmpeg
```

Phone:

```text
Android phone on the same Wi-Fi as the Mac
Termux installed
VLC for Android installed
Bluetooth speaker paired to the phone and selected as media output
Battery optimization disabled for Termux
```

The current setup was tested with a Redmi Note 7 on Android 9/MIUI and a
Bluetooth speaker named `CHARGE MINI`, but the same setup should work with any
Android phone that can run Termux, VLC, and stay on Wi-Fi.

## Generate Or Refresh Sounds

The committed `sounds/` folder contains normalized public-domain alert
sequences and short startle-burst test clips from downloaded gunshot,
clap/thwack, wood-hit, and explosion candidate sources.
To regenerate them:

```sh
./android_alert/download_scare_sounds.py
```

The script downloads the curated National Park Service Sound Gallery whitelist
and separate startle candidates, normalizes the source clips with `ffmpeg`,
creates 20-second random concatenation/repetition alert sequences, creates
short `startle_burst_*.mp3` files with 2 seconds of lead-in silence, and
verifies levels with `volumedetect`/`silencedetect`. It also builds
`startle_combo_*.mp3` files by combining four preserved startle sources.
Metadata, licenses, source URLs, and level checks are written to
`android_alert/sounds/manifest.json`.

## Deploy With USB ADB

1. Enable Developer Options and USB debugging on the phone.
2. Connect the phone by USB.
3. Confirm the phone is authorized:

```sh
adb devices
```

If more than one device is connected, pass the target serial explicitly:

```sh
ANDROID_SERIAL=PHONE_SERIAL ./android_alert/deploy_adb.sh
```

Otherwise:

```sh
./android_alert/deploy_adb.sh
```

This copies files to:

```text
/sdcard/Download/pigeon-setup
```

## First-Time Termux Setup

On the phone, open Termux and run:

```sh
termux-setup-storage
sh ~/storage/downloads/pigeon-setup/termux_setup.sh
```

Then start the receiver:

```sh
export BIRD_ALERT_TOKEN='change-this-to-a-long-random-string'
~/bird-alert/start.sh
```

The token is optional, but recommended. If you set it here, pass the same value
from the detector with `--alert-token`.

The receiver listens on port `8765`.

## Restart After Updates

After redeploying files from the Mac, restart the Termux receiver:

```sh
sh /sdcard/Download/pigeon-setup/restart_receiver.sh
```

If the receiver is already running in the current Termux session, press
`Ctrl+C` first, then run the restart command.

## Find The Phone IP

Use Android Wi-Fi settings, your router's device list, or Termux:

```sh
ip route get 1.1.1.1
```

Use the phone's LAN IP in the Mac commands below.

## Test From The Mac

Health check:

```sh
curl -fsS http://PHONE_IP:8765/health
```

Expected response after the startle-combo sound set is active:

```json
{"ok":true,"sounds":10,"available_sounds":40,"sound_counts":{"available":40,"by_kind":{"alert_sequence":12,"source_clip":9,"startle_burst":9,"startle_combo":10},"duration_filtered":0,"selected":10},"alert_kind":"startle_combo","min_duration_s":0.0,"alert_dir":"/sdcard/Download/pigeon-setup/sounds"}
```

Trigger one alert:

```sh
curl -fsS -X POST http://PHONE_IP:8765/bird \
  -H 'X-Alert-Token: change-this-to-a-long-random-string'
```

If you did not set `BIRD_ALERT_TOKEN`, omit the header.

The response includes the selected sound file:

```json
{"ok":true,"alert":{"file":"startle_combo_03.mp3","path":"/sdcard/Download/pigeon-setup/sounds/startle_combo_03.mp3","timestamp":1777280000.0}}
```

Check the last selected file:

```sh
curl -fsS http://PHONE_IP:8765/last
```

Set Android media volume to max over ADB if needed:

```sh
adb -s PHONE_SERIAL shell media volume --stream 3 --set 15
```

## Detector Integration

HTTP receiver mode:

```sh
python benchmark/live_detect.py \
  --backend mac \
  --no-think \
  --preset-cycle 1,2 \
  --preset-dwell 55 \
  --vlm-max-size 1440x810 \
  --alert-url http://PHONE_IP:8765/bird \
  --alert-token change-this-to-a-long-random-string \
  --alert-cooldown 60
```

If no token is configured in Termux, remove `--alert-token`.

Alert attempts and cooldown skips are written into `detections/log.jsonl` under
the `alert` field.

## ADB/VLC Fallback

This does not require the Termux HTTP server to be running. It does require ADB
to remain connected to the phone, so it is less robust for unattended use.

USB ADB:

```sh
ANDROID_ALERT_ADB_SERIAL=PHONE_SERIAL ./android_alert/play_via_adb.sh
```

Classic Wi-Fi ADB for older Android versions:

```sh
adb -s PHONE_SERIAL tcpip 5555
adb connect PHONE_IP:5555
ANDROID_ALERT_ADB_SERIAL=PHONE_IP:5555 ./android_alert/play_via_adb.sh
```

Detector fallback mode:

```sh
python benchmark/live_detect.py \
  --backend mac \
  --no-think \
  --preset-cycle 1,2 \
  --preset-dwell 55 \
  --vlm-max-size 1440x810 \
  --alert-command './android_alert/play_via_adb.sh' \
  --alert-timeout 5
```

If exactly one Wi-Fi ADB device is connected, `play_via_adb.sh` can auto-detect
it. Otherwise set `ANDROID_ALERT_ADB_SERIAL`.

## How Playback Works

Default random sound directory:

```text
/sdcard/Download/pigeon-setup/sounds
```

Fallback sound if the directory is missing or empty:

```text
/sdcard/Download/pigeon-setup/alert.mp3
```

Environment overrides in Termux:

```sh
export BIRD_ALERT_DIR=/sdcard/Download/pigeon-setup/sounds
export BIRD_ALERT_FILE=/sdcard/Download/pigeon-setup/alert.mp3
export BIRD_ALERT_COOLDOWN=2
export BIRD_ALERT_MIN_DURATION=0
export BIRD_ALERT_KIND=startle_combo
```

The receiver avoids repeating the exact same file twice in a row when multiple
sounds are available. If `sounds/manifest.json` is present, the current default
setup plays only `kind=startle_combo` entries. Set `BIRD_ALERT_KIND=startle_burst`
to use the preserved single-hit files, `BIRD_ALERT_KIND=alert_sequence` and
`BIRD_ALERT_MIN_DURATION=5.0` to return to the older 20-second sequence files,
or `BIRD_ALERT_KIND=any` to include every manifest entry.

## Troubleshooting

If `/health` returns only `{"ok":true}`, the old receiver is still running.
Restart it with:

```sh
sh /sdcard/Download/pigeon-setup/restart_receiver.sh
```

If no sound plays, open VLC once manually, check that Android media output is
the Bluetooth speaker, and verify phone media volume.

If the Mac cannot reach `PHONE_IP:8765`, confirm the Mac and phone are on the
same Wi-Fi/VLAN and that Android did not kill Termux in the background.

For reliable long-running use, keep the phone plugged in and reserve a fixed IP
for it in the router.
