#!/usr/bin/env python3
"""Rebuild every translated PS2 movie from verified fresh source extracts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import credits_ass
import patch_mpeg2_ps2_headers as headers
import remux_ps2_movie as remux
import verify_remux_timing as timing
from build_ending_movie import (
    lavfi_path, picture_data, sequence_info, video_payload,
)

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent / "PyTOD2"
MOVIE_NAMES = ("00001", "00002", "00003", "00004", "00005", "00007", "00008", "00010")
MINIMUM_LEAD_MS = {
    "00001": 50.0, "00002": 50.0, "00003": 50.0, "00004": 50.0,
    "00005": 50.0, "00007": 0.0, "00008": 10.0, "00010": 40.0,
}
WIDTH, HEIGHT = 640, 448
FPS = "30000/1001"
VBV_BITS = 1_835_008
PSTD_BYTES = 1_841_152
DECLARED_BITRATES = {name: 9_000_000 for name in MOVIE_NAMES}
DECLARED_BITRATES["00010"] = 7_750_000
TARGET_BITRATES = {
    "00001": 7_750_000,
    "00002": 6_000_000,
    "00003": 4_000_000,
    "00004": 6_000_000,
    "00005": 8_250_000,
    "00007": 2_300_000,
    "00008": 2_700_000,
    "00010": 7_750_000,
}
SUBTITLE_SIZE = 20
SUBTITLE_MARGIN = 24
MAX_SUBTITLE_WIDTH = WIDTH - 2 * SUBTITLE_MARGIN
STYLE = (
    "FontName=Ubuntu,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginL=24,MarginR=24,MarginV=24"
)
TIMESTAMP = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)

@dataclass
class Movie:
    name: str
    original: Path
    subtitle: Path
    size: int
    capacity: int
    frames: int
    keyframes: list[int]
    source_sha256: str
    subtitle_cues: int
    aspect_code: int

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def parse_srt(path: Path) -> list[list[str]]:
    blocks = re.split(r"\r?\n\r?\n", path.read_text(encoding="utf-8-sig").strip())
    cues = []
    previous_start = -1
    for expected_index, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(expected_index):
            raise ValueError(f"{path.name}: malformed cue {expected_index}")
        match = TIMESTAMP.fullmatch(lines[1])
        if not match:
            raise ValueError(f"{path.name}: invalid timestamp {lines[1]!r}")
        values = [int(value) for value in match.groups()]
        start = (((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 + values[3])
        end = (((values[4] * 60 + values[5]) * 60 + values[6]) * 1000 + values[7])
        if start < previous_start or end <= start or not any(line.strip() for line in lines[2:]):
            raise ValueError(f"{path.name}: invalid cue order or duration at {expected_index}")
        previous_start = start
        cues.append(lines[2:])
    return cues

def validate_subtitle(path: Path) -> int:
    cues = parse_srt(path)
    metrics = credits_ass.TrueTypeMetrics(credits_ass.FONT_FILE)
    for cue_index, lines in enumerate(cues, 1):
        for line in lines:
            plain = re.sub(r"<[^>]+>", "", line)
            width = metrics.text_width(plain, SUBTITLE_SIZE)
            if width > MAX_SUBTITLE_WIDTH:
                raise ValueError(
                    f"{path.name}: cue {cue_index} line is {width:.1f}px wide; "
                    f"limit is {MAX_SUBTITLE_WIDTH}px"
                )
    return len(cues)

def validate_source(root: Path, name: str) -> Movie:
    original = root / "MOVIE" / f"{name}.mpeg"
    subtitle = root / "MOVIE" / f"{name}.en.srt"
    if not original.is_file() or not subtitle.is_file():
        raise FileNotFoundError(f"{name}: original movie or English SRT is missing")
    data = original.read_bytes()
    packs, packets, audio_packets, audio_bytes = remux.inspect_original(data)
    video = video_payload(data, packets)
    pictures, keyframes = picture_data(video)
    info = sequence_info(video)
    expected = {
        "width": WIDTH, "height": HEIGHT, "frame_rate_code": 4,
        "vbv_bits": VBV_BITS, "profile_level": 0x48, "chroma_format": 1,
    }
    differences = {key: (info[key], value) for key, value in expected.items()
                   if info[key] != value}
    if differences:
        raise ValueError(f"{name}: unexpected source headers: {differences}")
    pstd = remux.video_pstd_buffer_bound(data, packets)
    if pstd != PSTD_BYTES:
        raise ValueError(f"{name}: P-STD bound is {pstd:,}; expected {PSTD_BYTES:,}")
    capacity = sum(packet[4] for packet in packets)
    cues = validate_subtitle(subtitle)
    print(
        f"{name} source OK: size={len(data):,}, packs={packs:,}, "
        f"capacity={capacity:,}, frames={len(pictures):,}, I_frames={len(keyframes):,}, "
        f"audio_packets={audio_packets:,}, audio_bytes={audio_bytes:,}, cues={cues}"
    )
    return Movie(
        name, original, subtitle, len(data), capacity, len(pictures), keyframes,
        hashlib.sha256(data).hexdigest(), cues, info["aspect_code"],
    )

def subtitle_filter(movie: Movie) -> str:
    font_dir = lavfi_path(credits_ass.FONT_FILE.parent)
    srt = lavfi_path(movie.subtitle)
    filters = [
        f"subtitles=filename='{srt}':original_size={WIDTH}x{HEIGHT}:"
        f"fontsdir='{font_dir}':force_style='{STYLE}'"
    ]
    if movie.name == "00005":
        filters.append(
            f"ass=filename='{lavfi_path(credits_ass.OUT)}':fontsdir='{font_dir}'"
        )
    return ",".join(filters)

def encode(
    ffmpeg: str, movie: Movie, output: Path, setting: int, log_path: Path
) -> None:
    keyframe_times = ",".join(
        f"{max(0, frame - 0.5) * 1001 / 30000:.6f}" for frame in movie.keyframes
    )
    rate_control = (
        ["-b:v", str(setting), "-minrate", str(setting),
         "-maxrate", str(DECLARED_BITRATES[movie.name]), "-bufsize", str(VBV_BITS)]
        if movie.name == "00010"
        else ["-b:v", str(setting), "-qmin", "1",
              "-maxrate", str(DECLARED_BITRATES[movie.name]), "-bufsize", str(VBV_BITS)]
    )
    command = [
        ffmpeg, "-hide_banner", "-y", "-loglevel", "verbose",
        "-i", str(movie.original), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", subtitle_filter(movie),
        "-c:v", "mpeg2video", "-profile:v", "main", "-level:v", "main",
        "-pix_fmt", "yuv420p", "-r", FPS, "-fps_mode", "cfr",
        "-frames:v", str(movie.frames),
        "-g", "18", "-bf", "2", "-b_strategy", "0",
        *rate_control, "-sc_threshold", "1000000000", "-force_key_frames", keyframe_times,
        "-f", "mpeg2video", str(output),
    ]
    if movie.aspect_code == 2:
        command[command.index("-g"):command.index("-g")] = ["-aspect", "4:3"]
    setting_text = (
        f"{setting:,} bit/s CBR" if movie.name == "00010"
        else f"{setting:,} bit/s average"
    )
    print(f"{movie.name}: encoding at {setting_text}...")
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        subprocess.run(
            command, check=True, stdout=log, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
        )
    log_text = log_path.read_text(encoding="utf-8")
    if "libass API version" not in log_text or "fontselect:" not in log_text:
        raise ValueError(f"{movie.name}: FFmpeg log does not confirm libass/font selection")
    expected_filters = 2 if movie.name == "00005" else 1
    if log_text.count("libass API version") < expected_filters:
        raise ValueError("00005: both dialogue SRT and ending-credit ASS must load through libass")
    if log_text.count("Ubuntu-Bold") < expected_filters:
        raise ValueError(f"{movie.name}: bundled Ubuntu Bold was not selected for every subtitle layer")
    actual_errors = [
        line for line in log_text.splitlines()
        if re.search(r"\]\s+(?:Error|Failed)\b", line, re.IGNORECASE)
    ]
    if actual_errors:
        raise ValueError(f"{movie.name}: FFmpeg reported subtitle/encode errors: {actual_errors}")

def validate_raw(movie: Movie, path: Path) -> bytes:
    video = path.read_bytes()
    if len(video) > movie.capacity:
        raise ValueError(
            f"{movie.name}: encode is {len(video):,} bytes but capacity is "
            f"{movie.capacity:,}"
        )
    pictures, keyframes = picture_data(video)
    if len(pictures) != movie.frames:
        raise ValueError(
            f"{movie.name}: encode has {len(pictures):,} frames; expected {movie.frames:,}"
        )
    missing = sorted(set(movie.keyframes) - set(keyframes))
    unexpected = sorted(set(keyframes) - set(movie.keyframes) - {movie.frames - 1})
    if missing or unexpected:
        raise ValueError(
            f"{movie.name}: I-frame mismatch; missing={missing}, unexpected={unexpected}"
        )
    print(
        f"{movie.name} encode OK: {len(video):,}/{movie.capacity:,} bytes, "
        f"frames={len(pictures):,}, source I-frames preserved"
    )
    return video

def verify_movie_sequence(movie: Movie, video: bytes) -> None:
    actual = sequence_info(video)
    expected = {
        "width": WIDTH, "height": HEIGHT, "aspect_code": movie.aspect_code,
        "frame_rate_code": 4, "declared_bitrate": DECLARED_BITRATES[movie.name],
        "vbv_bits": VBV_BITS, "profile_level": 0x48, "progressive": 1,
        "chroma_format": 1,
    }
    differences = {key: (actual[key], value) for key, value in expected.items()
                   if actual[key] != value}
    if differences:
        raise ValueError(f"{movie.name}: replacement header mismatch: {differences}")

def verify_fresh_sources(root: Path, movies: list[Movie]) -> None:
    backup = root / "MOVIE.FPB.before-hardsubs.bak"
    executable = HERE.parent / "scripts" / "SLPS_251.72"
    if not backup.is_file() or not executable.is_file():
        raise FileNotFoundError("pre-hardsub MOVIE.FPB backup or SLPS pointer table is missing")
    pointers = struct.unpack_from("<12I", executable.read_bytes(), 0xE62F0)
    with backup.open("rb") as archive:
        for movie in movies:
            number = int(movie.name)
            remainder = pointers[number] & 0x3F
            start = pointers[number] & 0xFFFFFFC0
            end = (pointers[number + 1] & 0xFFFFFFC0) - remainder
            if end - start != movie.size:
                raise ValueError(f"{movie.name}: backup slot size differs from source extract")
            digest = hashlib.sha256()
            archive.seek(start)
            remaining = movie.size
            while remaining:
                block = archive.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError(f"{movie.name}: backup archive ended early")
                digest.update(block)
                remaining -= len(block)
            if digest.hexdigest() != movie.source_sha256:
                raise ValueError(f"{movie.name}: source extract is not the fresh backup slot")
            print(f"{movie.name}: fresh backup slot confirmed")

def build_movie(
    ffmpeg: str, movie: Movie, stage: Path, work: Path, bitrate_step: int,
) -> dict[str, object]:
    movie_work = work / movie.name
    movie_work.mkdir(parents=True, exist_ok=True)
    raw_path = movie_work / f"{movie.name}.raw.m2v"
    patched_path = movie_work / f"{movie.name}.ps2.m2v"
    candidate = movie_work / f"{movie.name}.mpeg"
    log_path = movie_work / f"{movie.name}.ffmpeg.log"

    last_error = None
    settings = range(TARGET_BITRATES[movie.name], 999_999, -bitrate_step)
    for setting in settings:
        for path in (raw_path, patched_path, candidate):
            if path.exists():
                path.unlink()
        encode(ffmpeg, movie, raw_path, setting, log_path)
        if raw_path.stat().st_size > movie.capacity:
            last_error = ValueError(
                f"encoded payload {raw_path.stat().st_size:,} exceeds "
                f"{movie.capacity:,} bytes"
            )
            next_setting = setting - bitrate_step
            print(f"{movie.name}: {last_error}; retrying with setting {next_setting}")
            continue
        raw = validate_raw(movie, raw_path)
        patched, sequence_count, picture_count = headers.patch_headers(
            raw, DECLARED_BITRATES[movie.name]
        )
        if sequence_count < 1 or picture_count != movie.frames:
            raise ValueError(
                f"{movie.name}: header patch saw {sequence_count} sequences and "
                f"{picture_count} pictures"
            )
        patched_path.write_bytes(patched)
        verify_movie_sequence(movie, patched)
        try:
            metrics = remux.remux(
                movie.original, patched_path, candidate,
                buffer_aware=True,
                minimum_decode_lead_ms=MINIMUM_LEAD_MS[movie.name],
            )
        except ValueError as error:
            retryable = any(word in str(error) for word in (
                "capacity", "decode deadline", "pre-decode", "P-STD", "underflow"
            ))
            has_retry = setting - bitrate_step >= 1_000_000
            if retryable and has_retry:
                last_error = error
                next_setting = setting - bitrate_step
                print(f"{movie.name}: {error}; retrying with setting {next_setting}")
                continue
            raise
        timing.verify(movie.original, candidate, remux)
        candidate_data = candidate.read_bytes()
        if len(candidate_data) != movie.size:
            raise ValueError(
                f"{movie.name}: output is {len(candidate_data):,}; expected {movie.size:,}"
            )
        _packs, packets, _audio_count, _audio_bytes = remux.inspect_original(candidate_data)
        verify_movie_sequence(movie, video_payload(candidate_data, packets))
        output = stage / f"{movie.name}.mpeg"
        os.replace(candidate, output)
        result = {
            "name": movie.name,
            "source_sha256": movie.source_sha256,
            "output_sha256": sha256(output),
            "size": movie.size,
            "subtitle_cues": movie.subtitle_cues,
            "credits_overlay": movie.name == "00005",
            "rate_control": "constant_bitrate" if movie.name == "00010" else "average_bitrate",
            "rate_setting": setting,
            "aspect_code": movie.aspect_code,
            "declared_bitrate": DECLARED_BITRATES[movie.name],
            "encoded_video_bytes": metrics["new_video"],
            "video_capacity_bytes": metrics["video_capacity"],
            "frames": metrics["frames"],
            "i_frames": len(movie.keyframes),
            "terminal_i_frame_allowed": True,
            "audio_packets": metrics["audio_packets"],
            "audio_packet_bytes": metrics["audio_packet_bytes"],
            "pstd_maximum_bytes": metrics["maximum_occupancy"],
            "pstd_bound_bytes": metrics["buffer_bound"],
            "minimum_decode_lead_ms": round(metrics["minimum_lead_27mhz"] / 27_000, 3),
            "padding_slots": metrics["padding_slots"],
        }
        print(f"{movie.name}: fully verified -> {output}")
        return result
    raise ValueError(f"{movie.name}: no safe bitrate setting succeeded: {last_error}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--bitrate-step", type=int, default=250_000)
    parser.add_argument("--names", nargs="+", choices=MOVIE_NAMES, default=MOVIE_NAMES)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.bitrate_step < 100_000:
        parser.error("--bitrate-step must be at least 100000")

    root = args.root.resolve()
    rendered, event_count = credits_ass.render_ass()
    if not credits_ass.OUT.exists() or credits_ass.OUT.read_text(encoding="utf-8") != rendered:
        raise ValueError("ending_credits.ass is stale; run credits_ass.py first")
    print(f"credits OK: {event_count} events, pinned font and fitting verified")
    movies = [validate_source(root, name) for name in args.names]
    verify_fresh_sources(root, movies)
    if args.validate_only:
        return

    ffmpeg = shutil.which(args.ffmpeg)
    if ffmpeg is None and Path(args.ffmpeg).is_file():
        ffmpeg = str(Path(args.ffmpeg).resolve())
    if ffmpeg is None:
        raise FileNotFoundError("FFmpeg was not found; pass --ffmpeg with its full path")
    version = subprocess.run(
        [ffmpeg, "-hide_banner", "-version"], check=True, capture_output=True,
        text=True, errors="replace",
    ).stdout.splitlines()[0]
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], check=True, capture_output=True,
        text=True, errors="replace",
    ).stdout
    if not re.search(r"^\s*...\s+ass\s", filters, re.MULTILINE):
        raise ValueError("this FFmpeg build does not provide the libass filter")

    stage = (args.stage_dir or (root / "hardsubbed_movies.rebuilt")).resolve()
    work = (args.work_dir or (root / ".movie-rebuild-work")).resolve()
    for folder, label in ((stage, "stage"), (work, "work")):
        if folder.exists() and any(folder.iterdir()):
            raise ValueError(f"{label} directory must be empty: {folder}")
        folder.mkdir(parents=True, exist_ok=True)

    results = []
    for movie in movies:
        results.append(
            build_movie(ffmpeg, movie, stage, work, args.bitrate_step)
        )
    manifest = {
        "ffmpeg": version,
        "font_sha256": credits_ass.FONT_SHA256,
        "subtitle_style": STYLE,
        "movies": results,
    }
    manifest_path = stage / "build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"all {len(results)} movies passed; manifest: {manifest_path}")
    print("the existing hardsubbed_movies directory was not modified")

if __name__ == "__main__":
    main()
