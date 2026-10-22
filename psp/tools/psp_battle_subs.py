#!/usr/bin/env python3
"""English subtitles for the spoken battle lines (PSP).

    python psp/tools/psp_battle_subs.py check       # the table as the PSP draws it

build_psp.py calls patch_boot() on BOOT.BIN after the variable width font.

The PSP port runs the PS2 battle engine (compiled into BOOT.BIN, source
paths ../btl/bt_main.c and so on), so the subtitles work like the PS2 ones
(ps2/menu/battle_subs.py) with PSP addresses. Found in PPSSPP on the
retail image, vaddr (file offset = vaddr + 0xC0, runtime = vaddr +
0x08804000):

* Battle globals at 0x60DBC0 (data segment 0x1DCC00 + 0x430FC0, the
  PS2 block 0x2FA000): +0x160 pointer to the party actors, +0x164 pointer
  to the enemy actors (party slot 4: four party slots come first, used or
  not), +0x195 party size, +0x196 enemy count.
* Actors are 0x2B8 byte records (PS2 0x2A8); the PS2 fields moved by 0xC:
  +0x14A is the id of the voice the actor is speaking (0 when silent),
  +0x155 the character (0 Kyle, 1 Reala, 2 Loni, 3 Judas, 4 Nanaly,
  5 Harold), +0x158 is 1 for enemies. The voice ids are the PS2 ids (Kyle
  4..86, Loni 179..261, ...), so the PS2 table applies unchanged.
* The battle loop 0x1B164 calls the frame function 0x1B2F4 once per frame
  from 0x1B27C (jal, return 0x1B284).
* Text helper 0x544F8 (draws "ENEMY DATA"): a0 x, a1 y, a2 string, a3
  colour, t0 x scale, t1 y scale (0x100 = 1.0). It prints through the
  game's text printer, so the variable width font and lowercase apply.

What this step adds, at the end of the string pool segment (psp_pool;
the kernel loads it since PR 120): the hook code and the subtitle table.
The jal at 0x1B27C gets the hook as its target. The word keeps its
relocation entry (R_MIPS_26, address base = the text segment at vaddr 0):
the loader adds the load address to whatever target the word holds, and
the pool is loaded at load address + its vaddr like every segment, so no
new relocation is needed. The hook builds every other address from its
return address (load address + 0x1B284): it calls the frame function,
then checks the party and the enemies and draws the lines of every actor
whose voice id has text, white, centred, above the HP bars; a second
speaker stacks above the first. The lines are drawn at about 80 % of the
menu text size, and a speaker whose lines would reach above TOP_Y (four
lines above the bottom one) is left out, so stacked speakers cover at
most the lower part of the fight; the first speaker always shows.

Not covered: the story voices that play during the last Fortuna fight
(PSP file.fpb members 8122..8138, the PS2 story voices 5731..5747). They
are ATRAC3plus streams, not battle voices, so no actor holds their id.
They go through the game's one ATRAC stream channel (vaddr 0x452DC8,
file name "file.fpb" at +8, +0 state, nonzero while it streams, +0x88
the file offset of the next read); a hook for them would have to match
that offset against the members and needs a test on that fight.

Table: psp/text/battle_subtitles.csv, the PSP snapshot of
ps2/menu/battle_subtitles.csv (refreshed by sync_text_from_ps2.py). The
English, the speaker rules ('*' = the game supplies the name of the
character whose voice plays) and '|' line breaks are the PS2 ones; the
lines are wrapped again for the PSP screen by pixel width.
"""
import argparse
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mips_asm  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
TABLE = os.path.join(ROOT, 'psp', 'text', 'battle_subtitles.csv')

TEXT_BIAS = 0xC0
POOL_VADDR = 0x881000
FRAME_CALL = 0x1B27C        # jal 0x1B2F4 in the battle loop
RET = FRAME_CALL + 8
FRAME = 0x1B2F4             # battle frame function
TEXT = 0x544F8              # text helper (x, y, string, colour, xscale, yscale)
GLOBALS = 0x60DBC0          # battle globals
PARTY, ENEMIES = 0x160, 0x164
PARTY_SIZE, ENEMY_COUNT = 0x195, 0x196
ACTOR_SIZE = 0x2B8
MAX_ACTORS = 8              # per group, a cap against stray counts
VOICE = 0x14A
CHARACTER = 0x155
ENEMY = 0x158
NAMES = ('Kyle', 'Reala', 'Loni', 'Judas', 'Nanaly', 'Harold')
ENTRIES = 8 + 4 * len(NAMES)
ENTRY_SIZE = 16
MAGIC = b'BSUB'

COLOUR = 7                  # white with the font's dark outline
# The helper works in the PS2 screen space (640 x 448), which the PSP shows
# at 0.75 across and 0.61 down; x : y = 1 : 1.25 keeps the letters in shape.
# 0xD0 x 0x100 is about 80 % of the menu text size (tab 13: the lines were
# too big and several speakers covered the fight).
XSCALE, YSCALE = 0xD0, 0x100
SPACING = 1.05              # measured advance / glyph table advance
SCREEN_W = 640
BOTTOM = 330                # y of the lowest line: above the HP bars and the item banner
LINE_H = 24
GAP = 4
LINE_W = 600                # width a line may use
MAX_LINES = 3
# Highest line drawn: a speaker whose block would reach above this is left
# out (at most four lines on screen; the first speaker always shows).
TOP_Y = BOTTOM - 3 * LINE_H - GAP
FIXED_ADVANCE = 12          # per character without the variable width font


def frame_call_word(target):
    return 0x0C000000 | ((target >> 2) & 0x3FFFFFF)


# --- widths -----------------------------------------------------------------
def advances(vwf=True):
    """Advance per character in font pixels, from the Latin glyph table the
    build draws (psp/fonts/latin_glyphs.json); None without the variable
    width font (one fixed advance)."""
    if not vwf:
        return None
    import psp_latin_font
    g = psp_latin_font.load()['glyphs1']
    return {c: g[c]['adv'] for c in g}


def width(text, adv):
    """Width of `text` in the helper's screen space at XSCALE."""
    if adv is None:
        units = FIXED_ADVANCE * len(text)
    else:
        units = sum(adv.get(c, adv[' ']) for c in text)
    return int(units * XSCALE / 256 * SPACING + 0.5)


# --- the table --------------------------------------------------------------
def read_table(path=TABLE):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def speaker_from_game(row):
    return (row.get('speaker') or '').strip() == '*'


def subtitle(row):
    english = (row.get('english') or '').strip()
    if not english:
        return ''
    speaker = (row.get('speaker') or '').strip()
    return '%s: %s' % (speaker, english) if speaker and speaker != '*' else english


def name_width(adv):
    return max(width(n + ': ', adv) for n in NAMES)


def wrap(text, adv, room=LINE_W):
    lines = []
    for part in text.split('|'):
        line = ''
        for w in part.split():
            test = (line + ' ' + w) if line else w
            if line and width(test, adv) > room:
                lines.append(line)
                line = w
            else:
                line = test
        if line:
            lines.append(line)
    return lines


def problems(rows, adv):
    out = []
    for k, row in enumerate(rows, 2):
        text = subtitle(row)
        if not text:
            continue
        try:
            text.encode('ascii')
        except UnicodeEncodeError:
            out.append('row %d (voice %s): not ASCII' % (k, row['voice_id']))
            continue
        room = LINE_W - (name_width(adv) if speaker_from_game(row) else 0)
        lines = wrap(text, adv, room)
        if len(lines) > MAX_LINES:
            out.append('row %d (voice %s): %d lines, at most %d fit' % (k, row['voice_id'], len(lines), MAX_LINES))
        if any(width(line, adv) > LINE_W for line in lines):
            out.append('row %d (voice %s): a word wider than the screen' % (k, row['voice_id']))
    return out


def build_data(rows, adv):
    """'BSUB', count, six names as (u16 offset, u16 width in pixels), count
    x (u16 id, s16 x, s16 dy, s16 block height, u32 string offset, u16
    flags, u16 0), strings. Offsets count from 'BSUB'. Flag 1: draw the
    speaking character's name in front of this line."""
    entries = []
    for row in rows:
        live = speaker_from_game(row)
        room = LINE_W - (name_width(adv) if live else 0)
        lines = wrap(subtitle(row), adv, room)
        if not lines:
            continue
        height = len(lines) * LINE_H + GAP
        for i, line in enumerate(lines):
            x = max(4, (SCREEN_W - width(line, adv)) // 2)
            dy = (len(lines) - 1 - i) * LINE_H
            entries.append((int(row['voice_id']), x, dy, height, line, 1 if live and i == 0 else 0))
    head = ENTRIES + ENTRY_SIZE * len(entries)
    strings, names, table = b'', b'', b''
    for name in NAMES:
        text = name + ': '
        names += struct.pack('<HH', head + len(strings), width(text, adv))
        strings += text.encode('ascii') + b'\0'
    for vid, x, dy, height, line, flags in entries:
        table += struct.pack('<HhhhIHH', vid, x, dy, height, head + len(strings), flags, 0)
        strings += line.encode('ascii') + b'\0'
    out = MAGIC + struct.pack('<I', len(entries)) + names + table + strings
    return out + b'\0' * (-len(out) % 4), len(entries)


# --- the hook ---------------------------------------------------------------
def hook_code(origin, data):
    """Code at `origin` (vaddr) followed by `data`. Registers: s0 actor,
    s1 actors left in the group, s2 y of the next block's bottom line,
    s3 subtitle data, s4 height of the block drawn for this actor, s5
    load address + RET, t3/t4 table walk."""
    a = mips_asm.Asm(origin)
    op = a.op

    def draw():
        op('lui', 't9', ('hi', TEXT - RET))
        op('addiu', 't9', 't9', ('lo', TEXT - RET))
        op('addu', 't9', 't9', 's5')
        op('li', 'a3', COLOUR)
        op('li', 't0', XSCALE)
        op('jalr', 't9')
        op('li', 't1', YSCALE)

    op('addiu', 'sp', 'sp', -0x50)
    for i, r in enumerate(('ra', 's0', 's1', 's2', 's3', 's4', 's5')):
        op('sw', r, 4 * i, 'sp')
    op('move', 's5', 'ra')
    op('addiu', 't9', 'ra', FRAME - RET)
    op('jalr', 't9')                                  # a0 is the caller's
    op('nop')
    op('sw', 'v0', 0x1C, 'sp')
    op('lui', 's3', ('hi', 'data', RET))
    op('addiu', 's3', 's3', ('lo', 'data', RET))
    op('addu', 's3', 's3', 's5')
    op('lui', 't0', ('hi', GLOBALS - RET))
    op('addiu', 't0', 't0', ('lo', GLOBALS - RET))
    op('addu', 't0', 't0', 's5')
    op('sw', 't0', 0x20, 'sp')
    op('li', 's2', BOTTOM)
    op('lw', 's0', PARTY, 't0')
    op('bal', 'scan')
    op('lbu', 's1', PARTY_SIZE, 't0')
    op('lw', 't0', 0x20, 'sp')
    op('lw', 's0', ENEMIES, 't0')
    op('bal', 'scan')
    op('lbu', 's1', ENEMY_COUNT, 't0')
    op('lw', 'v0', 0x1C, 'sp')
    for i, r in enumerate(('ra', 's0', 's1', 's2', 's3', 's4', 's5')):
        op('lw', r, 4 * i, 'sp')
    op('jr', 'ra')
    op('addiu', 'sp', 'sp', 0x50)

    a.label('scan')                                   # one group of actors
    op('sw', 'ra', 0x24, 'sp')
    op('beqz', 's0', 'scan_end')
    op('sltiu', 't1', 's1', MAX_ACTORS + 1)
    op('bnez', 't1', 'actor')
    op('nop')
    op('li', 's1', MAX_ACTORS)
    a.label('actor')
    op('blez', 's1', 'scan_end')
    op('nop')
    op('lh', 't2', VOICE, 's0')
    op('beqz', 't2', 'next')
    op('move', 's4', 'zero')
    op('lw', 't3', 4, 's3')
    op('addiu', 't4', 's3', ENTRIES)
    a.label('search')
    op('blez', 't3', 'found')
    op('nop')
    op('lhu', 't5', 0, 't4')
    op('bne', 't5', 't2', 'skip')
    op('nop')
    # one line: x at +2, dy at +4, block height at +6, string at +8, flags at +12
    op('lh', 'a0', 2, 't4')
    op('lh', 't6', 4, 't4')
    op('lh', 's4', 6, 't4')
    # the block's top line is at s2 - s4 + GAP + LINE_H: leave the speaker
    # out when that is above TOP_Y
    op('subu', 't7', 's2', 's4')
    op('slti', 't7', 't7', TOP_Y - GAP - LINE_H)
    op('bnez', 't7', 'drop')
    op('nop')
    op('lw', 'a2', 8, 't4')
    op('addu', 'a2', 'a2', 's3')
    op('subu', 'a1', 's2', 't6')
    op('sw', 't2', 0x28, 'sp')
    op('sw', 't3', 0x2C, 'sp')
    op('sw', 't4', 0x30, 'sp')
    # flag 1: the speaking character's name in front ("Kyle: "), whole line centred
    op('lhu', 't7', 12, 't4')
    op('andi', 't7', 't7', 1)
    op('beqz', 't7', 'line')
    op('nop')
    op('lb', 't8', ENEMY, 's0')
    op('bnez', 't8', 'line')
    op('nop')
    op('lb', 't8', CHARACTER, 's0')
    op('sltiu', 't9', 't8', len(NAMES))
    op('beqz', 't9', 'line')
    op('sll', 't8', 't8', 2)
    op('addu', 't8', 't8', 's3')
    op('lhu', 't9', 8, 't8')
    op('lhu', 't7', 10, 't8')
    op('srl', 't5', 't7', 1)
    op('subu', 'a0', 'a0', 't5')
    op('sw', 'a0', 0x34, 'sp')
    op('sw', 'a1', 0x38, 'sp')
    op('sw', 'a2', 0x3C, 'sp')
    op('sw', 't7', 0x40, 'sp')
    op('addu', 'a2', 't9', 's3')
    draw()
    op('lw', 'a0', 0x34, 'sp')
    op('lw', 'a1', 0x38, 'sp')
    op('lw', 'a2', 0x3C, 'sp')
    op('lw', 't7', 0x40, 'sp')
    op('addu', 'a0', 'a0', 't7')
    a.label('line')
    draw()
    op('lw', 't2', 0x28, 'sp')
    op('lw', 't3', 0x2C, 'sp')
    op('lw', 't4', 0x30, 'sp')
    a.label('skip')
    op('addiu', 't3', 't3', -1)
    op('b', 'search')
    op('addiu', 't4', 't4', ENTRY_SIZE)
    a.label('drop')
    op('b', 'next')
    op('move', 's4', 'zero')
    a.label('found')
    op('subu', 's2', 's2', 's4')
    a.label('next')
    op('addiu', 's1', 's1', -1)
    op('b', 'actor')
    op('addiu', 's0', 's0', ACTOR_SIZE)
    a.label('scan_end')
    op('lw', 'ra', 0x24, 'sp')
    op('jr', 'ra')
    op('nop')
    a.align(4)
    a.label('data')
    a.data(data)
    return a.assemble(), dict(a.labels)


# --- BOOT.BIN -----------------------------------------------------------------
def _pool_header(b):
    phoff = struct.unpack_from('<I', b, 0x1C)[0]
    phnum = struct.unpack_from('<H', b, 0x2C)[0]
    for i in range(phnum):
        o = phoff + 32 * i
        p = list(struct.unpack_from('<8I', b, o))
        if p[0] == 1 and p[2] == POOL_VADDR:
            return o, p
    raise ValueError('no pool segment (run psp_pool first)')


def patch_boot(boot, rows=None, vwf=True):
    """Append the hook and the table to the pool and point the frame call
    at it. boot: BOOT.BIN with the pool ending the file. Returns (bytes, info)."""
    b = bytearray(boot)
    got = struct.unpack_from('<I', b, FRAME_CALL + TEXT_BIAS)[0]
    if got != frame_call_word(FRAME):
        raise ValueError('unexpected word %08x at vaddr %#x (battle subtitles already applied, or not a retail BOOT.BIN)'
                         % (got, FRAME_CALL))
    rows = read_table() if rows is None else rows
    adv = advances(vwf)
    errs = problems(rows, adv)
    if errs:
        raise ValueError('battle_subtitles.csv:\n  ' + '\n  '.join(errs))
    off, p = _pool_header(b)
    if p[1] + p[4] != len(b) or p[4] != p[5]:
        raise ValueError('the pool segment must end the file')
    pad = (-p[4]) % 16
    base = POOL_VADDR + p[4] + pad
    data, count = build_data(rows, adv)
    code, labels = hook_code(base, data)
    b += bytes(pad) + code
    p[4] = p[5] = p[4] + pad + len(code)
    struct.pack_into('<8I', b, off, *p)
    struct.pack_into('<I', b, FRAME_CALL + TEXT_BIAS, frame_call_word(base))
    return bytes(b), {'hook_vaddr': hex(base), 'code_bytes': labels['data'] - base, 'lines': count,
                      'subtitles': sum(1 for r in rows if subtitle(r))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check', help='check the table as the PSP draws it')
    c.add_argument('--table', default=TABLE)
    c.add_argument('--vwf', choices=('on', 'off'), default='on')
    a = ap.parse_args(argv)
    rows = read_table(a.table)
    adv = advances(a.vwf == 'on')
    errs = problems(rows, adv)
    for e in errs:
        print('  ' + e)
    if errs:
        print('%s: %d problem(s)' % (os.path.basename(a.table), len(errs)))
        return 1
    data, count = build_data(rows, adv)
    print('%s: %d rows, %d with English, %d screen lines, %d bytes'
          % (os.path.basename(a.table), len(rows), sum(1 for r in rows if subtitle(r)), count, len(data)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
