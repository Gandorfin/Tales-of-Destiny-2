#!/usr/bin/env python3
"""Variable width font (VWF) for single-byte (ASCII) text on the PSP.

The problem (every PSP release up to 0.3.x): the engine gives every
single-byte character the same advance, half a font cell, so English reads
like a typewriter ("L o n i  a c q u i r e d"), lines are long and boxes are
wide. The lowercase font hack (psp_lowercase) also draws the 23 px font-1
cells about 22 % narrower than they are tall.

What this step does: it measures every Latin glyph in the built font 1 and
gives each one its own advance, in all four places that lay out or draw
single-byte text. Kanji (two-byte) text, icons and control codes keep the
retail behaviour.

Where (vaddr; file offset = vaddr + 0xC0; runtime = vaddr + 0x08804000):

1. Line layout 0x13EADC, single-byte path 0x13EE00..0x13EE44. It fills the
   10-byte glyph records of a text window ([0] font type, [1] reveal alpha,
   [2] colour, [3] unused in retail, [4] glyph slot, [6] width, [8] height,
   1/16 px). The hook writes the record, stores the sprite width in [6], sets
   [3] = 1 (VWF marker) and returns the glyph's advance, which the routine
   adds to the line width. The kanji path (0x13ECA4/0x13ECAC) and the tag
   path (0x13F010/0x13F018) clear [3] instead.
2. Window glyph loop 0x140C7C (font 1 sprites, 0x140CE4..0x140E94). Retail
   draws each sprite from x to x + width and moves x by the same width. The
   hook draws marked records shifted left by the glyph's left bearing and
   moves x by the glyph's advance.
3. Text printer put-char 0x1432C0 (window labels such as "notice", choices,
   names, many UI strings). Same idea, for its single-byte path at 0x143380.
4. Box measurer 0x1426B4 (called by 0x13E340 before a window opens): its
   single-byte width at 0x14283C..0x14285C now uses the same advance, so the
   box fits the text.

How the hooks are reached without new relocation entries: every word the
loader relocates (lui/LO16/j/jal) is left where it is. The call sites build
the hook address from a register that already holds a relocated address
(the slot table in v1 or t7, data + 0xA0DE0 in s2) or from the return
address of a `bal`, so the jump is right at any load address. The hooks and
the width table are appended to the string pool segment (psp_pool), which
the PSP kernel loads since PR 120 (psp_pool.make_hardware_loadable).

Width table: 256 entries of (left, advance) in font pixels, indexed by glyph
slot, built from the font-1 member the build writes. advance 0 = retail
behaviour for that slot. Digits share one advance (tabular numbers). The
sprite is scaled by SX/256 (default 320 = 1.25, which undoes the condensed
look); the advance is measured at that scale.

Run after psp_lowercase.patch_bold_table (the pool must exist and end the
file) and only with the lowercase font (the hooks draw font 1).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mips_asm  # noqa: E402

TEXT_BIAS = 0xC0
SLOTTAB = 0x27DC40              # 8-bit slot table (data segment + 0xA1040)
SLOTTAB_FILE = 0x27DD40
DATA_DE0 = 0x27D9E0             # data segment + 0xA0DE0
POOL_VADDR = 0x881000
CELL, COLS, FONT_W = 23, 11, 256
RECIP23 = 2849                  # 65536 / 23
DEFAULT_SX = 320
DEFAULT_GAP = 2
SPACE_ADVANCE = 7
DIGIT_LEFT, DIGIT_ADVANCE = 4, 15
HALO = 4
# The lowercase glyphs squeeze descenders into the cell (bowls end on the
# baseline row 20 only for letters without a descender). Draw these lower,
# in font pixels, so g p q y j hang below the line like real descenders.
DESCENDERS = {'g': 3, 'p': 3, 'q': 3, 'y': 3, 'j': 2}
# '-', '~' and '_' share the slot of the long Japanese dash (18 px of ink).
# Single-byte text draws it squeezed to a hyphen (sprite width x n/256);
# the kanji path (Japanese long vowel marks) is not affected.
SQUEEZE = {'-': 115}

# Retail words at every site the call-site patches overwrite (vaddr: word).
# 0x143384 is the font select (2 in retail, 1 after psp_lowercase).
RETAIL = {
    0x13ECA4: 0xA2030000, 0x13ECAC: 0xA2000001,
    0x13EE24: 0x8FAE0008, 0x13EE28: 0x00003021, 0x13EE2C: 0x91CD0000,
    0x13EE30: 0xA18D0002, 0x13EE34: 0x90910000, 0x13EE38: 0xA5970008,
    0x13EE3C: 0xA5910004, 0x13EE44: 0xA5930006,
    0x13F010: 0xA1F20000, 0x13F018: 0xA1E00001,
    0x140E78: 0x8FAD0014, 0x140E7C: 0xA555043C, 0x140E80: 0x3115FFFF,
    0x140E84: 0xA547043E, 0x140E88: 0xA54D0442,
    0x14283C: 0x30440002, 0x142840: 0x54800007, 0x142844: 0x96DE0000,
    0x142848: 0x8FA6004C, 0x14284C: 0x94C50000, 0x142850: 0x30A30001,
    0x142854: 0x50600004, 0x142858: 0x96C70000, 0x14285C: 0x96DE0000,
    0x143380: 0x8D240020, 0x143384: (0x24100002, 0x24100001),
    0x143388: 0x00059243, 0x14338C: 0xA0900000,
    0x143394: 0x90EF0000, 0x143398: 0x8DAE0020, 0x14339C: 0xA5CF0002,
    0x1433A0: 0x8DA20020,
}
# bold routine: prologue stores (0x144250..0x14427C) and loop tail
# (0x144438..0x144454), patched only with bold=True
RETAIL_BOLD = {
    0x144250: 0xAFB7002C, 0x144254: 0x0000B821, 0x144258: 0xAFB20018,
    0x14425C: 0x00809021, 0x144260: 0xAFBF0034, 0x144264: 0xAFBE0030,
    0x144268: 0xAFB60028, 0x14426C: 0xAFB50024, 0x144270: 0xAFB40020,
    0x144274: 0xAFB3001C, 0x144278: 0xAFB10014, 0x14427C: 0xAFB00010,
    0x144438: 0x95040000, 0x14443C: 0x95050004, 0x144440: 0xAD930004,
    0x144444: 0x00854821, 0x144448: 0xA5090000, 0x14444C: 0x92500000,
    0x144450: 0x1600FFA8, 0x144454: 0x2E060020,
}
BOLD_RET = 0x144454
BOLD_START_RET = 0x144270
GU_TEX_IMAGE = 0x0059E4          # the game's sceGuTexImage(mip, w, h, tbw, tbp)
CODE_TO_CELL = 0x144604          # two-byte code -> font 2 cell (low 8 bits)
# third walker (skit ticker, battle and some menu text): single-byte layout
# 0x149FD0..0x149FE4 and the font-1 sprite in its draw loop 0x14A4A0..0x14A4C0
RETAIL_TICKER = {
    0x149FD0: 0x0204C021, 0x149FD4: 0x930F0000, 0x149FD8: 0x8FB90004,
    0x149FDC: 0xA64F0002, 0x149FE0: 0x0019A042, 0x149FE4: 0xA6540004,
    0x14A4A0: 0xA48A043C, 0x14A4A4: 0x96630006, 0x14A4A8: 0x03C33023,
    0x14A4AC: 0x24C57900, 0x14A4B0: 0xA485043E, 0x14A4B4: 0x96630004,
    0x14A4B8: 0xA4890442, 0x14A4BC: 0x00745821, 0x14A4C0: 0x25726C00,
}
TICKER_DRAW_RET = 0x14A4BC
HALF_PER_HEIGHT = 205           # half cell width = height * 0x9A / 0xC0 (n/256)
CELL2_W, CELL2_H, COLS2, CELLS2 = 12, 16, 10, 320
RECIP12 = 5462                  # 65536 / 12 (font 2 cell width)
BOLD_CELLS_RANGE = (49, 74)     # psp_bold_lowercase.BOLD_CELLS
BOLD_GAP = 1
BOLD_SPACE = 5


def glyph_extents(gray, slot):
    """(left, right) columns of the non-background pixels of a font-1 cell, or None."""
    r, c = divmod(slot, COLS)
    xs = []
    for y in range(CELL):
        row = (r * CELL + y) * FONT_W + c * CELL
        for x in range(CELL):
            # palette index >= 4: indices 1..3 are the faint outer halo
            if gray[row + x] // 17 >= HALO:
                xs.append(x)
    return (min(xs), max(xs)) if xs else None


def build_widths(gray, slot_table, gap=DEFAULT_GAP):
    """1024-byte table for the ASCII characters, in font pixels: (left,
    advance) per slot, then (signed y offset, horizontal squeeze n/256 or 0)
    per slot. left and advance are measured on the unsqueezed glyph and
    scaled with it."""
    w = bytearray(1024)
    for ch in range(0x21, 0x7F):
        s = slot_table[ch]
        e = glyph_extents(gray, s)
        if e:
            w[2 * s] = e[0]
            w[2 * s + 1] = e[1] - e[0] + 1 + gap
    for d in b'0123456789':
        s = slot_table[d]
        w[2 * s], w[2 * s + 1] = DIGIT_LEFT, DIGIT_ADVANCE + gap
    s = slot_table[0x20]
    w[2 * s], w[2 * s + 1] = 0, SPACE_ADVANCE
    for ch, dy in DESCENDERS.items():
        s = slot_table[ord(ch)]
        if s != slot_table[0x20] and glyph_extents(gray, s):
            w[512 + 2 * s] = dy & 0xFF
    for ch, n in SQUEEZE.items():
        s = slot_table[ord(ch)]
        if s == slot_table[0x20] or not glyph_extents(gray, s):
            continue
        w[512 + 2 * s + 1] = n
        w[2 * s + 1] = min(255, w[2 * s + 1] + (gap * 256 // n - gap))   # keep the gap unsqueezed
    return bytes(w)


def build_bold_widths(font2_pixels, slot_table, gap=BOLD_GAP, lower_cells=()):
    """640-byte table (left, advance) per font-2 cell, font-2 pixels, for
    the bold routine: letters and punctuation reached through the slot
    table plus the lowercase cells; digits keep the full cell (tabular)."""
    w = bytearray(2 * CELLS2)
    cells = {slot_table[ch] for ch in range(0x21, 0x7F)} | set(lower_cells)
    cells -= {slot_table[d] for d in b'0123456789'}
    for cell in cells:
        r, c = divmod(cell, COLS2)
        xs = [x for y in range(CELL2_H) for x in range(CELL2_W)
              if font2_pixels[(r * CELL2_H + y) * 128 + c * CELL2_W + x] >= 3]
        if xs:
            w[2 * cell] = min(xs)
            w[2 * cell + 1] = min(CELL2_W, max(xs) - min(xs) + 1 + gap)
    s = slot_table[0x20]
    w[2 * s], w[2 * s + 1] = 0, BOLD_SPACE
    return bytes(w)


def _bold_hook(a):
    """5: bold routine loop tail. in: t0 ctx, t4 second vertex, a0 v of this
    glyph, s0 next char, ra = runtime of BOLD_RET. out: a2 = (s0 < 0x20),
    vertices shifted by the left bearing, ctx x advanced by the glyph width."""
    a.label('bold')
    a.op('sltiu', 'a2', 's0', 0x20)
    a.op('lhu', 't1', 0, 't0')
    a.op('lhu', 'a1', 4, 't0')
    a.op('lui', 't8', ('hi', 'bold_flag', BOLD_RET))  # copy bound for this string?
    a.op('addiu', 't8', 't8', ('lo', 'bold_flag', BOLD_RET))
    a.op('addu', 't8', 't8', 'ra')
    a.op('lw', 't9', 0, 't8')
    a.op('beqz', 't9', 'bold_end')
    a.op('nop')
    a.op('lhu', 't6', -0x10, 't4')                     # u of the first vertex
    a.op('li', 't7', 2731)
    a.op('mult', 't6', 't7')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 15)                       # column = u / 12
    a.op('sra', 't7', 'a0', 4)                        # row = v / 16
    a.op('sll', 't8', 't7', 3)
    a.op('sll', 't7', 't7', 1)
    a.op('addu', 't7', 't7', 't8')
    a.op('addu', 't6', 't6', 't7')                    # cell
    a.op('lui', 't8', ('hi', 'bold_widths', BOLD_RET))
    a.op('addiu', 't8', 't8', ('lo', 'bold_widths', BOLD_RET))
    a.op('addu', 't8', 't8', 'ra')
    a.op('sll', 't6', 't6', 1)
    a.op('addu', 't8', 't8', 't6')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'bold_end')
    a.op('lbu', 't6', 0, 't8')
    a.op('lh', 't7', -8, 't4')                        # x of both vertices
    a.op('lh', 't8', 8, 't4')
    a.op('subu', 't5', 't8', 't7')
    a.op('mult', 't6', 't5')
    a.op('mflo', 't6')
    a.op('li', 't5', RECIP12)
    a.op('mult', 't6', 't5')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('subu', 't7', 't7', 't6')
    a.op('sh', 't7', -8, 't4')
    a.op('subu', 't8', 't8', 't6')
    a.op('sh', 't8', 8, 't4')
    a.op('mult', 't9', 'a1')
    a.op('mflo', 'a1')
    a.op('mult', 'a1', 't5')
    a.op('mflo', 'a1')
    a.op('sra', 'a1', 'a1', 16)
    a.label('bold_end')
    a.op('addu', 't1', 't1', 'a1')
    a.op('jr', 'ra')
    a.op('sh', 't1', 0, 't0')


def _squeeze(a, reg, entry, tmp, label):
    """reg = reg * entry[513] >> 8 when that byte is not 0"""
    a.op('lbu', tmp, 513, entry)
    a.op('beqz', tmp, label)
    a.op('nop')
    a.op('mult', reg, tmp)
    a.op('mflo', reg)
    a.op('sra', reg, reg, 8)
    a.label(label)


def _bold_start_hook(a):
    """8: bold routine start. in: a0 string, ra = runtime of BOLD_START_RET,
    sp = the routine's frame. Saves fp/s6/s5 (the call site saves the rest),
    s7 = 0, s2 = a0, then binds the lowercase copy of font 2 unless the
    string has a two-byte code drawn from one of the borrowed cells.
    a0..a3 and v1 come back unchanged: the routine passes a0 (the string)
    on to 0x187C60 right after its prologue. Scratch: the routine's locals
    at sp+0..0xC (written before use) and its unused slots 0x38/0x3C."""
    lo_cell, hi_cell = BOLD_CELLS_RANGE
    a.label('bold_start')
    a.op('sw', 'fp', 0x30, 'sp')
    a.op('sw', 's6', 0x28, 'sp')
    a.op('sw', 's5', 0x24, 'sp')
    a.op('sw', 'ra', 0x38, 'sp')
    a.op('sw', 'v1', 0x3C, 'sp')
    a.op('sw', 'a1', 0, 'sp')
    a.op('sw', 'a2', 4, 'sp')
    a.op('sw', 'a3', 8, 'sp')
    a.op('move', 's7', 'zero')
    a.op('move', 's2', 'a0')
    a.op('move', 's5', 'a0')
    a.op('lui', 's6', ('hi', 'bold_flag', BOLD_START_RET))
    a.op('addiu', 's6', 's6', ('lo', 'bold_flag', BOLD_START_RET))
    a.op('addu', 's6', 's6', 'ra')
    a.op('sw', 'zero', 0, 's6')
    a.label('bs_scan')
    a.op('lbu', 't0', 0, 's5')
    a.op('beqz', 't0', 'bs_copy')
    a.op('sltiu', 't1', 't0', 0x20)
    a.op('beqz', 't1', 'bs_text')
    a.op('sltiu', 't1', 't0', 3)                      # control code: 3..0x10 carry 4 bytes
    a.op('bnez', 't1', 'bs_one')
    a.op('sltiu', 't1', 't0', 0x11)
    a.op('beqz', 't1', 'bs_one')
    a.op('nop')
    a.op('b', 'bs_scan')
    a.op('addiu', 's5', 's5', 5)
    a.label('bs_text')
    a.op('addiu', 't1', 't0', -0x7F)                  # two-byte lead: 0x7F..0xA0 or >= 0xE0
    a.op('andi', 't1', 't1', 0xFF)
    a.op('sltiu', 't1', 't1', 0x22)
    a.op('bnez', 't1', 'bs_two')
    a.op('sltiu', 't1', 't0', 0xE0)
    a.op('beqz', 't1', 'bs_two')
    a.op('nop')
    a.label('bs_one')
    a.op('b', 'bs_scan')
    a.op('addiu', 's5', 's5', 1)
    a.label('bs_two')
    a.op('move', 'a0', 't0')
    a.op('lbu', 'a1', 1, 's5')
    a.op('lw', 't3', 0x38, 'sp')
    a.op('lui', 'at', ('hi', CODE_TO_CELL - BOLD_START_RET))
    a.op('addiu', 'at', 'at', ('lo', CODE_TO_CELL - BOLD_START_RET))
    a.op('addu', 'at', 'at', 't3')
    a.op('jalr', 'at')
    a.op('addiu', 's5', 's5', 2)
    a.op('sltiu', 't1', 'v0', lo_cell)
    a.op('bnez', 't1', 'bs_scan')
    a.op('sltiu', 't1', 'v0', hi_cell + 1)
    a.op('bnez', 't1', 'bs_done')                     # kana from a borrowed cell: retail font
    a.op('nop')
    a.op('b', 'bs_scan')
    a.op('nop')
    a.label('bs_copy')
    a.op('li', 't0', 1)
    a.op('sw', 't0', 0, 's6')
    a.op('lw', 't3', 0x38, 'sp')
    a.op('lui', 'at', ('hi', GU_TEX_IMAGE - BOLD_START_RET))
    a.op('addiu', 'at', 'at', ('lo', GU_TEX_IMAGE - BOLD_START_RET))
    a.op('addu', 'at', 'at', 't3')
    a.op('lui', 't0', ('hi', 'bold_texture', BOLD_START_RET))
    a.op('addiu', 't0', 't0', ('lo', 'bold_texture', BOLD_START_RET))
    a.op('addu', 't0', 't0', 't3')
    a.op('move', 'a0', 'zero')
    a.op('li', 'a1', 0x80)
    a.op('li', 'a2', 0x200)
    a.op('jalr', 'at')
    a.op('li', 'a3', 0x80)
    a.label('bs_done')
    a.op('move', 'a0', 's2')
    a.op('lw', 'a1', 0, 'sp')
    a.op('lw', 'a2', 4, 'sp')
    a.op('lw', 'a3', 8, 'sp')
    a.op('lw', 'ra', 0x38, 'sp')
    a.op('jr', 'ra')
    a.op('lw', 'v1', 0x3C, 'sp')


def _ticker_hooks(a, sx):
    """6: ticker layout, single byte. in: s0 char, a0 slottab, s2 record,
    sp frame. out: record [2] slot, [4] advance; s4 = advance.
    7: ticker draw, font-1 sprite. in: a0 gfx, s3 record, s4 x, t2 x0,
    fp y base, t1 y1, ra = runtime of TICKER_DRAW_RET. out: x0/y0/y1
    stored, s2 = x1 (stored by the caller's delay slot)."""
    a.label('ticker_layout')
    a.op('addu', 't8', 's0', 'a0')
    a.op('lbu', 't7', 0, 't8')
    a.op('sh', 't7', 2, 's2')
    a.op('lw', 't9', 4, 'sp')
    a.op('srl', 's4', 't9', 1)
    a.op('lui', 't8', ('hi', 'widths', SLOTTAB))
    a.op('addiu', 't8', 't8', ('lo', 'widths', SLOTTAB))
    a.op('addu', 't8', 't8', 'a0')
    a.op('sll', 't7', 't7', 1)
    a.op('addu', 't8', 't8', 't7')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'ticker_layout_end')
    _scale(a, 's4', 'at', sx)                         # its li sits in the delay slot
    _squeeze(a, 's4', 't8', 'at', 'ticker_layout_sq')
    a.op('li', 'at', RECIP23)
    a.op('mult', 's4', 'at')
    a.op('mflo', 's4')
    a.op('mult', 't9', 's4')
    a.op('mflo', 's4')
    a.op('sra', 's4', 's4', 16)
    a.label('ticker_layout_end')
    a.op('jr', 'ra')
    a.op('sh', 's4', 4, 's2')

    a.label('ticker_draw')
    a.op('lhu', 'v1', 6, 's3')                        # height
    a.op('subu', 'a2', 'fp', 'v1')
    a.op('addiu', 'a1', 'a2', 0x7900)
    a.op('sh', 'a1', 0x43E, 'a0')
    a.op('sh', 't1', 0x442, 'a0')
    a.op('lhu', 't3', 4, 's3')                        # advance / width
    a.op('addu', 's2', 't3', 's4')
    a.op('addiu', 's2', 's2', 0x6C00)                 # retail x1
    a.op('lhu', 't4', 2, 's3')                        # glyph
    a.op('sltiu', 't5', 't4', 0x100)
    a.op('beqz', 't5', 'ticker_plain')
    a.op('sll', 't5', 't3', 2)                        # single byte if width*4 < height*5
    a.op('sll', 't6', 'v1', 2)
    a.op('addu', 't6', 't6', 'v1')
    a.op('sltu', 't5', 't5', 't6')
    a.op('beqz', 't5', 'ticker_plain')
    a.op('lui', 't8', ('hi', 'widths', TICKER_DRAW_RET))
    a.op('addiu', 't8', 't8', ('lo', 'widths', TICKER_DRAW_RET))
    a.op('addu', 't8', 't8', 'ra')
    a.op('sll', 't4', 't4', 1)
    a.op('addu', 't8', 't8', 't4')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'ticker_plain')
    a.op('li', 't7', HALF_PER_HEIGHT)
    a.op('mult', 'v1', 't7')
    a.op('mflo', 't7')
    a.op('sra', 't7', 't7', 8)                        # half cell width
    _scale(a, 't7', 'at', sx)
    _squeeze(a, 't7', 't8', 'at', 'ticker_draw_sq')
    a.op('lbu', 't6', 0, 't8')                        # left
    a.op('mult', 't6', 't7')
    a.op('mflo', 't6')
    a.op('li', 'at', RECIP23)
    a.op('mult', 't6', 'at')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('subu', 't2', 't2', 't6')                    # x0 - left
    a.op('addu', 's2', 't2', 't7')                    # x1 = x0 + sprite width
    a.label('ticker_plain')
    a.op('jr', 'ra')
    a.op('sh', 't2', 0x43C, 'a0')


def _scale(a, reg, tmp, sx):
    """reg = reg * sx >> 8"""
    a.op('li', tmp, sx)
    a.op('mult', reg, tmp)
    a.op('mflo', reg)
    a.op('sra', reg, reg, 8)


def hooks(base, widths, sx=DEFAULT_SX, fontsel=1, bold_widths=None, ticker=False, bold_texture=None):
    """Assemble the hooks + width tables at vaddr base (the fifth, bold,
    hook only with bold_widths). Returns (bytes, labels)."""
    a = mips_asm.Asm(base)
    # 1: put-char of the text printer. in: a0 item, a1 width source, a2 height,
    #    a3 &slottab[c], v1 slottab, s4 y, s5 x. out: item filled, s2 = advance
    a.label('putchar')
    a.op('li', 't0', fontsel)
    a.op('sb', 't0', 0, 'a0')
    a.op('lbu', 't7', 0, 'a3')
    a.op('sh', 't7', 2, 'a0')
    a.op('sra', 's2', 'a1', 9)
    a.op('sh', 's4', 6, 'a0')
    a.op('sh', 'a2', 0xA, 'a0')
    a.op('sh', 's2', 8, 'a0')
    a.op('sh', 's5', 4, 'a0')
    a.op('lui', 't8', ('hi', 'widths', SLOTTAB))
    a.op('addiu', 't8', 't8', ('lo', 'widths', SLOTTAB))
    a.op('addu', 't8', 't8', 'v1')
    a.op('sll', 't6', 't7', 1)
    a.op('addu', 't8', 't8', 't6')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'putchar_end')
    a.op('lbu', 't6', 0, 't8')
    _scale(a, 's2', 't0', sx)
    _squeeze(a, 's2', 't8', 't0', 'putchar_sq')
    a.op('sh', 's2', 8, 'a0')
    a.op('li', 't0', RECIP23)
    a.op('mult', 's2', 't0')
    a.op('mflo', 't0')
    a.op('mult', 't6', 't0')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('subu', 't6', 's5', 't6')
    a.op('sh', 't6', 4, 'a0')
    a.op('mult', 't9', 't0')
    a.op('mflo', 's2')
    a.op('sra', 's2', 's2', 16)
    a.op('lb', 't6', 512, 't8')                       # y offset (t8 = &widths[2*slot])
    a.op('mult', 't6', 'a2')
    a.op('mflo', 't6')
    a.op('li', 't9', RECIP23)
    a.op('mult', 't6', 't9')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('addu', 't6', 't6', 's4')
    a.op('sh', 't6', 6, 'a0')
    a.label('putchar_end')
    a.op('jr', 'ra')
    a.op('nop')
    # 2: line layout. in: t4 record, a0 &slottab[c], t7 slottab, s3 cell width,
    #    s7 height, sp frame. out: record + marker, s3 = advance
    a.label('layout')
    a.op('lw', 't6', 8, 'sp')
    a.op('lbu', 't5', 0, 't6')
    a.op('sb', 't5', 2, 't4')
    a.op('lbu', 's1', 0, 'a0')
    a.op('sh', 's7', 8, 't4')
    a.op('sh', 's1', 4, 't4')
    a.op('sh', 's3', 6, 't4')
    a.op('li', 't5', 1)
    a.op('sb', 't5', 3, 't4')
    a.op('lui', 't6', ('hi', 'widths', SLOTTAB))
    a.op('addiu', 't6', 't6', ('lo', 'widths', SLOTTAB))
    a.op('addu', 't6', 't6', 't7')
    a.op('sll', 't5', 's1', 1)
    a.op('addu', 't6', 't6', 't5')
    a.op('lbu', 't5', 1, 't6')
    a.op('beqz', 't5', 'layout_end')
    _scale(a, 's3', 't6', sx)                         # its li sits in the delay slot
    a.op('lui', 't6', ('hi', 'widths', SLOTTAB))      # entry again (t6 was the scale)
    a.op('addiu', 't6', 't6', ('lo', 'widths', SLOTTAB))
    a.op('addu', 't6', 't6', 't7')
    a.op('sll', 'at', 's1', 1)
    a.op('addu', 't6', 't6', 'at')
    _squeeze(a, 's3', 't6', 'at', 'layout_sq')
    a.op('sh', 's3', 6, 't4')
    a.op('li', 't6', RECIP23)
    a.op('mult', 's3', 't6')
    a.op('mflo', 't6')
    a.op('mult', 't5', 't6')
    a.op('mflo', 's3')
    a.op('sra', 's3', 's3', 16)
    a.label('layout_end')
    a.op('jr', 'ra')
    a.op('nop')
    # 3: window glyph loop. in: t2 gfx state, s5 x, t0 x + sprite width, a3 y0,
    #    s3 record, s2 DATA_DE0, sp frame. out: x0/y0/y1 stored, t0 = x1, s5 = next x
    a.label('draw')
    a.op('lw', 't5', 0x14, 'sp')
    a.op('sh', 'a3', 0x43E, 't2')
    a.op('sh', 't5', 0x442, 't2')
    a.op('lbu', 't6', 3, 's3')
    a.op('beqz', 't6', 'draw_plain')
    a.op('lhu', 't7', 4, 's3')
    a.op('sltiu', 't6', 't7', 0x100)
    a.op('beqz', 't6', 'draw_plain')
    a.op('lui', 't8', ('hi', 'widths', DATA_DE0))
    a.op('addiu', 't8', 't8', ('lo', 'widths', DATA_DE0))
    a.op('addu', 't8', 't8', 's2')
    a.op('sll', 't7', 't7', 1)
    a.op('addu', 't8', 't8', 't7')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'draw_plain')
    a.op('lbu', 't6', 0, 't8')
    a.op('subu', 't7', 't0', 's5')
    a.op('li', 't8', RECIP23)
    a.op('mult', 't7', 't8')
    a.op('mflo', 't8')
    a.op('mult', 't6', 't8')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('subu', 't6', 's5', 't6')
    a.op('sh', 't6', 0x43C, 't2')
    a.op('addu', 't0', 't6', 't7')
    a.op('mult', 't9', 't8')
    a.op('mflo', 't9')
    a.op('sra', 't9', 't9', 16)
    a.op('addu', 's5', 's5', 't9')
    a.op('andi', 's5', 's5', 0xFFFF)
    a.op('lui', 't8', ('hi', 'widths', DATA_DE0))      # y offset of this slot
    a.op('addiu', 't8', 't8', ('lo', 'widths', DATA_DE0))
    a.op('addu', 't8', 't8', 's2')
    a.op('lhu', 't7', 4, 's3')
    a.op('sll', 't7', 't7', 1)
    a.op('addu', 't8', 't8', 't7')
    a.op('lb', 't6', 512, 't8')
    a.op('beqz', 't6', 'draw_end')
    a.op('subu', 't7', 't5', 'a3')                    # sprite height
    a.op('mult', 't6', 't7')
    a.op('mflo', 't6')
    a.op('li', 't7', RECIP23)
    a.op('mult', 't6', 't7')
    a.op('mflo', 't6')
    a.op('sra', 't6', 't6', 16)
    a.op('addu', 't7', 'a3', 't6')
    a.op('sh', 't7', 0x43E, 't2')
    a.op('addu', 't7', 't5', 't6')
    a.op('sh', 't7', 0x442, 't2')
    a.label('draw_end')
    a.op('jr', 'ra')
    a.op('nop')
    a.label('draw_plain')
    a.op('sh', 's5', 0x43C, 't2')
    a.op('jr', 'ra')
    a.op('andi', 's5', 't0', 0xFFFF)
    # 4: box measurer. in: v0 flags, s1 &char, s6 width source, sp frame,
    #    ra = runtime of 0x142858. out: fp = width of this char
    ret4 = 0x142858
    a.label('measure')
    a.op('andi', 't9', 'v0', 2)
    a.op('bnez', 't9', 'measure_full')
    a.op('lw', 'a2', 0x4C, 'sp')
    a.op('lhu', 'a1', 0, 'a2')
    a.op('andi', 'v1', 'a1', 1)
    a.op('bnez', 'v1', 'measure_full')
    a.op('lhu', 'a3', 0, 's6')
    a.op('srl', 'fp', 'a3', 1)
    a.op('lbu', 't9', 0, 's1')
    a.op('lui', 't8', ('hi', SLOTTAB - ret4))
    a.op('addiu', 't8', 't8', ('lo', SLOTTAB - ret4))
    a.op('addu', 't8', 't8', 'ra')
    a.op('addu', 't9', 't9', 't8')
    a.op('lbu', 't9', 0, 't9')
    a.op('sll', 't9', 't9', 1)
    a.op('addu', 't8', 't8', 't9')
    a.op('lui', 't9', ('hi', 'widths', SLOTTAB))
    a.op('addiu', 't9', 't9', ('lo', 'widths', SLOTTAB))
    a.op('addu', 't8', 't8', 't9')
    a.op('lbu', 't9', 1, 't8')
    a.op('beqz', 't9', 'measure_end')
    _scale(a, 'fp', 'at', sx)                         # its li sits in the delay slot
    _squeeze(a, 'fp', 't8', 'at', 'measure_sq')
    a.op('li', 't8', RECIP23)
    a.op('mult', 'fp', 't8')
    a.op('mflo', 't8')
    a.op('mult', 't9', 't8')
    a.op('mflo', 'fp')
    a.op('jr', 'ra')
    a.op('sra', 'fp', 'fp', 16)
    a.label('measure_full')
    a.op('lhu', 'fp', 0, 's6')
    a.label('measure_end')
    a.op('jr', 'ra')
    a.op('nop')
    if bold_widths is not None:
        _bold_hook(a)
        _bold_start_hook(a)
    if ticker:
        _ticker_hooks(a, sx)
    a.align(4)
    a.label('widths')
    a.data(widths)
    if bold_widths is not None:
        a.label('bold_widths')
        a.data(bold_widths)
        a.align(4)
        a.label('bold_flag')
        a.data(bytes(4))
        a.align(64)
        a.label('bold_texture')
        a.data(bold_texture if bold_texture is not None else bytes(0x8000))
    return a.assemble(), dict(a.labels)


def call_sites(labels):
    """[(vaddr, word)] for every patched word in the executable."""
    words = []

    def site(base, build):
        s = mips_asm.Asm(base)
        build(s)
        words.extend(s.words())

    def putchar(s):                                   # 0x143380..0x1433A0
        s.op('lw', 'a0', 0x20, 't1')
        s.op('lui', 'at', ('hi', labels['putchar'] - SLOTTAB))
        s.op('addiu', 'at', 'at', ('lo', labels['putchar'] - SLOTTAB))
        s.op('addu', 'at', 'at', 'v1')
        s.pc += 4                                     # 0x143390: relocated lw, kept
        s.op('jalr', 'at')
        s.op('nop')
        s.op('b', 0x1433C0)
        s.op('nop')
    site(0x143380, putchar)

    def layout(s):                                    # 0x13EE24..0x13EE44
        s.op('lui', 'at', ('hi', labels['layout'] - SLOTTAB))
        s.op('addiu', 'at', 'at', ('lo', labels['layout'] - SLOTTAB))
        s.op('addu', 'at', 'at', 't7')
        s.op('jalr', 'at')
        s.op('move', 'a2', 'zero')
        s.op('nop')
        s.op('nop')
        s.pc += 4                                     # 0x13EE40: relocated j, kept
        s.op('nop')                                   # hook stored the width
    site(0x13EE24, layout)
    site(0x13ECA4, lambda s: s.op('sh', 'v1', 0, 's0'))
    site(0x13ECAC, lambda s: s.op('sb', 'zero', 3, 's0'))
    site(0x13F010, lambda s: s.op('sh', 's2', 0, 't7'))
    site(0x13F018, lambda s: s.op('sb', 'zero', 3, 't7'))

    def draw(s):                                      # 0x140E78..0x140E88
        s.op('lui', 'at', ('hi', labels['draw'] - DATA_DE0))
        s.op('addiu', 'at', 'at', ('lo', labels['draw'] - DATA_DE0))
        s.op('addu', 'at', 'at', 's2')
        s.op('jalr', 'at')
        s.op('nop')
    site(0x140E78, draw)

    def measure(s):                                   # 0x14283C..0x14285C
        s.op('bal', 0x142844)
        s.op('nop')
        s.op('lui', 'at', ('hi', labels['measure'] - 0x142844))
        s.op('addiu', 'at', 'at', ('lo', labels['measure'] - 0x142844))
        s.op('addu', 'at', 'at', 'ra')
        s.op('jalr', 'at')
        s.op('nop')
        s.op('b', 0x142860)
        s.op('nop')
    site(0x14283C, measure)

    def bold(s):                                      # 0x144438..0x144454
        s.op('bal', 0x144440)
        s.op('sw', 's3', 4, 't4')
        s.op('lui', 'at', ('hi', labels['bold'] - 0x144440))
        s.op('addiu', 'at', 'at', ('lo', labels['bold'] - 0x144440))
        s.op('addu', 'at', 'at', 'ra')
        s.op('jalr', 'at')
        s.op('lbu', 's0', 0, 's2')
        s.op('bnez', 's0', 0x1442F4)
    def bold_start(s):                                # 0x144250..0x14426C
        s.op('sw', 'ra', 0x34, 'sp')
        s.op('bal', 0x14425C)
        s.op('sw', 's7', 0x2C, 'sp')
        s.op('lui', 'at', ('hi', labels['bold_start'] - 0x14425C))
        s.op('addiu', 'at', 'at', ('lo', labels['bold_start'] - 0x14425C))
        s.op('addu', 'at', 'at', 'ra')
        s.op('jalr', 'at')
        s.op('sw', 's2', 0x18, 'sp')
        s.op('sw', 's4', 0x20, 'sp')
        s.op('sw', 's3', 0x1C, 'sp')
        s.op('sw', 's1', 0x14, 'sp')
        s.op('sw', 's0', 0x10, 'sp')
    if 'bold' in labels:
        site(0x144438, bold)
        site(0x144250, bold_start)

    def ticker_layout(s):                             # 0x149FD0..0x149FE4
        s.op('lui', 'at', ('hi', labels['ticker_layout'] - SLOTTAB))
        s.op('addiu', 'at', 'at', ('lo', labels['ticker_layout'] - SLOTTAB))
        s.op('addu', 'at', 'at', 'a0')
        s.op('jalr', 'at')
        s.op('nop')
        s.op('nop')

    def ticker_draw(s):                               # 0x14A4A0..0x14A4C0
        s.op('bal', 0x14A4A8)
        s.op('nop')
        s.op('lui', 'at', ('hi', labels['ticker_draw'] - 0x14A4A8))
        s.op('addiu', 'at', 'at', ('lo', labels['ticker_draw'] - 0x14A4A8))
        s.op('addu', 'at', 'at', 'ra')
        s.op('jalr', 'at')
        s.op('nop')
        s.op('nop')
        s.op('nop')
    if 'ticker_layout' in labels:
        site(0x149FD0, ticker_layout)
        site(0x14A4A0, ticker_draw)
    return words


def _pool_header(b):
    phoff = struct.unpack_from('<I', b, 0x1C)[0]
    phnum = struct.unpack_from('<H', b, 0x2C)[0]
    for i in range(phnum):
        o = phoff + 32 * i
        p = list(struct.unpack_from('<8I', b, o))
        if p[0] == 1 and p[2] == POOL_VADDR:
            return o, p
    raise ValueError('no pool segment (run psp_pool first)')


def patch_boot(boot, font_member, sx=DEFAULT_SX, gap=DEFAULT_GAP, bold=False, ticker=False):
    """Append the hooks + width table to the pool and patch the call sites.
    boot: BOOT.BIN after psp_pool / patch_bold_table; font_member: the built
    font-1 member (psp_lowercase.build_font). Returns (bytes, info)."""
    import psp_font
    b = bytearray(boot)
    checks = {**RETAIL, **(RETAIL_BOLD if bold else {}), **(RETAIL_TICKER if ticker else {})}
    for va, want in checks.items():
        got = struct.unpack_from('<I', b, va + TEXT_BIAS)[0]
        if got not in (want if isinstance(want, tuple) else (want,)):
            raise ValueError('unexpected word %08x at vaddr %#x (VWF already applied, or not a retail BOOT.BIN)' % (got, va))
    off, p = _pool_header(b)
    if p[1] + p[4] != len(b) or p[4] != p[5]:
        raise ValueError('the pool segment must end the file')
    gray = psp_font.deswizzle(font_member)
    widths = build_widths(gray, b[SLOTTAB_FILE:SLOTTAB_FILE + 256], gap)
    pad = (-p[4]) % 16
    base = POOL_VADDR + p[4] + pad
    bold_widths = texture = None
    if bold:
        import psp_bold_lowercase
        tab_at = psp_bold_lowercase.map_table(b)
        texture, pixels = psp_bold_lowercase.bold_texture(b, font_member)
        bold_widths = build_bold_widths(pixels, b[tab_at:tab_at + 256],
                                        lower_cells=psp_bold_lowercase.BOLD_CELLS)
    code, labels = hooks(base, widths, sx, bold_widths=bold_widths, ticker=ticker,
                         bold_texture=texture)
    b += bytes(pad) + code
    p[4] = p[5] = p[4] + pad + len(code)
    struct.pack_into('<8I', b, off, *p)
    for va, word in call_sites(labels):
        struct.pack_into('<I', b, va + TEXT_BIAS, word)
    return bytes(b), {'hooks_vaddr': hex(base), 'bytes': len(code), 'scale': sx, 'gap': gap, 'bold': bold, 'ticker': ticker,
                      'glyphs': sum(1 for i in range(256) if widths[2 * i + 1])}
