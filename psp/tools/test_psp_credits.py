"""PSP staff roll overlay: run from psp/tools, python -m unittest test_psp_credits"""
import unittest

import psp_credits as C


class CreditsTests(unittest.TestCase):
    def test_overlay_is_generated_from_the_table(self):
        text, count = C.render()
        self.assertEqual(open(C.OUT, encoding='utf-8').read(), text)
        self.assertGreater(count, 700)

    def test_every_row_is_translated_or_kept(self):
        for row in C.read_rows():
            self.assertTrue(row['english'])
            if row['english'] != 'KEEP':
                self.assertEqual(len(C.segments(row)), len(C.texts(row)), row['id'])


if __name__ == '__main__':
    unittest.main()
