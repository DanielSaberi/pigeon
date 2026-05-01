# Scare Sound Sources

The active random sound set is in `android_alert/sounds/`. The receiver starts
in `startle_burst` mode by default for the current audio-only test.

Source policy: use public-domain clips only. The National Park Service Sound
Gallery states that its files are in the public domain and may be downloaded.
The local downloader stores original clips in the ignored
`android_alert/sound_sources/` cache and writes per-file metadata to
`android_alert/sounds/manifest.json`.

Deterrent rationale: pigeon sound deterrents are imperfect and can habituate.
The set uses a curated whitelist of source clips that sounded useful in manual
review, then creates randomized 20-second concatenation/repetition sequences so
consecutive detections do not always produce the same pattern.

The current test set adds short `startle_burst_*.mp3` files. Each starts with 2
seconds of silence to avoid losing the actual impulse if Android/VLC/speaker
wake-up clips the beginning. The burst then uses public-domain NPS impact
sources such as cannon fire, musket fire, thunder, avalanche, and bighorn sheep
ramming heads.

Generation command:

```sh
python3 android_alert/download_scare_sounds.py
```

Current level thresholds:

```text
minimum peak: -2.0 dBFS
minimum mean: -26.0 dBFS
target loudness: -12 LUFS
target true peak: -1.0 dBTP before final limiting
startle lead-in: 2.0s, lead peak <= -35 dBFS, burst peak >= -2.0 dBFS
```

Whitelisted source clips:

```text
clip_bison.mp3
clip_canada_geese.mp3
clip_car_alarm.mp3
clip_common_raven.mp3
clip_coyotes.mp3
clip_musket_fire.mp3
clip_siren.mp3
clip_sandhill_crane.mp3
clip_stellers_jay.mp3
```

Active alert sequences:

```text
alert_sequence_01.mp3
alert_sequence_02.mp3
alert_sequence_03.mp3
alert_sequence_04.mp3
alert_sequence_05.mp3
alert_sequence_06.mp3
alert_sequence_07.mp3
alert_sequence_08.mp3
alert_sequence_09.mp3
alert_sequence_10.mp3
alert_sequence_11.mp3
alert_sequence_12.mp3
```

Active startle bursts:

```text
startle_burst_01.mp3  Cannon Fire Single
startle_burst_02.mp3  Musket Fire Single
startle_burst_03.mp3  Bighorn Ram Single
startle_burst_04.mp3  Thunder Crack
startle_burst_05.mp3  Avalanche Bang
startle_burst_06.mp3  Cannon Musket Double
startle_burst_07.mp3  Musket Ram Double
startle_burst_08.mp3  Ram Cannon Double
startle_burst_09.mp3  Thunder Musket Double
startle_burst_10.mp3  Avalanche Cannon Double
```

The Android receiver now defaults to `BIRD_ALERT_KIND=startle_burst` and
`BIRD_ALERT_MIN_DURATION=0` via `android_alert/start.sh`. Set
`BIRD_ALERT_KIND=alert_sequence` to return to the older 20-second sequence
files. The source clips are kept for reproducibility and can be included by
setting `BIRD_ALERT_KIND=any`.
