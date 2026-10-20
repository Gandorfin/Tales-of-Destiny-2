"""Run from psp/tools: python -m unittest test_psp_boot_script

A synthetic BOOT.BIN with a small SCED at the real offset, no game files."""
import struct
import unittest

import psp_boot_script as B
import psp_menu
import psp_text


def make_boot(texts):
    """SCED with one F8 operand per text, then an end opcode."""
    code = b''.join(b'\xf8' + struct.pack('<H', 0) + b'\xe0\x02\xc0' for _ in texts) + b'\xf0'
    head = 12
    text_at = head + len(code)
    area = bytearray(); offs = []
    for t in texts:
        offs.append(len(area)); area += psp_text.encode_line(t) + b'\0'
    code = bytearray(code)
    for k, o in enumerate(offs):
        struct.pack_into('<H', code, 6 * k + 1, o)
    sced = b'SCED' + struct.pack('<II', head, text_at) + bytes(code) + bytes(area)
    return bytes(B.SCED_FILE) + sced + b'\xaa' * 16


class BootScriptTests(unittest.TestCase):
    def test_strings_are_rebuilt_in_place(self):
        boot = make_boot(['からっぽだ', 'からっぽだ', '<item:FFFFFFFF>を{01}手にいれました'])
        table = {'からっぽだ': 'Empty.', '<item:FFFFFFFF>を{01}手にいれました': 'Got <item:FFFFFFFF>.'}
        out, st = B.patch(boot, table)
        self.assertEqual((st['strings'], st['translated']), (3, 3))
        self.assertEqual(len(out), len(boot))
        self.assertEqual(out[-16:], b'\xaa' * 16)          # nothing after the text area moves
        d, text, refs = B.strings(out)
        self.assertEqual([B._key(d, t) for _, t in refs], ['Empty.', 'Empty.', 'Got <item:FFFFFFFF>.'])
        self.assertEqual(refs[0][1], refs[1][1])            # equal strings stored once
        self.assertEqual(B.verify(out, table), [])

    def test_too_long_is_refused(self):
        boot = make_boot(['から'])
        with self.assertRaises(ValueError):
            B.patch(boot, {'から': 'This English text is far too long for the slot'})

    def test_zero_byte_inside_a_code(self):
        d = b'\x16\xa0\x00\x08\x30\x18\xca\xc0' + psp_menu.encode_en('X') + b'\0'
        self.assertEqual(B._end(d, 0), len(d) - 1)


if __name__ == '__main__':
    unittest.main()
