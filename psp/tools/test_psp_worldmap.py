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

    def test_english_that_fits_takes_the_japanese_slot(self):
        # クレスタの街 is 12 bytes + NUL, Cresta 6 + NUL: written in place, no growth
        old = sced(['クレスタの街', 'ラグナ遺跡'])
        new = w.patch_script(9272, old, {'クレスタの街': 'Cresta', 'ラグナ遺跡': 'Laguna Ruins Far Away'},
                             collections.Counter())
        _, tb = struct.unpack_from('<II', old, 4)
        self.assertEqual(records(new), ['Cresta', 'Laguna Ruins Far Away'])
        self.assertEqual(new[:tb], old[:tb][:12] + new[12:tb])           # header kept
        self.assertEqual(struct.unpack_from('<H', new, 13)[0], 1)        # pointer kept
        self.assertEqual(new[tb + 1:tb + 14], b'Cresta' + b'\0' * 7)
        # the long one does not fit its 11 byte slot nor the 6 byte tail: appended
        self.assertEqual(len(new), len(old) + 1 + len('Laguna Ruins Far Away') + (-(len(old) + 22) % 4))

    def test_long_english_goes_into_a_free_tail(self):
        old = sced(['いってらっしゃいませ', 'ラグナ遺跡'])        # 20 + NUL, 10 + NUL bytes
        new = w.patch_script(9272, old, {'いってらっしゃいませ': 'Bye.', 'ラグナ遺跡': 'Laguna Ruins'},
                             collections.Counter())
        self.assertEqual(records(new), ['Bye.', 'Laguna Ruins'])
        self.assertEqual(len(new), len(old) + (-len(old) % 4))           # nothing appended

    def test_shared_and_overlapping_slots_are_not_reused(self):
        # two operands on one string, one of them pointing into its middle
        jp = psp_text.encode_record(['クレスタの街'])
        code = b'\xF8\x01\x00' + b'\xF8' + struct.pack('<H', 1 + jp.index(psp_text.encode_line('の街')))
        tb = 12 + len(code)
        old = b'SCED' + struct.pack('<II', 12, tb) + code + b'\0' + jp
        new = w.patch_script(9272, old, {'クレスタの街': 'Cresta'}, collections.Counter())
        read = [psp_text.decode_string(new, tb + struct.unpack_from('<H', new, at)[0]) for at in (13, 16)]
        self.assertEqual(read, ['Cresta', 'の街'])                     # the inner operand keeps its text
        self.assertEqual(new[tb:tb + 1 + len(jp)], old[tb:])             # Japanese bytes untouched

    def test_identical_english_is_stored_once(self):
        old = sced(['ラグナ遺跡です', 'ラグナの遺跡'])
        en = 'The Laguna Ruins, far away'
        new = w.patch_script(9272, old, {'ラグナ遺跡です': en, 'ラグナの遺跡': en}, collections.Counter())
        self.assertEqual(records(new), [en, en])
        self.assertEqual(new.count(en.encode()), 1)

    def test_pack_over_the_game_buffer_is_refused(self):
        self.assertEqual(w.sectors(w.PACK_BUFFER - 0xC0), 0xFD800)
        self.assertGreater(w.sectors(0xFDE6C), w.PACK_BUFFER)            # 09276 of PSP 0.3.5
        self.assertLessEqual(w.sectors(0xFCE30), w.PACK_BUFFER)          # retail 09276

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
