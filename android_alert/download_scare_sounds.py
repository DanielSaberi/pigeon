#!/usr/bin/env python3
"""Download and normalize public-domain scare-alert sounds.

The selected sources are public-domain NPS Sound Gallery clips. Outputs are
short MP3 files normalized for alert playback and verified with ffmpeg's
volumedetect filter.
"""

from __future__ import annotations

import json
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
]


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

    manifest = []
    failures = []

    for spec in SOUNDS:
        print(f"Processing {spec.slug}...", flush=True)
        source_path, audio_url = download(spec)
        output_path = OUTPUT_DIR / f"{spec.slug}.mp3"
        normalize(source_path, output_path)
        levels = measure(output_path)

        if levels["peak_db"] < MIN_PEAK_DB or levels["mean_db"] < MIN_MEAN_DB:
            failures.append((spec.slug, levels))

        manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "title": spec.title,
                "category": spec.category,
                "source_page": spec.page_url,
                "source_audio": audio_url,
                "license": "Public domain; National Park Service Sound Gallery",
                **levels,
            }
        )

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
