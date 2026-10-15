"""Run: python -B -m unittest discover -s psp/tools -p test_psp_jpscan.py -v

Synthetic data only, no ISO needed."""
import csv
import os
import struct
import tempfile
import unittest

import psp_jpscan as js
import psp_text as pt

WORD = 'こんにちは'
OTHER = 'ありがとう'


def enc(text):
    return pt.encode_line(text)


def plaus():
    return js.Plausible([WORD, OTHER, 'こんばんは', 'さようなら'])


def script(code, text):
    return b'SCED' + struct.pack('<II', 12, 12 + len(code)) + code + text


def pak(members):
    return pt.pak_pack(members)


class DecodeTests(unittest.TestCase):
    def test_decode_round_trip(self):
        self.assertEqual(js.decode(enc(WORD) + b'\0', 0), WORD)

    def test_scan_finds_nul_bounded_string(self):
        data = b'\x10\x20\x30\x00' + enc(WORD) + b'\0' + b'\xff' * 8
        hits = js.scan_strings(data, plaus(), 2)
        self.assertEqual([(h[0], h[2], h[3]) for h in hits], [(4, 'tbl', WORD)])

    def test_scan_rejects_halfwidth_noise(self):
        data = b'\x00\xb1\xb2\xb3' + enc('でで') + b'\0'
        self.assertEqual(js.scan_strings(data, plaus(), 2), [])


class ContainerTests(unittest.TestCase):
    def test_pak_and_deflate_leaf_paths(self):
        inner = pt.deflate(b'LEAF' + enc(WORD) + b'\0')
        tree = pt.deflate(pak([b'RAW0' * 4, inner]))
        paths = dict(js.leaves(tree, '00001'))
        self.assertEqual(sorted(paths), ['00001/z/p0', '00001/z/p1/z'])
        self.assertTrue(paths['00001/z/p1/z'].startswith(b'LEAF'))

    def test_sizes_pack_with_lzss_child(self):
        text = b'LEAF' + enc(WORD) + b'\0' + b'padding text ' * 4
        kids = [js.lzss.pack(text, 3), b'RAW1' * 5]
        blob = struct.pack('<I', len(kids)) + b''.join(struct.pack('<I', len(k)) for k in kids) + b''.join(kids)
        paths = dict(js.leaves(blob, '06333'))
        self.assertEqual(sorted(paths), ['06333/n0/l', '06333/n1'])
        self.assertEqual(paths['06333/n0/l'], text)

    def test_offsets_pack_with_deflate_child(self):
        kids = [pt.deflate(b'LEAF' + enc(WORD) + b'\0'), b'RAW1' * 4]
        head = 4 + 4 * len(kids)
        blob = struct.pack('<III', 2, head, head + len(kids[0])) + b''.join(kids)
        paths = dict(js.leaves(blob, '00002'))
        self.assertEqual(sorted(paths), ['00002/o0/z', '00002/o1'])

    def test_lzss_stream_alone(self):
        text = b'SFM_' + enc(OTHER) * 6 + b'\0'
        self.assertEqual(dict(js.leaves(js.lzss.pack(text, 1), 'x')), {'x/l': text})

    def test_plain_tables_are_not_packs(self):
        # a size table whose children are all uncompressed is plain data
        blob = struct.pack('<III', 2, 8, 8) + b'A' * 16
        self.assertEqual(list(js.leaves(blob, 'x')), [('x', blob)])
        # a fake LZSS header whose lengths do not fit the leaf
        fake = b'\x03' + struct.pack('<II', 500, 1000) + b'\x00' * 40
        self.assertEqual(list(js.leaves(fake, 'y')), [('y', fake)])


class ReferenceTests(unittest.TestCase):
    def compare(self, retail, patched):
        occs, info = [], []
        js.compare_leaf('00001/z/p1', retail, patched, plaus(), 2, occs, info, 'skit')
        return occs

    def test_unchanged_target_is_live_japanese(self):
        r = script(bytes.fromhex('f8 01 00 c0 f1'), b'\0' + enc(WORD) + b'\0')
        occs = self.compare(r, r)
        self.assertEqual([(o.status, o.text) for o in occs], [('live_jp', WORD)])

    def test_redirected_target_is_translated(self):
        jp = b'\0' + enc(WORD) + b'\0'
        r = script(bytes.fromhex('f8 01 00 c0 f1'), jp)
        new = len(jp)
        p = script(bytes.fromhex('f8') + struct.pack('<H', new) + bytes.fromhex('c0 f1'), jp + b'Hello\0')
        occs = self.compare(r, p)
        self.assertEqual([(o.status, o.patched) for o in occs], [('translated', 'Hello')])


def sfm(strings, target=None):
    """SFM module: one `02 0c 03 00 <u32>` push per string; target overrides
    the pushed offset of the first string (a moved string)."""
    data = bytearray(0x20)
    rels = []
    for text in strings:
        rels.append(len(data))
        data += text + b'\0'
    while len(data) % 4:
        data.append(0)
    if target is not None:
        rels[0] = target
    code = b''.join(b'\x02\x0c\x03\x00' + struct.pack('<I', r) for r in rels) + b'\0\0'
    head = struct.pack('<4s7L', b'SFM_', 0x3FC, 0x20 + len(code) + len(data), 0x20 + len(code),
                       len(data), 0x20, 0x20 + len(code), 0)
    return head + code + bytes(data)


class SfmTests(unittest.TestCase):
    def compare(self, retail, patched):
        occs, info = [], []
        js.compare_leaf('06348/z', retail, patched, plaus(), 2, occs, info, 'other')
        return [(o.status, o.text, o.patched) for o in occs]

    def test_untouched_quiz_string_is_live(self):
        r = sfm([enc(WORD), enc(OTHER)])
        self.assertEqual(sorted(self.compare(r, r)), [('live_jp', OTHER, ''), ('live_jp', WORD, '')])

    def test_moved_quiz_string_is_translated(self):
        strings = [enc(WORD), enc(OTHER)]
        r = sfm(strings)
        moved = 0x20 + len(strings[0]) + len(strings[1]) + 2     # English stored after them
        p = sfm(strings + [b'Hello'], target=moved)
        self.assertIn(('translated', WORD, 'Hello'), self.compare(r, p))
        self.assertIn(('live_jp', OTHER, ''), self.compare(r, p))


class GroupingTests(unittest.TestCase):
    def test_missed_copy_and_duplicates(self):
        occs = [js.Occ('BOOT', 'boot', 0x100, 'tbl', WORD, 'translated', '0x10:ptr0', 'Hello'),
                js.Occ('00002/z', 'other:data', 0x40, 'tbl', WORD, 'jp'),
                js.Occ('00003/z', 'other:data', 0x80, 'tbl', WORD, 'jp')]
        with tempfile.TemporaryDirectory() as out:
            rows = js.report(occs, [], {}, out, 'r', 'p')
            self.assertEqual(rows[0]['category'], 'missed_copy')
            self.assertEqual(rows[0]['english_in_build'], 'Hello')
            with open(os.path.join(out, 'duplicates.tsv'), encoding='utf-8') as f:
                dup = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual((dup[0]['label'], dup[0]['state']), ('triplicate', 'partly_patched'))

    def test_partly_patched_leaf_cluster(self):
        info = [('00001', 'other:member', 64, 'aa', 'changed'), ('00002', 'other:member', 64, 'aa', 'same')]
        with tempfile.TemporaryDirectory() as out:
            rows = js.write_leaf_duplicates(info, out)
        self.assertEqual(rows[0]['state'], 'partially_patched')

    def test_shared_string_table(self):
        texts = [WORD, OTHER, 'こんばんは', 'さようなら']
        occs = [js.Occ('A', 'other:data', 0x10 * i, 'tbl', t, 'translated' if i < 2 else 'jp')
                for i, t in enumerate(texts)]
        occs += [js.Occ('B', 'other:data', 0x20 * i, 'tbl', t, 'jp') for i, t in enumerate(texts)]
        with tempfile.TemporaryDirectory() as out:
            rows = js.write_table_duplicates(occs, out)
        self.assertEqual([(r['run'], r['state']) for r in rows], [(4, 'partly_patched')])


if __name__ == '__main__':
    unittest.main()
