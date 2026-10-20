"""Tests for replace_iso_files.py on small synthetic ISO9660 + UDF images.

python -m unittest discover -s ps2/menu -p test_replace_iso_files.py
(needs pycdlib to build the images)
"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import pycdlib
import fix_disc_layout as L
import replace_iso_files as R
from test_fix_disc_layout import FILES, build, read_back


class ReplaceFiles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.iso = self.dir / 'japanese.iso'
        build(self.iso)
        L.fix(str(self.iso))
        self.original = read_back(self.iso)
        with open(self.iso, 'rb') as fp:
            records = R.iso9660_records(L.Image(fp))
        self.last = max(records, key=lambda p: records[p][1])[1:]
        self.assertEqual(self.last, 'SYSTEM.CNF')    # pycdlib writes them in name order

    def source(self, name, data):
        path = self.dir / name
        path.write_bytes(data)
        return str(path)

    def test_same_size_and_grown_last_file(self):
        slps = bytes(reversed(FILES['SLPS_251.72']))
        cnf = b'NEW' * 9000                          # last file, grows past the old end
        out = self.dir / 'english.iso'
        report = R.replace(str(self.iso), str(out), {
            'SLPS_251.72': self.source('slps', slps), 'SYSTEM.CNF': self.source('cnf', cnf)})
        self.assertEqual(report['replaced']['SYSTEM.CNF'], (len(FILES['SYSTEM.CNF']), len(cnf)))
        got = {}
        iso = pycdlib.PyCdlib()
        iso.open(str(out))
        for name in FILES:
            for key, path in (('udf_path', '/' + name), ('iso_path', '/' + name + ';1')):
                buf = io.BytesIO()
                iso.get_file_from_iso_fp(buf, **{key: path})
                got[name, key] = buf.getvalue()
        iso.close()
        for key in ('udf_path', 'iso_path'):
            self.assertEqual(got['SLPS_251.72', key], slps)
            self.assertEqual(got['SYSTEM.CNF', key], cnf)
            self.assertEqual(got['FILE.FPB', key], FILES['FILE.FPB'])
        with open(out, 'rb') as fp:
            self.assertEqual(L.plan(L.Image(fp))[0], [])
        self.assertEqual(out.stat().st_size % (16 * L.SECTOR), 0)
        self.assertEqual(read_back(self.iso), self.original)      # the input stays untouched

    def test_files_keep_their_sectors(self):
        out = self.dir / 'english.iso'
        R.replace(str(self.iso), str(out), {'SLPS_251.72': self.source('slps', b'x' * 1000)})
        with open(self.iso, 'rb') as a, open(out, 'rb') as b:
            old, new = R.iso9660_records(L.Image(a)), R.iso9660_records(L.Image(b))
        self.assertEqual({p: r[1] for p, r in old.items()}, {p: r[1] for p, r in new.items()})
        self.assertEqual(new['/SLPS_251.72'][2], 1000)

    def test_growing_a_file_into_the_next_is_refused(self):
        out = self.dir / 'english.iso'
        big = self.source('fpb', b'y' * (len(FILES['FILE.FPB']) + 8 * L.SECTOR))
        with self.assertRaisesRegex(R.ReplaceError, 'next file'):
            R.replace(str(self.iso), str(out), {'FILE.FPB': big})
        self.assertFalse(out.exists())

    def test_unknown_file_and_in_place_output_are_refused(self):
        with self.assertRaisesRegex(R.ReplaceError, 'not on the disc'):
            R.replace(str(self.iso), str(self.dir / 'o.iso'), {'NOPE.BIN': self.source('n', b'1')})
        with self.assertRaisesRegex(R.ReplaceError, 'copy'):
            R.replace(str(self.iso), str(self.iso), {'SLPS_251.72': self.source('s', b'1')})

    def test_command_line(self):
        out = self.dir / 'english.iso'
        with contextlib.redirect_stdout(io.StringIO()) as text:
            code = R.main([str(self.iso), str(out), 'FILE.FPB=' + self.source('f', b'z' * 5000)])
        self.assertEqual(code, 0)
        self.assertIn('retail disc layout OK', text.getvalue())


if __name__ == '__main__':
    unittest.main()
