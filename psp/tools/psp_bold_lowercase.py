#!/usr/bin/env python3
"""Lowercase for the PSP "bold" menu text (party names, HP/TP/LV labels,
Battle Rank, Custom menu values, arte grid, name entry labels).

The problem: that text is drawn by the routine at vaddr 0x144248 (wrapper
0x1464BC), which can only draw font 2, the small 12x16 icon/ASCII font in
BOOT.BIN. Font 2 has capitals but no lowercase, so since PSP 0.2.0 the
lowercase build gives this routine a private copy of the retail slot table
(psp_lowercase.patch_bold_table) and it draws capitals: KYLE, LONI, NORMAL.

What this module provides (psp_vwf.py puts it into the executable):
1. map_table(): maps a..z in the bold routine's private slot table to
   the hiragana cells BOLD_CELLS.
2. bold_texture(): a copy of font 2 with the Latin glyphs of psp_latin_font
   (the same typeface as the dialogue) drawn into every cell that table
   reaches, a..z included, swizzled the way the game swizzles font 2 at
   startup.
psp_vwf's start hook binds the copy for every bold string except one that
contains kana drawn from those cells. That keeps the name entry keyboard
right: its kana are two-byte codes drawn by this same routine from font 2.
Font 2 itself has no free cells (its bottom rows hold the stone texture of
the "next" indicator and the icons), so it stays retail.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patch_font_iso as F  # noqa: E402

SLOTTAB_FILE = 0x27DD40
BOLD_LUI, BOLD_ADDIU = 0x1443D8, 0x1443DC          # file offsets of the table pair
DATA_SEG_VADDR = 0x1DCC00
POOL_VADDR = 0x881000
BOLD_CELLS = list(range(49, 75))                    # ぁ .. ず in font 2 (10 cells per row)
CELL2_W, CELL2_H, COLS2 = 12, 16, 10                # font 2


def bold_table_offset(b):
    """File offset of the bold routine's private slot table (in the pool)."""
    hi = struct.unpack_from('<I', b, BOLD_LUI)[0] & 0xFFFF
    lo = struct.unpack_from('<I', b, BOLD_ADDIU)[0] & 0xFFFF
    rel = (hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)
    vaddr = DATA_SEG_VADDR + rel
    phoff = struct.unpack_from('<I', b, 0x1C)[0]
    for i in range(struct.unpack_from('<H', b, 0x2C)[0]):
        p = struct.unpack_from('<8I', b, phoff + 32 * i)
        if p[0] == 1 and p[2] == POOL_VADDR and p[2] <= vaddr < p[2] + p[4]:
            return p[1] + vaddr - p[2]
    raise ValueError('the bold table is not in the pool (run psp_lowercase.patch_bold_table first)')


def map_table(b):
    """Map a..z in the bold routine's private table (bytearray b) to BOLD_CELLS."""
    tab_at = bold_table_offset(b)
    table = b[tab_at:tab_at + 256]
    if table[0x41] != 0x17 or any(table[0x61 + i] != table[0x41 + i] for i in range(26)):
        raise ValueError('bold table is not the retail copy (lowercase already applied?)')
    for i in range(26):
        b[tab_at + 0x61 + i] = BOLD_CELLS[i]
    return tab_at


def swizzle2(linear):
    """Font 2 pixel bytes (128x512 4bpp, 64 bytes per row) in the PSP's
    16 byte x 8 row swizzle, as the game stores it in memory."""
    out, pos = bytearray(len(linear)), 0
    for by in range(F.FONT2_HEIGHT // 8):
        for bx in range(64 // 16):
            for row in range(8):
                at = (by * 8 + row) * 64 + bx * 16
                out[pos:pos + 16] = linear[at:at + 16]
                pos += 16
    return bytes(out)


def bold_texture(boot):
    """(swizzled 128x512 texture, its pixel indices): font 2 with the Latin
    glyphs of psp_latin_font drawn into every cell the bold routine's
    private table reaches (capitals, digits, punctuation and a..z in
    BOLD_CELLS). Run map_table() first."""
    import psp_latin_font
    _, texture = F.embedded_font2(bytes(boot))
    pixels = bytearray(F.font_indices(texture[F.FONT2_PIXEL_OFFSET:], 2))
    tab_at = bold_table_offset(boot)
    for cell, (rows, _, _) in psp_latin_font.font2_cells(boot[tab_at:tab_at + 256]).items():
        r, c = divmod(cell, COLS2)
        for y in range(CELL2_H):
            for x in range(CELL2_W):
                pixels[(r * CELL2_H + y) * F.FONT2_WIDTH + c * CELL2_W + x] = int(rows[y][x], 16)
    return swizzle2(F.indices_font(bytes(pixels), 2)), bytes(pixels)
