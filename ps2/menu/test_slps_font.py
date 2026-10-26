"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_slps_font.py'

Synthetic executable only, no game files needed."""
import os, struct, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slps_font as F
import lzss


def make_font(cells=()):
    """A TM2@ font texture like the game's: one 16-colour palette, 128x512 4bpp.
    `cells` are filled with a fixed pseudo-random pattern, like real glyphs
    that compress poorly; the rest stays empty."""
    import random
    w, h = F.TEX_W, F.TEX_H
    idx = bytearray(w * h)
    rnd = random.Random(7)
    for c in cells:
        x0, y0 = F.cell_origin(c)
        for y in range(F.CELL_H):
            for x in range(F.CELL_W):
                idx[(y0 + y) * w + x0 + x] = rnd.randrange(16)
    body = bytearray(w * h // 2)
    for i in range(0, w * h, 2):
        body[i // 2] = idx[i] | (idx[i + 1] << 4)
    pal = b"".join(bytes((v, v, v, 255 if v else 0)) for v in range(16))
    head = F.MAGIC + bytes([1, 1, 1, 0]) + b"\x00" * 8
    palblk = struct.pack("<IIIHH", 16 + len(pal), 0, 0, 8, 2) + pal
    imgblk = struct.pack("<IIIHH", 16 + len(body), 0x14, 0, w, h) + bytes(body)
    return head + palblk + imgblk


def make_slps(font_cells=tuple(range(0x00, 0x4F)), room=None):
    d = bytearray(F.FONT_OFF + 0x6000)
    packed = lzss.pack(make_font(font_cells), 3)
    room = room or len(packed) + 64
    d[F.FONT_OFF:F.FONT_OFF + len(packed)] = packed
    d[F.FONT_OFF + len(packed):F.FONT_OFF + room] = b"\0" * (room - len(packed))
    d[F.FONT_OFF + room:F.FONT_OFF + room + 4] = b"\x06\0\0\0"      # unrelated data after the room
    table = bytes(range(0x60))
    d[F.MAP_OFF:F.MAP_OFF + 0x60] = table
    d[F.MAP_OFF + 0x26 - 0x20] = 0xC3
    d[F.MAP_OFF + 0x7E - 0x20] = 0xD2
    return bytes(d)


class Glyphs(unittest.TestCase):
    def test_art_is_well_formed(self):
        for cell, (ch, art) in F.GLYPHS.items():
            self.assertEqual(len(art), F.CELL_H, ch)
            self.assertTrue(all(len(r) == F.CELL_W for r in art), ch)
            self.assertTrue(any('#' in r for r in art), ch)
            self.assertFalse(any(r[0] == '#' or r[-1] == '#' for r in art), ch)   # room for the outline

    def test_rendered_has_ink_and_outline(self):
        px = F.rendered(F.GLYPHS[0x4B][1])
        flat = [v for row in px for v in row]
        self.assertIn(F.INK, flat)
        self.assertIn(F.OUTLINE, flat)
        self.assertEqual(sum(1 for v in flat if v == F.INK) + sum(1 for v in flat if v == F.EDGE),
                         sum(r.count('#') for r in F.GLYPHS[0x4B][1]))


def cells_of(d, *cells):
    tex = lzss.unpack(F.packed_blob(d))
    base, w, h = F.image_block(tex)
    return [F.read_cell(tex, base, w, c) for c in cells]


class Patch(unittest.TestCase):
    def setUp(self):
        # let the synthetic font's cell 03 stand in for the retail middle dot
        self.saved_dot = dict(F.BASE_DOT)
        F.BASE_DOT[0x03] = F.cell_digest(cells_of(make_slps(), 0x03)[0])

    def tearDown(self):
        F.BASE_DOT.clear()
        F.BASE_DOT.update(self.saved_dot)

    def test_apply_paints_and_remaps(self):
        src = make_slps()
        self.assertEqual(F.state(src), (False, False))
        new, changes = F.apply(src)
        self.assertEqual(len(new), len(src))
        self.assertEqual(len(changes), 7)
        self.assertEqual(F.state(new), (True, True))
        self.assertEqual(new[F.MAP_OFF + 6], 0x4B)
        self.assertEqual(new[F.MAP_OFF + 0x5E], 0x4C)
        self.assertEqual(new[F.MAP_OFF + 7], 0x03)          # "'"
        self.assertEqual(new[F.MAP_OFF + 2], src[F.MAP_OFF + 2])   # '"' untouched
        # nothing outside the font stream and the three table bytes changed
        n = struct.unpack_from("<I", src, F.FONT_OFF + 1)[0] + 9
        changed = [i for i in range(len(src)) if src[i] != new[i]]
        table = (F.MAP_OFF + 6, F.MAP_OFF + 7, F.MAP_OFF + 0x5E)
        self.assertTrue(all(F.FONT_OFF <= i < F.FONT_OFF + n or i in table for i in changed))
        tex = lzss.unpack(F.packed_blob(new))
        base, w, h = F.image_block(tex)
        for cell, (ch, art) in F.GLYPHS.items():
            self.assertEqual(F.read_cell(tex, base, w, cell), F.rendered(art), ch)
        # the apostrophe cell now holds the quote of cell 09
        self.assertEqual(F.read_cell(tex, base, w, 0x03), cells_of(src, 0x09)[0])
        # the cells next door are untouched
        before = lzss.unpack(F.packed_blob(src))
        for cell in (0x02, 0x04, 0x4A, 0x4D, 0x4F):
            self.assertEqual(F.read_cell(tex, base, w, cell), F.read_cell(before, base, w, cell))

    def test_custom_apostrophe_is_kept(self):
        # a custom font already drew its own glyph in cell 03: no copy
        F.BASE_DOT[0x03] = '0' * 16
        src = make_slps()
        new, changes = F.apply(src)
        self.assertFalse(any("copied" in c for c in changes))
        self.assertEqual(cells_of(new, 0x03), cells_of(src, 0x03))
        self.assertEqual(new[F.MAP_OFF + 7], 0x03)
        self.assertEqual(F.glyph_state(new), 'custom')

    def test_glyph_state_tells_drawn_custom_and_base_apart(self):
        new, _ = F.apply(make_slps())
        self.assertEqual(F.glyph_state(new), 'drawn')
        # the middle dot still in cell 03 counts as the base font
        self.assertEqual(F.glyph_state(make_slps()), 'base')
        # a custom font (e.g. inserted with patch_font_iso.py) redraws the cells
        F.BASE_DOT[0x03] = '0' * 16
        self.assertEqual(F.glyph_state(make_slps()), 'custom')
        # the 2008 quote/star cells are recognised by their fingerprints:
        # pretend this synthetic font's cell 4C is the 2008 glyph
        import hashlib
        src = make_slps()
        tex = lzss.unpack(F.packed_blob(src))
        base, w, h = F.image_block(tex)
        cell = bytes(v for row in F.read_cell(tex, base, w, 0x4C) for v in row)
        saved = dict(F.BASE_CELLS)
        try:
            F.BASE_CELLS[0x4C] = hashlib.sha1(cell).hexdigest()[:16]
            self.assertEqual(F.glyph_state(src), 'base')
        finally:
            F.BASE_CELLS.clear()
            F.BASE_CELLS.update(saved)

    def test_idempotent(self):
        new, _ = F.apply(make_slps())
        again, changes = F.apply(new)
        self.assertEqual(changes, [])
        self.assertEqual(again, new)

    def test_refuses_to_grow(self):
        # an all-empty texture packs to a few hundred bytes; the glyphs would not fit
        with self.assertRaises(F.FontError) as cm:
            F.apply(make_slps(font_cells=()))
        self.assertIn("grew", str(cm.exception))

    def test_rejects_foreign_data(self):
        d = bytearray(make_slps())
        d[F.FONT_OFF] = 0x55
        with self.assertRaises(F.FontError):
            F.apply(bytes(d))


if __name__ == "__main__":
    unittest.main()
