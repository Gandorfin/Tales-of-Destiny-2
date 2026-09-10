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


class Patch(unittest.TestCase):
    def test_apply_paints_and_remaps(self):
        src = make_slps()
        self.assertEqual(F.state(src), (False, False))
        new, changes = F.apply(src)
        self.assertEqual(len(new), len(src))
        self.assertEqual(len(changes), 5)
        self.assertEqual(F.state(new), (True, True))
        self.assertEqual(new[F.MAP_OFF + 6], 0x4B)
        self.assertEqual(new[F.MAP_OFF + 0x5E], 0x4C)
        # nothing outside the font stream and the two table bytes changed
        n = struct.unpack_from("<I", src, F.FONT_OFF + 1)[0] + 9
        changed = [i for i in range(len(src)) if src[i] != new[i]]
        self.assertTrue(all(F.FONT_OFF <= i < F.FONT_OFF + n or i in (F.MAP_OFF + 6, F.MAP_OFF + 0x5E) for i in changed))
        tex = lzss.unpack(F.packed_blob(new))
        base, w, h = F.image_block(tex)
        for cell, (ch, art) in F.GLYPHS.items():
            self.assertEqual(F.read_cell(tex, base, w, cell), F.rendered(art), ch)
        # the cells next door are untouched
        before = lzss.unpack(F.packed_blob(src))
        for cell in (0x4A, 0x4D, 0x4F):
            self.assertEqual(F.read_cell(tex, base, w, cell), F.read_cell(before, base, w, cell))

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
