"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_refine_lens.py'

The refine screen's lens line and the LZSS copies of the menu modules."""
import os, struct, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import refine_lens as R
import patch_menu_text


class RefineLens(unittest.TestCase):
    """06802.md1 0xE1C loads the 2008 format "A%d,B%d/%3d" (0x669E);
    refine_lens.apply points it at the translated one at 0x63A0."""

    def module(self):
        d = bytearray(R.OLD + 32)
        struct.pack_into('<L', d, R.ADDIU, 0x2465219E)        # the retail word
        d[R.OLD:R.OLD + 12] = b'A%d,B%d/%3d\x00'
        d[R.NEW:R.NEW + len(R.TEXT)] = R.TEXT
        return d

    def test_retail_word_is_the_2008_format(self):
        self.assertEqual(R.BASE + R.OLD, 0x2A219E)

    def test_pointer_moves_once(self):
        d = self.module()
        before = bytes(d)
        self.assertEqual(R.apply(d), (1, 0))
        self.assertEqual(struct.unpack_from('<L', d, R.ADDIU)[0], 0x24651EA0)
        self.assertEqual([i for i in range(len(d)) if d[i] != before[i]],
                         [R.ADDIU, R.ADDIU + 1])
        after = bytes(d)
        self.assertEqual(R.apply(d), (0, 1))
        self.assertEqual(bytes(d), after)

    def test_untranslated_slot_is_refused(self):
        d = self.module()
        d[R.NEW:R.NEW + 12] = b'A%d,B%d/%3d\x00'
        with self.assertRaises(ValueError):
            R.apply(d)

    def test_unknown_instruction_is_refused(self):
        d = self.module()
        struct.pack_into('<L', d, R.ADDIU, 0x24650000)
        with self.assertRaises(ValueError):
            R.apply(d)


class PackedTwins(unittest.TestCase):
    def test_every_menu_module_has_its_copy(self):
        self.assertEqual(len(patch_menu_text.PACKED_TWINS), 19)
        self.assertEqual(patch_menu_text.PACKED_TWINS['06821.md1'], '06802.md1')
        self.assertEqual(patch_menu_text.PACKED_TWINS['06835.md1'], '06816.md1')


if __name__ == '__main__':
    unittest.main()
