#!/usr/bin/env python3
"""Dual-Tile Encoding (DTE) for the PSP menu text: half-width Latin.

The menu/battle renderer draws single-byte ASCII at a FULL kanji-cell width, so
English arte names collide in the grid and descriptions overrun their box. It
draws two-byte glyph codes one-cell-wide though (that is how the element kanji
render), so if we paint TWO half-width Latin letters into one glyph cell and
encode a common letter-pair as that cell's two-byte code, the pair renders in a
single cell -> effective half width, in every renderer, with no code patch.

The font has no blank cells, but the English build never displays the ~1800
kanji glyphs, so we repurpose kanji cells as donor tiles (their codes never
appear in English text). Each DTE code is two bytes and replaces two ASCII
bytes, so a DTE string is never longer than the ASCII one -> the in-place and
pool logic are untouched.

Width only for v1: text is upper-cased before pairing (keeps the current look),
lowercase is deferred. A pair with no tile falls back to two single glyphs.
"""
import os, sys, struct, collections, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_font

W, COLS, CELL, GLYPH = 256, 11, 23, 22
H = 4400
NCELL = (H // CELL) * COLS
ASCII_MAP = 0x27DB40

# Kanji still shown in ENGLISH menus as short single/compound labels (elements,
# equip slots, monster categories, resistances, tab glyphs). These must NOT be
# repurposed as DTE tiles or an English screen would show a stray Latin pair.
# The explicit core, plus every kanji in a short (<=4 char) menu-table JP entry,
# since those short labels are the ones that can survive as on-screen kanji.
_CORE_KEEP = set('光水火風地闇無雷氷炎樹地空聖魔剣刀槍杖弓拳体頭腕脚足靴胴盾'
                 '獣鳥虫魚人竜龍鈍弱強無効吸収反射石鉄木布革骨')


def _keep_kanji():
    keep = set(_CORE_KEEP)
    path = os.path.join(HERE, 'psp_menu.tsv')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            if line.startswith('#') or '\t' not in line:
                continue
            jp = line.split('\t')[0]
            if len(jp) <= 4:
                for ch in jp:
                    if '一' <= ch <= '鿿':
                        keep.add(ch)
    return keep


KEEP_KANJI = _keep_kanji()

# characters we build tiles from (everything printable ASCII that a menu uses)
TILE_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?:'-+/%()<>"


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


def _cell2code():
    m = {}
    for hi in list(range(0x99, 0xa0)) + list(range(0xe0, 0xe5)):
        for lo in range(0x40, 0xfd):
            c = _decode((hi << 8) | lo)
            if 0 <= c < NCELL:
                m.setdefault(c, (hi << 8) | lo)
    return m


def _donor_cells(pt):
    """Kanji cells the English build never shows, with an emittable code."""
    c2c = _cell2code()
    donors = []
    for k, ch in pt.TBL.items():
        cell = _decode(int(k))
        if not (0 <= cell < NCELL) or cell not in c2c:
            continue
        if any('一' <= x <= '鿿' for x in ch) and not any(x in KEEP_KANJI for x in ch):
            donors.append(cell)
    # Highest cells first = rarest JIS level-2 kanji, least likely to appear in
    # any still-Japanese text, so a repurposed cell almost never mis-renders.
    donors.sort(reverse=True)
    return donors, c2c


def _corpus_pairs(paths):
    """Count adjacent-char pairs over the uppercased menu corpus."""
    cnt = collections.Counter()
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8'):
            if line.startswith('#') or '\t' not in line:
                continue
            en = line.rstrip('\n').split('\t')[1].upper()
            en = ''.join(c if c in TILE_CHARS else ' ' for c in en)
            for i in range(len(en) - 1):
                a, b = en[i], en[i + 1]
                if a in TILE_CHARS and b in TILE_CHARS:
                    cnt[(a, b)] += 1
    return cnt


_TABLE = None      # {(a,b): code}
_ASSIGN = None     # {(a,b): cell}


def build_table(pt, boot, extra_paths=()):
    """Deterministically pick the top letter-pairs and bind each to a donor
    cell/code. Returns (pairs {(a,b):code}, assign {(a,b):cell})."""
    global _TABLE, _ASSIGN
    donors, c2c = _donor_cells(pt)
    paths = [os.path.join(HERE, 'psp_menu.tsv'), os.path.join(HERE, 'psp_monsters.tsv')] + list(extra_paths)
    pairs = _corpus_pairs(paths)
    # rank pairs by frequency, cap at donor capacity, and don't waste a tile on
    # a pair that occurs only a handful of times.
    ranked = [ab for ab, n in pairs.most_common() if n >= 8]
    ranked = ranked[:len(donors)]
    table, assign = {}, {}
    for ab, cell in zip(ranked, donors):
        table[ab] = c2c[cell]
        assign[ab] = cell
    _TABLE, _ASSIGN = table, assign
    return table, assign


def ascii_cell(boot, ch):
    """Glyph cell that a printable ASCII byte maps to (from the BOOT map)."""
    code = struct.unpack_from('<H', boot, ASCII_MAP + ord(ch) * 2)[0]
    return _decode(code)


def _read_glyph(gray, cell):
    col, row = cell % COLS, cell // COLS
    x0, y0 = col * CELL, row * CELL + 1
    return [[gray[(y0 + r) * W + (x0 + c)] for c in range(GLYPH)] for r in range(GLYPH)]


def _write_glyph(gray, cell, bmp):
    col, row = cell % COLS, cell // COLS
    x0, y0 = col * CELL, row * CELL + 1
    for r in range(GLYPH):
        for c in range(GLYPH):
            gray[(y0 + r) * W + (x0 + c)] = bmp[r][c]


def _half(bmp):
    """22px-wide glyph -> 10px, max-pooled so thin stems survive the threshold."""
    out = [[0] * 10 for _ in range(GLYPH)]
    for r in range(GLYPH):
        for oc in range(10):
            a = bmp[r][oc * 2]
            b = bmp[r][oc * 2 + 1]
            out[r][oc] = a if a >= b else b
    return out


def draw_tiles(member00000, boot, assign):
    """Paint each assigned pair as two half-width letters into its donor cell."""
    gray = bytearray(psp_font.deswizzle(member00000))
    # cache half-width source glyphs
    halves = {}
    for ch in TILE_CHARS:
        if ch == ' ':
            halves[ch] = [[0] * 10 for _ in range(GLYPH)]
        else:
            halves[ch] = _half(_read_glyph(gray, ascii_cell(boot, ch)))
    for (a, b), cell in assign.items():
        tile = [[0] * GLYPH for _ in range(GLYPH)]
        for r in range(GLYPH):
            for c in range(10):
                tile[r][c] = halves[a][r][c]           # left  0..9
                tile[r][c + 11] = halves[b][r][c]      # right 11..20
        _write_glyph(gray, cell, tile)
    return psp_font.reswizzle(bytes(gray))


def encode_greedy(text):
    """Upper-case, then greedily emit DTE codes for tiled pairs. Returns a list
    of tokens: ('code', u16) or ('chr', ch). The caller turns these into bytes
    with the game's normal single-glyph path for 'chr'."""
    t = text.upper()
    out, i = [], 0
    while i < len(t):
        if i + 1 < len(t) and (t[i], t[i + 1]) in _TABLE:
            out.append(('code', _TABLE[(t[i], t[i + 1])]))
            i += 2
        else:
            out.append(('chr', t[i]))
            i += 1
    return out
