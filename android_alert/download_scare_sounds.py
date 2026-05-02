#!/usr/bin/env python3
"""Download and normalize public-domain/CC0 scare-alert sounds.

The long alert sequences use public-domain NPS Sound Gallery clips. The short
startle bursts use separate gunshot, explosion, and clap sources.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
import zipfile
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
STARTLE_MIN_BURST_PEAK_DB = -2.0
STARTLE_MIN_ATTACK_MEAN_DB = -18.0
STARTLE_ATTACK_WINDOW_SECONDS = 0.12
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
STARTLE_PATTERNS = [
    ("startle_burst_01", "Basic Gunshot", "oga_basic_gunshot", 1.00, 0.45),
    ("startle_burst_02", "Clapperboard Thwack 08", "oga_thwack_08", 1.00, 0.50),
    ("startle_burst_03", "Wood Hammer Clap 01", "oga_wood_hammer_01", 1.00, 0.36),
    ("startle_burst_04", "Wood Clap Hit 09", "oga_wood_hit_09", 1.00, 0.36),
    ("startle_burst_05", "Wood Clap Hit 02", "oga_sfx100v2_wood_hit_02", 1.00, 0.42),
    ("startle_burst_06", "Wood Board Clap", "oga_wood_misc_06", 1.00, 0.45),
    ("startle_burst_07", "9mm Gunshot Brighter", "commons_9mm_gunshot", 1.08, 0.38),
    ("startle_burst_08", "Short Thwack 01", "oga_thwack_01", 1.00, 0.38),
    ("startle_burst_10", "Metal Sheet Clap", "oga_metal_sheet_05", 1.00, 0.36),
]

STARTLE_COMBO_PATTERNS = [
    ("startle_combo_01", "Gunshot Clap Stack A", [
        "startle_burst_01",
        "startle_burst_02",
        "startle_burst_03",
        "startle_burst_07",
    ]),
    ("startle_combo_02", "Wood Hit Stack A", [
        "startle_burst_04",
        "startle_burst_05",
        "startle_burst_06",
        "startle_burst_10",
    ]),
    ("startle_combo_03", "Clap Stack A", [
        "startle_burst_07",
        "startle_burst_02",
        "startle_burst_03",
        "startle_burst_10",
    ]),
    ("startle_combo_04", "Mixed Stack A", [
        "startle_burst_07",
        "startle_burst_04",
        "startle_burst_05",
        "startle_burst_01",
    ]),
    ("startle_combo_05", "Mixed Stack B", [
        "startle_burst_01",
        "startle_burst_06",
        "startle_burst_08",
        "startle_burst_04",
    ]),
    ("startle_combo_06", "Gunshot Wood Stack", [
        "startle_burst_07",
        "startle_burst_02",
        "startle_burst_05",
        "startle_burst_10",
    ]),
    ("startle_combo_07", "Clap Wood Stack", [
        "startle_burst_03",
        "startle_burst_04",
        "startle_burst_08",
        "startle_burst_06",
    ]),
    ("startle_combo_08", "Hard Hit Stack", [
        "startle_burst_01",
        "startle_burst_10",
        "startle_burst_04",
        "startle_burst_07",
    ]),
    ("startle_combo_09", "Thwack Stack B", [
        "startle_burst_01",
        "startle_burst_06",
        "startle_burst_03",
        "startle_burst_08",
    ]),
    ("startle_combo_10", "Clap Stack B", [
        "startle_burst_07",
        "startle_burst_01",
        "startle_burst_05",
        "startle_burst_04",
    ]),
]


@dataclass(frozen=True)
class SoundSpec:
    slug: str
    title: str
    page_url: str
    category: str


@dataclass(frozen=True)
class DirectSoundSpec:
    slug: str
    title: str
    page_url: str
    audio_url: str
    category: str
    license: str
    author: str
    archive_member: str | None = None


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
STARTLE_SOURCES = [
    DirectSoundSpec(
        "oga_22_pistol",
        "22 Pistol",
        "https://opengameart.org/content/gunshots",
        "https://opengameart.org/sites/default/files/22%20Pistol.wav",
        "gunshot",
        "CC0; OpenGameArt",
        "kurt",
    ),
    DirectSoundSpec(
        "oga_22_magnum",
        "22 Magnum",
        "https://opengameart.org/content/gunshots",
        "https://opengameart.org/sites/default/files/22%20Magnum.wav",
        "gunshot",
        "CC0; OpenGameArt",
        "kurt",
    ),
    DirectSoundSpec(
        "oga_black_powder",
        "Black Powder",
        "https://opengameart.org/content/gunshots",
        "https://opengameart.org/sites/default/files/Black%20Powder.wav",
        "gunshot",
        "CC0; OpenGameArt",
        "kurt",
    ),
    DirectSoundSpec(
        "oga_basic_gunshot",
        "Basic Gunshot",
        "https://opengameart.org/content/basic-sound-effects",
        "https://opengameart.org/sites/default/files/gunshot_0.mp3",
        "gunshot",
        "CC0; OpenGameArt",
        "n4",
    ),
    DirectSoundSpec(
        "commons_gunshots_8",
        "Gunshots 8",
        "https://commons.wikimedia.org/wiki/File:Gunshots_8.ogg",
        "https://upload.wikimedia.org/wikipedia/commons/e/ee/Gunshots_8.ogg",
        "gunshot",
        "Public domain; Wikimedia Commons / PDSounds",
        "aradlaw",
    ),
    DirectSoundSpec(
        "commons_9mm_gunshot",
        "9 mm gunshot",
        "https://commons.wikimedia.org/wiki/File:9_mm_gunshot-mike-koenig-123.wav",
        "https://upload.wikimedia.org/wikipedia/commons/0/05/9_mm_gunshot-mike-koenig-123.wav",
        "gunshot",
        "CC BY-SA 4.0; Wikimedia Commons",
        "Dantedun",
    ),
    DirectSoundSpec(
        "oga_chunky_explosion",
        "Chunky Explosion",
        "https://opengameart.org/content/chunky-explosion",
        "https://opengameart.org/sites/default/files/Chunky%20Explosion.mp3",
        "explosion",
        "CC0; OpenGameArt",
        "Joth",
    ),
    DirectSoundSpec(
        "oga_retro_explosion",
        "Retro Explosion",
        "https://opengameart.org/content/explosion-0",
        "https://opengameart.org/sites/default/files/explosion.wav",
        "explosion",
        "CC0; OpenGameArt",
        "TinyWorlds",
    ),
    DirectSoundSpec(
        "oga_basic_explosion",
        "Basic Explosion",
        "https://opengameart.org/content/basic-sound-effects",
        "https://opengameart.org/sites/default/files/explosion_0.mp3",
        "explosion",
        "CC0; OpenGameArt",
        "n4",
    ),
    DirectSoundSpec(
        "commons_clap_leaving",
        "Clapping Then Leaving",
        "https://commons.wikimedia.org/wiki/File:619016_mrrap4food_clapping-then-leaving.mp3",
        "https://upload.wikimedia.org/wikipedia/commons/0/02/619016_mrrap4food_clapping-then-leaving.mp3",
        "clap",
        "CC0; Wikimedia Commons / Freesound",
        "mrrap4food",
    ),
    DirectSoundSpec(
        "oga_thwack_08",
        "Thwack 08",
        "https://opengameart.org/content/thwack-sounds",
        "https://opengameart.org/sites/default/files/thwack-1.0.zip",
        "clap/slap",
        "CC0; OpenGameArt",
        "Jordan Irwin (AntumDeluge)",
        "PCM/thwack-08.wav",
    ),
    DirectSoundSpec(
        "oga_thwack_03",
        "Thwack 03",
        "https://opengameart.org/content/thwack-sounds",
        "https://opengameart.org/sites/default/files/thwack-1.0.zip",
        "clap/slap",
        "CC0; OpenGameArt",
        "Jordan Irwin (AntumDeluge)",
        "PCM/thwack-03.wav",
    ),
    DirectSoundSpec(
        "oga_thwack_01",
        "Thwack 01",
        "https://opengameart.org/content/thwack-sounds",
        "https://opengameart.org/sites/default/files/thwack-1.0.zip",
        "clap/slap",
        "CC0; OpenGameArt",
        "Jordan Irwin (AntumDeluge)",
        "PCM/thwack-01.wav",
    ),
    DirectSoundSpec(
        "oga_wood_hit_09",
        "Wood Hit 09",
        "https://opengameart.org/content/100-cc0-metal-and-wood-sfx",
        "https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip",
        "wood clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "wood_hit_09.ogg",
    ),
    DirectSoundSpec(
        "oga_wood_hammer_01",
        "Wood Hammer 01",
        "https://opengameart.org/content/100-cc0-metal-and-wood-sfx",
        "https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip",
        "wood clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "wood_hammer_01.ogg",
    ),
    DirectSoundSpec(
        "oga_wood_misc_06",
        "Wood Misc 06",
        "https://opengameart.org/content/100-cc0-metal-and-wood-sfx",
        "https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip",
        "wood clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "wood_misc_06.ogg",
    ),
    DirectSoundSpec(
        "oga_wood_hit_07",
        "Wood Hit 07",
        "https://opengameart.org/content/100-cc0-metal-and-wood-sfx",
        "https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip",
        "wood clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "wood_hit_07.ogg",
    ),
    DirectSoundSpec(
        "oga_metal_sheet_05",
        "Metal Sheet 05",
        "https://opengameart.org/content/100-cc0-metal-and-wood-sfx",
        "https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip",
        "metal clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "metal_sheet_05.ogg",
    ),
    DirectSoundSpec(
        "oga_sfx100v2_wood_hit_02",
        "SFX100v2 Wood Hit 02",
        "https://opengameart.org/content/100-cc0-sfx-2",
        "https://opengameart.org/sites/default/files/sfx_100_v2.zip",
        "wood clap/hit",
        "CC0; OpenGameArt",
        "rubberduck",
        "sfx100v2_wood_hit_02.ogg",
    ),
]
STARTLE_SOURCES_BY_SLUG = {spec.slug: spec for spec in STARTLE_SOURCES}


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
    if not source_path.exists():
        source_path.write_bytes(fetch_bytes(audio_url))
    return source_path, audio_url


def download_direct(spec: DirectSoundSpec) -> Path:
    if spec.archive_member is not None:
        archive_suffix = Path(spec.audio_url.split("?", 1)[0]).suffix or ".zip"
        archive_path = SOURCE_DIR / f"{spec.slug}_archive{archive_suffix}"
        member_path = Path(spec.archive_member)
        source_path = SOURCE_DIR / f"{spec.slug}{member_path.suffix}"
        if not source_path.exists():
            if not archive_path.exists():
                archive_path.write_bytes(fetch_bytes(spec.audio_url))
            with zipfile.ZipFile(archive_path) as archive:
                if spec.archive_member not in archive.namelist():
                    raise RuntimeError(f"{spec.archive_member} not found in {archive_path}")
                source_path.write_bytes(archive.read(spec.archive_member))
        return source_path

    suffix = Path(spec.audio_url.split("?", 1)[0]).suffix or ".mp3"
    source_path = SOURCE_DIR / f"{spec.slug}{suffix}"
    if not source_path.exists():
        source_path.write_bytes(fetch_bytes(spec.audio_url))
    return source_path


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


def prepare_startle_segment(source_path: Path, output_path: Path,
                            segment_seconds: float,
                            pitch_factor: float) -> None:
    sample_rate = max(32000, int(round(44100 * pitch_factor)))
    filter_graph = (
        "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
        f"apad=pad_dur={segment_seconds},atrim=0:{segment_seconds},"
        "asetpts=PTS-STARTPTS,"
        f"asetrate={sample_rate},aresample=44100,"
        "highpass=f=140,"
        "afade=t=in:st=0:d=0.002,"
        f"afade=t=out:st={max(0.0, segment_seconds - 0.04):.3f}:d=0.04,"
        "loudnorm=I=-5:TP=-0.7:LRA=2,"
        "volume=8dB,"
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


def build_startle_burst(source_path: Path, output_path: Path,
                        pitch_factor: float, segment_seconds: float) -> list[str]:
    """Build a short startle clip with two seconds of lead-in silence."""
    temp_dir = output_path.with_suffix(".tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    pieces = []

    try:
        lead_path = temp_dir / "lead.wav"
        make_silence(lead_path, STARTLE_LEAD_IN_SECONDS)
        pieces.append(lead_path)

        segment_path = temp_dir / "segment.wav"
        prepare_startle_segment(source_path, segment_path, segment_seconds, pitch_factor)
        pieces.append(segment_path)

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

    return [source_path.stem]


def build_startle_combo(source_paths: list[Path], output_path: Path) -> list[str]:
    """Build a short startle clip from four existing startle files."""
    temp_dir = output_path.with_suffix(".combo.tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    pieces = []

    try:
        lead_path = temp_dir / "lead.wav"
        make_silence(lead_path, STARTLE_LEAD_IN_SECONDS)
        pieces.append(lead_path)

        for index, source_path in enumerate(source_paths):
            segment_path = temp_dir / f"segment_{index:02d}.wav"
            prepare_combo_segment(source_path, segment_path, 0.60)
            pieces.append(segment_path)

            if index != len(source_paths) - 1:
                gap_path = temp_dir / f"gap_{index:02d}.wav"
                make_silence(gap_path, 0.08)
                pieces.append(gap_path)

        concat_file = temp_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{path.resolve()}'\n" for path in pieces),
            encoding="utf-8",
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
                "alimiter=limit=0.89:level=false",
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


def prepare_combo_segment(source_path: Path, output_path: Path, segment_seconds: float) -> None:
    filter_graph = (
        "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
        f"atrim=0:{segment_seconds},"
        "afade=t=in:st=0:d=0.003,"
        f"afade=t=out:st={max(0.0, segment_seconds - 0.06):.3f}:d=0.06,"
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
            "-b:a",
            "192k",
            str(output_path),
        ],
        check=True,
    )


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
    missing_startle = {
        source_slug
        for _, _, source_slug, _, _ in STARTLE_PATTERNS
        if source_slug not in STARTLE_SOURCES_BY_SLUG
    }
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
    for spec in STARTLE_SOURCES:
        print(f"Processing startle source {spec.slug}...", flush=True)
        source_path = download_direct(spec)
        startle_source_paths[spec.slug] = source_path

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
    for slug, title, source_slug, pitch_factor, segment_seconds in STARTLE_PATTERNS:
        print(f"Building {slug}...", flush=True)
        output_path = OUTPUT_DIR / f"{slug}.mp3"
        source_spec = STARTLE_SOURCES_BY_SLUG[source_slug]
        source_path = startle_source_paths[source_slug]
        source_sequence = build_startle_burst(
            source_path,
            output_path,
            pitch_factor,
            segment_seconds,
        )
        levels = inspect_startle(output_path)
        attack = measure_segment(
            output_path,
            STARTLE_LEAD_IN_SECONDS - 0.05,
            STARTLE_ATTACK_WINDOW_SECONDS,
        )

        first_loud = levels["first_loud_time_s"]
        if levels["lead_peak_db"] > STARTLE_MAX_LEAD_PEAK_DB:
            failures.append((slug, {"lead_peak_db": levels["lead_peak_db"]}))
        if levels["burst_peak_db"] < STARTLE_MIN_BURST_PEAK_DB:
            failures.append((slug, {"burst_peak_db": levels["burst_peak_db"]}))
        if attack["mean_db"] < STARTLE_MIN_ATTACK_MEAN_DB:
            failures.append((slug, {"attack_mean_db": attack["mean_db"]}))
        if first_loud is None or first_loud < STARTLE_LEAD_IN_SECONDS - 0.15:
            failures.append((slug, {"first_loud_time_s": first_loud}))

        startle_manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "kind": "startle_burst",
                "title": title,
                "category": "short impulsive startle with 2s lead-in silence",
                "source_clips": source_sequence,
                "source_slug": source_spec.slug,
                "source_page": source_spec.page_url,
                "source_audio": source_spec.audio_url,
                "source_author": source_spec.author,
                "license": source_spec.license,
                "lead_in_seconds": STARTLE_LEAD_IN_SECONDS,
                "pitch_factor": pitch_factor,
                "attack_window_seconds": STARTLE_ATTACK_WINDOW_SECONDS,
                "attack_mean_db": attack["mean_db"],
                "attack_peak_db": attack["peak_db"],
                **levels,
            }
        )

    combo_manifest = []
    combo_source_paths = {
        path.stem: path
        for path in OUTPUT_DIR.glob("startle_burst_*.mp3")
    }
    missing_combo = {
        source_name
        for _, _, source_names in STARTLE_COMBO_PATTERNS
        for source_name in source_names
        if source_name not in combo_source_paths
    }
    if missing_combo:
        print(f"Missing combo sources: {sorted(missing_combo)}", file=sys.stderr)
        return 1

    for slug, title, source_names in STARTLE_COMBO_PATTERNS:
        print(f"Building {slug}...", flush=True)
        output_path = OUTPUT_DIR / f"{slug}.mp3"
        source_paths = [combo_source_paths[name] for name in source_names]
        source_sequence = build_startle_combo(source_paths, output_path)
        levels = inspect_startle(output_path)
        attack = measure_segment(
            output_path,
            STARTLE_LEAD_IN_SECONDS - 0.05,
            STARTLE_ATTACK_WINDOW_SECONDS,
        )

        first_loud = levels["first_loud_time_s"]
        if levels["lead_peak_db"] > STARTLE_MAX_LEAD_PEAK_DB:
            failures.append((slug, {"lead_peak_db": levels["lead_peak_db"]}))
        if levels["burst_peak_db"] < STARTLE_MIN_BURST_PEAK_DB:
            failures.append((slug, {"burst_peak_db": levels["burst_peak_db"]}))
        if attack["mean_db"] < STARTLE_MIN_ATTACK_MEAN_DB:
            failures.append((slug, {"attack_mean_db": attack["mean_db"]}))
        if first_loud is None or first_loud < STARTLE_LEAD_IN_SECONDS - 0.15:
            failures.append((slug, {"first_loud_time_s": first_loud}))

        combo_manifest.append(
            {
                "file": str(output_path.relative_to(ROOT)),
                "kind": "startle_combo",
                "title": title,
                "category": "4-sound combo with 2s lead-in silence",
                "source_clips": source_sequence,
                "source_kind": "startle_burst",
                "source_count": len(source_sequence),
                "lead_in_seconds": STARTLE_LEAD_IN_SECONDS,
                "attack_window_seconds": STARTLE_ATTACK_WINDOW_SECONDS,
                "attack_mean_db": attack["mean_db"],
                "attack_peak_db": attack["peak_db"],
                **levels,
            }
        )

    manifest = sequence_manifest + startle_manifest + combo_manifest + clip_manifest
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
