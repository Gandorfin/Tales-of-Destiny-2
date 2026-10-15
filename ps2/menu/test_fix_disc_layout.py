"""Tests for fix_disc_layout.py on small synthetic ISO9660 + UDF images.

python -m unittest discover -s ps2/menu -p test_fix_disc_layout.py
(needs pycdlib to build the images)
"""
import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest

import pycdlib
import fix_disc_layout as L

FILES = {'SYSTEM.CNF': b'BOOT2 = cdrom0:\\SLPS_251.72;1\r\n',
         'SLPS_251.72': bytes(range(256)) * 300,
         'FILE.FPB': b'FPB' * 50000}


def build(path):
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1, sys_ident='PLAYSTATION', vol_ident='TOD2', udf='2.60')
    keep = []
    for name, data in FILES.items():
        stream = io.BytesIO(data)
        keep.append(stream)
        iso.add_fp(stream, len(data), iso_path='/' + name + ';1', udf_path='/' + name)
    iso.write(str(path))
    iso.close()


def read_back(path):
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    out = {}
    for name in FILES:
        for key in ('udf_path', 'iso_path'):
            buf = io.BytesIO()
            iso.get_file_from_iso_fp(buf, **{key: '/' + name + (';1' if key == 'iso_path' else '')})
            out[name, key] = buf.getvalue()
    iso.close()
    return out


def mangle_like_ps2isotools(path):
    """Reproduce the release image's UDF differences on a retail-shaped image."""
    with open(path, 'r+b') as fp:
        image = L.Image(fp)
        info = L.udf(image)
        for sector in info['pds']:
            block = bytearray(image.read(sector))
            struct.pack_into('<I', block, 184, 0)                        # access unspecified
            struct.pack_into('<I', block, 192, image.sectors + 2 - info['start'])
            fp.seek(sector * L.SECTOR); fp.write(L.retag(block, sector))
        for sector, lb, _, is_dir, _ in info['entries']:
            if not is_dir:
                block = bytearray(image.read(sector))
                block[27] = 0                                            # file type unspecified
                fp.seek(sector * L.SECTOR); fp.write(L.retag(block, lb))
        anchor = info['anchor']
        fp.seek((image.sectors - 1) * L.SECTOR); fp.write(bytes(L.SECTOR))
        fp.seek((image.sectors + 2) * L.SECTOR); fp.write(L.retag(anchor, image.sectors + 2))
        sectors = image.sectors + 3                                      # odd size, anchor at the end
        fp.seek(16 * L.SECTOR + 80); fp.write(struct.pack('<I', sectors) + struct.pack('>I', sectors))


def run(*argv):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        code = L.main(list(argv))
    return code, out.getvalue()


class DiscLayout(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.iso = Path(tmp.name) / 'game.iso'
        build(self.iso)
        L.fix(str(self.iso))                     # pycdlib's own layout -> retail rules
        self.files = read_back(self.iso)

    def test_fixed_image_passes_and_fix_is_idempotent(self):
        self.assertEqual(run('check', str(self.iso))[0], 0)
        before = self.iso.read_bytes()
        self.assertEqual(L.fix(str(self.iso)), [])
        self.assertEqual(self.iso.read_bytes(), before)
        self.assertEqual(self.iso.stat().st_size % (16 * L.SECTOR), 0)

    def test_ps2isotools_layout_is_reported_and_repaired(self):
        mangle_like_ps2isotools(self.iso)
        code, out = run('check', str(self.iso))
        self.assertEqual(code, 1)
        for words in ('16-sector', 'access type 0', 'wrong file type', 'partition length'):
            self.assertIn(words, out)
        self.assertEqual(run('fix', str(self.iso))[0], 0)
        self.assertEqual(run('check', str(self.iso))[0], 0)
        self.assertEqual(read_back(self.iso), self.files)
        with open(self.iso, 'rb') as fp:
            image = L.Image(fp)
            info = L.udf(image)
            self.assertEqual(image.sectors % 16, 0)
            self.assertEqual(info['access'], 1)
            self.assertEqual(info['start'] + info['length'], image.sectors - 1)
            self.assertTrue(all(ft == (4 if d else 5) for _, _, _, d, ft in info['entries']))
            self.assertEqual(L.iso9660(image)[0], image.sectors)

    def test_damaged_descriptor_is_refused(self):
        with open(self.iso, 'r+b') as fp:
            sector = L.udf(L.Image(fp))['pds'][0]
            fp.seek(sector * L.SECTOR + 190); fp.write(b'\xff')
        before = self.iso.read_bytes()
        self.assertEqual(run('fix', str(self.iso))[0], 2)
        self.assertEqual(self.iso.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
