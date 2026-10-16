"""Run: python -B -m unittest discover -s psp/tools -p test_psp_worldmap.py -v

Synthetic SCED scripts and sizes packs plus the real psp_worldmap.tsv, no
game image needed."""
import collections
import re
import struct
import unittest

import psp_text
import psp_worldmap as w

TAG = re.compile(r'<[^>]+>')


def sced(strings):
    """SCED with one F8 text reference per string (code at 12, text after)."""
    text = bytearray(b'\0')
    addrs = []
    for s in strings:
        addrs.append(len(text))
        text += psp_text.encode_record(s.split('\n'))
    code = b''.join(b'\xF8' + struct.pack('<H', a) for a in addrs)
    tb = 12 + len(code)
    return b'SCED' + struct.pack('<II', 12, tb) + code + bytes(text)


def records(data):
    return psp_text.extract_sced(data)[0]


class WorldMapTests(unittest.TestCase):
    def test_translates_and_keeps_the_rest(self):
        old = sced(['sx = %d', 'ラグナ遺跡', 'クレスタの街'])
        stats = collections.Counter()
        new = w.patch_script(9272, old, {'ラグナ遺跡': 'Laguna Ruins'}, stats)
        self.assertEqual(records(new), ['sx = %d', 'Laguna Ruins', 'クレスタの街'])
        self.assertEqual(len(new) % 4, 0)
        self.assertEqual(stats['translated'], 1)
        self.assertEqual(stats['without English'], 1)
        self.assertIn('クレスタの街', stats['lines'][0])

    def test_bytecode_only_operands_change(self):
        old = sced(['ラグナ遺跡', 'いってらっしゃいませ'])
        new = w.patch_script(9272, old, {'ラグナ遺跡': 'Laguna Ruins',
                                         'いってらっしゃいませ': 'Have a good day.'}, collections.Counter())
        _, tb = struct.unpack_from('<II', old, 4)
        changed = [p for p in range(12, tb) if old[p] != new[p]]
        self.assertTrue(all(old[p - 1] == 0xF8 or old[p - 2] == 0xF8 for p in changed))
        self.assertEqual(new[tb:len(old)], old[tb:])         # Japanese text stays in place

    def test_nothing_to_do(self):
        self.assertIsNone(w.patch_script(9272, sced(['sx = %d']), {}, collections.Counter()))

    def test_pack_round_trip(self):
        kids = [b'\x04' + b'\0' * 7, sced(['ラグナ遺跡']) + b'\0' * 3, b'\x04abc']
        kids[1] = kids[1][:len(kids[1]) - len(kids[1]) % 4]
        pack = w.build_sizes_pack(kids)
        self.assertEqual(w.sizes_pack(pack), kids)
        self.assertEqual(w.script(kids)[0], 1)
        with self.assertRaises(ValueError):
            w.script([kids[0], kids[2]])


class TableTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        with open(w.TSV, encoding='utf-8') as f:
            for line in f:
                if line.startswith('#'):
                    continue
                self.rows.append(line.rstrip('\n').split('\t'))

    def test_rows_have_a_source(self):
        sources = {'ps2-menu', 'ps2-scenario', 'psp-supplement', 'translated'}
        for row in self.rows:
            self.assertEqual(len(row), 3, row)
            self.assertIn(row[2], sources, row)
        self.assertEqual(len({r[0] for r in self.rows}), len(self.rows))

    def test_every_row_encodes(self):
        for jp, en, _ in self.rows:
            psp_text.encode_record(w.unesc(en).split('\n'))
            self.assertIsNone(psp_text.JP.search(en.replace('★', '')), en)

    def test_control_codes_match_the_japanese(self):
        for jp, en, _ in self.rows:
            self.assertEqual(collections.Counter(TAG.findall(jp)), collections.Counter(TAG.findall(en)), jp)
            self.assertEqual(re.match(r'(<(?:03|size):[0-9A-F]{8}>)*', jp).group(),
                             re.match(r'(<(?:03|size):[0-9A-F]{8}>)*', en).group(), jp)

    def test_map_labels_use_the_full_names(self):
        table = w.load_table()
        self.assertEqual(table['ラグナ遺跡'], 'Laguna Ruins')
        self.assertEqual(table['クレスタの街'], 'Cresta')
        self.assertEqual(table['神のたまご'], 'Atamoni Ovum')


if __name__ == '__main__':
    unittest.main()
