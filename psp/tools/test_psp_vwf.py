"""Tests for psp_vwf.py and mips_asm.py (no game files needed)."""
import hashlib
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mips_asm  # noqa: E402
import psp_font  # noqa: E402
import psp_vwf  # noqa: E402

# Words the PSP loader relocates inside the patched ranges (retail BOOT.BIN
# relocation table). The VWF patch must never write to them.
RELOCATED = [0x13EC94, 0x13EC98, 0x13ECB8, 0x13ECC0, 0x13ECC4, 0x13EE00, 0x13EE08,
             0x13EE10, 0x13EE40, 0x140E74, 0x140E8C, 0x140E94, 0x142834, 0x142860,
             0x142868, 0x143390, 0x1433C0, 0x1443F8, 0x14445C, 0x149FB8, 0x149FCC,
             0x149FE8, 0x14A49C, 0x14A4C4]


def one(name, *args, pc=0x143380):
    a = mips_asm.Asm(pc)
    a.op(name, *args)
    return a.words()[0][1]


class AsmTests(unittest.TestCase):
    def test_encodings_match_the_game_and_armips(self):
        # expected words taken from the retail executable / armips v0.11.0
        self.assertEqual(one('lw', 'a0', 0x20, 't1'), 0x8D240020)
        self.assertEqual(one('sra', 's2', 'a1', 9), 0x00059243)
        self.assertEqual(one('sb', 's0', 0, 'a0'), 0xA0900000)
        self.assertEqual(one('lbu', 't7', 0, 'a3'), 0x90EF0000)
        self.assertEqual(one('sh', 't7', 2, 't6'), 0xA5CF0002)
        self.assertEqual(one('lui', 'at', 0x61), 0x3C010061)
        self.assertEqual(one('addiu', 'at', 'at', 0x6EC0), 0x24216EC0)
        self.assertEqual(one('addu', 'at', 'at', 'v1'), 0x00230821)
        self.assertEqual(one('jalr', 'at'), 0x0020F809)
        self.assertEqual(one('b', 0x1433C0, pc=0x143394), 0x1000000A)
        self.assertEqual(one('bal', 0x142844, pc=0x14283C), 0x04110001)
        self.assertEqual(one('andi', 'v1', 'a1', 1), 0x30A30001)
        self.assertEqual(one('srl', 'fp', 'a3', 1), 0x0007F042)
        self.assertEqual(one('move', 's1', 't0'), 0x01008821)
        self.assertEqual(one('mult', 'v1', 't7'), 0x006F0018)
        self.assertEqual(one('mflo', 't4'), 0x00006012)
        self.assertEqual(one('jr', 'ra'), 0x03E00008)

    def test_hi_lo_pair_rebuilds_the_value(self):
        for v in (0x616EC0, 0x60FFFF, 0x618000, -0x10, 0x7FFF8000):
            h, l = mips_asm.hi(v), mips_asm.lo(v)
            l = l - 0x10000 if l & 0x8000 else l
            self.assertEqual(((h << 16) + l) & 0xFFFFFFFF, v & 0xFFFFFFFF)

    def test_branch_range_and_unknown_ops_fail(self):
        with self.assertRaises(ValueError):
            one('b', 0x143380 + 0x40000)
        with self.assertRaises(ValueError):
            one('teq', 'a0', 'a1')


class HookTests(unittest.TestCase):
    def test_hooks_equal_armips_output(self):
        # psp/tools/... source was assembled with armips v0.11.0 for this
        # base, scale and width table; same sha1 = identical machine code
        widths = bytes((i * 7 + 3) & 0x1F for i in range(1024))
        code, labels = psp_vwf.hooks(0x894B00, widths, 320)
        self.assertEqual(hashlib.sha1(code).hexdigest(), '3a9c807fc68d15a2b9aadf8eb415f126f7ce4f2b')
        self.assertEqual(labels['putchar'], 0x894B00)
        self.assertEqual(code[-1024:], widths)

    def test_bold_hook_equals_armips_output(self):
        widths = bytes((i * 7 + 3) & 0x1F for i in range(1024))
        bold = bytes((i * 5 + 1) & 0xF for i in range(640))
        code, labels = psp_vwf.hooks(0x894B00, widths, 320, bold_widths=bold)
        self.assertEqual(code[labels['bold_widths'] - 0x894B00:][:640], bold)
        self.assertEqual(labels['bold_texture'] % 64, 0)
        self.assertEqual(len(code) - (labels['bold_texture'] - 0x894B00), 0x8000)
        sites = dict(psp_vwf.call_sites(labels))
        self.assertEqual(set(psp_vwf.RETAIL_BOLD) - set(sites), set())

    def test_call_sites_never_touch_relocated_words(self):
        _, labels = psp_vwf.hooks(0x894B00, bytes(1024))
        sites = [va for va, _ in psp_vwf.call_sites(labels)]
        self.assertFalse(set(sites) & set(RELOCATED))
        self.assertEqual(set(sites), set(psp_vwf.RETAIL))
        _, labels = psp_vwf.hooks(0x894B00, bytes(1024), bold_widths=bytes(640), ticker=True)
        sites = [va for va, _ in psp_vwf.call_sites(labels)]
        self.assertFalse(set(sites) & set(RELOCATED))
        self.assertEqual(set(sites), set(psp_vwf.RETAIL) | set(psp_vwf.RETAIL_BOLD)
                         | set(psp_vwf.RETAIL_TICKER))

    def test_all_hooks_equal_armips_output(self):
        widths = bytes((i * 7 + 3) & 0x1F for i in range(1024))
        bold = bytes((i * 5 + 1) & 0xF for i in range(640))
        code, _ = psp_vwf.hooks(0x894B00, widths, 320, bold_widths=bold, ticker=True)
        self.assertEqual(hashlib.sha1(code).hexdigest(), 'ca2bdb9441bc101469d39dcbf6df832c5bb756ae')

    def test_call_site_jumps_reach_the_hooks(self):
        _, labels = psp_vwf.hooks(0x894B00, bytes(1024))
        w = dict(psp_vwf.call_sites(labels))

        def target(hi_at, lo_at, base):
            h = w[hi_at] & 0xFFFF
            l = w[lo_at] & 0xFFFF
            l = l - 0x10000 if l & 0x8000 else l
            return ((h << 16) + l + base) & 0xFFFFFFFF
        self.assertEqual(target(0x143384, 0x143388, psp_vwf.SLOTTAB), labels['putchar'])
        self.assertEqual(target(0x13EE24, 0x13EE28, psp_vwf.SLOTTAB), labels['layout'])
        self.assertEqual(target(0x140E78, 0x140E7C, psp_vwf.DATA_DE0), labels['draw'])
        self.assertEqual(target(0x142844, 0x142848, 0x142844), labels['measure'])
        _, labels = psp_vwf.hooks(0x894B00, bytes(1024), bold_widths=bytes(640), ticker=True)
        w = dict(psp_vwf.call_sites(labels))
        self.assertEqual(target(0x144440, 0x144444, 0x144440), labels['bold'])
        self.assertEqual(target(0x149FD0, 0x149FD4, psp_vwf.SLOTTAB), labels['ticker_layout'])
        self.assertEqual(target(0x14A4A8, 0x14A4AC, 0x14A4A8), labels['ticker_draw'])


def fake_font(cells):
    """Font member with filled columns [left, right] in the given slots."""
    gray = bytearray(256 * psp_font.H)
    for slot, (left, right) in cells.items():
        r, c = divmod(slot, 11)
        for y in range(5, 18):
            for x in range(left, right + 1):
                gray[(r * 23 + y) * 256 + c * 23 + x] = 15 * 17
    return psp_font.reswizzle(bytes(gray))


def fake_boot():
    """Text words at every site, slot table, pool segment at EOF."""
    size = 0x2A0000
    b = bytearray(size)
    struct.pack_into('<I', b, 0x1C, 0x34)
    struct.pack_into('<H', b, 0x2C, 2)
    struct.pack_into('<8I', b, 0x34, 1, 0xC0, 0, 0, 0x1DCBF0, 0x1DCBF0, 7, 0x40)
    pool = bytes(range(256)) * 4
    struct.pack_into('<8I', b, 0x54, 1, size, psp_vwf.POOL_VADDR, psp_vwf.POOL_VADDR, len(pool), len(pool), 4, 0x40)
    for va, word in psp_vwf.RETAIL.items():
        struct.pack_into('<I', b, va + 0xC0, word[-1] if isinstance(word, tuple) else word)
    table = bytearray(256)
    table[0x20] = 0
    table[ord('A')] = 0x17
    table[ord('i')] = 0xE2
    table[ord('0')] = 0x0D
    b[psp_vwf.SLOTTAB_FILE:psp_vwf.SLOTTAB_FILE + 256] = table
    return bytes(b + pool)


class PatchTests(unittest.TestCase):
    def test_widths_from_glyph_table(self):
        import psp_latin_font
        data = psp_latin_font.load()
        table = bytearray(256)
        table[ord('A')], table[ord('i')], table[ord('0')], table[ord('1')] = 0x17, 0xE2, 0x0D, 0x0E
        w = psp_vwf.build_widths(table, data)
        a, i = data['glyphs1']['A'], data['glyphs1']['i']
        self.assertEqual((w[2 * 0x17], w[2 * 0x17 + 1]), (a['left'], a['adv']))
        self.assertEqual((w[2 * 0xE2], w[2 * 0xE2 + 1]), (i['left'], i['adv']))
        self.assertLess(i['adv'], a['adv'])                  # proportional
        self.assertEqual(w[2 * 0x0D + 1], w[2 * 0x0E + 1])   # tabular digits
        self.assertEqual(w[1], data['glyphs1'][' ']['adv'])  # space = slot 0
        self.assertEqual(w[512:], bytes(512))                # no offsets or squeeze needed

    def test_patch_appends_to_pool_and_is_not_applied_twice(self):
        boot = fake_boot()
        font = fake_font({0x17: (2, 21), 0xE2: (9, 14)})
        out, info = psp_vwf.patch_boot(boot, font)
        self.assertEqual(out[:0x34], boot[:0x34])
        p = struct.unpack_from('<8I', out, 0x54)
        self.assertEqual(p[1] + p[4], len(out))
        self.assertEqual(p[4], p[5])
        self.assertGreater(len(out), len(boot))
        self.assertEqual(out[len(boot) - 1024:len(boot)], boot[-1024:])   # old pool bytes unchanged
        for va in RELOCATED:
            self.assertEqual(out[va + 0xC0:va + 0xC4], boot[va + 0xC0:va + 0xC4])
        with self.assertRaises(ValueError):
            psp_vwf.patch_boot(out, font)

    def test_patch_refuses_a_pool_that_does_not_end_the_file(self):
        boot = fake_boot() + b'\0' * 16
        with self.assertRaises(ValueError):
            psp_vwf.patch_boot(boot, fake_font({}))


if __name__ == '__main__':
    unittest.main()
