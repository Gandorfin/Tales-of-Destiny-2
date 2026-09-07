#!/usr/bin/env python3
"""Build a release-safe English ending movie for Tales of Destiny 2 PS2."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import credits_ass
import patch_mpeg2_ps2_headers as headers
import remux_ps2_movie as remux
import verify_remux_timing as timing

EXPECTED_SIZE = 405_274_628
EXPECTED_CAPACITY = 379_099_747
EXPECTED_FRAMES = 13_127
EXPECTED_PSTD_BYTES = 1_841_152
WIDTH, HEIGHT = 640, 448
FPS = "30000/1001"
VIDEO_BITRATE = 8_250_000
MAXRATE = 9_000_000
VBV_BITS = 1_835_008
DECLARED_BITRATE = 9_000_000
MINIMUM_DECODE_LEAD_MS = 50.0
SUBTITLE_STYLE = (
    "FontName=Ubuntu,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginL=24,MarginR=24,MarginV=24"
)

def video_payload(data: bytes, packets: list[tuple]) -> bytes:
    result = bytearray()
    for pack_index, start, end, payload_at, _capacity in packets:
        base = pack_index * remux.PACK_SIZE
        result.extend(data[base + start + payload_at:base + end])
    return bytes(result)

def picture_data(video: bytes) -> tuple[list[tuple[int, int, int]], list[int]]:
    pictures = remux.picture_timestamps(video)
    keyframes = [
        (pts - pictures[0][1]) // 3_003
        for offset, pts, _dts in pictures
        if ((video[offset + 5] >> 3) & 7) == 1
    ]
    return pictures, keyframes

def sequence_info(video: bytes) -> dict[str, int]:
    sequence = video.find(remux.START + b"\xB3")
    if sequence < 0 or sequence + 12 > len(video):
        raise ValueError("MPEG-2 sequence header is missing")
    width = (video[sequence + 4] << 4) | (video[sequence + 5] >> 4)
    height = ((video[sequence + 5] & 15) << 8) | video[sequence + 6]
    aspect = video[sequence + 7] >> 4
    frame_rate = video[sequence + 7] & 15
    bitrate_value = (
        (video[sequence + 8] << 10)
        | (video[sequence + 9] << 2)
        | (video[sequence + 10] >> 6)
    )
    vbv_value = ((video[sequence + 10] & 31) << 5) | (video[sequence + 11] >> 3)
    extension = -1
    search_at = sequence + 12
    while True:
        candidate = video.find(remux.START + b"\xB5", search_at)
        if candidate < 0 or candidate + 6 > len(video):
            break
        if video[candidate + 4] >> 4 == 1:
            extension = candidate
            break
        search_at = candidate + 4
    if extension < 0:
        raise ValueError("MPEG-2 sequence extension is missing")
    return {
        "width": width,
        "height": height,
        "aspect_code": aspect,
        "frame_rate_code": frame_rate,
        "declared_bitrate": bitrate_value * 400,
        "vbv_bits": vbv_value * 16_384,
        "profile_level": ((video[extension + 4] & 15) << 4) | (video[extension + 5] >> 4),
        "progressive": (video[extension + 5] >> 3) & 1,
        "chroma_format": (video[extension + 5] >> 1) & 3,
    }

def verify_sequence(video: bytes) -> None:
    actual = sequence_info(video)
    expected = {
        "width": WIDTH,
        "height": HEIGHT,
        "aspect_code": 2,
        "frame_rate_code": 4,
        "declared_bitrate": DECLARED_BITRATE,
        "vbv_bits": VBV_BITS,
        "profile_level": 0x48,
        "progressive": 1,
        "chroma_format": 1,
    }
    differences = {
        key: (actual[key], value) for key, value in expected.items()
        if actual[key] != value
    }
    if differences:
        raise ValueError(f"replacement MPEG-2 headers do not match PS2 requirements: {differences}")

def validate_original(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) != EXPECTED_SIZE:
        raise ValueError(f"ending movie is {len(data):,} bytes; expected {EXPECTED_SIZE:,}")
    packs, packets, audio_packets, audio_bytes = remux.inspect_original(data)
    capacity = sum(packet[4] for packet in packets)
    if capacity != EXPECTED_CAPACITY:
        raise ValueError(f"video capacity is {capacity:,}; expected {EXPECTED_CAPACITY:,}")
    video = video_payload(data, packets)
    pictures, keyframes = picture_data(video)
    if len(pictures) != EXPECTED_FRAMES:
        raise ValueError(f"ending movie has {len(pictures):,} frames; expected {EXPECTED_FRAMES:,}")
    pstd_bytes = remux.video_pstd_buffer_bound(data, packets)
    if pstd_bytes != EXPECTED_PSTD_BYTES:
        raise ValueError(f"P-STD bound is {pstd_bytes:,} bytes; expected {EXPECTED_PSTD_BYTES:,}")
    print(
        f"original OK: size={len(data):,}, packs={packs:,}, "
        f"video_capacity={capacity:,}, frames={len(pictures):,}, "
        f"I_frames={len(keyframes):,}, audio_packets={audio_packets:,}, "
        f"audio_packet_bytes={audio_bytes:,}, P-STD={pstd_bytes:,} bytes"
    )
    return keyframes

def lavfi_path(path: Path) -> str:
    return path.resolve().as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

def encode(
    ffmpeg: str, original: Path, subtitle: Path, raw_video: Path,
    keyframes: list[int],
) -> None:
    keyframe_times = ",".join(
        f"{max(0, frame - 0.5) * 1001 / 30000:.6f}" for frame in keyframes
    )
    font_dir = lavfi_path(credits_ass.FONT_FILE.parent)
    video_filter = (
        f"subtitles=filename='{lavfi_path(subtitle)}':original_size={WIDTH}x{HEIGHT}:"
        f"fontsdir='{font_dir}':force_style='{SUBTITLE_STYLE}',"
        f"ass=filename='{lavfi_path(credits_ass.OUT)}':fontsdir='{font_dir}'"
    )
    command = [
        ffmpeg, "-hide_banner", "-y", "-i", str(original),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", video_filter,
        "-c:v", "mpeg2video", "-profile:v", "main", "-level:v", "main",
        "-pix_fmt", "yuv420p", "-r", FPS, "-fps_mode", "cfr",
        "-frames:v", str(EXPECTED_FRAMES), "-aspect", "4:3",
        "-g", "18", "-bf", "2", "-b_strategy", "0",
        "-b:v", str(VIDEO_BITRATE), "-qmin", "1", "-maxrate", str(MAXRATE),
        "-bufsize", str(VBV_BITS), "-sc_threshold", "1000000000",
        "-force_key_frames", keyframe_times,
        "-f", "mpeg2video", str(raw_video),
    ]
    print("encoding dialogue subtitles and translated credits with FFmpeg...")
    subprocess.run(command, check=True)

def check_encoded_video(raw_video: Path, original_keyframes: list[int]) -> bytes:
    video = raw_video.read_bytes()
    if len(video) > EXPECTED_CAPACITY:
        raise ValueError(
            f"encoded video is {len(video):,} bytes, over capacity by "
            f"{len(video) - EXPECTED_CAPACITY:,} bytes"
        )
    pictures, keyframes = picture_data(video)
    if len(pictures) != EXPECTED_FRAMES:
        raise ValueError(f"encode has {len(pictures):,} frames; expected {EXPECTED_FRAMES:,}")
    missing = sorted(set(original_keyframes) - set(keyframes))
    unexpected = sorted(
        set(keyframes) - set(original_keyframes) - {EXPECTED_FRAMES - 1}
    )
    if missing or unexpected:
        raise ValueError(
            "encode does not preserve original I-frame positions: "
            f"missing={missing}, unexpected={unexpected}"
        )
    print(
        f"encode OK: {len(video):,}/{EXPECTED_CAPACITY:,} bytes "
        f"({len(video) / EXPECTED_CAPACITY:.2%}), frames={len(pictures):,}, "
        f"source I-frames preserved"
    )
    return video

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def build(args: argparse.Namespace) -> None:
    original = args.original.resolve()
    subtitle = original.with_suffix(".en.srt")
    if not subtitle.is_file():
        raise FileNotFoundError(f"English subtitle track is missing: {subtitle}")
    output = args.output.resolve() if args.output else None
    if output == original:
        raise ValueError("output must not overwrite the original movie")
    if output and output.exists() and not args.force:
        raise FileExistsError(f"{output} exists; pass --force to replace it")

    keyframes = validate_original(original)
    rendered, event_count = credits_ass.render_ass()
    if not credits_ass.OUT.exists() or credits_ass.OUT.read_text(encoding="utf-8") != rendered:
        raise ValueError("ending_credits.ass is stale; run credits_ass.py first")
    print(f"credits OK: {event_count} events, pinned font and fitting verified")
    if args.validate_only:
        return
    if output is None:
        raise ValueError("output is required unless --validate-only is used")

    ffmpeg = shutil.which(args.ffmpeg)
    if ffmpeg is None and Path(args.ffmpeg).is_file():
        ffmpeg = str(Path(args.ffmpeg).resolve())
    if ffmpeg is None:
        raise FileNotFoundError("FFmpeg was not found; pass --ffmpeg with its full path")

    remove_work = False
    if args.work_dir:
        work = args.work_dir.resolve()
        if work.exists() and any(work.iterdir()):
            raise ValueError(f"work directory must be empty: {work}")
        work.mkdir(parents=True, exist_ok=True)
    else:
        parent = output.parent if args.keep_work else None
        work = Path(tempfile.mkdtemp(prefix="tod2-ending-", dir=parent))
        remove_work = not args.keep_work
    raw_video = work / "ending.raw.m2v"
    patched_video = work / "ending.ps2.m2v"
    candidate = work / "ending.candidate.mpeg"
    try:
        encode(ffmpeg, original, subtitle, raw_video, keyframes)
        raw = check_encoded_video(raw_video, keyframes)
        patched, sequence_count, picture_count = headers.patch_headers(
            raw, DECLARED_BITRATE
        )
        if sequence_count < 1 or picture_count != EXPECTED_FRAMES:
            raise ValueError(
                f"header patch saw {sequence_count} sequences and "
                f"{picture_count} pictures; expected at least 1 and {EXPECTED_FRAMES}"
            )
        patched_video.write_bytes(patched)
        verify_sequence(patched)
        print("MPEG-2 headers OK: 640x448, 4:3, 30000/1001, Main/Main, progressive 4:2:0")

        remux.remux(
            original, patched_video, candidate,
            buffer_aware=True,
            minimum_decode_lead_ms=MINIMUM_DECODE_LEAD_MS,
        )
        timing.verify(original, candidate, remux)
        candidate_data = candidate.read_bytes()
        if len(candidate_data) != EXPECTED_SIZE:
            raise ValueError(f"remux size is {len(candidate_data):,}; expected {EXPECTED_SIZE:,}")
        _packs, candidate_packets, _audio_count, _audio_bytes = remux.inspect_original(candidate_data)
        candidate_video = video_payload(candidate_data, candidate_packets)
        verify_sequence(candidate_video)

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as staged:
            staged_path = Path(staged.name)
        try:
            shutil.copyfile(candidate, staged_path)
            os.replace(staged_path, output)
        finally:
            if staged_path.exists():
                staged_path.unlink()
        print(f"release movie written: {output}")
        print(f"SHA-256={sha256(output)}")
    finally:
        if remove_work:
            shutil.rmtree(work)
        else:
            print(f"work files retained: {work}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="original extracted 00005.mpeg")
    parser.add_argument("output", type=Path, nargs="?", help="verified replacement movie")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable or full path")
    parser.add_argument("--work-dir", type=Path, help="empty directory for intermediate files")
    parser.add_argument("--keep-work", action="store_true", help="keep a generated work directory")
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="validate the original movie, credits, font, and fitting without encoding",
    )
    args = parser.parse_args()
    if args.validate_only and args.output:
        parser.error("do not provide output with --validate-only")
    build(args)

if __name__ == "__main__":
    main()
