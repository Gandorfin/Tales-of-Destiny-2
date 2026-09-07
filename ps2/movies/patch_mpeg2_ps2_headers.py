#!/usr/bin/env python3
"""Match Tales of Destiny 2's MPEG-2 sequence and picture timing headers."""

from __future__ import annotations

import argparse
from pathlib import Path


START = b"\x00\x00\x01"


def patch_headers(data: bytes, declared_bitrate: int) -> tuple[bytes, int, int]:
    bitrate_value = declared_bitrate // 400
    if declared_bitrate % 400 or not 1 <= bitrate_value < (1 << 18):
        raise ValueError("declared bitrate must be a valid MPEG-2 400-bit/s value")

    result = bytearray(data)
    sequence_headers = 0
    picture_headers = 0
    search_at = 0
    while True:
        position = data.find(START, search_at)
        if position < 0 or position + 11 > len(data):
            break
        code = data[position + 3]
        if code == 0xB3:
            result[position + 8] = (bitrate_value >> 10) & 0xFF
            result[position + 9] = (bitrate_value >> 2) & 0xFF
            result[position + 10] = (
                (result[position + 10] & 0x3F) | ((bitrate_value & 3) << 6)
            )
            sequence_headers += 1
        elif code == 0x00:
            # vbv_delay is the 16-bit field starting at bit 21 of a picture header.
            result[position + 5] = (result[position + 5] & 0xF8) | 0x07
            result[position + 6] = 0xFF
            result[position + 7] = (result[position + 7] & 0x07) | 0xF8
            picture_headers += 1
        search_at = position + 4
    return bytes(result), sequence_headers, picture_headers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--declared-bitrate", type=int, default=9_000_000)
    args = parser.parse_args()

    patched, sequence_headers, picture_headers = patch_headers(
        args.input.read_bytes(), args.declared_bitrate
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"sequence_headers_patched={sequence_headers:,}")
    print(f"picture_headers_patched={picture_headers:,}")
    print(f"output_size={len(patched):,}")


if __name__ == "__main__":
    main()
