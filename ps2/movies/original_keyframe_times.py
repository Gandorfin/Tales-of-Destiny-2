#!/usr/bin/env python3
"""Print original MPEG-2 GOP/keyframe presentation times for FFmpeg."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_remux_module(script: Path):
    spec = importlib.util.spec_from_file_location("tod2_remux", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("movie", type=Path)
    parser.add_argument(
        "--remux-script",
        type=Path,
        default=Path(__file__).with_name("remux_ps2_movie.py"),
    )
    args = parser.parse_args()

    remux = load_remux_module(args.remux_script)
    data = args.movie.read_bytes()
    _packs, video_packets, _audio_packets, _audio_bytes = remux.inspect_original(data)
    video = bytearray()
    for pack_index, start, end, payload_at, _capacity in video_packets:
        base = pack_index * remux.PACK_SIZE
        video.extend(data[base + start + payload_at : base + end])

    pictures = remux.picture_timestamps(bytes(video))
    keyframe_times = []
    search_at = 0
    picture_index = 0
    while True:
        position = video.find(remux.START + b"\x00", search_at)
        if position < 0:
            break
        coding_type = (video[position + 5] >> 3) & 7
        if coding_type == 1:
            pts = pictures[picture_index][1]
            keyframe_times.append((pts - pictures[0][1]) / 90_000)
        picture_index += 1
        search_at = position + 4

    print(",".join(f"{time:.6f}" for time in keyframe_times))


if __name__ == "__main__":
    main()
