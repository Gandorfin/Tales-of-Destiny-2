"""PSP font tests using synthetic assets; Pillow + pycdlib required for tests.

python -m unittest discover -s psp/tools -p test_patch_font_iso.py
"""
import contextlib
import hashlib
import io
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from PIL import Image
import pycdlib
import patch_font_iso as F


def fixture():
    font = (bytes(range(256)) * ((F.FONT_SIZE + 255) // 256))[:F.FONT_SIZE]
    capacity = 8192
    blob, _ = F.pack_font(font, capacity)
    glyphs = bytes.fromhex("8140814381448145") + bytes(5112)
    tail = b"KEEP ALL OTHER ARCHIVE MEMBERS"
    archive = blob + bytes(capacity - len(blob)) + glyphs + bytes(1024)
    end = len(archive)
    archive += tail + bytes(2048 - len(tail))
    table = [capacity - len(blob), capacity | 1024,
             end | (2048 - len(tail))]
    table += [len(archive)] * ((F.TABLE_END - F.TABLE_START) // 4 - len(table))
    boot = bytearray(F.TABLE_END + 1024)
    boot[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", boot, 18, 8)
    struct.pack_into("<%dI" % len(table), boot, F.TABLE_START, *table)
    boot[100:120] = b"KEEP FONT MAPPING!!!"
    keys = b"DISC_ID\0"
    sfo = struct.pack("<4s4I", b"\0PSF", 0x101, 36, 44, 1)
    sfo += struct.pack("<HHIII", 0, 0x204, 10, 12, 0) + keys + b"ULJS00097\0\0\0"
    return bytes(boot), archive, sfo, font


def make_iso(path, boot, archive, sfo, encrypted=False):
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3)
    for folder in ("/PSP_GAME", "/PSP_GAME/SYSDIR", "/PSP_GAME/USRDIR"):
        iso.add_directory(iso_path=folder)
    eboot = b"~PSP" + bytes(len(boot) + 60) if encrypted else boot
    streams = []
    entries = {F.BOOT: boot, F.EBOOT: eboot, F.ARCHIVE: archive,
               "/PSP_GAME/PARAM.SFO": sfo,
               "/PSP_GAME/USRDIR/MOVIE.BIN": b"KEEP HARDSUBS"}
    for name, data in entries.items():
        stream = io.BytesIO(data)
        streams.append(stream)
        iso.add_fp(stream, len(data), iso_path=name + ";1")
    iso.write(str(path))
    iso.close()
    return hashlib.sha256(eboot).hexdigest()


class Codec(unittest.TestCase):
    def test_swizzle_coordinates_and_low_nibble_first(self):
        indices = bytearray(F.WIDTH * F.HEIGHT)
        indices[0:2] = b"\x02\x0d"
        indices[F.WIDTH] = 7
        indices[32] = 6
        indices[8 * F.WIDTH] = 9
        data = F.indices_font(indices)
        self.assertEqual(data[0], 0xd2)
        self.assertEqual(data[16], 7)
        self.assertEqual(data[128], 6)
        self.assertEqual(data[1024], 9)
        self.assertEqual(F.font_indices(data), bytes(indices))

    def test_empty_block_padding_is_a_complete_deflate_stream(self):
        data = bytes(F.FONT_SIZE)
        blob, compressed = F.pack_font(data, 299008)
        self.assertLess(compressed, 2048)
        self.assertTrue(0 <= 299008 - len(blob) < 2048)
        self.assertEqual(F.unpack_font(blob), data)
        decoder = zlib.decompressobj(-15)
        self.assertEqual(decoder.decompress(blob[9:]), data)
        self.assertTrue(decoder.eof)
        self.assertFalse(decoder.unused_data)

    def test_corrupt_stream_and_overflow_rejected(self):
        blob, _ = F.pack_font(bytes(F.FONT_SIZE), 8192)
        for data in (blob[:-1], blob + b"x", b"\0" + blob[1:]):
            with self.subTest(data=data[:10]), self.assertRaises(F.FontError):
                F.unpack_font(data)
        rng = random.Random(12)
        with self.assertRaisesRegex(F.FontError, "compresses to"):
            F.pack_font(rng.randbytes(F.FONT_SIZE), 8192)


class Workflow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.iso = self.root / "source.iso"
        self.png = self.root / "font.png"
        self.output = self.root / "output.iso"
        self.boot, self.archive, self.sfo, self.font = fixture()
        make_iso(self.iso, self.boot, self.archive, self.sfo)
        F.write_png(self.png, F.font_indices(self.font))

    def edit(self):
        with Image.open(self.png) as image:
            image.load()
            image.putpixel((0, 0), 15)
            image.save(self.png, bits=4)

    def test_export_reimport_identical_and_noop_iso(self):
        context = F.read_iso(self.iso)
        indices = F.png_indices(self.png)
        self.assertEqual(F.font_plan(context, indices)[0], [])
        with contextlib.redirect_stdout(io.StringIO()):
            F.patch_iso(self.iso, self.png, self.output)
        self.assertEqual(self.iso.read_bytes(), self.output.read_bytes())

    def test_edited_iso_preserves_all_other_bytes_and_tables(self):
        self.edit()
        before = self.iso.read_bytes()
        context = F.read_iso(self.iso)
        with contextlib.redirect_stdout(io.StringIO()):
            F.patch_iso(self.iso, self.png, self.output)
        result = F.read_iso(self.output)
        self.assertEqual(self.iso.read_bytes(), before)
        self.assertEqual(result.font, F.indices_font(F.png_indices(self.png)))
        self.assertEqual(result.boot[:F.TABLE_START], context.boot[:F.TABLE_START])
        self.assertEqual(result.boot[F.TABLE_START + 4:], context.boot[F.TABLE_START + 4:])
        self.assertEqual(result.boot, result.eboot)
        self.assertEqual(result.files, context.files)
        patches, _, _, _ = F.font_plan(context, F.png_indices(self.png))
        F.verify_copy(self.iso, self.output, patches)

    def test_retail_eboot_uses_decrypted_disc_copy(self):
        self.iso.unlink()
        digest = make_iso(self.iso, self.boot, self.archive, self.sfo, encrypted=True)
        self.edit()
        with mock.patch.object(F, "RETAIL_EBOOT_SHA256", digest):
            before = F.read_iso(self.iso)
            with contextlib.redirect_stdout(io.StringIO()):
                F.patch_iso(self.iso, self.png, self.output)
        after = F.read_iso(self.output)
        self.assertFalse(after.encrypted)
        self.assertEqual(after.boot, after.eboot)
        self.assertEqual(after.files[F.EBOOT].size, len(self.boot))
        self.assertEqual(after.files[F.EBOOT].offset, before.files[F.EBOOT].offset)
        self.assertEqual(self.output.stat().st_size, self.iso.stat().st_size)

    def test_palette_reordering_uses_pixel_colours_not_indices(self):
        with Image.open(self.png) as image:
            indices = image.tobytes()
        reordered = Image.frombytes("P", (F.WIDTH, F.HEIGHT), bytes(15 - b for b in indices))
        reordered.putpalette([i * 17 for i in reversed(range(16)) for _ in range(3)])
        reordered.save(self.png, bits=4)
        self.assertEqual(F.png_indices(self.png), indices)

    def test_prepare_alpha_grayscale_and_explicit_levels(self):
        image = Image.new("RGBA", (F.WIDTH, F.HEIGHT), (255, 255, 255, 0))
        image.putpixel((1, 0), (255, 255, 255, 128))
        image.putpixel((2, 0), (255, 255, 255, 255))
        image.save(self.png)
        with self.assertRaisesRegex(F.FontError, "prepare"):
            F.png_indices(self.png)
        indices = F.png_indices(self.png, prepare=True)
        self.assertEqual(indices[:3], bytes((0, 8, 15)))
        self.assertEqual(set(F.png_indices(self.png, prepare=True, levels=2)), {0, 15})
        ready = self.root / "ready.png"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(F.main(["prepare", str(self.iso), str(self.png), str(ready)]), 0)
        self.assertEqual(F.png_indices(ready), indices)

    def test_wrong_dimensions_and_animation_rejected(self):
        Image.new("L", (128, 512)).save(self.png)
        with self.assertRaisesRegex(F.FontError, "256x4400"):
            F.png_indices(self.png)
        image = Image.new("RGBA", (F.WIDTH, F.HEIGHT))
        second = image.copy()
        second.putpixel((0, 0), (255, 255, 255, 255))
        image.save(self.png, save_all=True, append_images=[second], duration=100)
        with self.assertRaisesRegex(F.FontError, "Animated"):
            F.png_indices(self.png)

    def test_dry_run_overwrite_and_failure_cleanup(self):
        self.edit()
        with contextlib.redirect_stdout(io.StringIO()):
            F.patch_iso(self.iso, self.png, check=True)
        self.assertFalse(self.output.exists())
        with self.assertRaises(F.FontError):
            F.patch_iso(self.iso, self.png, self.iso)
        with mock.patch.object(F, "verify_copy", side_effect=F.FontError("forced")):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(F.FontError, "forced"):
                F.patch_iso(self.iso, self.png, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("*.partial")), [])
        self.output.write_bytes(b"existing")
        with self.assertRaises(F.FontError):
            F.patch_iso(self.iso, self.png, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_wrong_disc_and_disagreeing_tables_rejected(self):
        self.iso.unlink()
        make_iso(self.iso, self.boot, self.archive, self.sfo.replace(b"ULJS00097", b"ULJS99999"))
        with self.assertRaisesRegex(F.FontError, "ULJS-00097"):
            F.read_iso(self.iso)
        self.iso.unlink()
        make_iso(self.iso, self.boot, self.archive, self.sfo)
        context = F.read_iso(self.iso)
        with self.iso.open("r+b") as fp:
            fp.seek(context.files[F.EBOOT].offset + F.TABLE_START)
            word = struct.unpack("<I", fp.read(4))[0]
            fp.seek(-4, 1)
            fp.write(struct.pack("<I", word ^ 1))
        with self.assertRaisesRegex(F.FontError, "disagree"):
            F.read_iso(self.iso)

    def test_nonzero_font_padding_rejected(self):
        context = F.read_iso(self.iso)
        with self.iso.open("r+b") as fp:
            fp.seek(context.files[F.ARCHIVE].offset + len(context.blob))
            fp.write(b"x")
        with self.assertRaisesRegex(F.FontError, "padding"):
            F.read_iso(self.iso)

    def test_output_tampering_is_detected(self):
        self.output.write_bytes(self.iso.read_bytes())
        with self.output.open("r+b") as fp:
            fp.seek(-1, 2)
            fp.write(b"!")
        with self.assertRaisesRegex(F.FontError, "verification"):
            F.verify_copy(self.iso, self.output, [])


if __name__ == "__main__":
    unittest.main()
