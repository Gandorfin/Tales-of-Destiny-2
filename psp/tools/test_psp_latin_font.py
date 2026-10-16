"""Tests for psp_latin_font.py: the committed glyph table (no game files)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psp_latin_font as L  # noqa: E402


def ink_rows(gl, threshold=12):
    return [y for y, row in enumerate(gl['rows']) if any(int(v, 16) >= threshold for v in row)]


class GlyphTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = L.load()

    def test_every_printable_ascii_character(self):
        for key, g in (('glyphs1', self.data['font1']), ('glyphs2', self.data['font2'])):
            glyphs = self.data[key]
            self.assertEqual(set(glyphs), {chr(c) for c in range(0x20, 0x7F)})
            for ch, gl in glyphs.items():
                self.assertEqual(len(gl['rows']), g['h'], ch)
                self.assertTrue(all(len(r) == g['w'] for r in gl['rows']), ch)
                self.assertGreater(gl['adv'], 0, ch)

    def test_one_baseline_and_x_height(self):
        """The bug this module fixes: letters bouncing up and down."""
        for key, g in (('glyphs1', self.data['font1']), ('glyphs2', self.data['font2'])):
            glyphs = self.data[key]
            bottoms = {ch: ink_rows(glyphs[ch])[-1] for ch in 'acemnorsuvwxzHEIL'}
            self.assertLessEqual(max(bottoms.values()) - min(bottoms.values()), 1, (key, bottoms))
            tops = {ch: ink_rows(glyphs[ch])[0] for ch in 'acemnorsuvwxz'}
            self.assertLessEqual(max(tops.values()) - min(tops.values()), 1, (key, tops))
            base = max(bottoms.values())
            for ch in 'gpqy':                         # real descenders
                self.assertGreater(ink_rows(glyphs[ch])[-1], base, (key, ch))

    def test_tabular_digits(self):
        for key in ('glyphs1', 'glyphs2'):
            self.assertEqual(len({self.data[key][d]['adv'] for d in '0123456789'}), 1)

    def test_shared_slots_take_the_first_character(self):
        table = bytearray(256)
        table[ord('-')] = table[ord('~')] = table[ord('_')] = 0xD2
        table[ord('A')] = 0x17
        self.assertEqual(L.slot_chars(table), {0xD2: '-', 0x17: 'A'})


if __name__ == '__main__':
    unittest.main()
