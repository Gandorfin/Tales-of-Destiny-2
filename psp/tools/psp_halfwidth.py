#!/usr/bin/env python3
"""Half-width Latin for the PSP font (part 1 of 2: the glyph compression).

The PSP text engine is monospace: every glyph advances one full ~23px cell
(psp_font/PSP.md section 6). English therefore renders at full width, which
overruns description boxes and collides in the arte grid. The fix has two
parts:

  1. (this file) horizontally compress the Latin/digit/punctuation glyphs to
     ~half a cell, left-aligned, so a half-cell advance packs them without
     overlap. Derived by x-scaling the existing glyphs, so the style matches.
  2. (psp_halfwidth_code, separate) halve the pen advance for the single-byte
     (ASCII) path only, leaving two-byte kanji full width.

Part 1 is boot-test-independent and verifiable by round-trip; part 2 injects
code and must get one in-game boot test before it is trusted (it can crash if
the relocation is wrong).

The cell set to compress is derived from the ASCII map in BOOT.BIN AFTER the
lowercase remap, so it covers caps, digits, punctuation and every lowercase
cell (existing + the 15 psp_lowercase draws).
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_font

W, COLS, CELL, GLYPH = 256, 11, 23, 22
ASCII_MAP = 0x27DB40                 # file offset of the u16[256] map (vaddr 0x27DA40)


def _decode(code):
    if code <= 0x993f:
        code = 0x9940
    hi, lo = code >> 8, code & 0xff
    if hi >= 0xe0:
        hi -= 0x40
    if lo >= 0x80:
        lo -= 1
    if lo >= 0x5d:
        lo -= 1
    return (hi - 0x99) * 187 + (lo - 0x40)


def latin_cells(boot):
    """Cells that printable ASCII (0x21..0x7e) maps to, minus the space cell.

    Reads the map from `boot`, so run it AFTER psp_lowercase.patch_ascii_map
    to pick up the lowercase cells too.
    """
    space = _decode(struct.unpack_from('<H', boot, ASCII_MAP + 0x20 * 2)[0])
    cells = set()
    for byte in range(0x21, 0x7f):
        code = struct.unpack_from('<H', boot, ASCII_MAP + byte * 2)[0]
        cell = _decode(code)
        if cell != space and 0 <= cell < COLS * (psp_font.H // CELL):
            cells.add(cell)
    return cells


def _read_cell(gray, gi):
    col, row = gi % COLS, gi // COLS
    x0, y0 = col * CELL, row * CELL + 1
    return [[gray[(y0 + r) * W + (x0 + c)] for c in range(GLYPH)] for r in range(GLYPH)]


def _write_cell(gray, gi, bmp):
    col, row = gi % COLS, gi // COLS
    x0, y0 = col * CELL, row * CELL + 1
    for r in range(GLYPH):
        for c in range(GLYPH):
            gray[(y0 + r) * W + (x0 + c)] = bmp[r][c]


def _compress_rows(bmp):
    """22px wide -> ~11px, left-aligned, right half blanked.

    Each output column is the max of the two source columns it covers (max,
    not average, keeps thin stems from fading below the >60 render threshold).
    """
    out = [[0] * GLYPH for _ in range(GLYPH)]
    for r in range(GLYPH):
        for oc in range(11):
            a = bmp[r][oc * 2]
            b = bmp[r][oc * 2 + 1] if oc * 2 + 1 < GLYPH else 0
            out[r][oc] = a if a >= b else b
    return out


def compress_font(member00000, boot):
    """Return a new swizzled member-0 with Latin cells compressed to half width."""
    gray = bytearray(psp_font.deswizzle(member00000))
    cells = latin_cells(boot)
    for gi in cells:
        _write_cell(gray, gi, _compress_rows(_read_cell(gray, gi)))
    return psp_font.reswizzle(bytes(gray)), len(cells)


# --- part 2: halve the pen advance -------------------------------------------
# The layout walker (BOOT 0x13EADC, PSP.md section 6) computes ONE advance per
# string: fp = (font_width * scale) >> 8 at vaddr 0x13EB98 (`ext $fp,$a2,8,16`).
# Bumping the shift to 9 halves it, so the whole engine advances half a cell
# and the compressed Latin glyphs pack tightly (matching the PS2's 36-per-line
# layout). CAVEAT: this is global, so an all-Japanese string (mainly the kana
# name-input keyboard) also halves and its full-width kanji overlap. That is
# cosmetic, confined to the few untranslated-JP screens, and reversible.
# Per-char precision (single-byte only) would need an injected relocated hook
# and one in-game test; this shift does not and cannot crash.
ADVANCE_INSN = 0x13EB98              # vaddr; file = +0xC0
_ADVANCE_ORIG = bytes([0x00, 0x7a, 0xde, 0x7c])   # ext $fp,$a2,8,0x10
_ADVANCE_HALF = bytes([0x40, 0x7a, 0xde, 0x7c])   # ext $fp,$a2,9,0x10


def patch_advance(boot):
    """Halve the global pen advance (>>8 -> >>9). Returns (bytes, changed)."""
    b = bytearray(boot)
    fo = ADVANCE_INSN + 0xC0
    if b[fo:fo + 4] != _ADVANCE_ORIG:
        return bytes(b), False        # already patched or unexpected build
    b[fo:fo + 4] = _ADVANCE_HALF
    return bytes(b), True


if __name__ == '__main__':
    import psp_lowercase
    b = open('somestuffpsp/probe_BOOT.BIN', 'rb').read()
    b = psp_lowercase.patch_ascii_map(b)[0]
    font = psp_lowercase.build_font(open('somestuffpsp/FPB/00000.bin', 'rb').read())
    print('latin cells:', len(latin_cells(b)))
