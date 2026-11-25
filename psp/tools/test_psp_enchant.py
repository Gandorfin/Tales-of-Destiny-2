"""Tests for psp_enchant.py (no game files needed)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psp_enchant  # noqa: E402
import psp_latin_font  # noqa: E402
import psp_vwf  # noqa: E402

GLYPHS = psp_latin_font.load()['glyphs1']


class EnchantRowTests(unittest.TestCase):
    def test_every_name_pads_to_the_same_width(self):
        for name in ('Boost', 'Critical', 'Increase Accuracy', 'Penetrate Elemental', 'Thievery'):
            width, pad = psp_enchant.padding(name, GLYPHS)
            rest = 0
            if b'\x05' in pad:                   # <size:N> ' ' <size:100>: one small space
                self.assertEqual(pad[-11:-6], bytes([5, pad[-10], 0, 0, 0]))
                self.assertEqual(pad[-6:], b' \x05\x00\x01\x00\x00')
                rest = pad[-10] // 32
                pad = pad[:-11]
            self.assertEqual(pad, b' ' * len(pad))
            spaces = len(pad)
            self.assertEqual(width + spaces * psp_enchant.SPACE_PX + rest, psp_enchant.NAME_PX, name)

    def test_names_in_the_table_fit(self):
        self.assertEqual(psp_enchant.check_names(glyphs=GLYPHS), [])

    def test_too_long_name_is_reported(self):
        table = {k: 'Increase Accuracy' for k in psp_enchant.ENCHANT_KEYS}
        table[psp_enchant.ENCHANT_KEYS[0]] = 'Penetrate Elemental Attack'
        errs = psp_enchant.check_names(table, GLYPHS)
        self.assertEqual(len(errs), 1)
        self.assertIn('Penetrate Elemental Attack', errs[0])

    def test_cursor_columns_follow_the_digits(self):
        table = psp_enchant.cursor_table()
        self.assertEqual(table[0], table[1])
        # per level one VWF space (8 of 23 px) and one full-width digit, plus
        # the retail cursor's own drift (464 per level for 1.5 cells of 304)
        unit = psp_enchant.UNIT
        want = unit * (8 / 23 + 1) + (psp_enchant.RETAIL_CURSOR[2] - psp_enchant.RETAIL_CURSOR[1] - unit * 1.5)
        for i in range(1, 4):
            self.assertAlmostEqual(table[i + 1] - table[i], want, delta=1)

    def test_hook_reaches_back_without_new_relocations(self):
        code, labels = psp_enchant.hook_code(0x89D940, bytes(1024))
        self.assertEqual(labels['row'], 0x89D940)
        self.assertEqual(code[-1024:], bytes(1024))
        words = dict(psp_enchant.site_words(labels['row']))
        self.assertEqual(sorted(words), [psp_enchant.SITE + 4 * i for i in range(5)])
        lui, addiu = words[psp_enchant.SITE], words[psp_enchant.SITE + 4]
        target = ((lui & 0xFFFF) << 16) + (((addiu & 0xFFFF) ^ 0x8000) - 0x8000) + psp_enchant.S4_VADDR
        self.assertEqual(target, labels['row'])

    def test_lower_block_hook_jumps_back(self):
        code, labels = psp_enchant.lower_code(0x89DE00)
        words = struct.unpack('<%dI' % (len(code) // 4), code)
        here = labels['here']
        lui, addiu = words[(here - 0x89DE00) // 4], words[(here - 0x89DE00) // 4 + 1]
        back = ((lui & 0xFFFF) << 16) + (((addiu & 0xFFFF) ^ 0x8000) - 0x8000) + here
        self.assertEqual(back & 0xFFFFFFFF, psp_enchant.LOWER_BACK)
        self.assertEqual(psp_enchant.jump_word(psp_enchant.LOWER_BACK), 0x08044931)   # retail word


class BoldMeasureTests(unittest.TestCase):
    def test_font2_measure_uses_bold_widths_only_with_the_table(self):
        _, plain = psp_vwf.hooks(0x894B00, bytes(1024), bold_widths=bytes(640), ticker=True)
        self.assertNotIn('measure_bold', plain)
        _, labels = psp_vwf.hooks(0x894B00, bytes(1024), bold_widths=bytes(640), ticker=True,
                                  bold_table=0x8945C0)
        self.assertIn('measure_bold', labels)
        self.assertEqual(set(dict(psp_vwf.call_sites(labels))), set(dict(psp_vwf.call_sites(plain))))


if __name__ == '__main__':
    unittest.main()
