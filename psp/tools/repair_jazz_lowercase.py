#!/usr/bin/env python3
"""Make a Jazz/Claude PSP ISO menu-safe by reverting its global lowercase map.

The Jazz lowercase experiment remaps every ASCII a-z byte through font slots
0xD9..0xF2, while installing lowercase art only into font 1.  Menus and battle
screens use other fonts, where those slots contain unrelated/controller glyphs.
This repair keeps the translated archive and menu pool unchanged, but restores
the retail a-z -> uppercase slots and the two retail dialogue font selectors.

The input is never modified.  The output is a new ISO.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_iso  # noqa: E402

U8_TABLE = 0x27DD40
LOWER_ASCII = 0x61
JAZZ_SLOTS = bytes(range(0xD9, 0xF3))
RETAIL_SLOTS = bytes(range(0x17, 0x31))
FONT_SELECT = (0x13EEC4, 0x143444)


def repair_boot(data: bytes) -> tuple[bytes, dict[str, int]]:
    b = bytearray(data)
    start = U8_TABLE + LOWER_ASCII
    current = bytes(b[start : start + 26])
    if current == RETAIL_SLOTS and all(b[offset] == 0x02 for offset in FONT_SELECT):
        return bytes(b), {"slot_bytes_reverted": 0, "font_selectors_reverted": 0}
    if current != JAZZ_SLOTS:
        raise ValueError(
            "lowercase table is neither the Jazz signature nor the retail signature: "
            + current.hex()
        )
    b[start : start + 26] = RETAIL_SLOTS
    selectors = 0
    for offset in FONT_SELECT:
        if b[offset] != 0x01:
            raise ValueError(
                "unexpected Jazz font selector at 0x%X: 0x%02X" % (offset, b[offset])
            )
        b[offset] = 0x02
        selectors += 1
    return bytes(b), {"slot_bytes_reverted": 26, "font_selectors_reverted": selectors}


def repair_iso(input_iso: str, output_iso: str) -> dict[str, int]:
    if os.path.abspath(input_iso) == os.path.abspath(output_iso):
        raise ValueError("input and output ISO must be different paths")
    work = tempfile.mkdtemp(prefix="tod2_jazz_safe_")
    try:
        boot_path = os.path.join(work, "BOOT.BIN")
        fixed_path = os.path.join(work, "BOOT.menu-safe.BIN")
        psp_iso.extract(input_iso, "/PSP_GAME/SYSDIR/BOOT.BIN", boot_path)
        original = open(boot_path, "rb").read()
        repaired, stats = repair_boot(original)
        with open(fixed_path, "wb") as stream:
            stream.write(repaired)
        psp_iso.replace(
            input_iso,
            output_iso,
            [
                ("/PSP_GAME/SYSDIR/BOOT.BIN", fixed_path),
                ("/PSP_GAME/SYSDIR/EBOOT.BIN", fixed_path),
            ],
        )
        return stats
    finally:
        shutil.rmtree(work)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: repair_jazz_lowercase.py INPUT.iso OUTPUT.iso")
        return 2
    stats = repair_iso(sys.argv[1], sys.argv[2])
    print("Jazz lowercase repair:", stats)
    print("wrote", sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
