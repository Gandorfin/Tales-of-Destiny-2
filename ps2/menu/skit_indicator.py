#!/usr/bin/env python3
"""Skit indicator (PS2): while a skit can be started with SELECT, the field
shows "SELECT" in yellow and the skit's title in white in the bottom left
corner (the Lumina Tales idea, requested in the thread 2026-11; the PSP
twin is psp/tools/psp_skit_indicator.py).

    python ps2/menu/skit_indicator.py build FPB_FOLDER SLPS_251.72

build_ps2.py runs it after patch_slps_titles.py. It patches two files:
00017.pak3 in the extracted FPB folder (a new last member with the code)
and SLPS_251.72 (two trampolines and two call targets). Running it again
replaces the earlier code.

How the game decides (SLPS addresses; the PSP has the same functions,
TECHNICAL.md "Skit indicator: how SELECT finds a skit"):

* 0x11C230 is the SELECT handler, called every frame from the field
  overlays (the world map module 08996 calls it at 0x2B4E50 / 0x2B671C).
  It returns at once while an event runs (word 0x1CEE08 + 0x1548) or
  while 0x126DC8 returns 0; then it reads the pad (0x11C288: jal 0x10B028,
  a0 = 0) and goes on only with SELECT (bit 0x100), with bit 0x80 of the
  byte 0x1B8278 + 0x1ED6 clear, and, in mode 6 (0x100BD0), with 0x2B8440
  returning 0 (otherwise it forces skit 0x255 or 0x264). 0x11C32C calls
  0x129510, which returns the skit to play (0 = none), and 0x129758
  starts it.
* 0x129510 collects the skits whose conditions hold (at most 8 halfwords
  at 0x24A878, count at 0x24A888) and picks one with rand() (0x190540,
  state word at [0x1FD1E4] + 0x58).
* Skit number n is Skit Hut number n; its title pointer is at 0x1D6400 +
  4n (file 0xD7400 + 4n, the table patch_slps_titles.py translates).
* Text: the SLPS text API the debug coordinate display (0x168F00) uses on
  the field: 0x11AEF0 (current parameter block), 0x11AE88 (scale),
  0x11AE98 (r, g, b, a), 0x11AE70 (x, y in GS units: origin 0x6C00 /
  0x7900, 16 per pixel across, 8 per line of the 448 line screen),
  0x118D00 (string, 0xFF2000). Like that display, a dark copy is drawn at
  four offsets first, so the text has an outline.

What it adds:

* SLPS: the call of the pad reader at 0x11C288 (reached only when the
  event and field checks passed) goes to trampoline A, the call of
  0x129510 at 0x11C32C (SELECT pressed) to trampoline B. The trampolines
  (7 words each) sit in the zero tail of the second string pool (file
  0x115EE0.., after the strings slps_menu_patch.json places there); like
  the battle subtitle trampoline they find the code through the resident
  00017.pak3 (pointer at 0x234600, member offset table) and jump to it
  with v0 = the entry address, ra unchanged.
* 00017.pak3: a new last member (uncompressed, header type 0) with the
  code. The frame entry reads the pad as before, makes the game's other
  checks, asks 0x129510 with the rand() state saved and restored, keeps
  the shown skit while it is in the list and draws "SELECT" and the
  title. The pick entry calls 0x129510 as before and returns the shown
  skit if it is still in the list, otherwise the game's pick, so SELECT
  plays the skit whose title is on screen.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_subs as A  # noqa: E402  (the small assembler)
import pak3  # noqa: E402

CONTAINER = '00017.pak3'
BIAS = 0xFF000                  # SLPS: vaddr = file offset + BIAS
PAD_CALL = 0x11C288             # jal 0x10B028 (pad edges), a0 = 0 in its delay slot
PICK_CALL = 0x11C32C            # jal 0x129510 after SELECT
PAD = 0x10B028
FIND = 0x129510
MODE = 0x100BD0
MODE6_BUSY = 0x2B8440           # world map module; only called in mode 6, as the game does
LOCK = 0x1B8278 + 0x1ED6        # bit 0x80 set: no skits
RAND_BLOCK = 0x1FD1E4           # pointer to the block whose +0x58 is the rand() state
RAND_STATE = 0x58
CANDIDATES = 0x24A878           # halfword skit numbers found by FIND
CANDIDATE_COUNT = 0x24A888
TITLES = 0x1D6400               # title pointer n at TITLES + 4n
TITLE_COUNT = 622
SET_BLOCK, SET_SCALE, SET_RGBA, SET_POS, PRINT = 0x11AEF0, 0x11AE88, 0x11AE98, 0x11AE70, 0x118D00
GS_SET = 0x14F218               # (GS register, value): one A+D write into the frame's packet
GS_TEST_1 = 0x47
# alpha test on, pass when alpha > 0 (the font cell's transparent pixels are
# skipped; without it they draw as a blue box on the field), z test always
TEST_TEXT = 1 | (6 << 1) | (1 << 16) | (1 << 17)
PRINT_FLAGS = 0xFF2000
PAK_POINTER = 0x234600

TRAMP_FILE = 0x115EE0           # zero tail of the second pool (file 0x115E54..0x115F60)
TRAMP_END = 0x115F60
TRAMP_SIZE = 28

ORIGIN_X, ORIGIN_Y = 0x6C00, 0x7900
X, Y = 16, 410                  # bottom left, 640 x 448 space
XSCALE, YSCALE = 0xC0, 0x100    # as the debug display
ADVANCE = 12                    # pixels per character at XSCALE 0xC0 (battle font: 11 at 0xB0)
LABEL = 'SELECT'
YELLOW, WHITE = (0x80, 0x80, 0x10), (0x80, 0x80, 0x80)
OUTLINE = ((-2, -1), (2, -1), (2, 1), (-2, 1))   # pixels, as the debug display (x 1/16, y 1/8 units)
MAGIC = b'SKIN'
CODE_AT = 8                     # offset of the frame entry from MAGIC

_NAMES = 'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split()


def sw(rt, off, rs): return A._i(43, rs, rt, off)
def sh(rt, off, rs): return A._i(41, rs, rt, off)
def ori(rt, rs, imm): return A._i(13, rs, rt, imm)
def slti(rt, rs, imm): return A._i(10, rs, rt, imm)
def jalr(rs): return (A.REG[rs] << 21) | (31 << 11) | 9
def beqz(rs, label): return A.beq(rs, 'zero', label)
def bnez(rs, label): return A.bne(rs, 'zero', label)
def bal(label): return ('b', 1, 'zero', 'zero', label)  # regimm, rt 0x11 (assemble() encodes it)


def li(rt, value):
    if 0 <= value <= 0xFFFF:
        return [ori(rt, 'zero', value)]
    if -0x8000 <= value < 0:
        return [A.addiu(rt, 'zero', value)]
    hi, lo = A.hi_lo(value)
    return [A.lui(rt, hi), A.addiu(rt, rt, lo)]


def load_word(rt, addr):
    hi, lo = A.hi_lo(addr)
    return [A.lui(rt, hi), A.lw(rt, lo, rt)]


def gs_x(px): return ORIGIN_X + 16 * px
def gs_y(py): return ORIGIN_Y + 8 * py


def rgb(c): return c[0] | (c[1] << 8) | (c[2] << 16)


def title_x():
    return X + ADVANCE * (len(LABEL) + 1)


def hook_code():
    """Position independent code; offsets count from MAGIC. Entries:
    'frame' (= CODE_AT) and 'pick'; v0 holds the entry's own address."""
    L = []
    o = L.append

    def ext(*items):
        L.extend(items)

    # --- frame entry: replaces jal 0x10B028 at 0x11C288 -------------------
    o('frame')
    ext(A.addiu('sp', 'sp', -0x90),
        A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'), A.sd('s1', 0x20, 'sp'), A.sd('s2', 0x30, 'sp'))
    o(('rel', 's2', 'v0', 'data', 'frame'))           # s2 = data
    ext(A.jal(PAD), A.NOP,                            # a0 is still the caller's 0
        sw('v0', 0x50, 'sp'))
    hi, lo = A.hi_lo(LOCK)
    ext(A.lui('t0', hi), A.lbu('t0', lo, 't0'), A.andi('t0', 't0', 0x80))
    o(bnez('t0', 'out'))
    o(A.NOP)
    ext(A.jal(MODE), A.NOP, A.addiu('t0', 'zero', 6))
    o(A.bne('v0', 't0', 'ask'))
    o(A.NOP)
    ext(A.jal(MODE6_BUSY), A.NOP)
    o(bnez('v0', 'out'))
    o(A.NOP)
    o('ask')
    ext(*load_word('s0', RAND_BLOCK))
    ext(A.lw('t1', RAND_STATE, 's0'), sw('t1', 0x54, 'sp'),
        A.jal(FIND), A.NOP,
        A.move('s1', 'v0'),
        A.lw('t1', 0x54, 'sp'), sw('t1', RAND_STATE, 's0'),
        A.lh('a0', 0, 's2'))
    o(bal('listed'))
    o(A.NOP)
    o(bnez('v0', 'show'))
    o(A.lh('a0', 0, 's2'))
    ext(A.move('a0', 's1'), sh('a0', 0, 's2'))
    o('show')
    o(A.blez('a0', 'out'))
    o(A.NOP)
    ext(slti('t0', 'a0', TITLE_COUNT))
    o(beqz('t0', 'out'))
    o(A.sll('t0', 'a0', 2))
    hi, lo = A.hi_lo(TITLES)
    ext(A.lui('t1', hi), A.addu('t1', 't1', 't0'), A.lw('s1', lo, 't1'))
    o(beqz('s1', 'out'))
    o(A.NOP)
    ext(A.addiu('a0', 's2', 4), *li('a1', gs_x(X)))
    ext(*li('a2', rgb(YELLOW)))
    o(bal('draw'))
    o(A.NOP)
    ext(A.move('a0', 's1'), *li('a1', gs_x(title_x())))
    ext(*li('a2', rgb(WHITE)))
    o(bal('draw'))
    o(A.NOP)
    o('out')
    ext(A.lw('v0', 0x50, 'sp'),
        A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.ld('s1', 0x20, 'sp'), A.ld('s2', 0x30, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x90))

    # --- listed(a0 skit): v0 = 1 if a0 > 0 is in the game's list ----------
    o('listed')
    o(A.move('v0', 'zero'))
    o(A.blez('a0', 'listed_end'))
    hi, lo = A.hi_lo(CANDIDATE_COUNT)
    o(A.lui('t2', hi))
    o(A.lhu('t2', lo, 't2'))
    o(A.sltiu('t3', 't2', 9))
    o(bnez('t3', 'listed_start'))
    o(A.NOP)
    o(A.addiu('t2', 'zero', 8))
    o('listed_start')
    ext(*li('t4', CANDIDATES))
    o('listed_loop')
    o(A.blez('t2', 'listed_end'))
    o(A.NOP)
    o(A.lh('t3', 0, 't4'))
    o(A.addiu('t4', 't4', 2))
    o(A.bne('t3', 'a0', 'listed_loop'))
    o(A.addiu('t2', 't2', -1))
    o(A.addiu('v0', 'zero', 1))
    o('listed_end')
    o(A.jr('ra'))
    o(A.NOP)

    # --- draw(a0 string, a1 GS x, a2 rgb): outline, then the colour --------
    o('draw')
    ext(A.addiu('sp', 'sp', -0x70),
        A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'), A.sd('s1', 0x20, 'sp'), A.sd('s2', 0x30, 'sp'),
        A.move('s0', 'a0'), A.move('s1', 'a1'), A.move('s2', 'a2'),
        A.sd('zero', 0x50, 'sp'), A.sd('zero', 0x58, 'sp'),
        A.addiu('a0', 'zero', GS_TEST_1), *li('a1', TEST_TEXT)),
    ext(A.jal(GS_SET), A.NOP,
        A.jal(SET_BLOCK), A.addiu('a0', 'sp', 0x50),
        A.addiu('a0', 'sp', 0x50), A.addiu('a1', 'zero', XSCALE), A.jal(SET_SCALE), A.addiu('a2', 'zero', YSCALE),
        A.addiu('a0', 'sp', 0x50), A.move('a1', 'zero'), A.move('a2', 'zero'), A.move('a3', 'zero'),
        A.jal(SET_RGBA), A.addiu('t0', 'zero', 0x80))

    def text(dx, dy):
        ext(A.addiu('a0', 'sp', 0x50), A.addiu('a1', 's1', 16 * dx), *li('a2', gs_y(Y) + 8 * dy))
        ext(A.jal(SET_POS), A.NOP, A.move('a0', 's0'), A.lui('a1', PRINT_FLAGS >> 16),
            A.jal(PRINT), ori('a1', 'a1', PRINT_FLAGS & 0xFFFF))
    for dx, dy in OUTLINE:
        text(dx, dy)
    ext(A.addiu('a0', 'sp', 0x50), A.andi('a1', 's2', 0xFF), A.srl('a2', 's2', 8), A.andi('a2', 'a2', 0xFF),
        A.srl('a3', 's2', 16), A.jal(SET_RGBA), A.addiu('t0', 'zero', 0x80))
    text(0, 0)
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.ld('s1', 0x20, 'sp'), A.ld('s2', 0x30, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x70))

    # --- pick entry: replaces jal 0x129510 at 0x11C32C ---------------------
    o('pick')
    ext(A.addiu('sp', 'sp', -0x40),
        A.sd('ra', 0x00, 'sp'), A.sd('s1', 0x10, 'sp'), A.sd('s2', 0x20, 'sp'))
    o(('rel', 's2', 'v0', 'data', 'pick'))
    ext(A.jal(FIND), A.NOP, A.move('s1', 'v0'), A.lh('a0', 0, 's2'))
    o(bal('listed'))
    o(A.NOP)
    o(beqz('v0', 'pick_end'))
    o(A.move('v0', 's1'))
    o(A.lh('v0', 0, 's2'))
    o('pick_end')
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s1', 0x10, 'sp'), A.ld('s2', 0x20, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x40))
    o('data')
    return L


def assemble():
    """-> (code bytes starting at MAGIC, labels as offsets from MAGIC)."""
    lines = hook_code()
    labels, pc = {}, CODE_AT
    for item in lines:
        if isinstance(item, str):
            labels[item] = pc
        else:
            pc += 4
    words, pc = [], CODE_AT
    for item in lines:
        if isinstance(item, str):
            continue
        if isinstance(item, tuple) and item[0] == 'rel':
            _, rt, rs, to, frm = item
            words.append(A.addiu(rt, rs, labels[to] - labels[frm]))
        elif isinstance(item, tuple):
            _, op, rs, rt, label = item
            off = (labels[label] - pc - 4) >> 2
            if op == 1:                                # bal: regimm, rt field 0x11
                words.append((1 << 26) | (0x11 << 16) | (off & 0xFFFF))
            else:
                words.append(A._i(op, rs, rt, off))
        else:
            words.append(item)
        pc += 4
    data = struct.pack('<H', 0) + b'\0\0' + LABEL.encode('ascii') + b'\0'
    body = MAGIC + struct.pack('<I', 1) + struct.pack('<%dI' % len(words), *words) + data
    body += b'\0' * (-len(body) % 4)
    return body, labels


def member():
    """The pak3 member: header type 0, 3 pad bytes, then MAGIC..."""
    body, labels = assemble()
    payload = b'\0\0\0' + body
    return bytes([0]) + struct.pack('<II', len(payload), len(payload)) + payload, labels


def is_ours(blob):
    return len(blob) >= 16 and blob[0] == 0 and blob[12:16] == MAGIC


def trampoline(index, entry):
    """jump to member `index` of the resident 00017.pak3, MAGIC + entry, with
    v0 = that address; only v0/v1 change, ra stays the caller's."""
    p_hi, p_lo = A.hi_lo(PAK_POINTER)
    words = [A.lui('v0', p_hi), A.lw('v0', p_lo, 'v0'),
             A.lw('v1', 4 + 4 * index, 'v0'), A.addu('v0', 'v0', 'v1'),
             A.addiu('v0', 'v0', 12 + entry), A.jr('v0'), A.NOP]
    return struct.pack('<7I', *words)


def patch_container(data):
    """-> (bytes, member index, labels). Keeps every other member; replaces
    an earlier indicator member."""
    members = [blob for _, blob in pak3.parse(data)]
    members = [m for m in members if not is_ours(m)]
    if len(members) < 3:
        raise ValueError('%s: expected at least the three modules' % CONTAINER)
    blob, labels = member()
    out = pak3.build(members + [blob])
    again = [b for _, b in pak3.parse(out)]
    assert again[-1] == blob and again[:-1] == members
    return out, len(members), labels


def patch_slps(slps, index, labels):
    d = bytearray(slps)
    tramp_a, tramp_b = TRAMP_FILE, TRAMP_FILE + TRAMP_SIZE
    for site, original, tramp in ((PAD_CALL, PAD, tramp_a), (PICK_CALL, FIND, tramp_b)):
        got = struct.unpack_from('<I', d, site - BIAS)[0]
        if got not in (A.jal(original), A.jal(tramp + BIAS)):
            raise ValueError('unexpected word %08x at 0x%X (not a retail SLPS_251.72?)' % (got, site))
    area = bytes(d[TRAMP_FILE:TRAMP_FILE + 2 * TRAMP_SIZE])
    ta, tb = trampoline(index, labels['frame']), trampoline(index, labels['pick'])
    if any(area) and area[:TRAMP_SIZE][:8] != ta[:8]:
        raise ValueError('second pool tail 0x%X is in use; move the trampolines' % TRAMP_FILE)
    assert TRAMP_FILE + 2 * TRAMP_SIZE <= TRAMP_END
    d[tramp_a:tramp_a + TRAMP_SIZE] = ta
    d[tramp_b:tramp_b + TRAMP_SIZE] = tb
    struct.pack_into('<I', d, PAD_CALL - BIAS, A.jal(tramp_a + BIAS))
    struct.pack_into('<I', d, PICK_CALL - BIAS, A.jal(tramp_b + BIAS))
    return bytes(d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='patch 00017.pak3 in an extracted FPB folder and the SLPS')
    b.add_argument('folder')
    b.add_argument('slps')
    b.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    path = os.path.join(a.folder, CONTAINER)
    data = open(path, 'rb').read()
    out, index, labels = patch_container(data)
    slps = patch_slps(open(a.slps, 'rb').read(), index, labels)
    if not a.dry_run:
        open(path, 'wb').write(out)
        open(a.slps, 'wb').write(slps)
    print('%s %s (%d -> %d bytes, member %d, %d code bytes) and %s (calls at 0x%X and 0x%X to trampolines at 0x%X)'
          % ('would patch' if a.dry_run else 'patched', CONTAINER, len(data), len(out), index,
             labels['data'] - CODE_AT, os.path.basename(a.slps), PAD_CALL, PICK_CALL, TRAMP_FILE + BIAS))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
