#!/usr/bin/env python3
"""Lowercase for the PSP dialogue, via SkyBladeCloud's verified method.

Background (why the old data-only patch never worked in game): the engine has
TWO fonts. 8-bit ASCII is looked up through an 8-bit "uppercasing" slot table
(file 0x27DD40; 'A'=0x61 and 'a' both map to slot 0x17), and the resulting slot
is drawn from whichever font the renderer selected. Dialogue selects font 0x02
(an icon/ASCII font with no free space), which is why text renders ALL CAPS no
matter what we remap. Editing the OTHER table (the u16 code map at 0x27DB40)
had no effect for the same reason.

SkyBladeCloud's fix (he verified it in PPSSPP, screenshots), reproduced here
with every address/byte confirmed against our BOOT.BIN:

  1. Font 0x01 is member 00000 (the big font we can edit). Draw the 26 lowercase
     glyphs into its free slots 0xD9..0xF2 (retail-blank). The glyphs below are
     baked from SkyBladeCloud's edited font.
  2. Remap a..z (0x61..0x7A) in the 8-bit slot table (0x27DD40) to slots
     0xD9..0xF2, so 'a' resolves to the new lowercase glyph, not the 'A' slot.
  3. Force the dialogue renderers to use font 0x01 instead of 0x02, by changing
     two `li reg, 0x02` immediates to `0x01` (one byte each), verified as:
       - dialog TEXT font: vaddr 0x13EE04 / file 0x13EEC4  (addiu $s3,$zero,2)
       - dialog NAME font: vaddr 0x143384 / file 0x143444  (addiu $s0,$zero,2)
     (module load base 0x08804000: runtime = vaddr + base.)

This covers the SCED dialogue text + speaker names. Menus/battle use other
font-select sites (not yet located) and are unaffected.
"""
import os, sys, struct, base64, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_font

W, COLS, CELL = 256, 11, 23
U8_TABLE = 0x27DD40                 # file offset of the 8-bit slot table (index 0)
LOWER_SLOT_START = 0xD9            # a -> 0xD9, b -> 0xDA, ... z -> 0xF2
FONT_SELECT = (0x13EEC4, 0x143444)  # file offsets of the two `li reg,2` immediates
FONT_SELECT_FROM, FONT_SELECT_TO = 0x02, 0x01

# 26 lowercase glyphs (a..z), one 23x23 cell each, 4bpp nibbles, two per byte,
# zlib+base64. Baked from SkyBladeCloud's edited font (slots 0xD9..0xF2).
_LC_GLYPHS_B64 = (
    "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"
    "cPGMkJlDwz+A9E7axE="
)


def _glyphs():
    raw = zlib.decompress(base64.b64decode(_LC_GLYPHS_B64))
    # unpack 2 nibbles/byte -> 26 * 23*23 nibbles
    nib = bytearray()
    for b in raw:
        nib.append(b & 0xF); nib.append(b >> 4)
    per = CELL * CELL
    return [nib[i * per:(i + 1) * per] for i in range(26)]


def build_font(member00000):
    """Stamp a..z into slots 0xD9..0xF2 of member 0 (font 0x01)."""
    gray = bytearray(psp_font.deswizzle(member00000))
    glyphs = _glyphs()
    for i, cell in enumerate(glyphs):
        slot = LOWER_SLOT_START + i
        col, row = slot % COLS, slot // COLS
        x0, y0 = col * CELL, row * CELL
        for r in range(CELL):
            for c in range(CELL):
                yy, xx = y0 + r, x0 + c
                if yy < psp_font.H and xx < W:
                    gray[yy * W + xx] = cell[r * CELL + c] * 17
    return psp_font.reswizzle(bytes(gray))


def patch_boot(boot):
    """Remap a..z in the 8-bit slot table and force font 0x01 for dialogue.
    Returns (bytes, info)."""
    b = bytearray(boot)
    # 1) 8-bit slot table: a..z -> 0xD9..0xF2
    for i in range(26):
        b[U8_TABLE + 0x61 + i] = LOWER_SLOT_START + i
    # 2) font-select immediates 0x02 -> 0x01
    patched = 0
    for fo in FONT_SELECT:
        if b[fo] == FONT_SELECT_FROM:
            b[fo] = FONT_SELECT_TO
            patched += 1
    return bytes(b), {'slot_remap': 26, 'font_select_patched': patched}


# Backwards-compat shim: build_psp used to call patch_ascii_map(boot).
def patch_ascii_map(boot):
    out, info = patch_boot(boot)
    return out, info


if __name__ == '__main__':
    boot = open(sys.argv[1], 'rb').read()
    out, info = patch_boot(boot)
    print('lowercase patch:', info)
