"""Run: python -B -m unittest discover -s psp/tools -p test_psp_monsters.py -v

Synthetic leaves only, no game image needed."""
import unittest

import psp_monsters as pm
import psp_text as pt

NAME = 'ゴーレム'
ARTE = 'スフィアスパーク'
NAMES = {NAME: 'Golem', ARTE: 'Sphere Spark'}


def enc(text):
    return pt.encode_line(text)


def stats():
    return {'patched': 0, 'too_long': 0, 'inline_text': 0}


class PatchLeafTests(unittest.TestCase):
    def test_name_field_is_nul_padded(self):
        field = enc(NAME) + b'\0' * (23 - len(enc(NAME))) + b'\x07'
        st = stats()
        new = pm._patch_leaf(b'\x01\x02\x03\x00' + field, NAMES, st)
        self.assertEqual(new[4:4 + 24], b'Golem' + b'\0' * 18 + b'\x07')
        self.assertEqual((st['patched'], st['inline_text']), (1, 0))

    def test_inline_script_text_is_space_padded(self):
        # opcode 0A, argument byte, the string, its NUL, then the next opcode
        code = b'\x08\x04\x13\x00' + b'\x0a\x00' + enc(ARTE) + b'\x00' + b'\x11\x00\x04\x1b'
        st = stats()
        new = pm._patch_leaf(code, NAMES, st)
        slot = len(enc(ARTE))
        self.assertEqual(new[6:6 + slot + 1], b'Sphere Spark'.ljust(slot) + b'\0')
        self.assertEqual(new[6 + slot + 1:], b'\x11\x00\x04\x1b')
        self.assertEqual(len(new), len(code))
        self.assertEqual(st['inline_text'], 1)

    def test_too_long_is_skipped(self):
        st = stats()
        self.assertIsNone(pm._patch_leaf(b'\x00' + enc('デス') + b'\x00', {'デス': 'Death'}, st))
        self.assertEqual(st['too_long'], 1)


class EfdTests(unittest.TestCase):
    """Mystic Arte banners: inline 0A strings with any argument byte in an
    LZSS packed efD script, centred in their slot."""

    def script(self):
        return (b'efD\0' + b'\x08\x04\x13\x00' + b'\x0a\xff' + enc(ARTE) + b'\x00'
                + b'\x11\x00\x04\x1b' + b'\x0a\x07' + enc(NAME) + b'\x00' + b'\x33\x00')

    def test_banner_centred_and_code_kept(self):
        raw = self.script()
        lzss = pm._lzss()
        packed = lzss.pack(raw, 3)
        packed += b'\0' * (-len(packed) % 4)
        st = stats()
        new = pm._walk(packed, NAMES, st)
        self.assertEqual(st['efd'], 1)
        out = lzss.unpack(new)
        self.assertEqual(len(out), len(raw))
        slot = len(enc(ARTE))
        pad = slot - len('Sphere Spark')
        self.assertEqual(out[10:10 + slot + 1],
                         (b' ' * (pad // 2) + b'Sphere Spark').ljust(slot) + b'\0')
        self.assertEqual(out[10 + slot + 1:10 + slot + 5], b'\x11\x00\x04\x1b')
        self.assertIn(b'Golem', out)
        self.assertEqual(out[-2:], b'\x33\x00')

    def test_other_lzss_left_alone(self):
        lzss = pm._lzss()
        packed = lzss.pack(b'XXXX' + b'\x0a\xff' + enc(ARTE) + b'\x00', 3)
        self.assertIsNone(pm._walk(packed, NAMES, stats()))


class TableTests(unittest.TestCase):
    def test_table_loads_and_encodes(self):
        names = pm.load_names()
        self.assertEqual(names['ゴーレム'], 'Golem')
        for en in names.values():
            en.encode('cp932')


if __name__ == '__main__':
    unittest.main()


class TekiListTests(unittest.TestCase):
    """The encounter banner list in member 08331 (PAK child 2, LZSS)."""

    def build_member(self):
        lzss = pm._lzss()
        raw = bytearray(b'TEKI' + bytes(pm.TEKI_COUNT * pm.TEKI_RECORD))
        for i in range(pm.TEKI_COUNT):
            at = 4 + i * pm.TEKI_RECORD
            raw[at:at + pm.TEKI_NAME] = b' ' * pm.TEKI_NAME
        name = enc(NAME)
        raw[4:4 + len(name)] = name
        raw[4 + pm.TEKI_NAME:4 + pm.TEKI_RECORD] = b'\0\x06\0\0'
        long_jp = enc('ゴーレムゴーレムゴーレム')
        raw[4 + pm.TEKI_RECORD:4 + pm.TEKI_RECORD + len(long_jp)] = long_jp
        packed = lzss.pack(bytes(raw), 3)
        packed += b'\0' * ((-len(packed)) % 4)
        return pm._rebuild_pak([b'child0', b'child1', packed]), bytes(raw)

    def test_names_written_space_padded_and_data_kept(self):
        member, raw = self.build_member()
        names = dict(NAMES, **{'ゴーレムゴーレムゴーレム': 'G' * 25})
        st = {}
        new = pm.patch_teki(member, names, st)
        ents = pm._pak_entries(new)
        self.assertEqual(new[ents[0][0]:ents[0][0] + ents[0][1]], b'child0')
        blob = new[ents[2][0]:ents[2][0] + ents[2][1]]
        inl, outl = __import__('struct').unpack_from('<II', blob, 1)
        out = pm._lzss().decode(blob[9:9 + inl], blob[0], outl)
        self.assertEqual(out[4:4 + pm.TEKI_RECORD], b'Golem' + b' ' * 19 + b'\0\x06\0\0')
        self.assertEqual(out[4 + pm.TEKI_RECORD:], raw[4 + pm.TEKI_RECORD:])   # too long: untouched
        self.assertEqual((st['teki_patched'], st['teki_too_long']), (1, 1))

    def test_nothing_to_change_returns_none(self):
        member, _ = self.build_member()
        self.assertIsNone(pm.patch_teki(member, {}, {}))
