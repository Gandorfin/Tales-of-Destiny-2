"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_battle_subs.py'

battle_subs.py: the frame hook appended to the battle module, the text
member added to 00017.pak3, and the subtitle table."""
import csv, os, struct, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_subs as B
import lzss
import pak3


def fake_container(module_size=0x5368C):
    """Three compressed members like 00017.pak3; member 0 has the frame call."""
    module = bytearray(module_size)
    struct.pack_into('<I', module, B.HOOK, B.jal(B.FRAME))
    others = [bytes(range(256)) * 4, b'\x11' * 999]
    return pak3.build([lzss.pack(bytes(module), 3)] + [lzss.pack(o, 3) for o in others]), others


def row(vid, speaker, english):
    return {'voice_id': str(vid), 'member': str(7253 + vid), 'speaker': speaker,
            'seconds': '1.0', 'japanese': '', 'english': english}


class Machine:
    """Just enough of a MIPS CPU to run the hook: the instructions it uses,
    delay slots, and stubs for the functions it calls."""
    RETURN = 0xFFFFFFF0

    def __init__(self, stubs):
        self.mem, self.stubs = {}, stubs
        self.r = [0] * 32

    def read(self, a, n, signed=False):
        return int.from_bytes(bytes(self.mem.get(a + i, 0) for i in range(n)), 'little', signed=signed)

    def write(self, a, n, v):
        for i, x in enumerate((v & ((1 << 8 * n) - 1)).to_bytes(n, 'little')):
            self.mem[a + i] = x

    def string(self, a):
        out = bytearray()
        while self.mem.get(a, 0):
            out.append(self.mem[a])
            a += 1
        return out.decode()

    def load(self, a, blob):
        for i, x in enumerate(blob):
            self.mem[a + i] = x

    def step(self, pc):
        """Execute one instruction; returns (branch target or None, link register or None)."""
        r, w = self.r, self.read(pc, 4)
        op, rs, rt, rd, sa, fn = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31, w & 63
        imm = (w & 0xFFFF) - 0x10000 if w & 0x8000 else w & 0xFFFF
        rel = (pc + 4 + (imm << 2)) & 0xFFFFFFFF
        out = (None, None)
        if op == 0:
            if fn == 0x21: r[rd] = (r[rs] + r[rt]) & 0xFFFFFFFF
            elif fn == 0x23: r[rd] = (r[rs] - r[rt]) & 0xFFFFFFFF
            elif fn == 0x00: r[rd] = (r[rt] << sa) & 0xFFFFFFFF
            elif fn == 0x02: r[rd] = r[rt] >> sa
            elif fn == 0x08: out = (r[rs], None)
            elif fn == 0x09: out = (r[rs], rd)
            else: raise ValueError('function %#x at %#x' % (fn, pc))
        elif op == 3: out = ((pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2), 31)
        elif op == 1 and rt == 0x11: out = (rel, 31) if r[rs] < 0x80000000 else (None, 31)
        elif op == 4: out = (rel if r[rs] == r[rt] else None, None)
        elif op == 5: out = (rel if r[rs] != r[rt] else None, None)
        elif op == 6: out = (rel if r[rs] == 0 or r[rs] >= 0x80000000 else None, None)
        elif op == 9: r[rt] = (r[rs] + imm) & 0xFFFFFFFF
        elif op == 11: r[rt] = int(r[rs] < (imm & 0xFFFFFFFF))
        elif op == 12: r[rt] = r[rs] & (w & 0xFFFF)
        elif op == 13: r[rt] = r[rs] | (w & 0xFFFF)
        elif op == 15: r[rt] = (w & 0xFFFF) << 16
        elif op in (32, 33, 35, 36, 37, 55):
            n, signed = {32: (1, 1), 33: (2, 1), 35: (4, 0), 36: (1, 0), 37: (2, 0), 55: (8, 0)}[op]
            r[rt] = self.read((r[rs] + imm) & 0xFFFFFFFF, n, bool(signed)) & 0xFFFFFFFF
        elif op in (40, 41, 43, 63):
            self.write((r[rs] + imm) & 0xFFFFFFFF, {40: 1, 41: 2, 43: 4, 63: 8}[op], r[rt])
        else:
            raise ValueError('opcode %#x at %#x' % (op, pc))
        r[0] = 0
        return out

    def call(self, pc, limit=50000):
        """Run from pc until the code returns to the caller."""
        self.r[31] = self.RETURN
        for _ in range(limit):
            if pc == self.RETURN:
                return
            if pc in self.stubs:
                self.stubs[pc](self.r)
                pc = self.r[31]
                continue
            target, link = self.step(pc)
            if link is None and target is None and not self._is_branch(pc):
                pc += 4
                continue
            ret = pc + 8
            self.step(pc + 4)                      # delay slot
            if link is not None:
                self.r[link] = ret
            pc = target if target is not None else ret
        raise RuntimeError('the code did not return')

    def _is_branch(self, pc):
        w = self.read(pc, 4)
        op, rt, fn = w >> 26, (w >> 16) & 31, w & 63
        return op in (1, 3, 4, 5, 6) or (op == 0 and fn in (8, 9))


def battle(machine, party, enemies, voices):
    """Globals and actors: `party` and `enemies` are lists of character
    indexes (None for an enemy); the enemies start at party slot 4.
    voices: {slot: voice id}."""
    actors = 0x2FD280
    g = B.GLOBALS
    machine.write(g + 0x160, 4, actors)
    machine.write(g + 0x164, 4, actors + 4 * B.ACTOR_SIZE)
    machine.write(g + 0x195, 1, len(party))
    machine.write(g + 0x196, 1, len(enemies))
    for slot, who in list(enumerate(party)) + [(4 + i, None) for i in range(len(enemies))]:
        a = actors + slot * B.ACTOR_SIZE
        machine.write(a + B.CHARACTER, 1, who or 0)
        machine.write(a + B.ENEMY, 1, 1 if who is None else 0)
    for slot, vid in voices.items():
        machine.write(actors + slot * B.ACTOR_SIZE + B.VOICE, 2, vid)


class Container(unittest.TestCase):
    def test_patch_and_repeat(self):
        data, others = fake_container()
        rows = [row(82, 'Kyle', 'We did it!'), row(83, 'Kyle', '')]
        out, info = B.patch_container(data, rows)
        members = [b for _, b in pak3.parse(out)]
        self.assertEqual(len(members), 4)
        self.assertEqual([lzss.unpack(m) for m in members[1:3]], others)
        module = lzss.unpack(members[0])
        self.assertEqual(struct.unpack_from('<I', module, B.HOOK)[0], B.jal(info['code_at']))
        self.assertEqual(info['code_at'], B.BASE + 0x53690)
        self.assertLessEqual(info['module_end'], B.HEAP)
        self.assertEqual(module[-12:-4], B.TRAILER)
        self.assertTrue(B.is_data(members[3]))
        self.assertEqual(info['lines'], 1)
        # a second run replaces code and text instead of stacking them
        again, info2 = B.patch_container(out, [row(82, 'Kyle', 'Changed.')])
        members2 = [b for _, b in pak3.parse(again)]
        self.assertEqual(len(members2), 4)
        self.assertEqual(len(lzss.unpack(members2[0])), len(module))
        self.assertIn(b'Kyle: Changed.\0', members2[3])
        self.assertNotIn(b'We did it', members2[3])

    def test_unknown_module_refused(self):
        module = bytearray(0x1000)
        data = pak3.build([lzss.pack(bytes(module), 3), lzss.pack(b'a', 3), lzss.pack(b'b', 3)])
        with self.assertRaises(ValueError):
            B.patch_container(data, [])

    def test_too_big_refused(self):
        data, _ = fake_container(B.HEAP - B.BASE - 64)
        with self.assertRaises(ValueError):
            B.patch_container(data, [])

    def test_data_layout(self):
        """The hook reads 'BSUB' at member offset + 12, six names, entries of
        16 bytes (id, x, dy, block height, string offset from 'BSUB', flags)."""
        blob, n = B.build_data([row(510, 'Harold', 'word ' * 15)])
        self.assertEqual(n, 2)
        self.assertEqual(blob[0], 0)
        self.assertEqual(struct.unpack_from('<I', blob, 1)[0], len(blob) - 9)
        self.assertEqual(blob[12:16], B.MAGIC)
        payload = blob[12:]
        count = struct.unpack_from('<I', payload, 4)[0]
        lines = []
        for k in range(count):
            vid, x, dy, height, off, flags, _ = struct.unpack_from('<HhhhIHH', payload, B.ENTRIES + B.ENTRY_SIZE * k)
            self.assertEqual(flags, 0)
            text = payload[off:payload.index(b'\0', off)].decode()
            self.assertEqual(vid, 510)
            self.assertEqual(height, 2 * B.LINE_H + B.GAP)
            self.assertEqual(x, (B.SCREEN_W - B.ADVANCE * len(text)) // 2)
            lines.append((dy, text))
        self.assertEqual([dy for dy, _ in lines], [B.LINE_H, 0])
        self.assertTrue(lines[0][1].startswith('Harold: word'))

    def test_name_from_game(self):
        """speaker '*': the first line is flagged, the name is not in the text,
        and the line leaves room for the longest name."""
        blob, n = B.build_data([row(549, '*', 'word ' * 12)])
        payload = blob[12:]
        first = struct.unpack_from('<HhhhIHH', payload, B.ENTRIES)
        second = struct.unpack_from('<HhhhIHH', payload, B.ENTRIES + B.ENTRY_SIZE)
        self.assertEqual((first[5], second[5]), (1, 0))
        text = payload[first[4]:payload.index(b'\0', first[4])].decode()
        self.assertTrue(text.startswith('word'))
        self.assertLessEqual(len(text), B.LINE_CHARS - B.NAME_ROOM)
        off, length = struct.unpack_from('<HH', payload, 8 + 4 * 4)
        self.assertEqual(payload[off:off + length], b'Nanaly: ')


class Hook(unittest.TestCase):
    def test_code_shape(self):
        code = B.hook_code(0x302110)
        words = struct.unpack('<%dI' % (len(code) // 4), code)
        self.assertIn(B.jal(B.FRAME), words)
        self.assertIn(B.jal(B.TEXT), words)
        self.assertEqual(words[-2], B.JR_RA)
        self.assertLess(len(code), 0x280)

    def run_hook(self, party, enemies, voices, rows):
        """Run the hook on a fake battle; returns the strings drawn, in order."""
        drawn, frames = [], []
        m = Machine({B.FRAME: lambda r: frames.append(1),
                     B.TEXT: lambda r: drawn.append((m.string(r[6]), r[4], r[5]))})
        blob, _ = B.build_data(rows)
        pak = 0x1000000
        container = pak3.build([b'a', b'b', b'c', blob])
        m.load(pak, container)
        m.write(B.PAK_POINTER, 4, pak)
        battle(m, party, enemies, voices)
        origin = 0x302110
        m.load(origin, B.hook_code(origin))
        m.r[29] = 0x1F00000
        m.call(origin)
        self.assertEqual(frames, [1])
        return drawn

    def test_hook_party_and_enemies(self):
        rows = [row(82, '*', 'We did it!'), row(700, '', 'Boss line.'), row(5, '*', '')]
        # party of two: the enemy sits in slot 4, not slot 2
        drawn = self.run_hook([0, 2], [None], {0: 82, 4: 700}, rows)
        self.assertEqual([d[0] for d in drawn], ['Kyle: ', 'We did it!', 'Boss line.'])
        # the enemy block stacks above the party block
        self.assertLess(drawn[2][2], drawn[1][2])
        # silent actors and lines without English draw nothing
        self.assertEqual(self.run_hook([0, 2, 1], [None, None], {1: 5}, rows), [])

    def test_hi_lo(self):
        for v in (0x2FA000, 0x234600, 0x42555342):
            hi, lo = B.hi_lo(v)
            self.assertEqual(((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF, v)


class Table(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(B.wrap('a b c', 3), ['a b', 'c'])
        self.assertEqual(B.wrap(''), [])
        self.assertEqual(B.wrap('Did you see?|No!'), ['Did you see?', 'No!'])

    def test_problems(self):
        self.assertEqual(B.problems([row(4, 'Kyle', 'Fine, really!')]), [])
        self.assertTrue(B.problems([row(4, 'Kyle', 'Bad [char]')]))
        self.assertTrue(B.problems([row(4, 'Kyle', 'x'), row(4, 'Kyle', 'y')]))
        self.assertTrue(B.problems([row(4, 'Kyle', 'word ' * 60)]))

    def test_shipped_table(self):
        rows = B.read_table()
        self.assertEqual(B.problems(rows), [])
        ids = [int(r['voice_id']) for r in rows]
        self.assertEqual(ids, sorted(ids))
        for r in rows:
            self.assertEqual(int(r['member']), B.member_for(int(r['voice_id'])))

    def test_member_map(self):
        self.assertEqual(B.member_for(82), 7335)
        self.assertEqual(B.member_for(516), 7185)
        self.assertEqual(B.member_for(588), 7769)
        self.assertEqual(B.member_for(864), 8054)
        self.assertIsNone(B.member_for(3))


if __name__ == '__main__':
    unittest.main()
