#!/usr/bin/env python3
"""Verify TOD2 remux size, audio preservation, frame timing, and DTS order."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path


def load_remux_module(script: Path):
    spec = importlib.util.spec_from_file_location("tod2_remux", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def video_payload(remux, data: bytes, packets: list[tuple]) -> bytes:
    result = bytearray()
    for pack_index, start, end, payload_at, _capacity in packets:
        base = pack_index * remux.PACK_SIZE
        result.extend(data[base + start + payload_at : base + end])
    return bytes(result)


def private_packet_hash(remux, data: bytes) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    pack_count = (len(data) - 4) // remux.PACK_SIZE
    for pack_index in range(pack_count):
        base = pack_index * remux.PACK_SIZE
        pack = data[base : base + remux.PACK_SIZE]
        for start, end, stream_id in remux.packet_spans(pack):
            if stream_id == 0xBD:
                digest.update(pack[start:end])
                count += 1
    return digest.hexdigest(), count


def pts_by_display_frame(remux, video: bytes, timestamps: list[tuple[int, int]]):
    nominal = remux.picture_timestamps(video)
    return {
        (picture[1] - 12_000) // 3_003: exact[0]
        for picture, exact in zip(nominal, timestamps)
    }


def verify(original_path: Path, replacement_path: Path, remux) -> None:
    original = original_path.read_bytes()
    replacement = replacement_path.read_bytes()
    if len(original) != len(replacement):
        raise ValueError(f"size differs: {len(original):,} != {len(replacement):,}")

    original_audio, original_audio_count = private_packet_hash(remux, original)
    replacement_audio, replacement_audio_count = private_packet_hash(remux, replacement)
    if (original_audio, original_audio_count) != (
        replacement_audio,
        replacement_audio_count,
    ):
        raise ValueError("private audio packets differ")

    _opacks, original_packets, _oaudio, _obytes = remux.inspect_original(original)
    _rpacks, replacement_packets, _raudio, _rbytes = remux.inspect_original(replacement)
    original_video = video_payload(remux, original, original_packets)
    replacement_video = video_payload(remux, replacement, replacement_packets)
    original_timestamps = remux.original_picture_timestamps(
        original, original_packets, original_video
    )
    replacement_timestamps = remux.original_picture_timestamps(
        replacement, replacement_packets, replacement_video
    )

    original_pts = pts_by_display_frame(remux, original_video, original_timestamps)
    replacement_pts = pts_by_display_frame(remux, replacement_video, replacement_timestamps)
    if original_pts != replacement_pts:
        raise ValueError("replacement presentation timestamps differ from the original")

    dts = [timestamp[1] for timestamp in replacement_timestamps]
    if any(current <= previous for previous, current in zip(dts, dts[1:])):
        raise ValueError("replacement decode timestamps are not strictly increasing")

    print(
        f"{replacement_path.name}: size={len(replacement):,}, "
        f"frames={len(replacement_timestamps):,}, audio_packets={replacement_audio_count:,}, "
        "PTS=exact, DTS=monotonic, audio=exact"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original_folder", type=Path)
    parser.add_argument("replacement_folder", type=Path)
    parser.add_argument("names", nargs="+")
    parser.add_argument(
        "--remux-script",
        type=Path,
        default=Path(__file__).with_name("remux_ps2_movie.py"),
    )
    args = parser.parse_args()
    remux = load_remux_module(args.remux_script)
    for name in args.names:
        verify(args.original_folder / name, args.replacement_folder / name, remux)


if __name__ == "__main__":
    main()
