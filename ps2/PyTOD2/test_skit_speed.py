"""Check the skit speed rewrite without requiring proprietary game files."""
import struct
import unittest
import skit_speed as K


def fixture(lines):
    """A SCED with one skit line per (speed push, Japanese text bytes)."""
    code = bytearray()
    text = bytearray(b'\0')
    for push, japanese in lines:
        code += b'\x83\x80\x80' + push + b'\xF8'
        code += struct.pack('<H', len(text))
        text += japanese + b'\0'
    code_start = 0x1C
    text_start = code_start + len(code)
    head = b'SCED' + struct.pack('<LL', code_start, text_start)
    return bytearray(head.ljust(code_start, b'\0') + code + text)


KANA = b'\x99\x40'


class SkitSpeed(unittest.TestCase):
    def test_reads_both_push_forms(self):
        sced = fixture([(b'\x87', KANA * 3), (b'\x90\x08', KANA * 4)])
        rows = K.table_from_sced(sced)
        self.assertEqual([r[1:] for r in rows], [[7, 3], [8, 4]])

    def test_retime_changes_only_speed_bytes(self):
        sced = fixture([(b'\x87', KANA * 10), (b'\x90\x08', KANA * 10)])
        before = bytes(sced)
        table = {'x.sced': K.table_from_sced(sced)}
        fields = [r[0] for r in table['x.sced']]
        out = K.retime('x.sced', sced, fields, ['a' * 20, 'b' * 40], table)
        self.assertEqual([r[2] for r in out], [3, 2])
        changed = [i for i in range(len(sced)) if sced[i] != before[i]]
        self.assertEqual(len(changed), 2)
        self.assertEqual(len(sced), len(before))
        self.assertEqual(K.read_speed(sced, fields[0]), 3)
        self.assertEqual(K.read_speed(sced, fields[1]), 2)

    def test_never_slower_and_never_below_minimum(self):
        self.assertEqual(K.new_speed(8, 30, 10), 8)
        self.assertEqual(K.new_speed(8, 10, 1000), K.MIN_SPEED)
        self.assertEqual(K.new_speed(8, 30, 0), 8)

    def test_retime_is_idempotent_on_retimed_sced(self):
        sced = fixture([(b'\x90\x08', KANA * 10)])
        table = {'x.sced': K.table_from_sced(sced)}
        fields = [table['x.sced'][0][0]]
        K.retime('x.sced', sced, fields, ['a' * 40], table)
        once = bytes(sced)
        K.retime('x.sced', sced, fields, ['a' * 40], table)
        self.assertEqual(bytes(sced), once)

    def test_english_glyphs(self):
        self.assertEqual(K.en_glyphs('Hey, <Kyle>!'), 10)
        self.assertEqual(K.en_glyphs('<button:00000056>Go{82}'), 3)
        self.assertEqual(K.en_glyphs('<color:00000001>Hi<color:00000000>'), 2)

    def test_japanese_glyphs(self):
        name = b'\x07' + struct.pack('<I', 4)  # Judas, five kana
        sced = fixture([(b'\x87', KANA + name + b'\x01!')])
        self.assertEqual(K.table_from_sced(sced)[0][2], 1 + 5 + 1)

    def test_mismatch_is_an_error(self):
        sced = fixture([(b'\x87', KANA)])
        table = {'x.sced': K.table_from_sced(sced)}
        with self.assertRaises(RuntimeError):
            K.retime('x.sced', sced, [table['x.sced'][0][0]], [], table)


if __name__ == '__main__':
    unittest.main()
