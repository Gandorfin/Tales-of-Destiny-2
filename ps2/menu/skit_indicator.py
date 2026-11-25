#!/usr/bin/env python3
"""Skit indicator (PS2): while SELECT would start a skit not seen yet, the
bottom left corner shows a grey SELECT key and the skit's title on a
translucent dark band (the Lumina Tales idea, requested in the thread
2026-11; since 1.3.7 in the Tales of Rebirth / Abyss style pnvnd asked
for; the PSP twin is psp/tools/psp_skit_indicator.py).

    python ps2/menu/skit_indicator.py build FPB_FOLDER SLPS_251.72

build_ps2.py runs it after patch_slps_titles.py. It patches two files:
00017.pak3 in the extracted FPB folder (a new last member with the code)
and SLPS_251.72 (four trampolines, two call targets, two text layer
exits). Running it again replaces the earlier code.

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
  0x118D00 (string, 0xFF2000). Band and key are GS primitives written
  through 0x14F218 (one A+D register per call).
* Seen skits: bit n of the bytes at 0x1B8278 + 0x2E30 (0x128F78 tests it
  for lists that skip seen skits; other lists offer a seen skit again).

What it adds:

* SLPS: the call of the pad reader at 0x11C288 (reached only when the
  event and field checks passed) goes to trampoline A, the call of
  0x129510 at 0x11C32C (SELECT pressed) to trampoline B, the text layer's
  exits j 0x14F218 at 0x10E130 and jr ra at 0x10E15C to C and D. The
  trampolines (7 words each) sit in the zero tail of the second string
  pool (file 0x115EE0.., after the strings slps_menu_patch.json places
  there); like the battle subtitle trampoline they find the code through
  the resident 00017.pak3 (pointer at 0x234600, member offset table) and
  jump to it with v0 = the entry address, ra unchanged.
* 00017.pak3: a new last member (uncompressed, header type 0) with the
  code. The frame entry reads the pad as before, makes the game's other
  checks, asks 0x129510 with the rand() state saved and restored, keeps
  the shown skit while it is listed and not seen, else takes the first
  listed unseen one, else none, and asks the text layer to draw it. The
  pick entry calls 0x129510 as before and returns the shown skit if it is
  still listed and unseen, otherwise the game's pick (0 stays 0), so
  SELECT plays the skit whose title is on screen.
* Drawing: the text layer 0x10DE58 runs after the field, its reflections,
  the portraits and the minimap; its two exits (C, D) draw the indicator
  when the frame entry asked in the same frame. Name codes (07 n 00 00
  00) in a title become the English names.
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
SKIT_FLAGS = 0x1CEE08 + 0x1544  # bit 0x40 set while a skit plays (0x10E054 tests it)
SKIT_BIT = 0x40
PLAYING = 0x1CEE08 + 0x1CE8     # halfword: number of the skit started last (0x129758 stores it)
LAYER_EXIT = 0x10E130           # j 0x14F218: the text layer 0x10DE58 ends with the full scissor
RAND_BLOCK = 0x1FD1E4           # pointer to the block whose +0x58 is the rand() state
RAND_STATE = 0x58
CANDIDATES = 0x24A878           # halfword skit numbers found by FIND
CANDIDATE_COUNT = 0x24A888
SEEN = 0x1B8278 + 0x2E30       # bit n set: skit n was seen (0x128F78 tests it for lists that skip seen skits)
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

def j_word(target): return 0x08000000 | ((target >> 2) & 0x3FFFFFF)


TRAMP_FILE = 0x115EE0           # zero tail of the second pool (file 0x115E54..0x115F60)
TRAMP_END = 0x115F60
TRAMP_SIZE = 28

ORIGIN_X, ORIGIN_Y = 0x6C00, 0x7900
# Since 1.3.7 the indicator is drawn by the text layer (after the field,
# its reflections and the minimap), not in the field pass: there it was
# dimmed in dark places, cut by water reflections and the transparent
# font pixels needed the alpha test (blue edges on the world map).
EARLY_EXIT = 0x10E15C           # jr ra: the text layer's exit when no window is open (every field frame)
SCISSOR_1 = 0x40
SCISSOR_FULL = ((0xE000 << 30) | 0x9FC0) << 10   # what the layer's normal exit sets (0x10E0F8..0x10E10C)
GS_PRIM, GS_RGBAQ, GS_XYZ2, GS_ALPHA_1 = 0x00, 0x01, 0x05, 0x42
ALPHA_BLEND = 0x44              # (Cs - Cd) x As + Cd, the game's usual ALPHA_1
PRIM_SPRITE = 6
PRIM_TRISTRIP = 4
PRIM_IIP, PRIM_ABE = 0x08, 0x40

# Layout, 640 x 448 space (pnvnd's v1.3.6 report: Tales of Rebirth style;
# a CRT still shows it).
BG_Y0, BG_Y1 = 394, 420         # translucent dark band behind button and title
BG_RGBA = (0, 0, 0, 0x48)       # 0x80 = opaque
FADE = 64                       # pixels over which the band fades out on the right
BG_PAD = 10                     # band past the end of the title before the fade
BX, BY, BW, BH = 20, 398, 58, 16    # the SELECT button
PRESS = 2                       # lines the button moves down when "pressed"
BLINK = 0x20                    # frames per button state (animated like the O prompt)
KEY_SIDE = (0x18, 0x18, 0x1C)   # untextured colours: 0xFF = full
KEY_FACE = (0x50, 0x50, 0x58)
KEY_LIGHT = (0x88, 0x88, 0x90)
LABEL = 'SELECT'
LABEL_X, LABEL_Y = BX + 5, BY + 3
LABEL_SCALE = (0x80, 0xB0)      # 8 pixels per character
LABEL_RGB = (0x6C, 0x6C, 0x70)  # text colours: 0x80 = full
TITLE_X, TITLE_Y = BX + BW + 8, 398
TITLE_SCALE = (0x90, 0x100)     # 9 pixels per character (pnvnd: about 70 % of 1.3.6's 12)
TITLE_ADVANCE = 9
WHITE = (0x80, 0x80, 0x80)
NAMES = ('Kyle', 'Reala', 'Loni', 'Judas', 'Nanaly', 'Harold')   # title code 07 n (n = 1..6)
MAGIC = b'SKIN'
CODE_AT = 8                     # offset of the frame entry from MAGIC
# data block after the code
D_SHOWN, D_WANT, D_LABEL, D_TICK, D_NAMES, D_BUF = 0, 2, 4, 12, 16, 64
BUF_CHARS = 60

_NAMES = 'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split()


def sw(rt, off, rs): return A._i(43, rs, rt, off)
def sh(rt, off, rs): return A._i(41, rs, rt, off)
def sb(rt, off, rs): return A._i(40, rs, rt, off)
def ori(rt, rs, imm): return A._i(13, rs, rt, imm)
def slti(rt, rs, imm): return A._i(10, rs, rt, imm)
def jalr(rs): return (A.REG[rs] << 21) | (31 << 11) | 9
def or_(rd, rs, rt): return (A.REG[rs] << 21) | (A.REG[rt] << 16) | (A.REG[rd] << 11) | 0x25
def sltu(rd, rs, rt): return (A.REG[rs] << 21) | (A.REG[rt] << 16) | (A.REG[rd] << 11) | 0x2B
def srlv(rd, rt, rs): return (A.REG[rs] << 21) | (A.REG[rt] << 16) | (A.REG[rd] << 11) | 0x06
def xori(rt, rs, imm): return A._i(14, rs, rt, imm)
def dsll(rd, rt, sa): return (A.REG[rt] << 16) | (A.REG[rd] << 11) | (sa << 6) | 0x38
def dsll32(rd, rt, sa): return (A.REG[rt] << 16) | (A.REG[rd] << 11) | (sa << 6) | 0x3C
def beqz(rs, label): return A.beq(rs, 'zero', label)
def bnez(rs, label): return A.bne(rs, 'zero', label)
def b(label): return A.beq('zero', 'zero', label)
def bal(label): return ('b', 1, 'zero', 'zero', label)  # regimm, rt 0x11 (assemble() encodes it)


def li(rt, value):
    if 0 <= value <= 0xFFFF:
        return [ori(rt, 'zero', value)]
    if -0x8000 <= value < 0:
        return [A.addiu(rt, 'zero', value)]
    hi, lo = A.hi_lo(value)
    return [A.lui(rt, hi), A.addiu(rt, rt, lo)]


def li64(rt, value):
    """Any unsigned value below 2**64, zero extended (ori/dsll only: a GS
    register value with bit 31 set must not be sign extended)."""
    parts = [(value >> s) & 0xFFFF for s in (48, 32, 16, 0)]
    while len(parts) > 1 and parts[0] == 0:
        parts.pop(0)
    out = [ori(rt, 'zero', parts[0])]
    for p in parts[1:]:
        out.append(dsll(rt, rt, 16))
        if p:
            out.append(ori(rt, rt, p))
    return out


def load_word(rt, addr):
    hi, lo = A.hi_lo(addr)
    return [A.lui(rt, hi), A.lw(rt, lo, rt)]


def gs_x(px): return ORIGIN_X + 16 * px
def gs_y(py): return ORIGIN_Y + 8 * py
def rgb(c): return c[0] | (c[1] << 8) | (c[2] << 16)
def rgba(c, a=0xFF): return c[0] | (c[1] << 8) | (c[2] << 16) | (a << 24)


def hook_code():
    """Position independent code; offsets count from MAGIC. Entries 'frame'
    (= CODE_AT), 'pick', 'layer' and 'early'; v0 holds the entry's own
    address (the trampolines put it there)."""
    L = []
    o = L.append

    def ext(*items):
        L.extend(items)

    def gs(reg, value=None, value_ops=None):
        """one GS register write through 0x14F218 (a0 register, a1 value)"""
        ext(*(value_ops if value_ops is not None else li64('a1', value)))
        ext(A.jal(GS_SET), A.addiu('a0', 'zero', reg))

    def xy(px, py, dy=False, x_reg=None):
        """a1 = XYZ2 value; dy: add s4 (pressed offset, GS units) to y;
        x_reg: x in GS units from that register instead of px"""
        ops = [ori('a1', 'zero', gs_y(py))]
        if dy:
            ops.append(A.addu('a1', 'a1', 's4'))
        ops.append(dsll('a1', 'a1', 16))
        ops.append(or_('a1', 'a1', x_reg) if x_reg else ori('a1', 'a1', gs_x(px)))
        return ops

    def sprite(x0, y0, x1, y1, dy=False):
        gs(GS_XYZ2, value_ops=xy(x0, y0, dy))
        gs(GS_XYZ2, value_ops=xy(x1, y1, dy))

    # --- frame entry: replaces jal 0x10B028 at 0x11C288 -------------------
    # Decides which skit to show (none when the game would play none) and
    # asks the text layer to draw it; it draws nothing itself.
    o('frame')
    ext(A.addiu('sp', 'sp', -0x90),
        A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'), A.sd('s1', 0x20, 'sp'), A.sd('s2', 0x30, 'sp'))
    o(('rel', 's2', 'v0', 'data', 'frame'))           # s2 = data
    ext(sh('zero', D_WANT, 's2'),
        A.jal(PAD), A.NOP,                            # a0 is still the caller's 0
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
        A.lw('t1', 0x54, 'sp'), sw('t1', RAND_STATE, 's0'))
    # the game would play nothing: show nothing (the list it leaves behind
    # can be stale; 1.3.6 kept showing the last skit after all were seen)
    o(beqz('s1', 'hide'))
    o(A.lh('a0', D_SHOWN, 's2'))
    o(bal('listed'))                                  # the shown one, while listed and unseen
    o(A.NOP)
    o(bnez('v0', 'show'))
    o(A.lh('a0', D_SHOWN, 's2'))
    o(bal('first'))                                   # else the first unseen one listed
    o(A.NOP)
    o(beqz('v0', 'hide'))                             # only seen ones left (pnvnd, 1.3.6)
    o(A.move('a0', 'v0'))
    o(sh('a0', D_SHOWN, 's2'))
    o('show')
    o(bal('title'))
    o(A.NOP)
    o(beqz('v0', 'out'))
    o(A.addiu('t0', 'zero', 1))
    o(sh('t0', D_WANT, 's2'))
    o(b('out'))
    o(A.NOP)
    o('hide')
    o(sh('zero', D_SHOWN, 's2'))
    o('out')
    ext(A.lw('v0', 0x50, 'sp'),
        A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.ld('s1', 0x20, 'sp'), A.ld('s2', 0x30, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x90))

    # --- title(a0 skit): v0 = its title, 0 if none --------------------------
    o('title')
    o(A.blez('a0', 'title_end'))
    o(A.move('v0', 'zero'))
    ext(slti('t0', 'a0', TITLE_COUNT))
    o(beqz('t0', 'title_end'))
    o(A.sll('t0', 'a0', 2))
    hi, lo = A.hi_lo(TITLES)
    ext(A.lui('t1', hi), A.addu('t1', 't1', 't0'), A.lw('v0', lo, 't1'))
    o('title_end')
    o(A.jr('ra'))
    o(A.NOP)

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
    # listed: 1 unless its seen bit is set
    ext(A.srl('t5', 'a0', 3), *li('t6', SEEN), A.addu('t6', 't6', 't5'), A.lbu('t6', 0, 't6'),
        A.andi('t5', 'a0', 7), srlv('t6', 't6', 't5'), A.andi('t6', 't6', 1), xori('v0', 't6', 1))
    o('listed_end')
    o(A.jr('ra'))
    o(A.NOP)

    # --- first(): v0 = the first listed skit not seen yet, 0 if none -------
    o('first')
    ext(A.addiu('sp', 'sp', -0x30), A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'), A.sd('s1', 0x20, 'sp'),
        *li('s0', CANDIDATES))
    hi, lo = A.hi_lo(CANDIDATE_COUNT)
    ext(A.lui('s1', hi), A.lhu('s1', lo, 's1'))
    o('first_loop')
    o(A.blez('s1', 'first_none'))
    o(A.NOP)
    o(A.lh('a0', 0, 's0'))
    o(bal('listed'))
    o(A.addiu('s0', 's0', 2))
    o(beqz('v0', 'first_loop'))
    o(A.addiu('s1', 's1', -1))
    o(b('first_end'))
    o(A.lh('v0', -2, 's0'))
    o('first_none')
    o(A.move('v0', 'zero'))
    o('first_end')
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.ld('s1', 0x20, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x30))

    # --- text(a0 string, a1 GS x, a2 GS y, a3 rgb, t0 x scale, t1 y scale) --
    o('text')
    ext(A.addiu('sp', 'sp', -0x80),
        A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'), A.sd('s1', 0x20, 'sp'), A.sd('s2', 0x30, 'sp'),
        A.sd('s3', 0x40, 'sp'), A.sd('s5', 0x48, 'sp'),
        A.move('s0', 'a0'), A.move('s1', 'a1'), A.move('s2', 'a2'), A.move('s3', 'a3'),
        A.sll('s5', 't0', 16), or_('s5', 's5', 't1'),
        A.sd('zero', 0x50, 'sp'), A.sd('zero', 0x58, 'sp'),
        A.jal(SET_BLOCK), A.addiu('a0', 'sp', 0x50),
        A.addiu('a0', 'sp', 0x50), A.srl('a1', 's5', 16), A.andi('a2', 's5', 0xFFFF),
        A.jal(SET_SCALE), A.NOP,
        A.addiu('a0', 'sp', 0x50), A.andi('a1', 's3', 0xFF), A.srl('a2', 's3', 8), A.andi('a2', 'a2', 0xFF),
        A.srl('a3', 's3', 16), A.jal(SET_RGBA), A.addiu('t0', 'zero', 0x80),
        A.addiu('a0', 'sp', 0x50), A.move('a1', 's1'), A.jal(SET_POS), A.move('a2', 's2'),
        A.move('a0', 's0'), A.lui('a1', PRINT_FLAGS >> 16),
        A.jal(PRINT), ori('a1', 'a1', PRINT_FLAGS & 0xFFFF),
        A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.ld('s1', 0x20, 'sp'), A.ld('s2', 0x30, 'sp'),
        A.ld('s3', 0x40, 'sp'), A.ld('s5', 0x48, 'sp'), A.jr('ra'), A.addiu('sp', 'sp', 0x80))

    # --- paint(s0 data): the indicator, if the field asked for it this frame
    o('paint')
    ext(A.addiu('sp', 'sp', -0x60),
        A.sd('ra', 0x00, 'sp'), A.sd('s1', 0x10, 'sp'), A.sd('s2', 0x20, 'sp'), A.sd('s3', 0x30, 'sp'),
        A.sd('s4', 0x40, 'sp'))
    o(A.lhu('t0', D_WANT, 's0'))
    o(beqz('t0', 'paint_end'))
    o(sh('zero', D_WANT, 's0'))
    o(A.lh('a0', D_SHOWN, 's0'))
    o(bal('title'))
    o(A.NOP)
    o(beqz('v0', 'paint_end'))
    # copy the title into the buffer; code 07 n (5 bytes) = character name n
    ext(A.move('t0', 'v0'), A.addiu('s1', 's0', D_BUF), A.move('t1', 's1'),
        A.addiu('t5', 's1', BUF_CHARS))
    o('copy')
    o(A.lbu('t2', 0, 't0'))
    o(beqz('t2', 'copied'))
    o(A.addiu('t3', 'zero', 7))
    o(A.bne('t2', 't3', 'copy_char'))
    o(A.NOP)
    ext(A.lbu('t2', 1, 't0'), A.addiu('t0', 't0', 5), A.addiu('t2', 't2', -1),
        A.sltiu('t3', 't2', len(NAMES)))
    o(beqz('t3', 'copy'))
    o(A.sll('t2', 't2', 3))
    ext(A.addu('t2', 't2', 's0'), A.addiu('t2', 't2', D_NAMES))
    o('copy_name')
    o(A.lbu('t3', 0, 't2'))
    o(beqz('t3', 'copy'))
    o(sltu('t4', 't1', 't5'))
    o(beqz('t4', 'copied'))
    o(A.addiu('t2', 't2', 1))
    o(sb('t3', 0, 't1'))
    o(b('copy_name'))
    o(A.addiu('t1', 't1', 1))
    o('copy_char')
    o(sltu('t4', 't1', 't5'))
    o(beqz('t4', 'copied'))
    o(A.addiu('t0', 't0', 1))
    o(sb('t2', 0, 't1'))
    o(b('copy'))
    o(A.addiu('t1', 't1', 1))
    o('copied')
    ext(sb('zero', 0, 't1'), A.subu('s2', 't1', 's1'))       # s2 = length
    # s3 = end of the solid band (GS x) = title x + length x advance + pad
    assert TITLE_ADVANCE == 9                                  # 144 n = 128 n + 16 n
    ext(A.sll('t0', 's2', 7), A.sll('t1', 's2', 4), A.addu('t0', 't0', 't1'),
        *li('s3', gs_x(TITLE_X + BG_PAD)), A.addu('s3', 's3', 't0'))
    # s4 = button offset: 0 or PRESS lines, switching every BLINK frames
    ext(A.lw('t0', D_TICK, 's0'), A.addiu('t0', 't0', 1), sw('t0', D_TICK, 's0'),
        A.andi('t0', 't0', BLINK), A.move('s4', 'zero'))
    o(beqz('t0', 'released'))
    o(A.NOP)
    o(A.addiu('s4', 'zero', 8 * PRESS))
    o('released')
    # GS state for the primitives: alpha test (font cells), usual blend
    gs(GS_TEST_1, TEST_TEXT)
    gs(GS_ALPHA_1, ALPHA_BLEND)
    # the band: a solid part, then a fade to the right (Gouraud strip)
    bg = rgba(BG_RGBA[:3], BG_RGBA[3])
    gs(GS_PRIM, PRIM_SPRITE | PRIM_ABE)
    gs(GS_RGBAQ, bg)
    gs(GS_XYZ2, value_ops=xy(0, BG_Y0))
    gs(GS_XYZ2, value_ops=xy(0, BG_Y1, x_reg='s3'))
    gs(GS_PRIM, PRIM_TRISTRIP | PRIM_IIP | PRIM_ABE)
    gs(GS_XYZ2, value_ops=xy(0, BG_Y0, x_reg='s3'))
    gs(GS_XYZ2, value_ops=xy(0, BG_Y1, x_reg='s3'))
    ext(A.addiu('s3', 's3', 16 * FADE))
    gs(GS_RGBAQ, rgba(BG_RGBA[:3], 0))
    gs(GS_XYZ2, value_ops=xy(0, BG_Y0, x_reg='s3'))
    gs(GS_XYZ2, value_ops=xy(0, BG_Y1, x_reg='s3'))
    # the button: dark side below (seen while released), face, top light
    gs(GS_PRIM, PRIM_SPRITE)
    gs(GS_RGBAQ, rgba(KEY_SIDE))
    sprite(BX + 1, BY + PRESS, BX + BW - 1, BY + BH + PRESS)
    gs(GS_RGBAQ, rgba(KEY_FACE))
    sprite(BX + 1, BY, BX + BW - 1, BY + BH, dy=True)
    sprite(BX, BY + 2, BX + 1, BY + BH - 2, dy=True)
    sprite(BX + BW - 1, BY + 2, BX + BW, BY + BH - 2, dy=True)
    gs(GS_RGBAQ, rgba(KEY_LIGHT))
    sprite(BX + 2, BY, BX + BW - 2, BY + 2, dy=True)
    # the texts (the button label moves with the button)
    ext(A.addiu('a0', 's0', D_LABEL), *li('a1', gs_x(LABEL_X)), *li('a2', gs_y(LABEL_Y)),
        A.addu('a2', 'a2', 's4'), *li('a3', rgb(LABEL_RGB)), *li('t0', LABEL_SCALE[0]))
    o(bal('text'))
    o(ori('t1', 'zero', LABEL_SCALE[1]))
    ext(A.move('a0', 's1'), *li('a1', gs_x(TITLE_X)), *li('a2', gs_y(TITLE_Y)),
        *li('a3', rgb(WHITE)), *li('t0', TITLE_SCALE[0]))
    o(bal('text'))
    o(ori('t1', 'zero', TITLE_SCALE[1]))
    o('paint_end')
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s1', 0x10, 'sp'), A.ld('s2', 0x20, 'sp'), A.ld('s3', 0x30, 'sp'),
        A.ld('s4', 0x40, 'sp'), A.jr('ra'), A.addiu('sp', 'sp', 0x60))

    # --- pick entry: replaces jal 0x129510 at 0x11C32C ---------------------
    o('pick')
    ext(A.addiu('sp', 'sp', -0x40),
        A.sd('ra', 0x00, 'sp'), A.sd('s1', 0x10, 'sp'), A.sd('s2', 0x20, 'sp'))
    o(('rel', 's2', 'v0', 'data', 'pick'))
    ext(A.jal(FIND), A.NOP, A.move('s1', 'v0'))
    o(beqz('s1', 'pick_end'))                          # the game plays nothing: nor do we
    o(A.lh('a0', D_SHOWN, 's2'))
    o(bal('listed'))
    o(A.NOP)
    o(beqz('v0', 'pick_end'))
    o(A.move('v0', 's1'))
    o(A.lh('v0', D_SHOWN, 's2'))
    o('pick_end')
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s1', 0x10, 'sp'), A.ld('s2', 0x20, 'sp'),
        A.jr('ra'), A.addiu('sp', 'sp', 0x40))

    # --- layer entry: replaces the tail call j 0x14F218 at 0x10E130 --------
    # (the text layer's exit while a window is open; a0/a1 = the full scissor)
    o('layer')
    ext(A.addiu('sp', 'sp', -0x40), A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'))
    o(('rel', 's0', 'v0', 'data', 'layer'))
    ext(A.jal(GS_SET), A.NOP)
    o(bal('paint'))
    o(A.NOP)
    ext(A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'), A.jr('ra'), A.addiu('sp', 'sp', 0x40))

    # --- early entry: replaces jr ra at 0x10E15C (no window open) ----------
    o('early')
    ext(A.addiu('sp', 'sp', -0x40), A.sd('ra', 0x00, 'sp'), A.sd('s0', 0x10, 'sp'))
    o(('rel', 's0', 'v0', 'data', 'early'))
    o(A.lhu('t0', D_WANT, 's0'))
    o(beqz('t0', 'early_end'))
    o(A.NOP)
    gs(SCISSOR_1, SCISSOR_FULL)
    o(bal('paint'))
    o(A.NOP)
    o('early_end')
    ext(A.move('v0', 'zero'), A.ld('ra', 0x00, 'sp'), A.ld('s0', 0x10, 'sp'),
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
    data = bytearray(D_BUF + BUF_CHARS + 4)
    data[D_LABEL:D_LABEL + len(LABEL)] = LABEL.encode('ascii')
    for i, name in enumerate(NAMES):
        assert len(name) < 8
        data[D_NAMES + 8 * i:D_NAMES + 8 * i + len(name)] = name.encode('ascii')
    assert D_LABEL + len(LABEL) < D_TICK and D_NAMES + 8 * len(NAMES) <= D_BUF
    data = bytes(data)
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
    """Four sites: the pad read and the skit search in the SELECT handler
    (jal), the text layer's two exits (j 0x14F218 and jr ra). Each goes
    to a 7 word trampoline in the second pool's zero tail."""
    d = bytearray(slps)
    tramp = [TRAMP_FILE + i * TRAMP_SIZE for i in range(4)]
    assert tramp[3] + TRAMP_SIZE <= TRAMP_END
    sites = ((PAD_CALL, A.jal(PAD), A.jal(tramp[0] + BIAS), 'frame'),
             (PICK_CALL, A.jal(FIND), A.jal(tramp[1] + BIAS), 'pick'),
             (LAYER_EXIT, j_word(GS_SET), j_word(tramp[2] + BIAS), 'layer'),
             (EARLY_EXIT, A.JR_RA, j_word(tramp[3] + BIAS), 'early'))
    for site, original, ours, _ in sites:
        got = struct.unpack_from('<I', d, site - BIAS)[0]
        if got not in (original, ours):
            raise ValueError('unexpected word %08x at 0x%X (not a retail SLPS_251.72?)' % (got, site))
    area = bytes(d[TRAMP_FILE:TRAMP_END])
    first = trampoline(index, labels['frame'])
    if any(area) and area[:8] != first[:8]:
        raise ValueError('second pool tail 0x%X is in use; move the trampolines' % TRAMP_FILE)
    d[TRAMP_FILE:TRAMP_END] = bytes(TRAMP_END - TRAMP_FILE)      # 1.3.6 had three
    for (site, _, ours, label), t in zip(sites, tramp):
        d[t:t + TRAMP_SIZE] = trampoline(index, labels[label])
        struct.pack_into('<I', d, site - BIAS, ours)
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
    print('%s %s (%d -> %d bytes, member %d, %d code bytes) and %s (0x%X, 0x%X, 0x%X, 0x%X to trampolines at 0x%X)'
          % ('would patch' if a.dry_run else 'patched', CONTAINER, len(data), len(out), index,
             labels['data'] - CODE_AT, os.path.basename(a.slps), PAD_CALL, PICK_CALL, LAYER_EXIT,
             EARLY_EXIT, TRAMP_FILE + BIAS))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
