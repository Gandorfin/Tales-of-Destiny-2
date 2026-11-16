"""Tests for psp_skit_indicator.py (no game files needed)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psp_skit_indicator as K  # noqa: E402
from test_psp_battle_subs import Machine  # noqa: E402

LOAD = 0x08804000       # where the PSP kernel puts BOOT.BIN
ORIGIN = K.POOL_VADDR + 0x200
REENT_BLOCK = 0x08F00000
TITLE_AT = 0x09100000


class Field:
    """A fake field: the game functions the hooks call, as stubs."""

    def __init__(self, candidates=(), pick=None, busy=False, idle=True, lock=0, mode=0, mode6_busy=False,
                 titles=None, skit_flags=0, playing=0, gu=(0, 0)):
        self.m = Machine({})
        self.calls = []
        self.drawn = []
        m = self.m
        self.code, self.labels = K.hook_code(ORIGIN)
        m.load(LOAD + ORIGIN, self.code)
        m.write(LOAD + K.EVENT + K.EVENT_BUSY, 4, 1 if busy else 0)
        m.write(LOAD + K.EVENT + K.SKIT_FLAGS, 4, skit_flags)
        m.write(LOAD + K.EVENT + K.PLAYING, 2, playing)
        self.gu = {K.GU_ALPHA_TEST: gu[0], K.GU_BLEND: gu[1]}
        m.write(LOAD + K.FIELD + K.FIELD_LOCK, 1, lock & 0xFF)
        m.write(REENT_BLOCK + K.RAND_STATE, 4, 0x11111111)
        m.write(REENT_BLOCK + K.RAND_STATE + 4, 4, 0x22222222)
        titles = titles or {n: 'Skit %d' % n for n in range(1, 40)}
        for i, (n, t) in enumerate(titles.items()):
            at = TITLE_AT + 0x40 * i
            m.load(at, t.encode() + b'\0')
            m.write(LOAD + K.TITLES + 4 * n, 4, at)
        self.candidates, self.pick = list(candidates), pick

        def find(r):
            self.calls.append('find')
            # the game writes its list and advances rand()
            for i, n in enumerate(self.candidates):
                m.write(LOAD + K.CANDIDATES + 2 * i, 2, n)
            m.write(LOAD + K.CANDIDATES + K.CANDIDATE_COUNT, 2, len(self.candidates))
            m.write(REENT_BLOCK + K.RAND_STATE, 4, 0xDEAD)
            r[2] = (self.pick if self.pick is not None else (self.candidates[0] if self.candidates else 0))

        def text(r):
            # the font cells need blending and the alpha test (else: black boxes)
            assert self.gu == {K.GU_ALPHA_TEST: 1, K.GU_BLEND: 1, 'func': (K.GU_GREATER, 0, 0xFF)}, self.gu
            self.drawn.append((m.string(r[6]), r[4], r[5], r[7], r[8], r[9]))

        def part(r):
            self.calls.append(('part', r[4]))
            r[2] = 0x77
        m.stubs = {
            LOAD + K.FRAME_PART: part,
            LOAD + K.FIND: find,
            LOAD + K.REENT: lambda r: r.__setitem__(2, REENT_BLOCK),
            LOAD + K.IDLE: lambda r: r.__setitem__(2, 1 if idle else 0),
            LOAD + K.MODE: lambda r: r.__setitem__(2, mode),
            LOAD + K.MODE6_BUSY: lambda r: r.__setitem__(2, 1 if mode6_busy else 0),
            LOAD + K.TEXT: text,
            LOAD + K.GU_GET: lambda r: r.__setitem__(2, self.gu[r[4]]),
            LOAD + K.GU_ENABLE: lambda r: self.gu.__setitem__(r[4], 1),
            LOAD + K.GU_SET: lambda r: self.gu.__setitem__(r[4], r[5]),
            LOAD + K.GU_ALPHA_FUNC: lambda r: self.gu.__setitem__('func', (r[4], r[5], r[6])),
        }

    def shown(self):
        return self.m.read(LOAD + self.labels['data'], 2, True)

    def run(self, entry, ret):
        m = self.m
        m.r[29] = 0x09FFF000
        m.r[4] = 0x1234
        for reg in (16, 17, 18, 19, 20, 21, 22, 23, 30):
            m.r[reg] = 0x5000 + reg
        saved = list(m.r)
        self.drawn.clear()
        m.call(entry, ret)
        for reg in (16, 17, 18, 19, 20, 21, 22, 23, 29, 30):
            assert m.r[reg] == saved[reg], 'register %d not restored' % reg
        return m.r[2]

    def frame(self):
        return self.run(LOAD + ORIGIN, LOAD + K.FRAME_RET)

    def select(self):
        return self.run(LOAD + self.labels['pick'], LOAD + K.PICK_RET)


class FrameHookTests(unittest.TestCase):
    def test_field_part_still_runs(self):
        f = Field()
        self.assertEqual(f.frame(), 0x77)              # its result goes back to the game
        self.assertEqual(f.calls[0], ('part', 0x1234))  # with the caller's a0
        self.assertEqual(f.drawn, [])

    def test_draws_label_and_title(self):
        f = Field([4], titles={4: 'All Set'})
        f.frame()
        (label, lx, ly, lc, *ls), (title, tx, ty, tc, *ts) = f.drawn
        self.assertEqual((label, lx, ly, lc), ('SELECT', K.X, K.Y, K.YELLOW))
        self.assertEqual((title, ty, tc), ('All Set', K.Y, K.WHITE))
        self.assertEqual(tx, K.X + K.label_width() + K.GAP)
        self.assertEqual(ls, [K.XSCALE, K.YSCALE])

    def test_rand_state_is_kept(self):
        f = Field([4])
        f.frame()
        self.assertIn('find', f.calls)
        self.assertEqual(f.m.read(REENT_BLOCK + K.RAND_STATE, 4), 0x11111111)
        self.assertEqual(f.m.read(REENT_BLOCK + K.RAND_STATE + 4, 4), 0x22222222)

    def test_nothing_while_select_is_not_checked(self):
        for kw in ({'busy': True}, {'idle': False}, {'lock': -1}, {'mode': 6, 'mode6_busy': True}):
            f = Field([4], **kw)
            f.frame()
            self.assertEqual(f.drawn, [], kw)
            self.assertNotIn('find', f.calls, kw)
        f = Field([4], mode=6)                           # mode 6 without the busy flag shows
        f.frame()
        self.assertEqual(len(f.drawn), 2)

    def test_no_skit(self):
        f = Field([])
        f.frame()
        self.assertEqual(f.drawn, [])
        self.assertEqual(f.shown(), 0)

    def test_shown_skit_stays_while_available(self):
        f = Field([3, 5], pick=5)
        f.frame()
        self.assertEqual(f.drawn[1][0], 'Skit 5')
        f.pick = 3                                       # the game's pick changes with rand()
        f.frame()
        self.assertEqual(f.drawn[1][0], 'Skit 5')
        f.candidates, f.pick = [3], 3                    # 5 was seen: the next one shows
        f.frame()
        self.assertEqual(f.drawn[1][0], 'Skit 3')

    def test_render_states_come_back(self):
        for gu in ((0, 0), (1, 0), (0, 1), (1, 1)):
            f = Field([4], gu=gu)
            f.frame()
            self.assertEqual(len(f.drawn), 2)
            self.assertEqual(f.gu, {K.GU_ALPHA_TEST: gu[0], K.GU_BLEND: gu[1], 'func': (K.GU_GREATER, 0, 0xFF)})

    def test_skit_title_on_top_during_a_skit(self):
        f = Field([], busy=True, skit_flags=K.SKIT_BIT | 1, playing=4, titles={4: 'All Set'})
        f.frame()
        (title, x, y, colour, xs, ys), = f.drawn
        width = sum(K.advance_table()[ord(c) - 0x20] for c in 'All Set')
        self.assertEqual((title, x, y, colour, xs, ys),
                         ('All Set', 320 - width // 2, K.TOP_Y, K.WHITE, K.TOP_XSCALE, K.TOP_YSCALE))
        self.assertNotIn('find', f.calls)
        for kw in ({'skit_flags': 1, 'playing': 4}, {'skit_flags': K.SKIT_BIT, 'playing': 0},
                   {'skit_flags': K.SKIT_BIT, 'playing': 33}, {'skit_flags': K.SKIT_BIT, 'playing': K.TITLE_COUNT}):
            f = Field([], busy=True, titles={4: 'All Set'}, **kw)
            f.frame()
            self.assertEqual(f.drawn, [], kw)

    def test_untitled_skit_draws_nothing(self):
        f = Field([7], titles={1: 'One'})
        f.frame()
        self.assertEqual(f.drawn, [])


class PickHookTests(unittest.TestCase):
    def test_select_plays_the_shown_skit(self):
        f = Field([3, 5], pick=5)
        f.frame()
        f.pick = 3
        self.assertEqual(f.select(), 5)
        self.assertEqual(f.calls.count('find'), 2)       # the frame's and SELECT's own call

    def test_shown_skit_even_if_the_list_changed(self):
        # the frame hook asks at the end of a frame, SELECT is read in the
        # next one: the "Landmark" report (0.3.7) was a list that changed in
        # between, and the game's random pick played another skit
        f = Field([6, 13], pick=6)
        f.frame()
        self.assertEqual(f.drawn[1][0], 'Skit 6')
        f.candidates, f.pick = [13], 13
        self.assertEqual(f.select(), 6)

    def test_game_pick_when_nothing_was_shown(self):
        f = Field([3, 5], pick=3)
        self.assertEqual(f.select(), 3)                  # no frame yet
        f.frame()
        f.m.write(LOAD + K.EVENT + K.EVENT_BUSY, 4, 1)   # hidden in the last frame
        f.frame()
        f.candidates, f.pick = [5], 5
        self.assertEqual(f.select(), 5)
        f.candidates, f.pick = [], 0
        self.assertEqual(f.select(), 0)


def fake_boot():
    """A BOOT.BIN shaped image: three program headers, the two calls, a pool
    segment ending the file."""
    b = bytearray(0x200000)
    struct.pack_into('<I', b, 0x1C, 0x34)
    struct.pack_into('<H', b, 0x2C, 3)
    struct.pack_into('<8I', b, 0x34, 1, 0xC0, 0, 0, 0x194278, 0x194278, 7, 64)
    struct.pack_into('<8I', b, 0x54, 1, 0x1DCD00, 0x1DCC00, 0, 0x1000, 0x6A3C48, 6, 256)
    struct.pack_into('<8I', b, 0x74, 1, len(b) - 0x100, K.POOL_VADDR, 0, 0x100, 0x100, 6, 16)
    struct.pack_into('<I', b, K.FRAME_CALL + K.TEXT_BIAS, K.jal_word(K.FRAME_PART))
    struct.pack_into('<I', b, K.PICK_CALL + K.TEXT_BIAS, K.jal_word(K.FIND))
    return bytes(b)


class BootTests(unittest.TestCase):
    def test_patch(self):
        boot = fake_boot()
        out, info = K.patch_boot(boot)
        hook, pick = int(info['hook_vaddr'], 16), int(info['pick_vaddr'], 16)
        self.assertEqual(struct.unpack_from('<I', out, K.FRAME_CALL + K.TEXT_BIAS)[0], K.jal_word(hook))
        self.assertEqual(struct.unpack_from('<I', out, K.PICK_CALL + K.TEXT_BIAS)[0], K.jal_word(pick))
        p = struct.unpack_from('<8I', out, 0x74)
        self.assertEqual(p[1] + p[4], len(out))
        self.assertEqual(p[4], p[5])
        changed = {i // 4 * 4 for i in range(len(boot)) if out[i] != boot[i]}
        self.assertEqual(changed, {K.FRAME_CALL + K.TEXT_BIAS, K.PICK_CALL + K.TEXT_BIAS, 0x74 + 16, 0x74 + 20})
        self.assertIn(K.MAGIC, out[len(boot):])
        with self.assertRaises(ValueError):
            K.patch_boot(out)                            # applied twice

    def test_calls_are_relocated_jals(self):
        # the words the patch retargets: R_MIPS_26 against the text segment
        self.assertEqual(K.jal_word(K.FRAME_PART), 0x0C05331C)
        self.assertEqual(K.jal_word(K.FIND), 0x0C056326)


if __name__ == '__main__':
    unittest.main()
