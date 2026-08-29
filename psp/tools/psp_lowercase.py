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
     glyphs into its free slots (retail-blank). The glyphs below are baked from
     SkyBladeCloud's edited font.
  2. Remap a..z (0x61..0x7A) in the 8-bit slot table (0x27DD40) to those slots,
     so 'a' resolves to the new lowercase glyph, not the 'A' slot.
  3. Force the ASCII text paths to use font 0x01 instead of 0x02, by changing
     the font-select immediates to `0x01` (one byte each).

Fixes after Gandorff's first boot test of v0.1.0 (2026-08-29):

  * Retail slot 0xDB is the APOSTROPHE (the 8-bit table maps 0x27 -> 0xDB, the
    only retail entry inside 0xD9..0xF3). The first version stamped 'c' over it,
    so every ' rendered as "c" ("Donct worry, wecre"). The letters now use the
    26 retail-blank slots 0xD9, 0xDA, 0xDC..0xF3 and leave 0xDB alone.
  * SkyBladeCloud's 'i' and 'j' cells have no dot (they rendered as a dotless
    stroke). A dot is drawn above the x-height at load time.
  * A THIRD ASCII walker selects font 0x02 for single-byte text: party names in
    menus, Battle Rank, the arte shortcut grid, the Artes-screen tabs. With a..z
    remapped, those drew font 0x02's icon fragments. Its select is flipped too.

The text walkers that resolve 8-bit ASCII through the slot table (found by
disassembling BOOT.BIN and taking every `lui 0xa / addiu ..,0x1040` user; the
table sits at vaddr 0x27DC40 = data base 0x1DCC00 + 0xA1040) and their
single-byte font-select immediates (file offsets; module load base 0x08804000,
runtime = vaddr + base):

  - dialogue TEXT walker 0x13EC24: vaddr 0x13EE04 / file 0x13EEC4 (addiu $s3,$zero,2)
  - dialogue NAME walker 0x14304C: vaddr 0x143384 / file 0x143444 (addiu $s0,$zero,2)
  - menu/battle walker   0x149E74: vaddr 0x149FC4 / file 0x14A084 (ori $a2,$a3,2;
    low nibble = font, high nibble = flags)

Each walker's 2-byte (kanji) path already hard-codes font 0x01, and the retail
table maps every single-byte code to the same slot for both fonts, so font 0x01
has every glyph these paths can address.

The FOURTH table user is not a walker: 0x144248 (wrapper 0x1464BC, called from
nine menu subsystems) draws an ASCII string straight to a vertex list. It reads
the slot table at vaddr 0x144318/0x14431C (file 0x1443D8/0x1443DC), then
computes the glyph rectangle with the icon font's geometry hard-coded (10 cells
per row, 12x16 pixels) on texture slot 0, which the wrapper binds to the icon
font. There is no font byte and no font-0x01 branch, so this path can only ever
draw font 0x02. It is the "bold" menu text: party names in the menu, the Artes
tabs, the arte shortcut grid, the Battle Rank value, HP/TP/LV labels. Retail
got capitals here from the table's a->A fold; with a..z remapped it drew icon
fragments (Gandorff's v0.1.0/v15 boot tests). Fix: patch_bold_table() gives
this one routine its own untouched copy of the retail table (appended to the
menu pool segment, lui/addiu re-pointed; the HI16/LO16 relocations stay and
just add segment 1's base to the new immediates), so those contexts render
capitals exactly like retail while everything else keeps lowercase. Lowercase
there would need glyphs drawn into the icon font or a rewrite of 0x144248's
geometry.
"""
import os, sys, struct, base64, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_font

W, COLS, CELL = 256, 11, 23
U8_TABLE = 0x27DD40                 # file offset of the 8-bit slot table (index 0)
APOSTROPHE_SLOT = 0xDB              # retail: table[0x27] -> 0xDB, must stay untouched
# a..z -> the 26 retail-blank slots below 0x100 (0xD9, 0xDA, 0xDC..0xF3)
LOWER_SLOTS = [s for s in range(0xD9, 0xF4) if s != APOSTROPHE_SLOT]
assert len(LOWER_SLOTS) == 26
# file offsets of the single-byte font-select immediates (see module docstring)
FONT_SELECT = (0x13EEC4, 0x143444, 0x14A084)
FONT_SELECT_FROM, FONT_SELECT_TO = 0x02, 0x01
# the bold direct-draw routine's table address pair (file offsets of the
# `lui $t7,0xa` / `addiu $t6,$t7,0x1040` words at vaddr 0x144318 / 0x14431C)
BOLD_LUI, BOLD_ADDIU = 0x1443D8, 0x1443DC
BOLD_LUI_WORD, BOLD_ADDIU_WORD = 0x3C0F000A, 0x25EE1040
DATA_SEG_VADDR = 0x1DCC00       # segment 1 (HI16/LO16 addr_base of that pair)
POOL_VADDR = 0x881000           # psp_pool's 4th PT_LOAD segment

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
    glyphs = [nib[i * per:(i + 1) * per] for i in range(26)]
    _dot(glyphs[ord('i') - 0x61])
    _dot(glyphs[ord('j') - 0x61])
    return glyphs


# Cell geometry of the baked glyphs: cap top row 3, x-height row 7, baseline
# row 21. The i/j stems sit in columns 9..13 (core 10..12). Both cells came
# without a dot; this draws one above the x-height and, for 'j', cuts the stem
# back to x-height (it was drawn ascender-high).
def _dot(cell):
    for r in range(0, 7):                      # clear rows 0..6 (row 6 = gap)
        for c in range(CELL):
            cell[r * CELL + c] = 0
    for r in (3, 4, 5):                        # 3x3 dot, same weight as the stem
        for c in range(9, 14):
            cell[r * CELL + c] = 0xF if 10 <= c <= 12 else 0x5
    cell[7 * CELL + 10:7 * CELL + 13] = bytes([0x5, 0x5, 0x5])   # stem cap row
    cell[8 * CELL + 9:8 * CELL + 14] = bytes([0x5, 0x5, 0xF, 0x5, 0x5])


def build_font(member00000):
    """Stamp a..z into LOWER_SLOTS of member 0 (font 0x01)."""
    gray = bytearray(psp_font.deswizzle(member00000))
    glyphs = _glyphs()
    for i, cell in enumerate(glyphs):
        slot = LOWER_SLOTS[i]
        col, row = slot % COLS, slot // COLS
        x0, y0 = col * CELL, row * CELL
        for r in range(CELL):
            for c in range(CELL):
                yy, xx = y0 + r, x0 + c
                if yy < psp_font.H and xx < W:
                    gray[yy * W + xx] = cell[r * CELL + c] * 17
    return psp_font.reswizzle(bytes(gray))


def patch_boot(boot):
    """Remap a..z in the 8-bit slot table and force font 0x01 on the ASCII
    text paths. Returns (bytes, info)."""
    b = bytearray(boot)
    assert b[U8_TABLE + 0x27] == APOSTROPHE_SLOT, 'unexpected slot table'
    # 1) 8-bit slot table: a..z -> LOWER_SLOTS (0xDB = apostrophe stays)
    for i in range(26):
        b[U8_TABLE + 0x61 + i] = LOWER_SLOTS[i]
    # 2) font-select immediates 0x02 -> 0x01
    patched = 0
    for fo in FONT_SELECT:
        if b[fo] == FONT_SELECT_FROM:
            b[fo] = FONT_SELECT_TO
            patched += 1
    return bytes(b), {'slot_remap': 26, 'font_select_patched': patched}


def retail_table(table):
    """The retail 8-bit slot table, reconstructed from a (possibly remapped)
    copy: retail maps a..z to the same slots as A..Z."""
    t = bytearray(table)
    for i in range(26):
        t[0x61 + i] = t[0x41 + i]
    return bytes(t)


def patch_bold_table(boot):
    """Give the bold direct-draw routine (0x144248) an untouched copy of the
    retail slot table so its icon-font-only contexts render capitals like
    retail instead of icon fragments. Run AFTER psp_pool (the copy is appended
    to the pool segment; a pool segment is created if there is none).
    Returns (bytes, info)."""
    b = bytearray(boot)
    assert struct.unpack_from('<I', b, BOLD_LUI)[0] == BOLD_LUI_WORD, 'bold lui not found'
    assert struct.unpack_from('<I', b, BOLD_ADDIU)[0] == BOLD_ADDIU_WORD, 'bold addiu not found'
    assert b[U8_TABLE + 0x41] == 0x17 and b[U8_TABLE + 0x27] == APOSTROPHE_SLOT, 'unexpected slot table'
    copy = retail_table(b[U8_TABLE:U8_TABLE + 0x100])
    phnum = struct.unpack_from('<H', b, 0x2c)[0]
    if phnum == 4:
        p = list(struct.unpack_from('<8I', b, 0x34 + 3 * 32))
        assert p[2] == POOL_VADDR and p[1] + p[4] == len(b), 'pool segment must sit at EOF'
        off = p[4]                       # copy goes right after the pool bytes
        b += copy
        p[4] = p[5] = off + len(copy)
        struct.pack_into('<8I', b, 0x34 + 3 * 32, *p)
    else:
        assert phnum == 3, 'unexpected program header count'
        off = 0
        pool_file = len(b)
        b += copy
        struct.pack_into('<8I', b, 0x34 + 3 * 32,
                         1, pool_file, POOL_VADDR, POOL_VADDR, len(copy), len(copy), 4, 0x40)
        struct.pack_into('<H', b, 0x2c, 4)
    # re-point the pair: immediates are relative to segment 1 (reloc addr_base)
    rel = POOL_VADDR + off - DATA_SEG_VADDR
    hi, lo = ((rel + 0x8000) >> 16) & 0xffff, rel & 0xffff
    struct.pack_into('<I', b, BOLD_LUI, (BOLD_LUI_WORD & 0xffff0000) | hi)
    struct.pack_into('<I', b, BOLD_ADDIU, (BOLD_ADDIU_WORD & 0xffff0000) | lo)
    return bytes(b), {'bold_table_vaddr': hex(POOL_VADDR + off), 'hi': hex(hi), 'lo': hex(lo)}


# Backwards-compat shim: build_psp used to call patch_ascii_map(boot).
def patch_ascii_map(boot):
    out, info = patch_boot(boot)
    return out, info


if __name__ == '__main__':
    boot = open(sys.argv[1], 'rb').read()
    out, info = patch_boot(boot)
    print('lowercase patch:', info)
