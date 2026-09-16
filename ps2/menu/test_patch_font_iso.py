"""Standalone font patcher regression tests; no game assets required.

Run with Pillow and pycdlib installed:
    python -m unittest discover -s ps2/menu -p test_patch_font_iso.py
"""
import contextlib
import io
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest import mock

from PIL import Image
import pycdlib
import patch_font_iso as F


def texture():
    palettes = bytearray()
    positions = (0, 8, 0x80000, 0x80008, 0x10, 0x18, 0x80010, 0x80018, 0x100000, 0x100008)
    for position in positions:
        palettes += struct.pack("<IIIHH", 80, 0, position, 8, 2)
        palettes += bytes(v for i in range(16) for v in (i * 17, i * 17, i * 17, 128 if i else 0))
    pixels = bytes((i % 256 for i in range(WIDTH_BYTES)))
    return (b"TM2@" + bytes((1, 10, 1, 0)) + bytes(8) + palettes
            + struct.pack("<IIIHH", 32784, 0x14, 0xA00, F.WIDTH, F.HEIGHT) + pixels)


WIDTH_BYTES = F.WIDTH * F.HEIGHT // 2


def executable():
    data = bytearray(F.SLPS_SIZE)
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", data, 18, 8)
    blob = F.compress(texture())
    data[F.FONT_OFF:F.FONT_OFF + len(blob)] = blob
    data[F.FONT_OFF + F.FONT_ROOM:F.FONT_OFF + F.FONT_ROOM + 8] = b"KEEPTHIS"
    return bytes(data)


def make_iso(path, exe):
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, udf="2.60")
    config = b"BOOT2 = cdrom0:\\SLPS_251.72;1\r\n"
    buffers = [io.BytesIO(exe), io.BytesIO(config), io.BytesIO(b"KEEP MOVIES")]
    iso.add_fp(buffers[0], len(exe), iso_path="/SLPS_251.72;1", udf_path="/SLPS_251.72")
    iso.add_fp(buffers[1], len(config), iso_path="/SYSTEM.CNF;1", udf_path="/SYSTEM.CNF")
    iso.add_fp(buffers[2], 11, iso_path="/MOVIE.FPB;1", udf_path="/MOVIE.FPB")
    iso.write(str(path))
    iso.close()


class Codec(unittest.TestCase):
    def test_runs_dictionary_overlap_and_random_roundtrip(self):
        rng = random.Random(17)
        cases = [bytes(F.TEXTURE_SIZE),
                 (b"abc" * 12000)[:F.TEXTURE_SIZE],
                 bytes(rng.randrange(256) for _ in range(F.TEXTURE_SIZE)),
                 (bytes(range(256)) * 132)[:F.TEXTURE_SIZE]]
        for data in cases:
            with self.subTest(prefix=data[:6]):
                self.assertEqual(F.decompress(F.compress(data)), data)

    def test_rejects_truncated_and_overlong_stream(self):
        blob = F.compress(texture())
        for damaged in (blob[:-1], blob + b"X"):
            with self.assertRaises(F.FontError):
                F.decompress(damaged)

    def test_rejects_wrong_texture_header_and_palette(self):
        for offset in (0, 16, 0x330):
            data = bytearray(texture())
            data[offset] ^= 1
            with self.assertRaises(F.FontError):
                F.texture_parts(data)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.iso = self.root / "input.iso"
        self.png = self.root / "font.png"
        self.output = self.root / "output.iso"
        self.exe = executable()
        make_iso(self.iso, self.exe)
        with contextlib.redirect_stdout(io.StringIO()):
            F.export_png(self.iso, self.png)

    def save_variant(self, change):
        with Image.open(self.png) as im:
            edited = change(im.copy())
        edited.save(self.png, format="PNG")

    def test_export_reimport_is_identical(self):
        new, tex, packed, pixels, room = F.build_font(self.exe, self.png)
        self.assertEqual(new, self.exe)
        self.assertEqual(tex, texture())
        self.assertEqual(pixels, 0)
        self.assertEqual(room, F.FONT_ROOM)

    def test_edited_font_iso_only_changes_reserved_bytes(self):
        before = self.iso.read_bytes()
        def change(im):
            im.putpixel((12, 16), 15)
            return im
        self.save_variant(change)
        with contextlib.redirect_stdout(io.StringIO()):
            F.patch_iso(self.iso, self.png, self.output)
        offset, new, udf = F.read_iso(self.output)
        self.assertTrue(udf)
        self.assertEqual(self.iso.read_bytes(), before)
        after = self.output.read_bytes()
        self.assertEqual(len(after), len(before))
        a, b = offset + F.FONT_OFF, offset + F.FONT_OFF + F.FONT_ROOM
        self.assertEqual(after[:a], before[:a])
        self.assertEqual(after[b:], before[b:])
        self.assertNotEqual(after[a:b], before[a:b])
        _, tex, base, _, _ = F.font_from_executable(new)
        self.assertEqual(tex[:base], texture()[:base])  # all ten palettes preserved
        self.assertEqual(tex[base + (16 * 128 + 12) // 2] & 15, 15)

    def test_rgba_export_is_accepted_without_palette_reduction(self):
        self.save_variant(lambda im: im.convert("RGBA"))
        self.assertEqual(F.build_font(self.exe, self.png)[0], self.exe)

    def test_prepare_repairs_wrong_transparency_index(self):
        source = self.root / "wrong-transparency.png"
        ready = self.root / "ready.png"
        with Image.open(self.png) as template:
            image = Image.new("P", template.size, 4)
            image.putpalette(template.getpalette())
        image.putpixel((1, 0), 1)
        image.save(source, format="PNG", bits=4, transparency=4)
        with contextlib.redirect_stdout(io.StringIO()):
            F.prepare_png(self.iso, source, ready)
        with Image.open(ready) as prepared:
            self.assertEqual(prepared.mode, "P")
            self.assertEqual(prepared.getpixel((0, 0)), 0)
            self.assertEqual(prepared.getpixel((1, 0)), 1)
            self.assertEqual(prepared.info["transparency"],
                             bytes([0] + [128] * 15))
        self.assertLessEqual(F.build_font(self.exe, ready)[2], F.FONT_ROOM)
        with self.assertRaisesRegex(F.FontError, "already exists"):
            F.prepare_png(self.iso, source, ready)

    def test_prepare_reduces_noisy_rgba_until_it_fits(self):
        source = self.root / "noisy.png"
        ready = self.root / "ready.png"
        rng = random.Random(91)
        palette = [(i * 17, i * 17, i * 17, 255) for i in range(16)]
        pixels = [(0, 0, 0, 0) if rng.randrange(8) == 0
                  else palette[rng.randrange(1, 16)]
                  for _ in range(F.WIDTH * F.HEIGHT)]
        image = Image.new("RGBA", (F.WIDTH, F.HEIGHT))
        image.putdata(pixels)
        image.save(source, format="PNG")
        with contextlib.redirect_stdout(io.StringIO()):
            F.prepare_png(self.iso, source, ready)
        with Image.open(ready) as prepared:
            used = set(prepared.tobytes())
            self.assertLess(len(used), 16)
        self.assertLessEqual(F.build_font(self.exe, ready)[2], F.FONT_ROOM)

    def test_invalid_dimensions_palette_index_colour_and_animation(self):
        original = self.png.read_bytes()
        variants = [
            lambda im: im.resize((256, 1024)),
            lambda im: im.convert("RGBA").convert("RGB"),
            lambda im: self.edit_pixel(im, 16),
            lambda im: self.edit_pixel(im.convert("RGBA"), (1, 2, 3, 4)),
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.png.write_bytes(original)
                self.save_variant(variant)
                with self.assertRaises(F.FontError):
                    F.build_font(self.exe, self.png)
        self.png.write_bytes(original)
        with Image.open(self.png) as im:
            rgba = im.convert("RGBA")
        second = rgba.copy()
        second.putpixel((1, 1), (255, 255, 255, 128))
        rgba.save(self.png, save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaises(F.FontError):
            F.build_font(self.exe, self.png)

    @staticmethod
    def edit_pixel(im, value):
        if value == 16:
            palette = im.getpalette()
            im.putpalette(palette + [0] * (768 - len(palette)))
        im.putpixel((0, 0), value)
        return im

    def test_palette_reordering_and_opacity_change_are_rejected(self):
        def change(im):
            palette = im.getpalette()
            palette[3:6] = [12, 34, 56]
            im.putpalette(palette)
            return im
        self.save_variant(change)
        with self.assertRaises(F.FontError):
            F.build_font(self.exe, self.png)

    def test_overflow_rejected_before_iso_creation(self):
        def change(im):
            rng = random.Random(23)
            im.putdata([rng.randrange(16) for _ in range(F.WIDTH * F.HEIGHT)])
            return im
        self.save_variant(change)
        with self.assertRaisesRegex(F.FontError, "compresses to"):
            F.patch_iso(self.iso, self.png, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_and_same_input_rejected(self):
        self.output.write_bytes(b"existing")
        for out in (self.output, self.iso, self.png):
            with self.subTest(out=out), self.assertRaises(F.FontError):
                F.patch_iso(self.iso, self.png, out)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_dry_run_writes_nothing(self):
        with contextlib.redirect_stdout(io.StringIO()):
            F.patch_iso(self.iso, self.png, self.output, dry_run=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("*.partial")), [])

    def test_mismatched_udf_allocation_rejected(self):
        with mock.patch.object(pycdlib.PyCdlib, "get_record",
                               autospec=True, side_effect=self.bad_udf):
            with self.assertRaisesRegex(F.FontError, "share the executable"):
                F.read_iso(self.iso)

    _get_record = staticmethod(pycdlib.PyCdlib.get_record)

    def bad_udf(self, iso, **kwargs):
        rec = self._get_record(iso, **kwargs)
        if "udf_path" in kwargs:
            rec.alloc_descs[0].log_block_num += 1
        return rec

    def test_failure_during_verification_leaves_no_output(self):
        with mock.patch.object(F, "verify_copy", side_effect=F.FontError("forced failure")):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(F.FontError):
                F.patch_iso(self.iso, self.png, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("*.partial")), [])

    def test_nonzero_data_after_stream_is_not_reclaimed(self):
        bad = bytearray(self.exe)
        used = len(F.font_from_executable(self.exe)[0])
        bad[F.FONT_OFF + used] = 1
        with self.assertRaisesRegex(F.FontError, "nonzero"):
            F.font_from_executable(bad)


if __name__ == "__main__":
    unittest.main()
