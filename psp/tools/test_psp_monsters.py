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


class TableTests(unittest.TestCase):
    def test_table_loads_and_encodes(self):
        names = pm.load_names()
        self.assertEqual(names['ゴーレム'], 'Golem')
        for en in names.values():
            en.encode('cp932')


if __name__ == '__main__':
    unittest.main()
