#!/usr/bin/env python3
"""Skit indicator (PSP): while a skit can be started with SELECT, the field
screen shows "SELECT" in yellow and the skit's title in the bottom left
corner, as in the Lumina Tales concept (dreck's QoL request, 2026-11).

build_psp.py calls patch_boot() on BOOT.BIN after the battle subtitles.

How the game starts a skit (found in PPSSPP on the 0.3.6 image, vaddr;
file offset = vaddr + 0xC0, runtime = vaddr + 0x08804000; data addresses
in the code are relative to the data segment 0x1DCC00 and relocated):

* The field frame function 0x14BC10 checks SELECT only while no event runs
  (word at 0x662A64 + 0x1548 is 0): 0x15638C must return nonzero, the
  signed byte at 0x656CA8 + 0x2AA2 must be >= 0, the pad edge bits
  (0x13BAD4) must hold 0x100, and in mode 6 (0x133274) 0xA03C0 must
  return 0. Then 0x14C08C calls 0x158C98, which returns the skit to play
  (0 = none), and 0x158EB4 starts it (number stored at 0x662A64 + 0x1CE8,
  file.fpb member 213 + 2 x number; the number is the Skit Hut number).
* 0x158C98 walks the skit lists of the current place, keeps the skits whose
  conditions hold (0x15D14C: story progress range, flags, and the "seen"
  bit at 0x656CA8 + 0x3A00 for lists that skip seen skits) in a halfword
  list at 0x55EF30 (at most 8, count at +0x10), and picks one with rand()
  (0x18741C, newlib: 64 bit state at +0xA8 of the reent block from
  0x185874). Apart from that pick it only writes its own scratch globals.
* Skit titles: pointer table at 0x289400, entry n = skit n (the Skit Hut
  list, English since the menu patch).
* Text: the battle subtitle helper 0x544F8 (a0 x, a1 y, a2 string, a3
  colour, t0/t1 scale) also draws on the field, in the 640 x 448 space
  the PSP shows at 0.75 x 0.61; colour 6 is yellow, 7 white.

What this step adds, appended to the pool after the battle subtitles:

* A frame hook: the call of 0x14CC70 at 0x14BF74 (the last update of the
  field frame) is retargeted to it. It calls 0x14CC70, then, when SELECT
  would be checked (the same tests as the game), asks 0x158C98 for the
  available skits with the rand() state saved and restored, so the game's
  random numbers do not change. The skit it shows stays the same while it
  is available; when it is played or no longer available the hook takes
  the game's own pick of the new list. It draws "SELECT" and the title.
* A pick hook: the call of 0x158C98 at 0x14C08C (SELECT pressed) is
  retargeted to it. It calls 0x158C98 as before (same rand() use) and
  returns the skit the indicator drew in the last frame, otherwise the
  game's pick. So SELECT plays the skit whose title is on screen. (0.3.7
  returned it only if it was still in the list at SELECT; the frame hook
  asks at the end of a frame and the list can change before SELECT is
  read, so on the world map "Landmark" showed and "Trap" played.)
* The text: where the frame hook draws, the field leaves an alpha test
  function that passes the transparent pixels of the font cells, so they
  stood on black boxes (0.3.7). The hook sets sceGuAlphaFunc(GREATER, 0,
  0xFF) (0x9F8C; what the game sets almost everywhere), turns the alpha
  test and blending on (sceGuGetStatus 0x8E68, sceGuEnable 0x8D28; states
  0 and 4) and puts those two enable states back after its text
  (sceGuSetStatus 0x8DDC). Setting only the enables, the blend function,
  the texture function or reloading the font texture changed nothing
  (tried in PPSSPP).
* Since 0.3.9: only skits not seen yet are shown (seen bit n at 0x656CA8
  + 0x3A00; some lists offer seen skits again, and after all were seen
  the last one stayed, pnvnd), nothing when the search returns 0, name
  codes 07 n in a title become the English names, and no title at the
  top during a skit (0.3.8; on the world map the skit covered it).

Both calls are relocated jal words (R_MIPS_26 against the text segment);
the loader adds the load address to the pool target as for the battle
subtitles, and the hooks build every other address from their return
address, so no new relocation is needed. The shown skit is one halfword in
the pool (the PSP has no write protection for user memory).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mips_asm  # noqa: E402

REGS_T5, REGS_T6 = mips_asm.REGS['t5'], mips_asm.REGS['t6']

TEXT_BIAS = 0xC0
POOL_VADDR = 0x881000

FRAME_CALL = 0x14BF74       # jal 0x14CC70 in the field frame function 0x14BC10
FRAME_RET = FRAME_CALL + 8
FRAME_PART = 0x14CC70
PICK_CALL = 0x14C08C        # jal 0x158C98 after SELECT
PICK_RET = PICK_CALL + 8
FIND = 0x158C98             # returns the skit to play (0 = none)
REENT = 0x185874            # newlib reent block; rand() state at +0xA8/+0xAC
RAND_STATE = 0xA8
IDLE = 0x15638C             # nonzero when the field accepts SELECT
MODE = 0x133274             # game mode
MODE6_BUSY = 0xA03C0        # in mode 6 SELECT is ignored while this returns nonzero
EVENT = 0x662A64            # +0x1548 nonzero while an event runs
EVENT_BUSY = 0x1548
FIELD = 0x656CA8            # +0x2AA2 signed byte, negative: no skits
FIELD_LOCK = 0x2AA2
SEEN = 0x3A00               # FIELD + this: bit n set once skit n was seen (0x15D14C tests it)
NAMES = ('Kyle', 'Reala', 'Loni', 'Judas', 'Nanaly', 'Harold')   # title code 07 n (n = 1..6)
BUF_CHARS = 60
CANDIDATES = 0x55EF30       # halfword skit numbers found by FIND
CANDIDATE_COUNT = 0x10      # halfword after the list (at most 8)
TITLES = 0x289400           # pointer table, entry n = title of skit n
TEXT = 0x544F8              # text helper (x, y, string, colour, xscale, yscale)
SKIT_FLAGS = 0x1544         # EVENT + this: bit 0x40 while a skit plays (as on the PS2)
SKIT_BIT = 0x40
PLAYING = 0x1CE8            # EVENT + this: halfword, the skit started last (0x158EB4 stores it)
TITLE_COUNT = 623           # entries in the title table (622 is the last one)
GU_ENABLE = 0x8D28          # sceGuEnable(state) of the game's GU library (0x8D80 disable)
GU_SET = 0x8DDC             # sceGuSetStatus(state, value)
GU_GET = 0x8E68             # sceGuGetStatus(state)
GU_ALPHA_TEST, GU_BLEND = 0, 4
GU_ALPHA_FUNC = 0x9F8C      # sceGuAlphaFunc(func, ref, mask)
GU_GREATER = 6

YELLOW, WHITE = 6, 7
XSCALE, YSCALE = 0x100, 0xE0  # 0x100 high cut the descenders (g in "Nostalgic")
X, Y = 16, 410              # bottom left, in the helper's 640 x 448 space
LABEL = 'SELECT'
GAP = 10                    # between the label and the title
SPACING = 1.05              # measured advance / glyph table advance (battle subtitles)
FIXED_ADVANCE = 12          # per character without the variable width font
MAGIC = b'SKIN'


def jal_word(target):
    return 0x0C000000 | ((target >> 2) & 0x3FFFFFF)


def label_width(vwf=True):
    """Width of LABEL in the helper's space at XSCALE."""
    if vwf:
        import psp_latin_font
        g = psp_latin_font.load()['glyphs1']
        units = sum(g[c]['adv'] for c in LABEL)
    else:
        units = FIXED_ADVANCE * len(LABEL)
    return int(units * XSCALE / 256 * SPACING + 0.5)


def hook_code(origin, vwf=True):
    """The frame hook at `origin`, the pick hook at labels['pick'], data
    after them. Frame hook registers: s0 reent block, s1 game pick / title,
    s2 data, s3 load address + FRAME_RET, s4 the GU states found."""
    a = mips_asm.Asm(origin)
    op = a.op

    def addr(reg, target, base_reg, ret):
        """reg = base_reg - ret + target (target: vaddr or label)."""
        v = ('hi', target, ret) if isinstance(target, str) else ('hi', target - ret)
        op('lui', reg, v)
        op('addiu', reg, reg, ('lo',) + v[1:])
        op('addu', reg, reg, base_reg)

    def call(target, ret=FRAME_RET):
        addr('t9', target, 's3', ret)
        op('jalr', 't9')
        op('nop')

    def draw(x_reg_or_value, y, colour, xscale, yscale):
        if isinstance(x_reg_or_value, str):
            op('move', 'a0', x_reg_or_value)
        else:
            op('li', 'a0', x_reg_or_value)
        op('li', 'a1', y)
        op('li', 'a3', colour)
        op('li', 't0', xscale)
        addr('t9', TEXT, 's3', FRAME_RET)
        op('jalr', 't9')
        op('li', 't1', yscale)

    def blend_on():
        """Alpha test "greater than 0" and blending for the text; s4 = the old
        enable states. The field leaves an alpha test function here that lets
        the transparent pixels of the font cells through, so they drew as
        black boxes (0.3.7); GREATER 0 / 0xFF is what the game itself sets
        almost everywhere (0xEE0, 0x172850, ...), so it stays set."""
        op('li', 'a0', GU_ALPHA_TEST)
        call(GU_GET)
        op('move', 's4', 'v0')
        op('li', 'a0', GU_BLEND)
        call(GU_GET)
        op('sll', 'v0', 'v0', 1)
        op('addu', 's4', 's4', 'v0')                 # bit 0 alpha test, bit 1 blend
        op('li', 'a0', GU_ALPHA_TEST)
        call(GU_ENABLE)
        op('li', 'a0', GU_BLEND)
        call(GU_ENABLE)
        op('li', 'a0', GU_GREATER)
        op('li', 'a1', 0)
        op('li', 'a2', 0xFF)
        call(GU_ALPHA_FUNC)

    def blend_restore():
        op('li', 'a0', GU_ALPHA_TEST)
        op('andi', 'a1', 's4', 1)
        call(GU_SET)
        op('li', 'a0', GU_BLEND)
        op('srl', 'a1', 's4', 1)
        call(GU_SET)

    # --- frame hook -------------------------------------------------------
    op('addiu', 'sp', 'sp', -0x30)
    for i, r in enumerate(('ra', 's0', 's1', 's2', 's3')):
        op('sw', r, 4 * i, 'sp')
    op('sw', 's4', 0x20, 'sp')
    op('move', 's3', 'ra')
    op('addiu', 't9', 'ra', FRAME_PART - FRAME_RET)
    op('jalr', 't9')                                  # a0..a3 are the caller's
    op('nop')
    op('sw', 'v0', 0x14, 'sp')
    addr('s2', 'data', 's3', FRAME_RET)
    op('sh', 'zero', 2, 's2')                         # not shown (yet) in this frame
    # the tests the game makes before it looks at SELECT
    addr('t0', EVENT, 's3', FRAME_RET)
    op('lw', 't1', EVENT_BUSY, 't0')
    op('bnez', 't1', 'out')                           # also while a skit plays (no title on top since 0.3.9)
    op('nop')
    addr('t0', FIELD, 's3', FRAME_RET)
    op('lb', 't1', FIELD_LOCK, 't0')
    op('slti', 't1', 't1', 0)
    op('bnez', 't1', 'out')
    op('nop')
    call(IDLE)
    op('beqz', 'v0', 'out')
    op('nop')
    call(MODE)
    op('li', 't0', 6)
    op('bne', 'v0', 't0', 'ask')
    op('nop')
    call(MODE6_BUSY)
    op('bnez', 'v0', 'out')
    op('nop')
    a.label('ask')
    # ask the game, with rand() left as it was
    call(REENT)
    op('move', 's0', 'v0')
    op('lw', 't0', RAND_STATE, 's0')
    op('lw', 't1', RAND_STATE + 4, 's0')
    op('sw', 't0', 0x18, 'sp')
    op('sw', 't1', 0x1C, 'sp')
    call(FIND)
    op('move', 's1', 'v0')
    op('lw', 't0', 0x18, 'sp')
    op('lw', 't1', 0x1C, 'sp')
    op('sw', 't0', RAND_STATE, 's0')
    op('sw', 't1', RAND_STATE + 4, 's0')
    # the game would play nothing: show nothing
    op('beqz', 's1', 'hide')
    # keep the shown skit while it is listed and not seen yet, else the
    # first listed one not seen yet, else none (pnvnd, 0.3.8: after all
    # skits were seen the last one stayed; the game offers seen skits of
    # some lists again)
    op('lh', 'a0', 0, 's2')
    addr('a1', CANDIDATES, 's3', FRAME_RET)
    op('bal', 'listed')
    op('nop')
    op('bnez', 'v0', 'show')
    op('lh', 'a0', 0, 's2')
    addr('s0', CANDIDATES, 's3', FRAME_RET)
    op('lhu', 's4', CANDIDATE_COUNT, 's0')
    a.label('first')
    op('blez', 's4', 'hide')
    op('nop')
    op('lh', 'a0', 0, 's0')
    addr('a1', CANDIDATES, 's3', FRAME_RET)
    op('bal', 'listed')
    op('addiu', 's0', 's0', 2)
    op('beqz', 'v0', 'first')
    op('addiu', 's4', 's4', -1)
    op('lh', 'a0', -2, 's0')
    op('sh', 'a0', 0, 's2')
    a.label('show')
    op('bal', 'title')
    op('nop')
    op('beqz', 'v0', 'out')
    op('move', 't0', 'v0')
    # copy the title, code 07 n (2 bytes) = character name n
    addr('t1', 'buf', 's3', FRAME_RET)
    op('addiu', 't7', 't1', BUF_CHARS)
    a.label('copy')
    op('lbu', 't2', 0, 't0')
    op('beqz', 't2', 'copied')
    op('addiu', 't3', 'zero', 7)
    op('bne', 't2', 't3', 'copy_char')
    op('nop')
    op('lbu', 't2', 1, 't0')
    op('addiu', 't0', 't0', 2)
    op('addiu', 't2', 't2', -1)
    op('sltiu', 't3', 't2', len(NAMES))
    op('beqz', 't3', 'copy')
    op('sll', 't2', 't2', 3)
    addr('t4', 'names', 's3', FRAME_RET)
    op('addu', 't2', 't2', 't4')
    a.label('copy_name')
    op('lbu', 't3', 0, 't2')
    op('beqz', 't3', 'copy')
    op('sltu', 't4', 't1', 't7')
    op('beqz', 't4', 'copied')
    op('addiu', 't2', 't2', 1)
    op('sb', 't3', 0, 't1')
    op('b', 'copy_name')
    op('addiu', 't1', 't1', 1)
    a.label('copy_char')
    op('sltu', 't4', 't1', 't7')
    op('beqz', 't4', 'copied')
    op('addiu', 't0', 't0', 1)
    op('sb', 't2', 0, 't1')
    op('b', 'copy')
    op('addiu', 't1', 't1', 1)
    a.label('copied')
    op('sb', 'zero', 0, 't1')
    addr('s1', 'buf', 's3', FRAME_RET)
    op('li', 't0', 1)
    op('sh', 't0', 2, 's2')                           # on screen: SELECT plays it
    blend_on()
    op('addiu', 'a2', 's2', 4)
    draw(X, Y, YELLOW, XSCALE, YSCALE)
    op('move', 'a2', 's1')
    draw(X + label_width(vwf) + GAP, Y, WHITE, XSCALE, YSCALE)
    blend_restore()
    op('b', 'out')
    op('nop')

    a.label('hide')
    op('sh', 'zero', 0, 's2')

    a.label('out')
    op('lw', 'v0', 0x14, 'sp')
    for i, r in enumerate(('ra', 's0', 's1', 's2', 's3')):
        op('lw', r, 4 * i, 'sp')
    op('lw', 's4', 0x20, 'sp')
    op('jr', 'ra')
    op('addiu', 'sp', 'sp', 0x30)

    # --- title(a0 skit, s3 base): v0 = its title, 0 if none ----------------
    a.label('title')
    op('blez', 'a0', 'title_end')
    op('move', 'v0', 'zero')
    op('sltiu', 't0', 'a0', TITLE_COUNT)
    op('beqz', 't0', 'title_end')
    op('sll', 't0', 'a0', 2)
    addr('t1', TITLES, 's3', FRAME_RET)
    op('addu', 't1', 't1', 't0')
    op('lw', 'v0', 0, 't1')
    a.label('title_end')
    op('jr', 'ra')
    op('nop')

    # --- listed(a0 skit, a1 list): v0 = 1 if a0 > 0 is in the list --------
    a.label('listed')
    op('move', 'v0', 'zero')
    op('blez', 'a0', 'listed_end')
    op('lhu', 't2', CANDIDATE_COUNT, 'a1')
    op('sltiu', 't3', 't2', 9)                        # never more than 8
    op('bnez', 't3', 'listed_loop')
    op('nop')
    op('li', 't2', 8)
    a.label('listed_loop')
    op('blez', 't2', 'listed_end')
    op('nop')
    op('lh', 't3', 0, 'a1')
    op('addiu', 'a1', 'a1', 2)
    op('bne', 't3', 'a0', 'listed_loop')
    op('addiu', 't2', 't2', -1)
    # listed: 1 unless its seen bit is set (s3 = the frame hook's base)
    op('srl', 't5', 'a0', 3)
    addr('t6', FIELD + SEEN, 's3', FRAME_RET)
    op('addu', 't6', 't6', 't5')
    op('lbu', 't6', 0, 't6')
    op('andi', 't5', 'a0', 7)
    a.data(struct.pack('<I', (REGS_T5 << 21) | (REGS_T6 << 16) | (REGS_T6 << 11) | 0x06))   # srlv t6, t6, t5
    op('andi', 't6', 't6', 1)
    op('sltiu', 'v0', 't6', 1)
    a.label('listed_end')
    op('jr', 'ra')
    op('nop')

    # --- pick hook: SELECT plays the skit on screen -----------------------
    a.label('pick')
    op('addiu', 'sp', 'sp', -0x20)
    for i, r in enumerate(('ra', 's1', 's2', 's3')):
        op('sw', r, 4 * i, 'sp')
    op('move', 's3', 'ra')
    addr('t9', FIND, 's3', PICK_RET)                  # 0xCC04 away: too far for one addiu
    op('jalr', 't9')                                  # the game's own call, same rand() use
    op('nop')
    op('move', 's1', 'v0')
    addr('s2', 'data', 's3', PICK_RET)
    op('beqz', 's1', 'pick_end')                      # the game plays nothing: nor do we
    op('nop')
    # the skit drawn in the last frame, if any (the list may differ by now:
    # the frame hook asks at the end of the frame, SELECT is read in the next)
    op('lh', 't0', 2, 's2')
    op('beqz', 't0', 'pick_end')
    op('move', 'v0', 's1')
    op('lh', 'v0', 0, 's2')
    a.label('pick_end')
    for i, r in enumerate(('ra', 's1', 's2', 's3')):
        op('lw', r, 4 * i, 'sp')
    op('jr', 'ra')
    op('addiu', 'sp', 'sp', 0x20)

    a.align(4)
    a.data(MAGIC)
    a.label('data')
    a.data(b'\0\0\0\0' + LABEL.encode('ascii') + b'\0')   # shown skit, on screen, label
    a.align(4)
    a.label('names')
    a.data(b''.join(n.encode('ascii').ljust(8, b'\0') for n in NAMES))
    a.label('buf')
    a.data(bytes(BUF_CHARS + 4))
    a.align(4)
    return a.assemble(), dict(a.labels)


def _pool_header(b):
    phoff = struct.unpack_from('<I', b, 0x1C)[0]
    phnum = struct.unpack_from('<H', b, 0x2C)[0]
    for i in range(phnum):
        o = phoff + 32 * i
        p = list(struct.unpack_from('<8I', b, o))
        if p[0] == 1 and p[2] == POOL_VADDR:
            return o, p
    raise ValueError('no pool segment (run psp_pool first)')


def patch_boot(boot, vwf=True):
    """Append both hooks to the pool and retarget the two calls.
    boot: BOOT.BIN with the pool ending the file. Returns (bytes, info)."""
    b = bytearray(boot)
    for site, target in ((FRAME_CALL, FRAME_PART), (PICK_CALL, FIND)):
        got = struct.unpack_from('<I', b, site + TEXT_BIAS)[0]
        if got != jal_word(target):
            raise ValueError('unexpected word %08x at vaddr %#x (skit indicator already applied, or not a retail BOOT.BIN)'
                             % (got, site))
    off, p = _pool_header(b)
    if p[1] + p[4] != len(b) or p[4] != p[5]:
        raise ValueError('the pool segment must end the file')
    pad = (-p[4]) % 16
    base = POOL_VADDR + p[4] + pad
    code, labels = hook_code(base, vwf)
    b += bytes(pad) + code
    p[4] = p[5] = p[4] + pad + len(code)
    struct.pack_into('<8I', b, off, *p)
    struct.pack_into('<I', b, FRAME_CALL + TEXT_BIAS, jal_word(base))
    struct.pack_into('<I', b, PICK_CALL + TEXT_BIAS, jal_word(labels['pick']))
    return bytes(b), {'hook_vaddr': hex(base), 'pick_vaddr': hex(labels['pick']), 'bytes': len(code)}
