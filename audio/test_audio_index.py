"""audio_index tests on synthetic data.

python3 -m unittest discover -s audio -p test_audio_index.py
"""
import os, struct, sys, tempfile, unittest, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_index as A


def frame(nibbles, shift=12, filt=0, flags=0):
    body = bytes((nibbles[k] & 15) | (nibbles[k + 1] & 15) << 4 for k in range(0, 28, 2))
    return bytes((filt << 4 | shift, flags)) + body


class Adpcm(unittest.TestCase):
    def test_shift_12_filter_0_gives_the_nibbles(self):
        nib = [k % 8 for k in range(28)]
        pcm = struct.unpack('<28h', A.decode_adpcm(frame(nib)))
        self.assertEqual(list(pcm), nib)

    def test_negative_nibbles_and_filter_1(self):
        pcm = struct.unpack('<28h', A.decode_adpcm(frame([15] + [0] * 27, shift=0, filt=1)))
        self.assertEqual(pcm[0], -4096)
        self.assertEqual(pcm[1], (-4096 * 60 + 32) >> 6)     # filter 1 carries the last sample

    def test_end_flag_stops_and_sample_count(self):
        data = frame([1] * 28, flags=1) + frame([2] * 28)
        self.assertEqual(len(A.decode_adpcm(data)), 28 * 2)
        self.assertEqual(A.adpcm_samples(data), 28)
        silent_tail = frame([1] * 28) + bytes(16) * 3
        self.assertEqual(A.adpcm_samples(silent_tail), 28)

    def test_wav_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'x.wav')
            A.write_wav(path, A.decode_adpcm(frame([3] * 28)), 22050)
            with wave.open(path) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getnframes()), (22050, 1, 28))


class Riff(unittest.TestCase):
    def test_fmt_and_fact(self):
        fmt = struct.pack('<HHIIHH', 0xFFFE, 1, 44100, 0, 280, 0)
        head = (b'RIFF' + struct.pack('<I', 0) + b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt
                + b'fact' + struct.pack('<II', 8, 88200) + bytes(4) + b'data' + struct.pack('<I', 0))
        self.assertEqual(A.riff_info(head), dict(fmt=0xFFFE, channels=1, rate=44100, samples=88200))


class Pairing(unittest.TestCase):
    def test_extra_files_on_either_side(self):
        a = [1.0, 2.0, 3.0, 9.5, 4.0, 5.0]
        b = [1.1, 2.1, 7.0, 3.1, 4.1, 5.1]
        pairs = A.align(a, b)
        matched = [(x, y) for x, y in pairs if x is not None and y is not None]
        self.assertEqual(matched, [(0, 0), (1, 1), (2, 3), (4, 4), (5, 5)])
        self.assertIn((3, None), pairs)
        self.assertIn((None, 2), pairs)

    def test_lone_second_pass_match_is_dropped(self):
        pairs = [(0, None), (1, 5), (None, 6), (2, 7), (3, 8), (4, 9)]
        kept = A.keep_runs(pairs, 3)
        self.assertIn((1, None), kept)
        self.assertIn((None, 5), kept)
        self.assertIn((4, 9), kept)


if __name__ == '__main__':
    unittest.main()
