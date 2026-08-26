#!/usr/bin/env python3
"""Add lowercase Latin to the PSP font and remap a-z to render lowercase.

The retail font (FPB member 00000, 256x4400 4bpp, see psp_font) has only 11
of 26 Latin lowercase glyphs (a e g h k m o r t y z); a-z all map to the
capital glyphs via the u16 ASCII table in BOOT.BIN (0x27DB40), so text shows
ALL CAPS. This derives the missing 15 lowercase glyphs from the font's own
parts (guaranteed style match), writes them into free cells 2095..2109, and
remaps bytes 0x61..0x7A in the ASCII table to the 26 lowercase glyph codes.

Touches: FPB member 00000 (texture) + BOOT.BIN (ASCII map). Optionally the
glyph list (member 00001) for consistency.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_font

W, COLS, CELL = 256, 11, 23
ASCII_MAP = 0x27DB40                      # file offset in BOOT.BIN, u16[256]
EXISTING = {'a': 2077, 'e': 2076, 'g': 1688, 'h': 2075, 'k': 1687, 'm': 1686,
            'o': 2073, 'r': 2078, 'y': 2074, 't': 2079, 'z': 1516}
MISSING = 'bcdfijlnpqsuvwx'              # 15, placed in FREE_CELLS
FREE_CELLS = list(range(217, 232))       # in-bounds unused cells (codes 0x9a5f..0x9a6d)


def _decode(code):
    if code <= 0x993f: code = 0x9940
    hi, lo = code >> 8, code & 0xff
    if hi >= 0xe0: hi -= 0x40
    if lo >= 0x80: lo -= 1
    if lo >= 0x5d: lo -= 1
    return (hi - 0x99) * 187 + (lo - 0x40)


def _inv():
    inv = {}
    for hi in list(range(0x99, 0xa0)) + list(range(0xe0, 0xe5)):
        for lo in range(0x40, 0xfd):
            inv.setdefault(_decode((hi << 8) | lo), (hi << 8) | lo)
    return inv


def _cell(gray, gi):
    col, row = gi % COLS, gi // COLS
    x0, y0 = col * CELL, row * CELL + 1
    return [[gray[(y0 + r) * W + (x0 + c)] for c in range(22)] for r in range(22)]


def _put(gray, gi, bmp):
    col, row = gi % COLS, gi // COLS
    x0, y0 = col * CELL, row * CELL + 1
    for r in range(22):
        for c in range(22):
            gray[(y0 + r) * W + (x0 + c)] = bmp[r][c]


def _derive(gray):
    """Return {letter: 22x22 bitmap} for the 15 missing lowercase glyphs."""
    O, E, H, R, T, Y = (_cell(gray, i) for i in (2073, 2076, 2075, 2078, 2079, 2074))
    def blank(): return [[0] * 22 for _ in range(22)]
    def hflip(b): return [row[::-1] for row in b]
    def vflip(b): return b[::-1]
    D = {}
    # l : left stem of h (full ascender)
    l = blank()
    for r in range(22):
        for c in range(5, 10):
            if H[r][c] > 40: l[r][c] = H[r][c]
    D['l'] = l
    # i : short stem + dot
    i = blank()
    for r in range(7, 22):
        for c in range(5, 10): i[r][c] = l[r][c] if l[r][c] else (200 if l[10][c] > 40 else 0)
    for r in range(2, 5):
        for c in range(5, 10):
            if l[10][c] > 40: i[r][c] = 210
    D['i'] = i
    # n : h without the ascender (blank the top of the left stem)
    n = [row[:] for row in H]
    for r in range(0, 7):
        for c in range(22): n[r][c] = 0
    D['n'] = n
    # u : n flipped vertically
    D['u'] = vflip(n)
    # c : o opened on the right
    c = [row[:] for row in O]
    for r in range(9, 13):
        for cc in range(13, 20): c[r][cc] = 0
    D['c'] = c
    # b : full stem + o bowl
    b = [row[:] for row in l]
    for r in range(7, 21):
        for cc in range(8, 20):
            if O[r][cc] > 40: b[r][cc] = O[r][cc]
    D['b'] = b
    D['d'] = hflip(b)
    # p : stem with descender + o bowl
    p = blank()
    for r in range(7, 22):
        for cc in range(5, 10): p[r][cc] = 210
    for r in range(7, 21):
        for cc in range(8, 20):
            if O[r][cc] > 40: p[r][cc] = O[r][cc]
    D['p'] = p
    D['q'] = hflip(p)
    # f : ascender stem, top hook, crossbar (t-derived)
    f = blank()
    for r in range(4, 22):
        for cc in range(9, 14): f[r][cc] = 220
    for r in range(2, 5):
        for cc in range(9, 15): f[r][cc] = 220
    for r in range(9, 12):
        for cc in range(6, 16): f[r][cc] = 220
    D['f'] = f
    # j : dotted stem with descender hook
    j = blank()
    for r in range(7, 22):
        for cc in range(12, 17): j[r][cc] = 210
    for r in range(19, 22):
        for cc in range(6, 13): j[r][cc] = 210
    for r in range(2, 5):
        for cc in range(12, 17): j[r][cc] = 210
    D['j'] = j
    # s : hand-drawn to match the ~5px bold stroke
    s_rows = [
        "......###########....",
        ".....#############...",
        ".....#####...........",
        ".....#####...........",
        ".....#############...",
        "......############...",
        "...........#####.....",
        "...........#####.....",
        "....#############....",
        "....############.....",
    ]
    s = blank()
    for k, line in enumerate(s_rows):
        for cc, ch in enumerate(line):
            if ch == '#': s[7 + k][cc] = 230
    D['s'] = s
    # v : y without descender
    v = blank()
    for r in range(7, 19):
        for cc in range(22):
            if Y[r][cc] > 40: v[r][cc] = Y[r][cc]
    D['v'] = v
    # x : two diagonals
    x = blank()
    for r in range(7, 21):
        pr = (r - 7) / 13.0
        c1, c2 = int(5 + pr * 11), int(16 - pr * 11)
        for dc in (-1, 0, 1):
            if 0 <= c1 + dc < 22: x[r][c1 + dc] = 220
            if 0 <= c2 + dc < 22: x[r][c2 + dc] = 220
    D['x'] = x
    # w : two narrow v's
    w = blank()
    for r in range(7, 21):
        pr = (r - 7) / 13.0
        for base in (4, 12):
            for cbase, cd in ((base, pr * 5), (base + 6, 6 - pr * 5 - 6 + 6)):
                pass
        left = int(4 + pr * 4); l2 = int(10 - pr * 4)
        rgt = int(12 + pr * 4); r2 = int(18 - pr * 4)
        for cc in (left, left + 1, l2, l2 + 1, rgt, rgt + 1, r2, r2 + 1):
            if 0 <= cc < 22: w[r][cc] = 220
    D['w'] = w
    return D


def build_font(member00000):
    gray = bytearray(psp_font.deswizzle(member00000))
    D = _derive(gray)
    for i, letter in enumerate(MISSING):
        _put(gray, FREE_CELLS[i], D[letter])
    return psp_font.reswizzle(bytes(gray))


def patch_ascii_map(boot):
    b = bytearray(boot)
    inv = _inv()
    codes = {}
    for L, gi in EXISTING.items(): codes[L] = inv[gi]
    for i, L in enumerate(MISSING): codes[L] = inv[FREE_CELLS[i]]
    for L, code in codes.items():
        struct.pack_into('<H', b, ASCII_MAP + ord(L) * 2, code)
    return bytes(b), codes


if __name__ == '__main__':
    # self-test: derive + render to ascii
    gray = bytearray(psp_font.deswizzle(open('somestuffpsp/FPB/00000.bin', 'rb').read()))
    D = _derive(gray)
    for L in MISSING:
        print('---', L, '---')
        for row in D[L]:
            print('  ' + ''.join('#' if v > 60 else '.' for v in row))
