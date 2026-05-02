# Scare Sound Sources

The active random sound set is in `android_alert/sounds/`. The receiver starts
in `startle_combo` mode by default for the current audio-only test.

Source policy: prefer public-domain or CC0 clips; the current 9 mm gunshot
candidate is CC BY-SA 4.0 and is tracked explicitly in the manifest. The
National Park Service Sound Gallery states that its files are in the public
domain and may be downloaded. The local downloader stores original clips in the
ignored `android_alert/sound_sources/` cache and writes per-file metadata to
`android_alert/sounds/manifest.json`.

Deterrent rationale: pigeon sound deterrents are imperfect and can habituate.
The set uses a curated whitelist of source clips that sounded useful in manual
review, then creates randomized 20-second concatenation/repetition sequences so
consecutive detections do not always produce the same pattern.

The original short `startle_burst_*.mp3` files are kept as preserved source
clips. Each starts with 2
seconds of silence to avoid losing the actual impulse if Android/VLC/speaker
wake-up clips the beginning. The bursts are built from separately downloaded
gunshot, thwack/slap, wood-hit, and metal-hit sources, then normalized close to
full scale. Softer candidate sources are downloaded for reproducibility but are
not active in the receiver's default `startle_burst` set.

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
startle attack window: first 0.12s after lead-in, mean >= -18.0 dBFS
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

Downloaded startle source candidates:

```text
OpenGameArt Gunshots: 22 Pistol, 22 Magnum, Black Powder
OpenGameArt Basic Sound Effects: Basic Gunshot, Basic Explosion
OpenGameArt Chunky Explosion
OpenGameArt Explosion: Retro Explosion
OpenGameArt Thwack Sounds: Thwack 01, Thwack 03, Thwack 08
OpenGameArt 100 CC0 metal and wood SFX: wood/metal hit candidates
OpenGameArt 100 CC0 SFX 2: wood hit candidates
Wikimedia Commons: Gunshots 8
Wikimedia Commons: 9 mm gunshot
Wikimedia Commons/Freesound: Clapping Then Leaving
```

Active startle bursts:

```text
startle_burst_01.mp3  Basic Gunshot
startle_burst_02.mp3  Clapperboard Thwack 08
startle_burst_03.mp3  Wood Hammer Clap 01
startle_burst_04.mp3  Wood Clap Hit 09
startle_burst_05.mp3  Wood Clap Hit 02
startle_burst_06.mp3  Wood Board Clap
startle_burst_07.mp3  9mm Gunshot Brighter
startle_burst_08.mp3  Short Thwack 01
startle_burst_10.mp3  Metal Sheet Clap
```

Active combo set:

```text
startle_combo_01.mp3  Gunshot Clap Stack A
startle_combo_02.mp3  Wood Hit Stack A
startle_combo_03.mp3  Clap Stack A
startle_combo_04.mp3  Mixed Stack A
startle_combo_05.mp3  Mixed Stack B
startle_combo_06.mp3  Gunshot Wood Stack
startle_combo_07.mp3  Clap Wood Stack
startle_combo_08.mp3  Hard Hit Stack
startle_combo_09.mp3  Thwack Stack B
startle_combo_10.mp3  Clap Stack B
```

The Android receiver now defaults to `BIRD_ALERT_KIND=startle_combo` and
`BIRD_ALERT_MIN_DURATION=0` via `android_alert/start.sh`. Set
`BIRD_ALERT_KIND=startle_burst` to return to the preserved single-hit files or
`BIRD_ALERT_KIND=alert_sequence` to return to the older 20-second sequence
files. The source clips are kept for reproducibility and can be included by
setting `BIRD_ALERT_KIND=any`.
