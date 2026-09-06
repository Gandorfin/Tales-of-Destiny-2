"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_title_credit.py'

Synthetic textures only, no game files needed."""
import os, struct, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import title_credit as T
import title_glyphs as G
import pak3, lzss

PALETTE = ([(0, 0, 0, 0)] + [(0, 0, 0, a) for a in (36, 72, 107)] + [(2, 1, 1, 128)]
           + [(v, v, v, 128) for v in (40, 78, 111, 131, 150, 166, 192, 207, 221, 234, 255)])

def make_strip(w=128, h=32, fill_rows=()):
    """A TM2@ 16-colour 4bpp texture; `fill_rows` are painted with index 15."""
    idx = [0] * (w * h)
    for y in fill_rows:
        for x in range(w):
            idx[y * w + x] = 15
    body = bytearray(w * h // 2)
    for i in range(0, w * h, 2):
        body[i // 2] = idx[i] | (idx[i + 1] << 4)
    pal = b''.join(bytes(c) for c in PALETTE)
    head = b'TM2@' + bytes([1, 1, 1, 0]) + b'\x00' * 8
    palblk = struct.pack('<IIIHH', 16 + len(pal), 0, 0, 8, 2) + pal
    imgblk = struct.pack('<IIIHH', 16 + len(body), 0x14, 0, w, h) + bytes(body)
    return head + palblk + imgblk

class StripCodec(unittest.TestCase):
    def test_round_trip(self):
        s = make_strip(fill_rows=(3, 20))
        pal, idx, w, h = T.decode_strip(s)
        self.assertEqual((w, h), (128, 32))
        self.assertEqual(pal[15], (255, 255, 255, 128))
        self.assertEqual(idx[3 * w], 15)
        self.assertEqual(T.encode_strip(s, idx), s)

    def test_rejects_other_textures(self):
        with self.assertRaises(T.TitleError):
            T.decode_strip(b'TM2#' + make_strip()[4:])

class DrawLabel(unittest.TestCase):
    def test_clears_first_line_and_keeps_second(self):
        s = make_strip(fill_rows=(5, 20, 30))
        new, info = T.draw_label(s, 'Green Gel Patch v1.1.8', 'psp')
        pal, idx, w, h = T.decode_strip(new)
        self.assertEqual(idx[G.BAND * w:], T.rows_below_band(s))         # line two untouched
        row5 = idx[5 * w:6 * w]
        self.assertTrue(all(v != 15 for v in row5[info['right'] + 2:]))   # old fill gone
        self.assertTrue(any(v == 15 for v in row5))                        # text drawn in white
        self.assertLessEqual(info['right'], w - T.RIGHT_MARGIN)

    def test_ps2_style_is_wider_than_psp(self):
        s = make_strip(w=384)
        _, ps2 = T.draw_label(s, 'Green Gel Patch v1.1.8', 'ps2')
        _, psp = T.draw_label(s, 'Green Gel Patch v1.1.8', 'psp')
        self.assertGreater(ps2['right'], psp['right'])

    def test_too_wide_raises(self):
        with self.assertRaises(T.TitleError):
            T.draw_label(make_strip(), 'Green Gel Patch v10.10.10', 'psp')

    def test_unknown_glyph_raises(self):
        with self.assertRaises(T.TitleError):
            T.draw_label(make_strip(), 'v1 é', 'psp')

    def test_idempotent(self):
        s = make_strip(fill_rows=(2,))
        once, _ = T.draw_label(s, 'Green Gel Patch v1.1.8', 'psp')
        twice, _ = T.draw_label(once, 'Green Gel Patch v1.1.8', 'psp')
        self.assertEqual(once, twice)

class Ps2Pack(unittest.TestCase):
    def test_patch_pak3_changes_only_member_one(self):
        strip = make_strip(w=384, fill_rows=(4, 24))
        others = [lzss.pack(bytes([k]) * 300) for k in range(8)]
        others[1] = lzss.pack(strip)
        container = pak3.build(others)
        out, new_strip, info = T.patch_pak3(container, 'Green Gel Patch v1.1.8')
        members = pak3.parse(out)
        self.assertEqual(len(members), 8)
        for k, (_, b) in enumerate(members):
            if k != 1:
                self.assertEqual(b, others[k])
        self.assertEqual(lzss.unpack(members[1][1]), new_strip)
        self.assertEqual(T.rows_below_band(new_strip), T.rows_below_band(strip))

    def test_wrong_size_rejected(self):
        container = pak3.build([lzss.pack(b'x' * 64), lzss.pack(make_strip(w=128))])
        with self.assertRaises(T.TitleError):
            T.patch_pak3(container, 'x')

if __name__ == '__main__':
    unittest.main()
