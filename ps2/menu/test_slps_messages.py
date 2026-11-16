"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_slps_messages.py'"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slps_messages as S


def fake():
    d = bytearray(0xD0000)
    for off, old, _ in S.ENTRIES:
        d[off:off + len(old)] = old
    return bytes(d)


class Messages(unittest.TestCase):
    def test_translated_in_place(self):
        src = fake()
        out, n = S.apply(src)
        self.assertEqual((len(out), n), (len(src), 2))
        for off, old, new in S.ENTRIES:
            got = out[off:off + len(old)]
            self.assertEqual(got[:len(new) + 1], new + b'\0')
            self.assertFalse(any(got[len(new):]))           # zero padded, nothing past the slot
            self.assertEqual(got[:4], S.NAME)               # the name code stays first
        self.assertIn(S.TITLE, out[S.ENTRIES[0][0]:S.ENTRIES[0][0] + 34])
        changed = [i for i in range(len(src)) if src[i] != out[i]]
        self.assertTrue(all(any(o <= i < o + len(old) for o, old, _ in S.ENTRIES) for i in changed))

    def test_rerun_and_guard(self):
        out, _ = S.apply(fake())
        self.assertEqual(S.apply(out), (out, 0))
        bad = bytearray(fake())
        bad[S.ENTRIES[1][0] + 5] ^= 0xFF
        with self.assertRaises(S.MessageError):
            S.apply(bytes(bad))


if __name__ == '__main__':
    unittest.main()
