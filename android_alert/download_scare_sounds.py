#!/usr/bin/env python3
"""Download and normalize public-domain scare-alert sounds.

The selected sources are public-domain NPS Sound Gallery clips. Outputs are
short MP3 files normalized for alert playback and verified with ffmpeg's
volumedetect filter.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "sound_sources"
OUTPUT_DIR = ROOT / "sounds"
MANIFEST = OUTPUT_DIR / "manifest.json"
USER_AGENT = "pigeon-detector/1.0"
TARGET_LUFS = "-12"
TARGET_PEAK_DB = "-1.0"
MAX_DURATION_SECONDS = "7"
MIN_PEAK_DB = -2.0
MIN_MEAN_DB = -26.0
SEQUENCE_DURATION_SECONDS = "20"
SEQUENCE_COUNT = 12
SEQUENCE_RANDOM_SEED = 20260427
WHITELIST = {
    "bison",
    "canada_geese",
    "car_alarm",
    "common_raven",
    "coyotes",
    "musket_fire",
    "siren",
    "sandhill_crane",
    "stellers_jay",
}


@dataclass(frozen=True)
class SoundSpec:
    slug: str
    title: str
    page_url: str
    category: str


SOUNDS = [
    SoundSpec(
        "raven_peregrine",
        "Raven and Peregrine Falcon",
        "https://www.nps.gov/subjects/sound/sounds-peregrine-raven_bryce.htm",
        "predator/bird alarm",
    ),
    SoundSpec(
        "bald_eagle",
        "Bald Eagle",
        "https://www.nps.gov/subjects/sound/sounds-bald-eagle.htm",
        "predator call",
    ),
    SoundSpec(
        "osprey",
        "Osprey",
        "https://www.nps.gov/subjects/sound/sounds-osprey.htm",
        "predator call",
    ),
    SoundSpec(
        "spotted_owl",
        "Spotted Owl",
        "https://www.nps.gov/subjects/sound/sounds-spotted-owl.htm",
        "predator call",
    ),
    SoundSpec(
        "common_raven",
        "Common Raven",
        "https://www.nps.gov/subjects/sound/sounds-common-raven.htm",
        "alarm/harassment call",
    ),
    SoundSpec(
        "coyotes",
        "Coyotes",
        "https://www.nps.gov/subjects/sound/sounds-coyotes.htm",
        "predator/startle",
    ),
    SoundSpec(
        "coyote_chase",
        "Coyote Chase",
        "https://www.nps.gov/subjects/sound/sounds-coyote-chase.htm",
        "predator/startle",
    ),
    SoundSpec(
        "wolf",
        "Wolf",
        "https://www.nps.gov/subjects/sound/sounds-wolf.htm",
        "predator/startle",
    ),
    SoundSpec(
        "car_alarm",
        "Car Alarm",
        "https://www.nps.gov/subjects/sound/sounds-car-alarm.htm",
        "startle noise",
    ),
    SoundSpec(
        "siren",
        "Siren",
        "https://www.nps.gov/subjects/sound/sounds-siren.htm",
        "startle noise",
    ),
    SoundSpec(
        "chainsaw",
        "Chain Saw",
        "https://www.nps.gov/subjects/sound/sounds-chainsaw.htm",
        "startle noise",
    ),
    SoundSpec(
        "helicopter",
        "Helicopter",
        "https://www.nps.gov/subjects/sound/sounds-helicopter.htm",
        "startle noise",
    ),
    SoundSpec(
        "jet",
        "Jet",
        "https://www.nps.gov/subjects/sound/sounds-jet.htm",
        "startle noise",
    ),
    SoundSpec(
        "motorcycle",
        "Motorcycle",
        "https://www.nps.gov/subjects/sound/sounds-motorcycle.htm",
        "startle noise",
    ),
    SoundSpec(
        "propeller",
        "Propeller",
        "https://www.nps.gov/subjects/sound/sounds-propeller.htm",
        "startle noise",
    ),
    SoundSpec(
        "snowmobile",
        "Snowmobile",
        "https://www.nps.gov/subjects/sound/sounds-snowmobile.htm",
        "startle noise",
    ),
    SoundSpec(
        "cannon_fire",
        "Cannon Fire",
        "https://www.nps.gov/subjects/sound/sounds-cannon.htm",
        "startle noise",
    ),
    SoundSpec(
        "musket_fire",
        "Musket Fire",
        "https://www.nps.gov/subjects/sound/sounds-musket.htm",
        "startle noise",
    ),
    SoundSpec(
        "bear_cubs",
        "Bear with Cubs",
        "https://www.nps.gov/subjects/sound/sounds-bearcubs.htm",
        "predator/startle",
    ),
    SoundSpec(
        "bison",
        "Bison",
        "https://www.nps.gov/subjects/sound/sounds-bison.htm",
        "predator/startle",
    ),
    SoundSpec(
        "elk",
        "Elk",
        "https://www.nps.gov/subjects/sound/sounds-elk.htm",
        "predator/startle",
    ),
    SoundSpec(
        "alligator",
        "Alligator",
        "https://www.nps.gov/subjects/sound/sounds-alligator.htm",
        "predator/startle",
    ),
    SoundSpec(
        "thunder",
        "Thunder",
        "https://www.nps.gov/subjects/sound/sounds-thunder.htm",
        "startle noise",
    ),
    SoundSpec(
        "canada_geese",
        "Canada Geese",
        "https://www.nps.gov/subjects/sound/sounds-canada-geese.htm",
        "bird alarm/startle",
    ),
    SoundSpec(
        "killdeer",
        "Killdeer",
        "https://www.nps.gov/subjects/sound/sounds-killdeer.htm",
        "bird alarm/startle",
    ),
    SoundSpec(
        "western_gull",
        "Western Gull",
        "https://www.nps.gov/subjects/sound/sounds-western-gull.htm",
        "bird alarm/startle",
    ),
    SoundSpec(
        "stellers_jay",
        "Stellar's Jay",
        "https://www.nps.gov/subjects/sound/sounds-stellers-jay.htm",
        "bird alarm/startle",
    ),
    SoundSpec(
        "sandhill_crane",
        "Sandhill Crane",
        "https://www.nps.gov/subjects/sound/sounds-sandhill-crane.htm",
        "bird alarm/startle",
    ),
]

WHITELISTED_SOUNDS = [spec for spec in SOUNDS if spec.slug in WHITELIST]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def find_audio_url(page_url: str) -> str:
    html = fetch_text(page_url)
    match = re.search(r'<source\s+src="([^"]+)"\s+type="audio/[^"]+"', html)
    if match:
        return match.group(1)

    match = re.search(r"https://[^\"']+\.(?:mp3|m4a|wav|ogg)", html)
    if match:
        return match.group(0)

    raise RuntimeError(f"No audio URL found on {page_url}")


def download(spec: SoundSpec) -> tuple[Path, str]:
    audio_url = find_audio_url(spec.page_url)
    suffix = Path(audio_url.split("?", 1)[0]).suffix or ".mp3"
    source_path = SOURCE_DIR / f"{spec.slug}{suffix}"
    source_path.write_bytes(fetch_bytes(audio_url))
    return source_path, audio_url


def normalize(source_path: Path, output_path: Path) -> None:
    filter_graph = (
        "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB,"
        f"atrim=0:{MAX_DURATION_SECONDS},"
        "afade=t=in:st=0:d=0.02,"
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_PEAK_DB}:LRA=7,"
        "volume=2dB,"
        "alimiter=limit=0.89:level=false,"
        "afade=t=out:st=6.8:d=0.2"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-af",
            filter_graph,
            "-ac",
            "1",
            "-ar",
            "44100",
            "-b:a",
            "192k",
            str(output_path),
        ],
        check=True,
    )


def build_sequence(inputs: list[Path], output_path: Path, rng: random.Random) -> list[str]:
    """Build a normalized concatenation/repetition sequence."""
    if not inputs:
        raise ValueError("at least one input is required")

    chosen = []
    total_duration = 0.0
    while total_duration < float(SEQUENCE_DURATION_SECONDS) + 4:
        path = rng.choice(inputs)
        chosen.append(path)
        total_duration += measure(path)["duration_seconds"]

    concat_file = output_path.with_suffix(".concat.txt")
    concat_file.write_text(
        "".join(f"file '{path.resolve()}'\n" for path in chosen),
        encoding="utf-8",
    )
    try:
        filter_graph = (
            f"atrim=0:{SEQUENCE_DURATION_SECONDS},"
            "afade=t=in:st=0:d=0.02,"
            f"loudnorm=I={TARGET_LUFS}:TP={TARGET_PEAK_DB}:LRA=7,"
            "volume=2dB,"
            "alimiter=limit=0.89:level=false,"
            "afade=t=out:st=19.8:d=0.2"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-af",
                filter_graph,
                "-ac",
                "1",
                "-ar",
                "44100",
                "-b:a",
                "192k",
                str(output_path),
            ],
            check=True,
        )
    finally:
        concat_file.unlink(missing_ok=True)

    return [path.stem for path in chosen]


def measure(path: Path) -> dict[str, float]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    output = completed.stderr
    mean_match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    max_match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    if not mean_match or not max_match:
        raise RuntimeError(f"Could not parse volumedetect output for {path}")

    duration = run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    ).stdout.strip()

    return {
        "mean_db": float(mean_match.group(1)),
        "peak_db": float(max_match.group(1)),
        "duration_seconds": round(float(duration), 3),
    }


def main() -> int:
    if not shutil_which("ffmpeg") or not shutil_which("ffprobe"):
        print("ffmpeg and ffprobe are required", file=sys.stderr)
        return 1

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for old_file in OUTPUT_DIR.glob("*.mp3"):
        old_file.unlink()

    clip_manifest = []
    failures = []
    normalized_clips = []

    missing = WHITELIST - {spec.slug for spec in WHITELISTED_SOUNDS}
    if missing:
        print(f"Whitelist contains unknown sound slugs: {sorted(missing)}", file=sys.stderr)
        return 1

    for spec in WHITELISTED_SOUNDS:
        print(f"Processing {spec.slug}...", flush=True)
        source_path, audio_url = download(spec)
        output_path = OUTPUT_DIR / f"clip_{spec.slug}.mp3"
        normalize(source_path, output_path)
        levels = measure(output_path)
        normalized_clips.append(output_path)

        if levels["peak_db"] < MIN_PEAK_DB or levels["mean_db"] < MIN_MEAN_DB:
            failures.append((spec.slug, levels))

        clip_manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "kind": "source_clip",
                "title": spec.title,
                "category": spec.category,
                "source_page": spec.page_url,
                "source_audio": audio_url,
                "license": "Public domain; National Park Service Sound Gallery",
                **levels,
            }
        )

    rng = random.Random(SEQUENCE_RANDOM_SEED)
    sequence_manifest = []
    for index in range(1, SEQUENCE_COUNT + 1):
        output_path = OUTPUT_DIR / f"alert_sequence_{index:02d}.mp3"
        source_sequence = build_sequence(normalized_clips, output_path, rng)
        levels = measure(output_path)

        if levels["peak_db"] < MIN_PEAK_DB or levels["mean_db"] < MIN_MEAN_DB:
            failures.append((output_path.stem, levels))

        sequence_manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "kind": "alert_sequence",
                "title": f"Alert Sequence {index:02d}",
                "category": "random curated deterrent sequence",
                "source_clips": source_sequence,
                "license": "Public domain; National Park Service Sound Gallery",
                **levels,
            }
        )

    manifest = sequence_manifest + clip_manifest
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"Wrote {MANIFEST}")
    for item in manifest:
        print(
            f"{item['file']}: peak {item['peak_db']} dB, "
            f"mean {item['mean_db']} dB, {item['duration_seconds']}s"
        )

    if failures:
        print("The following files are below the configured loudness thresholds:", file=sys.stderr)
        for slug, levels in failures:
            print(f"  {slug}: {levels}", file=sys.stderr)
        return 1

    return 0


def shutil_which(command: str) -> str | None:
    return shutil.which(command)


if __name__ == "__main__":
    raise SystemExit(main())
