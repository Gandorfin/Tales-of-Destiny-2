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
        op, fn = w >> 26, w & 63
        rs, rt, rd, sa = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31
        r = self.r
        if op == 0 and fn in (0x25, 0x2B, 0x06, 0x38):      # or, sltu, srlv, dsll (32 bits here)
            if fn == 0x25: r[rd] = r[rs] | r[rt]
            elif fn == 0x2B: r[rd] = int(r[rs] < r[rt])
            elif fn == 0x06: r[rd] = r[rt] >> (r[rs] & 31)
            else: r[rd] = (r[rt] << sa) & 0xFFFFFFFF
            r[0] = 0
            return (None, None)
        if op == 14:                                         # xori
            r[rt] = r[rs] ^ (w & 0xFFFF)
            r[0] = 0
            return (None, None)
        if w >> 26 == 10:                               # slti
            rs, rt = (w >> 21) & 31, (w >> 16) & 31
            imm = (w & 0xFFFF) - 0x10000 if w & 0x8000 else w & 0xFFFF
            v = self.r[rs] - (1 << 32) if self.r[rs] & 0x80000000 else self.r[rs]
            self.r[rt] = int(v < imm)
            self.r[0] = 0
            return (None, None)
        return super().step(pc)


class Field:
    def __init__(self, candidates=(), pick=None, pad=0x100, lock=False, mode=0, mode6_busy=False, titles=None,
                 seen=()):
        self.m = m = Machine({})
        self.calls, self.prints = [], []
        self.body, self.labels = K.assemble()
        m.load(MEMBER_AT, self.body)
        m.write(K.LOCK, 1, 0x80 if lock else 0)
        m.write(K.RAND_BLOCK, 4, RAND_AT)
        m.write(RAND_AT + K.RAND_STATE, 4, 0x12345678)
        titles = titles or {n: 'Skit %d' % n for n in range(1, 40)}
        for i, (n, t) in enumerate(titles.items()):
            m.load(TITLE_AT + 0x40 * i, (t if isinstance(t, bytes) else t.encode()) + b'\0')
            m.write(K.TITLES + 4 * n, 4, TITLE_AT + 0x40 * i)
        for n in seen:
            m.write(K.SEEN + n // 8, 1, m.read(K.SEEN + n // 8, 1) | (1 << (n % 8)))
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
            self.prints.append((m.string(r[4]), self.state['rgb'], self.state['pos'], r[5], self.state['scale']))
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

    def paint(self, entry='early', a1=0x1234):
        """the text layer's exit; returns the GS writes"""
        self.calls.clear()
        self.m.r[5] = a1
        self.run(entry, a0=0x40)
        return [c[1:] for c in self.calls if c[0] == 'gs']

    def shown(self):
        return self.m.read(MEMBER_AT + self.labels['data'] + K.D_SHOWN, 2, True)

    def wanted(self):
        return self.m.read(MEMBER_AT + self.labels['data'] + K.D_WANT, 2)

    def texts(self):
        return [p[0] for p in self.prints]


class FrameHook(unittest.TestCase):
    def test_pad_value_goes_back(self):
        f = Field(pad=0x1234)
        self.assertEqual(f.frame(), 0x1234)
        self.assertEqual(f.calls[0], ('pad', 0))       # with the caller's a0

    def test_frame_only_asks_the_layer(self):
        f = Field([4], titles={4: 'All Set'})
        f.frame()
        self.assertEqual(f.prints, [])                 # nothing drawn in the field pass
        self.assertNotIn('gs', [c[0] for c in f.calls])
        self.assertEqual((f.shown(), f.wanted()), (4, 1))

    def test_rand_state_is_kept(self):
        f = Field([4])
        f.frame()
        self.assertIn('find', f.calls)
        self.assertEqual(f.m.read(RAND_AT + K.RAND_STATE, 4), 0x12345678)

    def test_hidden_when_select_would_be_ignored(self):
        for kw in ({'lock': True}, {'mode': 6, 'mode6_busy': True}):
            f = Field([4], **kw)
            f.frame()
            self.assertEqual(f.wanted(), 0, kw)
            self.assertNotIn('find', f.calls, kw)
        f = Field([4], mode=6)
        f.frame()
        self.assertEqual(f.wanted(), 1)

    def test_no_skit_or_no_title(self):
        for f in (Field([]), Field([7], titles={1: 'One'}), Field([K.TITLE_COUNT])):
            f.frame()
            self.assertEqual(f.wanted(), 0)

    def test_shown_skit_stays(self):
        f = Field([3, 5], pick=5)
        f.frame()
        self.assertEqual(f.shown(), 3)                 # the first unseen one listed
        f.pick = 5
        f.frame()
        self.assertEqual(f.shown(), 3)
        f.candidates, f.pick = [5], 5
        f.frame()
        self.assertEqual(f.shown(), 5)

    def test_seen_skits_are_not_shown(self):
        # pnvnd (1.3.6): after all skits were seen, the last one stayed on
        # screen (the game offers seen skits of some lists again)
        f = Field([3, 5], seen=[3])
        f.frame()
        self.assertEqual(f.shown(), 5)
        f = Field([3, 5], seen=[3, 5])
        f.frame()
        self.assertEqual((f.shown(), f.wanted()), (0, 0))
        f = Field([12], seen=[4, 11, 13, 20])          # other bits of the same bytes
        f.frame()
        self.assertEqual(f.shown(), 12)

    def test_shown_skit_goes_once_seen(self):
        f = Field([3, 5])
        f.frame()
        self.assertEqual(f.shown(), 3)
        f.m.write(K.SEEN, 1, 1 << 3)
        f.frame()
        self.assertEqual(f.shown(), 5)

    def test_nothing_when_the_game_finds_nothing(self):
        f = Field([3, 5])
        f.frame()
        f.pick = 0                                     # stale list, game says none
        f.frame()
        self.assertEqual((f.shown(), f.wanted()), (0, 0))


class Paint(unittest.TestCase):
    def test_label_and_title(self):
        f = Field([4], titles={4: 'All Set'})
        f.frame()
        writes = f.paint()
        (label, lc, lpos, lflags, lscale), (title, tc, tpos, _, tscale) = f.prints
        self.assertEqual((label, lc, lflags, lscale), ('SELECT', K.LABEL_RGB, K.PRINT_FLAGS, K.LABEL_SCALE))
        self.assertEqual((title, tc, tscale), ('All Set', K.WHITE, K.TITLE_SCALE))
        self.assertIn(lpos[1], (K.gs_y(K.LABEL_Y), K.gs_y(K.LABEL_Y) + 8 * K.PRESS))
        self.assertEqual(tpos, (K.gs_x(K.TITLE_X), K.gs_y(K.TITLE_Y)))
        self.assertEqual(f.wanted(), 0)               # asked once, drawn once
        regs = [w[0] for w in writes]
        self.assertEqual(regs[0], K.SCISSOR_1)        # the early exit sets the full scissor
        self.assertIn((K.GS_TEST_1, K.TEST_TEXT), writes)
        self.assertIn((K.GS_ALPHA_1, K.ALPHA_BLEND), writes)
        # the band: sprite from x 0, then the fade strip ending at alpha 0
        i = writes.index((K.GS_PRIM, K.PRIM_SPRITE | K.PRIM_ABE))
        self.assertEqual(writes[i + 1], (K.GS_RGBAQ, K.rgba(K.BG_RGBA[:3], K.BG_RGBA[3])))
        end = K.gs_x(K.TITLE_X + K.BG_PAD + K.TITLE_ADVANCE * len('All Set'))
        self.assertEqual(writes[i + 2], (K.GS_XYZ2, (K.gs_y(K.BG_Y0) << 16) | K.gs_x(0)))
        self.assertEqual(writes[i + 3], (K.GS_XYZ2, (K.gs_y(K.BG_Y1) << 16) | end))
        self.assertEqual(writes[i + 4], (K.GS_PRIM, K.PRIM_TRISTRIP | K.PRIM_IIP | K.PRIM_ABE))
        self.assertEqual(writes[i + 5:i + 7], [(K.GS_XYZ2, (K.gs_y(y) << 16) | end) for y in (K.BG_Y0, K.BG_Y1)])
        self.assertEqual(writes[i + 7], (K.GS_RGBAQ, K.rgba(K.BG_RGBA[:3], 0)))
        self.assertEqual(writes[i + 9], (K.GS_XYZ2, (K.gs_y(K.BG_Y1) << 16) | (end + 16 * K.FADE)))

    def test_button_blinks(self):
        f = Field([4], titles={4: 'All Set'})
        ys = set()
        for _ in range(2 * K.BLINK):
            f.frame()
            f.paint()
            ys.add(f.prints[0][2][1])
        self.assertEqual(ys, {K.gs_y(K.LABEL_Y), K.gs_y(K.LABEL_Y) + 8 * K.PRESS})

    def test_names_in_titles(self):
        # some titles are or hold a character name code (07 n 00 00 00);
        # 1.3.6 printed the code byte as a glyph (pnvnd: "strange glyph")
        f = Field([4, 5], titles={4: b'\x07\x03\x00\x00\x00', 5: b'Hero \x07\x01\x00\x00\x00!'})
        f.frame()
        f.paint()
        self.assertEqual(f.texts()[1], 'Loni')
        f.m.write(K.SEEN, 1, 1 << 4)
        f.frame()
        f.paint()
        self.assertEqual(f.texts()[1], 'Hero Kyle!')

    def test_long_title_is_cut(self):
        f = Field([4], titles={4: 'x' * 50 + '\x07\x05\x00\x00\x00' * 3})
        f.frame()
        f.paint()
        self.assertEqual(f.texts()[1], ('x' * 50 + 'Nanaly' * 2)[:K.BUF_CHARS])

    def test_nothing_unless_asked(self):
        f = Field([4], titles={4: 'All Set'})
        self.assertEqual(f.paint('early'), [])        # no field frame this frame
        self.assertEqual(f.prints, [])
        writes = f.paint('layer', a1=0x777)
        self.assertEqual(writes, [(0x40, 0x777)])      # the game's own scissor call only
        f.frame()
        f.paint('layer', a1=0x777)
        self.assertEqual(f.texts(), ['SELECT', 'All Set'])
        self.assertEqual(f.calls[0], ('gs', 0x40, 0x777))


class PickHook(unittest.TestCase):
    def test_select_plays_the_shown_skit(self):
        f = Field([3, 5], pick=5)
        f.frame()
        self.assertEqual(f.select(), 3)

    def test_game_pick_otherwise(self):
        f = Field([3, 5], pick=3)
        self.assertEqual(f.select(), 3)
        f.frame()
        f.candidates, f.pick = [5], 5
        self.assertEqual(f.select(), 5)
        f.candidates, f.pick = [], 0
        self.assertEqual(f.select(), 0)

    def test_none_when_the_game_finds_none(self):
        f = Field([3, 5], pick=5)
        f.frame()
        f.pick = 0
        self.assertEqual(f.select(), 0)

    def test_seen_shown_skit_gives_the_game_pick(self):
        f = Field([3, 5], pick=5, seen=[3, 5])
        f.frame()
        self.assertEqual(f.select(), 5)               # all seen: the game decides, as before


def fake_slps():
    d = bytearray(0x135328)
    struct.pack_into('<I', d, K.PAD_CALL - K.BIAS, B.jal(K.PAD))
    struct.pack_into('<I', d, K.PICK_CALL - K.BIAS, B.jal(K.FIND))
    struct.pack_into('<I', d, K.LAYER_EXIT - K.BIAS, K.j_word(K.GS_SET))
    struct.pack_into('<I', d, K.EARLY_EXIT - K.BIAS, B.JR_RA)
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
        tr = [K.TRAMP_FILE + i * K.TRAMP_SIZE for i in range(4)]
        self.assertEqual(struct.unpack_from('<I', slps, K.PAD_CALL - K.BIAS)[0], B.jal(tr[0] + K.BIAS))
        self.assertEqual(struct.unpack_from('<I', slps, K.PICK_CALL - K.BIAS)[0], B.jal(tr[1] + K.BIAS))
        self.assertEqual(struct.unpack_from('<I', slps, K.LAYER_EXIT - K.BIAS)[0], K.j_word(tr[2] + K.BIAS))
        self.assertEqual(struct.unpack_from('<I', slps, K.EARLY_EXIT - K.BIAS)[0], K.j_word(tr[3] + K.BIAS))
        self.assertEqual(K.patch_slps(slps, index, labels), slps)       # repeat
        base = fake_slps()
        changed = {i // 4 * 4 for i in range(len(slps)) if slps[i] != base[i]}
        sites = {K.PAD_CALL, K.PICK_CALL, K.LAYER_EXIT, K.EARLY_EXIT}
        # the four sites and the trampolines (their last word, a nop, stays 0)
        self.assertEqual(changed, {x - K.BIAS for x in sites} | {a for t in tr for a in range(t, t + 24, 4)})
        # the trampolines land on the entries with v0 = the entry address
        m = Machine({})
        pak_at = 0x0043C600
        m.load(pak_at, out)
        m.write(K.PAK_POINTER, 4, pak_at)
        m.load(tr[0] + K.BIAS, slps[tr[0]:tr[0] + 4 * K.TRAMP_SIZE])
        magic = pak_at + struct.unpack_from('<I', out, 4 + 4 * index)[0] + 12
        self.assertEqual(m.read(magic, 4).to_bytes(4, 'little'), K.MAGIC)
        for tramp, label in zip(tr, ('frame', 'pick', 'layer', 'early')):
            reached = []
            m.stubs = {magic + labels[label]: lambda r: reached.append(r[2])}
            m.r[31] = 0x11C290
            m.call(tramp + K.BIAS)
            self.assertEqual(reached, [magic + labels[label]])

    def test_136_slps_is_upgraded(self):
        """an executable patched by 1.3.6 (three trampolines) takes the new code"""
        data = self.patched_container()
        out, index, labels = K.patch_container(data)
        d = bytearray(fake_slps())
        tc = K.TRAMP_FILE + 2 * K.TRAMP_SIZE
        d[K.TRAMP_FILE:tc + K.TRAMP_SIZE] = (K.trampoline(index, labels['frame']) + b'\x11' * K.TRAMP_SIZE * 2)
        struct.pack_into('<I', d, K.LAYER_EXIT - K.BIAS, K.j_word(tc + K.BIAS))
        slps = K.patch_slps(bytes(d), index, labels)
        self.assertEqual(slps, K.patch_slps(fake_slps(), index, labels))

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
