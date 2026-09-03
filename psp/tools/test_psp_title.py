"""Run: python3 -B -m unittest discover -s psp/tools -p 'test_psp_title.py'"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'ps2', 'menu'))
import psp_title as P
import psp_fpb
import title_credit as T
from test_title_credit import make_strip

class OffsetsPack(unittest.TestCase):
    def test_round_trip_with_padding(self):
        blobs = [psp_fpb.compress(bytes([k]) * (100 + k)) for k in range(8)]
        pak = P.build_pak(blobs)
        parsed = P.parse_pak(pak)
        self.assertEqual([b for _, b in parsed], blobs)
        self.assertEqual(P.build_pak([b for _, b in parsed]), pak)
        self.assertTrue(all(o % 4 == 0 for o, _ in parsed))

class PatchPak(unittest.TestCase):
    def test_only_the_strip_changes(self):
        strip = make_strip(fill_rows=(6, 22))
        blobs = [psp_fpb.compress(bytes([k]) * 300) for k in range(8)]
        blobs[1] = psp_fpb.compress(strip)
        pak = P.build_pak(blobs)
        out, new_strip, info = P.patch_pak(pak, 'Green Gel Patch v0.1.0')
        members = P.parse_pak(out)
        self.assertEqual(len(members), 8)
        for k, (_, b) in enumerate(members):
            if k != 1:
                self.assertEqual(b, blobs[k])
        self.assertEqual(psp_fpb.decompress(members[1][1]), new_strip)
        self.assertEqual(T.rows_below_band(new_strip), T.rows_below_band(strip))
        self.assertLessEqual(info['right'], 128 - T.RIGHT_MARGIN)

    def test_label_for(self):
        self.assertEqual(P.label_for('v0.1.1'), 'Green Gel Patch v0.1.1')
        self.assertEqual(P.label_for(None, 'Custom'), 'Custom')
        with self.assertRaises(T.TitleError):
            P.label_for(None, None)

if __name__ == '__main__':
    unittest.main()
