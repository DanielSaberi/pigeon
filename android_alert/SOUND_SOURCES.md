# Scare Sound Sources

The active random sound set is in `android_alert/sounds/`. The receiver plays
`alert_sequence_*.mp3` files by default.

Source policy: use public-domain clips only. The National Park Service Sound
Gallery states that its files are in the public domain and may be downloaded.
The local downloader stores original clips in the ignored
`android_alert/sound_sources/` cache and writes per-file metadata to
`android_alert/sounds/manifest.json`.

Deterrent rationale: pigeon sound deterrents are imperfect and can habituate.
The set uses a curated whitelist of source clips that sounded useful in manual
review, then creates randomized 20-second concatenation/repetition sequences so
consecutive detections do not always produce the same pattern.

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

The Android receiver defaults to `BIRD_ALERT_KIND=alert_sequence`, so the 12
20-second sequence files are active by default. The source clips are kept for
reproducibility and can be included by setting `BIRD_ALERT_KIND=any`.
