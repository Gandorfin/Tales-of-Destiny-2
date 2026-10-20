"""Tests for ps2/build_ps2.py: PyTOD2 loads without its window, and the
comptoe stand-in round-trips.

python -m unittest discover -s ps2/PyTOD2 -p test_build_ps2.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_ps2  # noqa: E402

STEPS = ('extract_fpb', 'unpack', 'extract_scpk', 'extract_sced', 'extract_pak1', 'move_skits_out',
         'extract_skit', 'insert_sced', 'pack_scpk', 'insert_skit', 'move_skits_in', 'insert_pak1',
         'pack_fpb')


class Headless(unittest.TestCase):
    def test_every_button_function_loads_without_a_window(self):
        tod = build_ps2.load_pytod2()
        for name in STEPS:
            self.assertTrue(callable(getattr(tod, name, None)), name)
        self.assertNotIn('window', vars(tod))           # the GUI section was cut off
        self.assertIs(tod.subprocess.run.__func__, build_ps2._Subprocess.run)

    def test_comptoe_stand_in_round_trips(self):
        data = (b'Tales of Destiny 2 ' * 200) + bytes(range(256)) * 4
        with tempfile.TemporaryDirectory() as tmp:
            src, packed, back = (os.path.join(tmp, n) for n in ('in', 'in.c', 'in.d'))
            open(src, 'wb').write(data)
            for mode in ('-c1', '-c3'):
                build_ps2.comptoe_python([mode, src, packed])
                blob = open(packed, 'rb').read()
                self.assertEqual(blob[0], int(mode[2]))
                self.assertLess(len(blob), len(data))
                build_ps2.comptoe_python(['-d', packed, back])
                self.assertEqual(open(back, 'rb').read(), data)

    def test_arguments(self):
        args = build_ps2.parse_args(['--japanese-iso', 'j.iso', '--cless-iso', 'c.iso',
                                     '--movie-fpb', 'm.fpb', '--version', '1.3.1', '--out', 'o.iso'])
        self.assertTrue(args.work.endswith('o.iso.work'))
        with self.assertRaises(SystemExit):
            build_ps2.parse_args(['--japanese-iso', 'j.iso', '--base-fpb', 'f', '--movie-fpb', 'm',
                                  '--version', '1', '--out', 'o'])


if __name__ == '__main__':
    unittest.main()
