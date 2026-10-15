"""Run: python -B -m unittest discover -s psp/tools -p test_psp_quiz.py -v

Synthetic SFM modules only, no game image needed."""
import collections
import contextlib
import io
import struct
import unittest

import psp_quiz as q
import md1patch
import sfm_text

SAFE = b'\x02\x0c'        # a bytecode word that precedes string pushes
UNSAFE = b'\x44\x44'      # any other word: the reference cannot be proven a pointer


def sfm(strings, prev=SAFE):
    """SFM module with one `03 00 <u32>` push per string; returns (bytes, {text: rel})."""
    data = bytearray(0x20)                  # offsets below 0x20 are never strings
    rels = {}
    for text in strings:
        rels[text] = len(data)
        data += md1patch.encode(text) + b'\0'
    while len(data) % 4:
        data.append(0)
    code = bytearray()
    for text in strings:
        code += prev + b'\x03\x00' + struct.pack('<I', rels[text])
    code += b'\x00\x00'
    start = 0x20
    data_start = start + len(code)
    total = data_start + len(data)
    head = struct.pack('<4s7L', b'SFM_', 0x3FC, total, start + len(code), len(data), start, data_start, 0)
    return bytes(head + code + data), rels


def text_at(data, rel):
    return sfm_text.SFM(data).text_at(rel)[0]


class QuizTests(unittest.TestCase):
    def run_one(self, strings, english, prev=SAFE, index=6348, psp=None):
        data, rels = sfm(strings, prev)
        tables = ({q.ps2_file(index): english}, psp or {})
        stats = collections.Counter()
        return data, rels, q.patch_module('%05d' % index, index, data, tables, stats), stats

    def test_member_mapping(self):
        self.assertEqual(q.ps2_file(6335), '06171.sfm')
        self.assertEqual(q.ps2_file(6365), '06201.sfm')
        self.assertEqual(q.ps2_file(6367), '06202.sfm')
        self.assertEqual(q.ps2_file(6466), '06301.sfm')

    def test_pack_layout(self):
        self.assertIsNone(q.PACKS[6333](2))                # quiz pictures
        self.assertEqual(q.PACKS[6333](3), 6335)
        self.assertEqual(q.PACKS[6334](33), 6365)
        self.assertEqual(q.PACKS[6334](34), 6367)          # no copy of 06366
        self.assertEqual(q.PACKS[6333](133), 6466)
        self.assertEqual(q.PACKS[6366](30), 6365)
        self.assertEqual(q.PACKS[6467](99), 6466)

    def test_sizes_pack_round_trip(self):
        kids = [b'TM2@' + b'x' * 8, q.psp_text.deflate(sfm(['はい'])[0])]
        blob = q.build_sizes_pack(kids)
        self.assertEqual(q.sizes_pack(blob), kids)
        with self.assertRaises(ValueError):
            q.sizes_pack(blob + b'\0')

    def test_fits_in_place(self):
        data, rels, new, stats = self.run_one(['こんにちは'], {'こんにちは': 'Hello'})
        self.assertEqual(len(new), len(data))
        self.assertEqual(text_at(new, rels['こんにちは']), 'Hello')
        self.assertEqual((stats['patched'], stats['relocated']), (1, 0))

    def test_longer_english_is_appended_and_pointer_moved(self):
        data, rels, new, stats = self.run_one(['はい', 'いいえ'], {'はい': 'Yes, absolutely, no doubt about it'})
        self.assertEqual(stats['relocated'], 1)
        self.assertGreater(len(new), len(data))
        strings = {s['text']: rel for rel, s in sfm_text.SFM(new).strings().items()}
        self.assertIn('Yes, absolutely, no doubt about it', strings)
        self.assertNotIn('はい', strings)                 # no reference reaches the Japanese
        self.assertIn('いいえ', strings)                  # untouched neighbour
        self.assertEqual(struct.unpack_from('<I', new, 0x08)[0], len(new))

    def test_pinned_string_never_grows(self):
        data, rels, new, stats = self.run_one(['はい'], {'はい': 'Yes, absolutely'}, prev=UNSAFE)
        self.assertIsNone(new)
        self.assertEqual(stats['overflow'], 1)

    def test_psp_table_wins_and_tilde_is_fullwidth(self):
        data, rels, new, stats = self.run_one(['こんにちは'], {'こんにちは': 'Hi from PS2'},
                                              psp={'こんにちは': 'Hi~'})
        self.assertEqual(text_at(new, rels['こんにちは']), 'Hi～')
        self.assertEqual(stats['from psp'], 1)

    def test_psp_only_glyphs_encode(self):
        # ○ (the quiz's blank) is one of the codes only TBL_PSP.json lists
        data, rels, new, stats = self.run_one(['せいかい'], {'せいかい': 'Corr○ct'})
        at = sfm_text.SFM(new).data_start + rels['せいかい']
        want = md1patch.encode('Corr○ct')
        self.assertEqual(new[at:at + len(want) + 1], want + b'\0')
        self.assertEqual(len(want), 8)

    def test_missing_translation_is_counted(self):
        data, rels, new, stats = self.run_one(['こんにちは'], {})
        self.assertIsNone(new)
        self.assertEqual(stats['untranslated'], 1)

    def test_verify_member(self):
        english = {'はい': 'Yes, absolutely, no doubt about it', 'いいえ': 'No'}
        data, rels, new, stats = self.run_one(['はい', 'いいえ'], english)
        tables = ({q.ps2_file(6348): english}, {})
        checked, problems = q.verify_module('06348', 6348, data, new, tables)
        self.assertEqual((checked, problems), (2, []))
        # a reference that still leads to the Japanese is reported
        checked, problems = q.verify_module('06348', 6348, data, data, tables)
        self.assertEqual(len(problems), 2)
        # so is any other bytecode change
        broken = bytearray(new)
        broken[sfm_text.SFM(new).code_start] ^= 1
        self.assertIn('bytecode changed', q.verify_module('06348', 6348, data, bytes(broken), tables)[1][-1])

    def test_tables_have_no_unencodable_english(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(q.check(), 0, out.getvalue())


if __name__ == '__main__':
    unittest.main()
