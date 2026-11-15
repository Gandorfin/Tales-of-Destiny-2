"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_skit_indicator.py'

skit_indicator.py: the hook code (run on a small MIPS machine against a
fake field), the member added to 00017.pak3 and the SLPS patch."""
import os, struct, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skit_indicator as K
import battle_subs as B
import pak3
from test_battle_subs import Machine as BaseMachine, fake_container, row

MEMBER_AT = 0x01A91800          # where the test puts MAGIC
RAND_AT = 0x01F00000
TITLE_AT = 0x01E00000


class Machine(BaseMachine):
    def step(self, pc):
        w = self.read(pc, 4)
        if w >> 26 == 10:                               # slti
            rs, rt = (w >> 21) & 31, (w >> 16) & 31
            imm = (w & 0xFFFF) - 0x10000 if w & 0x8000 else w & 0xFFFF
            v = self.r[rs] - (1 << 32) if self.r[rs] & 0x80000000 else self.r[rs]
            self.r[rt] = int(v < imm)
            self.r[0] = 0
            return (None, None)
        return super().step(pc)


class Field:
    def __init__(self, candidates=(), pick=None, pad=0x100, lock=False, mode=0, mode6_busy=False, titles=None):
        self.m = m = Machine({})
        self.calls, self.prints = [], []
        self.body, self.labels = K.assemble()
        m.load(MEMBER_AT, self.body)
        m.write(K.LOCK, 1, 0x80 if lock else 0)
        m.write(K.RAND_BLOCK, 4, RAND_AT)
        m.write(RAND_AT + K.RAND_STATE, 4, 0x12345678)
        titles = titles or {n: 'Skit %d' % n for n in range(1, 40)}
        for i, (n, t) in enumerate(titles.items()):
            m.load(TITLE_AT + 0x40 * i, t.encode() + b'\0')
            m.write(K.TITLES + 4 * n, 4, TITLE_AT + 0x40 * i)
        self.candidates, self.pick = list(candidates), pick
        self.state = {}

        def find(r):
            self.calls.append('find')
            for i, n in enumerate(self.candidates):
                m.write(K.CANDIDATES + 2 * i, 2, n)
            m.write(K.CANDIDATE_COUNT, 2, len(self.candidates))
            m.write(RAND_AT + K.RAND_STATE, 4, 0xDEAD)
            r[2] = self.pick if self.pick is not None else (self.candidates[0] if self.candidates else 0)

        def pad_read(r):
            self.calls.append(('pad', r[4]))
            r[2] = pad

        def rgba(r):
            self.state['rgb'] = (r[5], r[6], r[7])

        def pos(r):
            self.state['pos'] = (r[5] & 0xFFFF, r[6] & 0xFFFF)

        def gs(r):
            self.calls.append(('gs', r[4], r[5]))

        def text(r):
            self.prints.append((m.string(r[4]), self.state['rgb'], self.state['pos'], r[5]))
        m.stubs = {K.PAD: pad_read, K.FIND: find,
                   K.MODE: lambda r: r.__setitem__(2, mode),
                   K.MODE6_BUSY: lambda r: r.__setitem__(2, 1 if mode6_busy else 0),
                   K.GS_SET: gs, K.SET_BLOCK: lambda r: None,
                   K.SET_SCALE: lambda r: self.state.__setitem__('scale', (r[5], r[6])),
                   K.SET_RGBA: rgba, K.SET_POS: pos, K.PRINT: text}

    def run(self, label, a0=0):
        m = self.m
        m.r[29] = 0x01FFF000
        m.r[4] = a0
        for reg in (16, 17, 18, 19, 20, 21, 22, 23, 30):
            m.r[reg] = 0x5000 + reg
        saved = list(m.r)
        m.r[2] = MEMBER_AT + self.labels[label]        # the trampoline's v0
        self.prints.clear()
        m.call(MEMBER_AT + self.labels[label])
        for reg in (16, 17, 18, 19, 20, 21, 22, 23, 29, 30):
            assert m.r[reg] == saved[reg], 'register %d not restored' % reg
        return m.r[2]

    def frame(self):
        return self.run('frame')

    def select(self):
        return self.run('pick')

    def shown(self):
        return self.m.read(MEMBER_AT + self.labels['data'], 2, True)

    def lines(self):
        """The coloured (last) copy of each string."""
        return [p for p in self.prints if p[1] != (0, 0, 0)]


class FrameHook(unittest.TestCase):
    def test_pad_value_goes_back(self):
        f = Field(pad=0x1234)
        self.assertEqual(f.frame(), 0x1234)
        self.assertEqual(f.calls[0], ('pad', 0))       # with the caller's a0

    def test_label_and_title(self):
        f = Field([4], titles={4: 'All Set'})
        f.frame()
        (label, lc, lpos, lflags), (title, tc, tpos, _) = f.lines()
        self.assertEqual((label, lc, lflags), ('SELECT', K.YELLOW, K.PRINT_FLAGS))
        self.assertEqual((title, tc), ('All Set', K.WHITE))
        self.assertEqual(lpos, (K.gs_x(K.X), K.gs_y(K.Y)))
        self.assertEqual(tpos, (K.gs_x(K.title_x()), K.gs_y(K.Y)))
        self.assertEqual(f.state['scale'], (K.XSCALE, K.YSCALE))
        # each string: four dark copies around it first
        self.assertEqual(len(f.prints), 10)
        dark = [p for p in f.prints if p[1] == (0, 0, 0)]
        self.assertEqual(sorted(p[2] for p in dark[:4]),
                         sorted((K.gs_x(K.X) + 16 * dx, K.gs_y(K.Y) + 8 * dy) for dx, dy in K.OUTLINE))
        self.assertIn(('gs', K.GS_TEST_1, K.TEST_TEXT), f.calls)

    def test_rand_state_is_kept(self):
        f = Field([4])
        f.frame()
        self.assertIn('find', f.calls)
        self.assertEqual(f.m.read(RAND_AT + K.RAND_STATE, 4), 0x12345678)

    def test_hidden_when_select_would_be_ignored(self):
        for kw in ({'lock': True}, {'mode': 6, 'mode6_busy': True}):
            f = Field([4], **kw)
            f.frame()
            self.assertEqual(f.prints, [], kw)
            self.assertNotIn('find', f.calls, kw)
        f = Field([4], mode=6)
        f.frame()
        self.assertEqual(len(f.lines()), 2)

    def test_no_skit_or_no_title(self):
        for f in (Field([]), Field([7], titles={1: 'One'}), Field([K.TITLE_COUNT])):
            f.frame()
            self.assertEqual(f.prints, [])

    def test_shown_skit_stays(self):
        f = Field([3, 5], pick=5)
        f.frame()
        self.assertEqual(f.lines()[1][0], 'Skit 5')
        f.pick = 3
        f.frame()
        self.assertEqual(f.lines()[1][0], 'Skit 5')
        f.candidates, f.pick = [3], 3
        f.frame()
        self.assertEqual(f.lines()[1][0], 'Skit 3')


class PickHook(unittest.TestCase):
    def test_select_plays_the_shown_skit(self):
        f = Field([3, 5], pick=5)
        f.frame()
        f.pick = 3
        self.assertEqual(f.select(), 5)

    def test_game_pick_otherwise(self):
        f = Field([3, 5], pick=3)
        self.assertEqual(f.select(), 3)
        f.frame()
        f.candidates, f.pick = [5], 5
        self.assertEqual(f.select(), 5)
        f.candidates, f.pick = [], 0
        self.assertEqual(f.select(), 0)


def fake_slps():
    d = bytearray(0x135328)
    struct.pack_into('<I', d, K.PAD_CALL - K.BIAS, B.jal(K.PAD))
    struct.pack_into('<I', d, K.PICK_CALL - K.BIAS, B.jal(K.FIND))
    return bytes(d)


class Files(unittest.TestCase):
    def patched_container(self):
        data, _ = fake_container()
        data, _ = B.patch_container(data, [row(82, 'Kyle', 'We did it!')])
        return data

    def test_container_and_slps(self):
        data = self.patched_container()
        out, index, labels = K.patch_container(data)
        self.assertEqual(index, 4)                     # after the battle subtitle member
        members = [b for _, b in pak3.parse(out)]
        self.assertEqual(len(members), 5)
        self.assertTrue(K.is_ours(members[4]) and B.is_data(members[3]))
        again, index2, _ = K.patch_container(out)    # repeat: replaced, not added
        self.assertEqual((again, index2), (out, 4))
        slps = K.patch_slps(fake_slps(), index, labels)
        ta, tb = K.TRAMP_FILE, K.TRAMP_FILE + K.TRAMP_SIZE
        self.assertEqual(struct.unpack_from('<I', slps, K.PAD_CALL - K.BIAS)[0], B.jal(ta + K.BIAS))
        self.assertEqual(struct.unpack_from('<I', slps, K.PICK_CALL - K.BIAS)[0], B.jal(tb + K.BIAS))
        self.assertEqual(K.patch_slps(slps, index, labels), slps)       # repeat
        base = fake_slps()
        changed = {i // 4 * 4 for i in range(len(slps)) if slps[i] != base[i]}
        # the two calls and the trampolines (their last word, a nop, stays 0)
        self.assertEqual(changed, {K.PAD_CALL - K.BIAS, K.PICK_CALL - K.BIAS}
                         | set(range(ta, ta + 24, 4)) | set(range(tb, tb + 24, 4)))
        # the trampolines land on the entries with v0 = the entry address
        m = Machine({})
        pak_at = 0x0043C600
        m.load(pak_at, out)
        m.write(K.PAK_POINTER, 4, pak_at)
        m.load(ta + K.BIAS, slps[ta:ta + 2 * K.TRAMP_SIZE])
        magic = pak_at + struct.unpack_from('<I', out, 4 + 4 * index)[0] + 12
        self.assertEqual(m.read(magic, 4).to_bytes(4, 'little'), K.MAGIC)
        for tramp, label in ((ta, 'frame'), (tb, 'pick')):
            reached = []
            m.stubs = {magic + labels[label]: lambda r: reached.append(r[2])}
            m.r[31] = 0x11C290
            m.call(tramp + K.BIAS)
            self.assertEqual(reached, [magic + labels[label]])

    def test_battle_subs_rerun_keeps_the_member(self):
        out, _, _ = K.patch_container(self.patched_container())
        again, _ = B.patch_container(out, [row(83, 'Kyle', 'Again!')])
        members = [b for _, b in pak3.parse(again)]
        self.assertTrue(K.is_ours(members[4]))
        # the wrong order is refused: the member would move
        alone, _, _ = K.patch_container(fake_container()[0])
        with self.assertRaises(ValueError):
            B.patch_container(alone, [row(82, 'Kyle', 'We did it!')])

    def test_used_pool_tail_is_refused(self):
        d = bytearray(fake_slps())
        d[K.TRAMP_FILE + 40] = 0x41
        with self.assertRaises(ValueError):
            K.patch_slps(bytes(d), 4, K.assemble()[1])


if __name__ == '__main__':
    unittest.main()
