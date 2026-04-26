# Scare Sound Sources

The active random sound set is in `android_alert/sounds/`.

Source policy: use public-domain clips only. The National Park Service Sound
Gallery states that its files are in the public domain and may be downloaded.
The local downloader stores original clips in the ignored
`android_alert/sound_sources/` cache and writes per-file metadata to
`android_alert/sounds/manifest.json`.

Deterrent rationale: pigeon sound deterrents are imperfect and can habituate.
The set intentionally mixes predator/bird-alarm style clips with abrupt startle
sounds so consecutive detections do not always produce the same pattern.

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

Current files:

```text
raven_peregrine.mp3
bald_eagle.mp3
osprey.mp3
spotted_owl.mp3
common_raven.mp3
coyotes.mp3
coyote_chase.mp3
wolf.mp3
car_alarm.mp3
siren.mp3
```
