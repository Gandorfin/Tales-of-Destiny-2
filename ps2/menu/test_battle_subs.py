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
        self.assertLess(len(code), 0x200)

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
