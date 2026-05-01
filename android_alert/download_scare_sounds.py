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
STARTLE_LEAD_IN_SECONDS = 2.0
STARTLE_SEGMENT_SECONDS = 1.4
STARTLE_GAP_SECONDS = 0.28
STARTLE_MIN_BURST_PEAK_DB = -2.0
STARTLE_MAX_LEAD_PEAK_DB = -35.0
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
STARTLE_SOURCE_SLUGS = {
    "avalanche",
    "bighorn_ram",
    "cannon_fire",
    "musket_fire",
    "thunder",
}
STARTLE_PATTERNS = [
    ("startle_burst_01", "Cannon Fire Single", ["cannon_fire"]),
    ("startle_burst_02", "Musket Fire Single", ["musket_fire"]),
    ("startle_burst_03", "Bighorn Ram Single", ["bighorn_ram"]),
    ("startle_burst_04", "Thunder Crack", ["thunder"]),
    ("startle_burst_05", "Avalanche Bang", ["avalanche"]),
    ("startle_burst_06", "Cannon Musket Double", ["cannon_fire", "musket_fire"]),
    ("startle_burst_07", "Musket Ram Double", ["musket_fire", "bighorn_ram"]),
    ("startle_burst_08", "Ram Cannon Double", ["bighorn_ram", "cannon_fire"]),
    ("startle_burst_09", "Thunder Musket Double", ["thunder", "musket_fire"]),
    ("startle_burst_10", "Avalanche Cannon Double", ["avalanche", "cannon_fire"]),
]


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
        "avalanche",
        "Avalanche",
        "https://www.nps.gov/subjects/sound/avalanche.htm",
        "impact/startle noise",
    ),
    SoundSpec(
        "bear_cubs",
        "Bear with Cubs",
        "https://www.nps.gov/subjects/sound/sounds-bearcubs.htm",
        "predator/startle",
    ),
    SoundSpec(
        "bighorn_ram",
        "Bighorn Sheep Ramming Heads",
        "https://www.nps.gov/subjects/sound/sounds-bighorn-ram.htm",
        "impact/startle noise",
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
STARTLE_SOUNDS = [spec for spec in SOUNDS if spec.slug in STARTLE_SOURCE_SLUGS]


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


def make_silence(output_path: Path, duration_seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            f"{duration_seconds:.3f}",
            "-ac",
            "1",
            "-ar",
            "44100",
            str(output_path),
        ],
        check=True,
    )


def prepare_startle_segment(source_path: Path, output_path: Path) -> None:
    filter_graph = (
        "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
        f"atrim=0:{STARTLE_SEGMENT_SECONDS},"
        "asetpts=PTS-STARTPTS,"
        "highpass=f=100,"
        "afade=t=in:st=0:d=0.005,"
        f"afade=t=out:st={max(0.0, STARTLE_SEGMENT_SECONDS - 0.08):.3f}:d=0.08,"
        "loudnorm=I=-8:TP=-0.8:LRA=4,"
        "volume=5dB,"
        "alimiter=limit=0.91:level=false"
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
            str(output_path),
        ],
        check=True,
    )


def build_startle_burst(source_paths: list[Path], output_path: Path) -> list[str]:
    """Build a short startle clip with two seconds of lead-in silence."""
    if not source_paths:
        raise ValueError("at least one source path is required")

    temp_dir = output_path.with_suffix(".tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    pieces = []

    try:
        lead_path = temp_dir / "lead.wav"
        make_silence(lead_path, STARTLE_LEAD_IN_SECONDS)
        pieces.append(lead_path)

        for index, source_path in enumerate(source_paths):
            segment_path = temp_dir / f"segment_{index}.wav"
            prepare_startle_segment(source_path, segment_path)
            pieces.append(segment_path)
            if index < len(source_paths) - 1:
                gap_path = temp_dir / f"gap_{index}.wav"
                make_silence(gap_path, STARTLE_GAP_SECONDS)
                pieces.append(gap_path)

        concat_file = temp_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{path.resolve()}'\n" for path in pieces),
            encoding="utf-8",
        )
        filter_graph = "alimiter=limit=0.89:level=false"
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
        shutil.rmtree(temp_dir, ignore_errors=True)

    return [path.stem for path in source_paths]


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


def measure_segment(path: Path, start_seconds: float, duration_seconds: float) -> dict[str, float]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
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

    return {
        "mean_db": float(mean_match.group(1)),
        "peak_db": float(max_match.group(1)),
    }


def first_loud_time(path: Path, threshold_db: str = "-35dB") -> float | None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={threshold_db}:d=0.02",
            "-f",
            "null",
            "-",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    match = re.search(r"silence_end:\s*(\d+(?:\.\d+)?)", completed.stderr)
    if not match:
        return None
    return round(float(match.group(1)), 3)


def inspect_startle(path: Path) -> dict[str, float | None]:
    levels = measure(path)
    lead = measure_segment(path, 0, max(0.1, STARTLE_LEAD_IN_SECONDS - 0.1))
    burst = measure_segment(path, STARTLE_LEAD_IN_SECONDS, max(0.1, levels["duration_seconds"] - STARTLE_LEAD_IN_SECONDS))
    return {
        **levels,
        "lead_peak_db": lead["peak_db"],
        "burst_peak_db": burst["peak_db"],
        "first_loud_time_s": first_loud_time(path),
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
    missing_startle = STARTLE_SOURCE_SLUGS - {spec.slug for spec in STARTLE_SOUNDS}
    if missing_startle:
        print(f"Startle source list contains unknown sound slugs: {sorted(missing_startle)}", file=sys.stderr)
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

    startle_source_paths = {}
    startle_source_urls = {}
    for spec in STARTLE_SOUNDS:
        print(f"Processing startle source {spec.slug}...", flush=True)
        source_path, audio_url = download(spec)
        startle_source_paths[spec.slug] = source_path
        startle_source_urls[spec.slug] = audio_url

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

    startle_manifest = []
    for slug, title, source_slugs in STARTLE_PATTERNS:
        print(f"Building {slug}...", flush=True)
        output_path = OUTPUT_DIR / f"{slug}.mp3"
        source_paths = [startle_source_paths[source_slug] for source_slug in source_slugs]
        source_sequence = build_startle_burst(source_paths, output_path)
        levels = inspect_startle(output_path)

        first_loud = levels["first_loud_time_s"]
        if levels["lead_peak_db"] > STARTLE_MAX_LEAD_PEAK_DB:
            failures.append((slug, {"lead_peak_db": levels["lead_peak_db"]}))
        if levels["burst_peak_db"] < STARTLE_MIN_BURST_PEAK_DB:
            failures.append((slug, {"burst_peak_db": levels["burst_peak_db"]}))
        if first_loud is None or first_loud < STARTLE_LEAD_IN_SECONDS - 0.15:
            failures.append((slug, {"first_loud_time_s": first_loud}))

        startle_manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "kind": "startle_burst",
                "title": title,
                "category": "short impulsive startle with 2s lead-in silence",
                "source_clips": source_sequence,
                "source_pages": [
                    next(spec.page_url for spec in STARTLE_SOUNDS if spec.slug == source_slug)
                    for source_slug in source_slugs
                ],
                "source_audio": [
                    startle_source_urls[source_slug]
                    for source_slug in source_slugs
                ],
                "license": "Public domain; National Park Service Sound Gallery",
                "lead_in_seconds": STARTLE_LEAD_IN_SECONDS,
                **levels,
            }
        )

    manifest = sequence_manifest + startle_manifest + clip_manifest
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
