"""Check the PMF rebuild without game files. Run from psp/tools:
python -m unittest test_psp_pmf"""
import struct
import unittest

import psp_pmf as P


def scr_head(t):
    """A 14-byte MPEG-2 pack header with SCR t (90 kHz) and the PSP mux rate."""
    b0 = 0x44 | ((t >> 27) & 0x38) | ((t >> 28) & 3)
    b1 = (t >> 20) & 0xFF
    b2 = ((t >> 12) & 0xF8) | 4 | ((t >> 13) & 3)
    b3 = (t >> 5) & 0xFF
    b4 = ((t << 3) & 0xF8) | 4
    return b'\x00\x00\x01\xba' + bytes([b0, b1, b2, b3, b4, 1]) + b'\x01\x86\xa3\xf8'


def picture(idr, size, ref=True):
    """An access unit of exactly size bytes: delimiter, slice NAL, filler."""
    nal = (0x65 if idr else (0x21 if ref else 0x01))
    body = b'\x00\x00\x00\x01\x09\x10' + b'\x00\x00\x01' + bytes([nal])
    return body + b'\x88' * (size - len(body))


SYS = b'\x00\x00\x01\xbb\x00\x0c' + bytes(12)
EXT = b'\x1e\x61\x75'
AUDIO = b'\x00\x00\x01\xbd\x07\xec\x81\x80\x05\x21\x00\x01\x00\x01' + b'\xa5' * (2034 - 14)


def movie(unit_sizes, audio_every=3, first_pts=900000):
    """A PMF whose units hold pictures of the given sizes, laid out by the
    rebuild code itself on generous slots, with an audio pack every few packs."""
    pics = []
    for sizes in unit_sizes:
        pics += [picture(i == 0, n) for i, n in enumerate(sizes)]
    packs = []
    first = 0
    for sizes in unit_sizes:
        es = sum(sizes)
        video = max(es // 1900, len(sizes)) + 2
        # the unit's packs start one second before its first picture is decoded
        t = first_pts + (first - 1) * P.FRAME - P.LEAD
        slots, heads = [], []
        for v in range(video):
            if v and v % audio_every == 0:
                packs.append(scr_head(t) + AUDIO)
                t += P.FRAME
            slots.append(len(packs))
            heads.append(scr_head(t))
            packs.append(None)
            t += P.FRAME
        offsets = [s - slots[0] for s in slots]
        bodies = P._lay_unit(offsets, heads, pics[first:first + len(sizes)], first, first_pts, SYS, EXT)
        bodies += [P._padding(2048 - 14)] * (len(slots) - len(bodies))
        for s, h, b in zip(slots, heads, bodies):
            packs[s] = h + b
        first += len(sizes)
    data = b''.join(packs)
    header = b'PSMF0014' + struct.pack('>II', 0x800, len(data))
    return header.ljust(0x800, b'\x00') + data, pics


class PmfTests(unittest.TestCase):
    def test_timestamps_round_trip(self):
        for v in (0, 90000, 2 ** 32 + 12345):
            self.assertEqual(P._ts(P._ts_bytes(3, v)), v)

    def test_scr_header(self):
        self.assertEqual(P._scr(scr_head(5474719)), 5474719)

    def test_pictures_split_on_delimiters(self):
        es = picture(True, 50) + picture(False, 30) + picture(False, 40)
        self.assertEqual([len(p) for p in P.pictures(es)], [50, 30, 40])

    def test_navigation_packet(self):
        pics = [picture(True, 100), picture(False, 60), picture(False, 70, ref=False)]
        nav = P._nav(pics, {0: 0, 1: 0, 2: 2})
        body = nav[6:]
        self.assertEqual(body[:2], b'\x01\xe0')
        self.assertEqual(struct.unpack_from('>4H', body, 2), (0, 0, 2, 0))
        self.assertEqual(struct.unpack_from('>HH', body, 14), (14, 3))
        self.assertEqual(struct.unpack_from('>3I', body, 18), (0x800000 | 100, 0x800000 | 60, 70))

    def test_layout_and_rebuild_keep_audio_and_timing(self):
        data, pics = movie([[3000] + [900] * 20, [2500] + [800] * 18])
        units, found, first_pts, sysraw, ext = P.layout(P.parse(data))
        self.assertEqual(found, pics)
        self.assertEqual([u[2:] for u in units], [[0, 21], [21, 19]])
        new = [picture(i in (0, 21), len(p) * 3 // 4) for i, p in enumerate(pics)]
        rebuilt = P.rebuild(data, new)
        self.assertEqual(len(rebuilt), len(data))
        a, b = P.parse(data), P.parse(rebuilt)
        audio = lambda m: [it['raw'] for pk in m['packs'] for it in pk['items'] if it['sid'] == 0xBD]
        self.assertEqual(audio(a), audio(b))
        self.assertEqual([p['head'] for p in a['packs']], [p['head'] for p in b['packs']])
        self.assertEqual(P.layout(b)[1], new)
        stats = P.buffer_stats(rebuilt)
        self.assertLessEqual(stats['peak'], stats['size'])
        self.assertGreater(stats['margin'], 0)

    def test_pes_timestamp_belongs_to_first_picture_in_packet(self):
        # tiny pictures put several picture starts into one packet
        data, pics = movie([[4000] + [30] * 40])
        starts, o = [], 0
        for p in pics:
            starts.append(o)
            o += len(p)
        es = 0
        stamped = 0
        for pk in P.parse(data)['packs']:
            for it in pk['items']:
                if it['sid'] != 0xE0:
                    continue
                a, b = es, es + len(it['payload'])
                es = b
                if 'pts' in it:
                    first = next(i for i, s in enumerate(starts) if s >= a)
                    self.assertLess(starts[first], b)
                    self.assertEqual(it['pts'], 900000 + first * P.FRAME)
                    stamped += 1
        self.assertGreaterEqual(stamped, 3)

    def test_too_big_unit_is_reported(self):
        data, pics = movie([[3000] + [900] * 20, [2500] + [800] * 18])
        new = [picture(i in (0, 21), len(p) * 3) for i, p in enumerate(pics)]
        with self.assertRaises(P.UnitOverflow) as e:
            P.rebuild(data, new)
        self.assertTrue(e.exception.units)

    def test_picture_count_must_match(self):
        data, pics = movie([[3000] + [900] * 5])
        with self.assertRaises(ValueError):
            P.rebuild(data, pics[:-1])

    def test_buffer_size_from_extension(self):
        self.assertEqual(P.buffer_size(b'\x1e\x61\x75'), 381952)
        self.assertEqual(P.buffer_size(b'\x1e\x61\xef'), 506880)


if __name__ == '__main__':
    unittest.main()
