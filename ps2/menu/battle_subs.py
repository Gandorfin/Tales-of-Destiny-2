#!/usr/bin/env python3
"""English subtitles for the spoken battle lines (PS2).

    python ps2/menu/battle_subs.py build <FPB folder>            # patch 00017.pak3
    python ps2/menu/battle_subs.py build <FPB folder> --dry-run
    python ps2/menu/battle_subs.py check                         # table only

How the game plays a battle voice: every battle actor is a 0x2A8 byte
record (array pointer at 0x2FA160, the party first, then the enemies;
party size byte at 0x2FA195, enemy count at 0x2FA196, all in the battle
module 08055). While an actor speaks, the halfword at +0x13E
holds the voice id and drops back to 0 when the line ends; the voice
routines 0x2ED158 / 0x2ED248 / 0x2ED7B0 put it there for arte shouts,
spells, victory quotes and the leader lines alike. Voice id N is FILE.FPB
member 7253 + N for the party (ids 4..515, SLPS function 0x133F30 has the
whole map), and the table below is keyed by that id.

What this step adds:

* about 300 bytes of MIPS code appended to the battle module (member 0 of
  00017.pak3, loaded at 0x2AEA80). The module is the biggest overlay and
  still leaves 4 KB free before the heap starts at 0x303100 (crt0 end of
  bss); the game flushes the caches after loading an overlay, so the code
  runs like the rest of the module.
* the call of the battle frame function at 0x2AEC18 (jal 0x2B40B8) goes to
  that code instead. It calls the frame function, then looks at each party
  actor: if +0x13E holds an id that has lines in the table, it draws them
  with the module's own text helper 0x2E6DA0 (the one that draws "ENEMY
  DATA"), white, centred, just above the HP bars. Enemies are checked
  the same way after the party (boss lines). Two speakers at once stack
  upwards.
* the text: a fourth member of 00017.pak3, stored uncompressed (comptoe
  header type 0). The game loads the whole container at boot into a heap
  block of its file size (pointer at 0x234600) and reads its three
  modules by index, so an extra member costs nothing and changes nothing
  else. The code finds it through the container's own offset table.

Running it again replaces the earlier code and text, so the table can be
edited and the step repeated on the same folder. A container that was
never patched is recognised by the original call at 0x2AEC18.

Table: battle_subtitles.csv next to this script (voice_id, member,
owner, speaker, seconds, japanese, english), one row per battle voice
file. Rows with an empty english column draw nothing. Speaker '*' lets
the game supply the name of the character whose voice plays (actor +0x149,
never for enemies), a name is written in front of the text, an empty
speaker shows the text alone. owner is for people reading the table. The battle font has no glyphs for [ ] _ @ ^ and maps # $ to
other symbols, so the text may only use letters, digits, space and
! ? . , ' " - : ; ( ) / & ~ * % + =. A line holds at most LINE_CHARS
characters; longer text is wrapped at spaces into up to MAX_LINES lines,
and '|' starts a new line (used for the exchanges with several speakers).
"""
import argparse
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lzss  # noqa: E402
import pak3  # noqa: E402

TABLE = os.path.join(HERE, 'battle_subtitles.csv')
CONTAINER = '00017.pak3'

BASE = 0x2AEA80             # load address of the battle module
HEAP = 0x303100             # end of the SLPS bss = start of the heap
HOOK = 0x2AEC18 - BASE      # jal 0x2B40B8 in the overlay's main loop
FRAME = 0x2B40B8            # battle frame function
TEXT = 0x2E6DA0             # text helper (x, y, string, colour, xscale, yscale)
PAK_POINTER = 0x234600      # SLPS: address of the resident 00017.pak3
GLOBALS = 0x2FA000          # battle globals (actors at +0x160, party size at +0x195)
ACTOR_SIZE = 0x2A8
MAX_ACTORS = 16             # party size (+0x195) plus enemy count (+0x196), capped
VOICE = 0x13E               # actor: id of the voice being played, 0 when silent
CHARACTER = 0x149          # actor: 0 Kyle, 1 Reala, 2 Loni, 3 Judas, 4 Nanaly, 5 Harold
ENEMY = 0x14C              # actor: 1 for enemies
NAMES = ('Kyle', 'Reala', 'Loni', 'Judas', 'Nanaly', 'Harold')
NAME_ROOM = 8              # 'Nanaly: '
ENTRIES = 8 + 4 * len(NAMES)
ENTRY_SIZE = 16
MAGIC = b'BSUB'
TRAILER = b'BSUBCODE'

COLOUR = 7                  # white with the font's dark outline
XSCALE, YSCALE = 0xB0, 0x100
ADVANCE = 11                # pixels per character at XSCALE 0xB0
SCREEN_W = 640
BOTTOM = 356                # y of the lowest line, just above the HP bars
LINE_H = 18
GAP = 4
LINE_CHARS = 54
MAX_LINES = 3
ALLOWED = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 '
              '!?.,\'"-:;()/&~*%+=')


# --- a small MIPS assembler, just what the hook needs ---------------------
REG = {n: i for i, n in enumerate(
    'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 '
    't8 t9 k0 k1 gp sp fp ra'.split())}


def _i(op, rs, rt, imm):
    return (op << 26) | (REG[rs] << 21) | (REG[rt] << 16) | (imm & 0xFFFF)


def lui(rt, imm): return _i(15, 'zero', rt, imm)
def addiu(rt, rs, imm): return _i(9, rs, rt, imm)
def lw(rt, off, rs): return _i(35, rs, rt, off)
def lh(rt, off, rs): return _i(33, rs, rt, off)
def lhu(rt, off, rs): return _i(37, rs, rt, off)
def lb(rt, off, rs): return _i(32, rs, rt, off)
def lbu(rt, off, rs): return _i(36, rs, rt, off)
def sltiu(rt, rs, imm): return _i(11, rs, rt, imm)
def sd(rt, off, rs): return _i(63, rs, rt, off)
def ld(rt, off, rs): return _i(55, rs, rt, off)
def andi(rt, rs, imm): return _i(12, rs, rt, imm)
def sll(rd, rt, sa): return (REG[rt] << 16) | (REG[rd] << 11) | (sa << 6)
def srl(rd, rt, sa): return (REG[rt] << 16) | (REG[rd] << 11) | (sa << 6) | 2
def addu(rd, rs, rt): return (REG[rs] << 21) | (REG[rt] << 16) | (REG[rd] << 11) | 0x21
def subu(rd, rs, rt): return (REG[rs] << 21) | (REG[rt] << 16) | (REG[rd] << 11) | 0x23
def move(rd, rs): return addu(rd, rs, 'zero')
def jal(target): return (3 << 26) | ((target >> 2) & 0x3FFFFFF)
def beq(rs, rt, label): return ('b', 4, rs, rt, label)
def bne(rs, rt, label): return ('b', 5, rs, rt, label)
def blez(rs, label): return ('b', 6, rs, 'zero', label)


NOP = 0
JR_RA = 0x03E00008


def hi_lo(value):
    """(hi, lo) for lui + addiu (addiu sign extends lo)."""
    return ((value + 0x8000) >> 16) & 0xFFFF, value & 0xFFFF


def assemble(lines, origin):
    labels, pc = {}, origin
    for item in lines:
        if isinstance(item, str):
            labels[item] = pc
        else:
            pc += 4
    words, pc = [], origin
    for item in lines:
        if isinstance(item, str):
            continue
        if isinstance(item, tuple):
            _, op, rs, rt, label = item
            words.append(_i(op, rs, rt, (labels[label] - pc - 4) >> 2))
        else:
            words.append(item)
        pc += 4
    return struct.pack('<%dI' % len(words), *words)


def hook_code(origin):
    """The frame hook. Registers: s0 actor, s1 actors left, s2 y of the
    next block's bottom line, s3 subtitle data, s4 height of the block
    drawn for this actor, t3/t4 table walk."""
    g_hi, g_lo = hi_lo(GLOBALS)
    p_hi, p_lo = hi_lo(PAK_POINTER)
    m_hi, m_lo = hi_lo(struct.unpack('<I', MAGIC)[0])
    draw = [addiu('a3', 'zero', COLOUR), addiu('t0', 'zero', XSCALE), jal(TEXT), addiu('t1', 'zero', YSCALE)]
    return assemble([
        addiu('sp', 'sp', -0x80),
        sd('ra', 0x00, 'sp'), sd('s0', 0x10, 'sp'), sd('s1', 0x18, 'sp'),
        sd('s2', 0x20, 'sp'), sd('s3', 0x28, 'sp'), sd('s4', 0x30, 'sp'),
        jal(FRAME), NOP,
        sd('v0', 0x38, 'sp'),
        # subtitle data = pak + offset of member 4 + 12 (header 9 + pad 3)
        lui('t0', p_hi), lw('s3', p_lo, 't0'),
        beq('s3', 'zero', 'done'), NOP,
        lw('t1', 0, 's3'), addiu('t1', 't1', -4),
        bne('t1', 'zero', 'done'), NOP,
        lw('t1', 0x10, 's3'), addu('s3', 's3', 't1'), addiu('s3', 's3', 12),
        lw('t1', 0, 's3'), lui('t2', m_hi), addiu('t2', 't2', m_lo),
        bne('t1', 't2', 'done'), NOP,
        # party first, then the enemies
        lui('t0', g_hi), addiu('t0', 't0', g_lo),
        lw('s0', 0x160, 't0'), lbu('t1', 0x195, 't0'), lbu('t2', 0x196, 't0'),
        addu('s1', 't1', 't2'), sltiu('t3', 's1', MAX_ACTORS + 1),
        bne('t3', 'zero', 'counted'), NOP,
        addiu('s1', 'zero', MAX_ACTORS),
        'counted',
        beq('s0', 'zero', 'done'), addiu('s2', 'zero', BOTTOM),
        'actor',
        blez('s1', 'done'), NOP,
        lh('t2', VOICE, 's0'),
        beq('t2', 'zero', 'next'), move('s4', 'zero'),
        lw('t3', 4, 's3'), addiu('t4', 's3', ENTRIES),
        'search',
        blez('t3', 'found'), NOP,
        lhu('t5', 0, 't4'),
        bne('t5', 't2', 'skip'), NOP,
        # one line: x at +2, dy at +4, block height at +6, string at +8, flags at +12
        lh('a0', 2, 't4'), lh('t6', 4, 't4'), lh('s4', 6, 't4'),
        lw('a2', 8, 't4'), addu('a2', 'a2', 's3'), subu('a1', 's2', 't6'),
        sd('t2', 0x40, 'sp'), sd('t3', 0x48, 'sp'), sd('t4', 0x50, 'sp'),
        # flag 1: put the speaking character's name in front ("Kyle: ")
        lhu('t7', 12, 't4'), andi('t7', 't7', 1),
        beq('t7', 'zero', 'line'), NOP,
        lb('t8', ENEMY, 's0'),
        bne('t8', 'zero', 'line'), NOP,
        lb('t8', CHARACTER, 's0'), sltiu('t9', 't8', len(NAMES)),
        beq('t9', 'zero', 'line'), sll('t8', 't8', 2),
        addu('t8', 't8', 's3'), lhu('t9', 8, 't8'), lhu('t8', 10, 't8'),
        beq('t9', 'zero', 'line'), NOP,
        # name width = length x 11; the whole line stays centred
        sll('t7', 't8', 3), sll('t5', 't8', 1), addu('t7', 't7', 't5'), addu('t7', 't7', 't8'),
        srl('t5', 't7', 1), subu('a0', 'a0', 't5'),
        sd('a0', 0x58, 'sp'), sd('a1', 0x60, 'sp'), sd('a2', 0x68, 'sp'), sd('t7', 0x70, 'sp'),
        addu('a2', 't9', 's3'),
        ] + draw + [
        ld('a0', 0x58, 'sp'), ld('a1', 0x60, 'sp'), ld('a2', 0x68, 'sp'), ld('t7', 0x70, 'sp'),
        addu('a0', 'a0', 't7'),
        'line',
        ] + draw + [
        ld('t2', 0x40, 'sp'), ld('t3', 0x48, 'sp'), ld('t4', 0x50, 'sp'),
        'skip',
        addiu('t3', 't3', -1),
        beq('zero', 'zero', 'search'), addiu('t4', 't4', ENTRY_SIZE),
        'found',
        subu('s2', 's2', 's4'),
        'next',
        addiu('s1', 's1', -1),
        beq('zero', 'zero', 'actor'), addiu('s0', 's0', ACTOR_SIZE),
        'done',
        ld('v0', 0x38, 'sp'),
        ld('ra', 0x00, 'sp'), ld('s0', 0x10, 'sp'), ld('s1', 0x18, 'sp'),
        ld('s2', 0x20, 'sp'), ld('s3', 0x28, 'sp'), ld('s4', 0x30, 'sp'),
        JR_RA, addiu('sp', 'sp', 0x80),
    ], origin)


# voice id -> FILE.FPB member, as the SLPS function 0x133F30 maps them
MEMBER_RANGES = ((4, 515, 7253), (516, 587, 6669), (588, 632, 7181), (633, 864, 7190))


def member_for(vid):
    for lo, hi, add in MEMBER_RANGES:
        if lo <= vid <= hi:
            return vid + add
    return None


# --- the table --------------------------------------------------------------
def read_table(path=TABLE):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def speaker_from_game(row):
    return (row.get('speaker') or '').strip() == '*'


def subtitle(row):
    """The text stored for a row: 'Speaker: English', the English alone
    (empty speaker, or '*' when the game supplies the name), or '' for none."""
    english = (row.get('english') or '').strip()
    if not english:
        return ''
    speaker = (row.get('speaker') or '').strip()
    return '%s: %s' % (speaker, english) if speaker and speaker != '*' else english


def wrap(text, width=LINE_CHARS):
    """Lines of at most `width` characters, broken at spaces; '|' forces a
    break (one line per speaker in the exchanges)."""
    lines = []
    for part in text.split('|'):
        line = ''
        for w in part.split():
            if line and len(line) + 1 + len(w) > width:
                lines.append(line)
                line = w
            else:
                line = (line + ' ' + w) if line else w
        if line:
            lines.append(line)
    return lines


def problems(rows):
    out, seen = [], set()
    for k, row in enumerate(rows, 2):
        try:
            vid = int(row['voice_id'])
        except (KeyError, ValueError):
            out.append('row %d: bad voice_id %r' % (k, row.get('voice_id')))
            continue
        if vid in seen:
            out.append('row %d: voice %d twice' % (k, vid))
        seen.add(vid)
        if member_for(vid) is None:
            out.append('row %d: voice %d is not a battle voice id' % (k, vid))
        elif (row.get('member') or '').strip() and int(row['member']) != member_for(vid):
            out.append('row %d: voice %d is member %d, not %s' % (k, vid, member_for(vid), row['member']))
        text = subtitle(row)
        bad = sorted(set(text) - ALLOWED - {'|'})
        if bad:
            out.append('row %d (voice %d): characters the battle font cannot draw: %s' % (k, vid, ' '.join(bad)))
        lines = wrap(text, LINE_CHARS - (NAME_ROOM if speaker_from_game(row) else 0))
        if len(lines) > MAX_LINES:
            out.append('row %d (voice %d): %d lines, at most %d fit' % (k, vid, len(lines), MAX_LINES))
        if any(len(line) > LINE_CHARS for line in lines):
            out.append('row %d (voice %d): a word longer than %d characters' % (k, vid, LINE_CHARS))
    return out


def build_data(rows):
    """Member 4 of 00017.pak3: header type 0, 3 pad bytes, then 'BSUB',
    count, the eight character names as (u16 offset, u16 length), count x
    (u16 id, s16 x, s16 dy, s16 block height, u32 string offset, u16 flags,
    u16 0), strings. Offsets count from 'BSUB'."""
    entries = []
    for row in rows:
        live = speaker_from_game(row)
        lines = wrap(subtitle(row), LINE_CHARS - (NAME_ROOM if live else 0))
        if not lines:
            continue
        height = len(lines) * LINE_H + GAP
        for i, line in enumerate(lines):
            x = max(8, (SCREEN_W - ADVANCE * len(line)) // 2)
            dy = (len(lines) - 1 - i) * LINE_H
            entries.append((int(row['voice_id']), x, dy, height, line, 1 if live and i == 0 else 0))
    head = ENTRIES + ENTRY_SIZE * len(entries)
    strings, names, table = b'', b'', b''
    for name in NAMES:
        text = (name + ': ').encode('ascii')
        names += struct.pack('<HH', head + len(strings), len(text))
        strings += text + b'\0'
    for vid, x, dy, height, line, flags in entries:
        table += struct.pack('<HhhhIHH', vid, x, dy, height, head + len(strings), flags, 0)
        strings += line.encode('ascii') + b'\0'
    payload = b'\0\0\0' + MAGIC + struct.pack('<I', len(entries)) + names + table + strings
    payload += b'\0' * (-len(payload) % 4)
    return bytes([0]) + struct.pack('<II', len(payload), len(payload)) + payload, len(entries)


# --- the container ----------------------------------------------------------
def strip_code(module):
    """Battle module bytes without an earlier hook: (bytes, was_patched)."""
    module = bytearray(module)
    if module[-12:-4] == TRAILER:
        original = struct.unpack_from('<I', module, len(module) - 4)[0]
        module = module[:original]
        module[HOOK:HOOK + 4] = struct.pack('<I', jal(FRAME))
        return bytes(module), True
    if struct.unpack_from('<I', module, HOOK)[0] != jal(FRAME):
        raise ValueError('battle module: unexpected code at 0x%X (expected jal 0x%X)' % (BASE + HOOK, FRAME))
    return bytes(module), False


def add_code(module):
    module, _ = strip_code(module)
    original = len(module)
    start = (original + 15) & ~15
    code = hook_code(BASE + start)
    out = bytearray(module) + b'\0' * (start - original) + code
    out += b'\0' * (-len(out) % 4) + TRAILER + struct.pack('<I', original)
    if BASE + len(out) > HEAP:
        raise ValueError('battle module would end at 0x%X, past the heap start 0x%X' % (BASE + len(out), HEAP))
    out[HOOK:HOOK + 4] = struct.pack('<I', jal(BASE + start))
    return bytes(out), BASE + start, len(code)


def is_data(blob):
    return len(blob) >= 16 and blob[0] == 0 and blob[12:16] == MAGIC


def patch_container(data, rows):
    members = [blob for _, blob in pak3.parse(data)]
    if len(members) == 4 and is_data(members[3]):
        members = members[:3]
    if len(members) != 3 or not lzss.is_packed(members[0]):
        raise ValueError('%s: expected three compressed modules' % CONTAINER)
    module = lzss.unpack(members[0])
    patched, where, size = add_code(module)
    blob, count = build_data(rows)
    members[0] = lzss.pack(patched, members[0][0])
    out = pak3.build(members + [blob])
    # prove it reads back
    again = [b for _, b in pak3.parse(out)]
    assert lzss.unpack(again[0]) == patched and again[3] == blob
    return out, {'code_at': where, 'code_bytes': size, 'lines': count, 'module_end': BASE + len(patched)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='patch 00017.pak3 in an extracted FPB folder')
    b.add_argument('folder')
    b.add_argument('--table', default=TABLE)
    b.add_argument('--dry-run', action='store_true')
    c = sub.add_parser('check', help='check the table only')
    c.add_argument('--table', default=TABLE)
    a = ap.parse_args(argv)
    rows = read_table(a.table)
    errs = problems(rows)
    for e in errs:
        print('  ' + e)
    if errs:
        print('battle_subtitles.csv: %d problem(s), nothing written' % len(errs))
        return 1
    with_text = sum(1 for r in rows if subtitle(r))
    if a.cmd == 'check':
        print('battle_subtitles.csv: %d rows, %d with English' % (len(rows), with_text))
        return 0
    path = os.path.join(a.folder, CONTAINER)
    data = open(path, 'rb').read()
    out, info = patch_container(data, rows)
    if not a.dry_run:
        open(path, 'wb').write(out)
    print('%s %s (%d -> %d bytes): %d subtitles, %d lines, hook code %d bytes at 0x%X, module ends 0x%X (heap 0x%X)'
          % ('would rebuild' if a.dry_run else 'rebuilt', CONTAINER, len(data), len(out), with_text,
             info['lines'], info['code_bytes'], info['code_at'], info['module_end'], HEAP))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
