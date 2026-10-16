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


def push(value):
    """A SCED push immediate of the width the game uses for value."""
    if value <= 0xF:
        return bytes([0x80 + value])
    if value <= 0xFFF:
        return bytes([0x90 + (value >> 8), value & 0xFF])
    return bytes([0xA0 + (value >> 16)]) + struct.pack('<H', value & 0xFFFF)


def cued(lines):
    """A SCED whose lines wait for their cue the way the retail skits do:
    FE <push T> CE C0 F3 .., FE <push T+3> CF C0 F3 .., then the line."""
    code = bytearray()
    text = bytearray(b'\0')
    for cue, speed, japanese in lines:
        code += b'\xFE' + push(cue - 3) + b'\xCE\xC0\xF3\x00\x00'
        code += b'\xFE' + push(cue) + b'\xCF\xC0\xF3\x00\x00'
        # the retail skits push speeds above 7 as 0x90 NN
        speed = bytes([0x80 + speed]) if speed <= 7 else bytes([0x90, speed])
        code += b'\x83\x80\x80' + speed + b'\xF8'
        code += struct.pack('<H', len(text))
        text += japanese + b'\0'
    code_start = 0x1C
    text_start = code_start + len(code)
    head = b'SCED' + struct.pack('<LL', code_start, text_start)
    return bytearray(head.ljust(code_start, b'\0') + code + text)


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

    def test_line_cues(self):
        # 4 is a 4-bit push, 1120 a 12-bit push, 4200 a 20-bit push
        sced = cued([(4, 8, KANA * 9), (1120, 7, KANA * 15), (4200, 9, KANA)])
        rows = K.table_from_sced(sced)
        self.assertEqual(K.line_cues(sced, [r[0] for r in rows]), [4, 1120, 4200])

    def test_line_without_cue(self):
        sced = fixture([(b'\x87', KANA)])
        self.assertEqual(K.line_cues(sced, [K.table_from_sced(sced)[0][0]]), [None])

    def test_cue_windows(self):
        # skit 00066_02 as measured: cues 123, 253, voice track 2099 frames
        rows = [[0, 7, 15], [0, 7, 6], [0, 9, 84]]
        self.assertEqual(K.cue_windows([123, 253, 1123], 2099, rows),
                         [253 - 3 - (123 + 13), 1123 - 3 - (253 + 13),
                          2099 + 4 - (1123 + 13)])
        # never shorter than the time the Japanese took
        self.assertEqual(K.cue_windows([100, 110], 200, [[0, 5, 4], [0, 8, 2]])[0], 20)

    def test_budget(self):
        # one row (60 glyphs) may go down to 2 frames per glyph ...
        self.assertEqual(K.budget([0, 8, 10, 100]), 50)
        self.assertEqual(K.budget([0, 8, 10, 150]), 60)
        # ... a longer line scrolls, so it needs 3 frames per glyph
        self.assertEqual(K.budget([0, 8, 10, 240]), 80)
        self.assertEqual(K.budget([0, 8, 10, 3000]), K.MAX_GLYPHS)
        # never below the Japanese line
        self.assertEqual(K.budget([0, 2, 5, 10]), 5)
        self.assertEqual(K.problems('x.sced', [[0, 8, 10, 150]], ['a' * 60]), [])
        self.assertEqual(len(K.problems('x.sced', [[0, 8, 10, 150]], ['a' * 61])), 1)

    def test_adpcm_frames(self):
        silent = bytes(16)
        loud = b'\x00\x00' + b'\x11' * 14
        end = b'\x00\x01' + b'\x11' * 14
        # 3000 blocks of 28 samples at 48 kHz = 1.75 s = 104.9 frames
        self.assertEqual(K.adpcm_frames(loud * 2999 + end + silent * 10), 105)
        # no end flag: up to the last block that is not silent
        self.assertEqual(K.adpcm_frames(loud * 3000 + silent * 50), 105)

    def test_mismatch_is_an_error(self):
        sced = fixture([(b'\x87', KANA)])
        table = {'x.sced': K.table_from_sced(sced)}
        with self.assertRaises(RuntimeError):
            K.retime('x.sced', sced, [table['x.sced'][0][0]], [], table)


if __name__ == '__main__':
    unittest.main()
