"""Run: python -B -m unittest discover -s psp/tools -p test_psp_pool.py -v

Synthetic BOOT.BIN images only, no game image needed."""
import struct
import unittest

import psp_pool as pool

JP = '防御回数'.encode('cp932')         # any bytes work; the pool never decodes
EN = b'Block Count'


def lui(reg, imm):
    return 0x3C000000 | (reg << 16) | imm


def addiu(reg, imm):
    return (0x09 << 26) | (reg << 21) | (reg << 16) | (imm & 0xFFFF)


class Image:
    """BOOT.BIN with the three retail program headers, an empty relocation
    table at the retail offset, and helpers to place code, data and relocs."""

    def __init__(self):
        self.b = bytearray(pool.RELOC_OFF + pool.RELOC_SIZE + 0x100)
        struct.pack_into('<H', self.b, 0x2C, 3)
        struct.pack_into('<8I', self.b, 0x34, 1, 0xC0, 0, 0, 0x1DCB40, 0x1DCB40, 5, 0x40)
        struct.pack_into('<8I', self.b, 0x54, 1, 0x1DCD00, 0x1DCC00, 0x1DCC00, 0xC3000, 0xC3000, 6, 0x40)
        struct.pack_into('<8I', self.b, 0x74, 0x700000A0, pool.RELOC_OFF, 0, 0, pool.RELOC_SIZE, 0, 0, 4)
        self.nrel = 0

    def word(self, vaddr, value):
        struct.pack_into('<I', self.b, pool._vaddr_to_file(vaddr), value)

    def text(self, vaddr, data):
        f = pool._vaddr_to_file(vaddr)
        self.b[f:f + len(data) + 1] = data + b'\0'

    def reloc(self, typ, vaddr, seg=0):
        ofsb = 1 if vaddr >= 0x1DCC00 else 0
        off = vaddr - (0x1DCC00 if ofsb else 0)
        struct.pack_into('<II', self.b, pool.RELOC_OFF + 8 * self.nrel, off, typ | (ofsb << 8) | (seg << 16))
        self.nrel += 1

    def pair(self, at, target, reg=2):
        hi, lo = (target + 0x8000) >> 16, target & 0xFFFF
        self.word(at, lui(reg, hi))
        self.reloc(pool.R_MIPS_HI16, at)
        self.word(at + 4, addiu(reg, lo))
        self.reloc(pool.R_MIPS_LO16, at + 4)

    def read(self, b, vaddr):
        return struct.unpack_from('<I', b, pool._vaddr_to_file(vaddr))[0]


def target_of(b, img, hi_at, lo_at):
    hi = img.read(b, hi_at) & 0xFFFF
    lo = img.read(b, lo_at) & 0xFFFF
    return (hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)


class PoolTests(unittest.TestCase):
    def test_code_pair_is_pointed_at_the_pool(self):
        img = Image()
        img.text(0x1AB014, JP)
        img.pair(0xFAE9C, 0x1AB014)
        out, st = pool.add_pool_and_relocate(bytes(img.b), [(JP, EN)], log=None)
        self.assertEqual(target_of(out, img, 0xFAE9C, 0xFAEA0), pool.POOL_VADDR)
        self.assertEqual(st['code_pairs_rewritten'], 1)
        pool_file = struct.unpack_from('<8I', out, 0x94)[1]
        self.assertEqual(out[pool_file:pool_file + len(EN) + 1], EN + b'\0')
        # the instruction fields outside the immediates are untouched
        self.assertEqual(img.read(out, 0xFAE9C) >> 16, lui(2, 0) >> 16)
        self.assertEqual(img.read(out, 0xFAEA0) >> 16, addiu(2, 0) >> 16)

    def test_shared_lui_with_an_unrelated_address_is_left_alone(self):
        img = Image()
        img.text(0x1AB014, JP)
        img.text(0x1AB040, b'other')
        img.word(0xFB000, lui(4, 0x1B))
        img.reloc(pool.R_MIPS_HI16, 0xFB000)
        img.word(0xFB004, addiu(4, 0xB014 - 0x10000))
        img.reloc(pool.R_MIPS_LO16, 0xFB004)
        img.word(0xFB008, addiu(4, 0xB040 - 0x10000))
        img.reloc(pool.R_MIPS_LO16, 0xFB008)
        logged = []
        out, st = pool.add_pool_and_relocate(bytes(img.b), [(JP, EN)], log=logged.append)
        for at in (0xFB000, 0xFB004, 0xFB008):
            self.assertEqual(img.read(out, at), img.read(img.b, at))
        self.assertEqual(st['code_pairs_left'], 1)
        self.assertEqual(len(logged), 1)

    def test_suffix_string_needs_a_pointer(self):
        img = Image()
        f = pool._vaddr_to_file(0x1C7930)
        img.b[f - 4:f] = b'\x8e\x45\x66\x3e'               # binary record bytes
        img.text(0x1C7930, JP)                       # right after binary bytes
        img.word(0x1DD000, 0x1C7930)                 # an R_MIPS_32 pointer to it
        img.reloc(pool.R_MIPS_32, 0x1DD000)
        f = pool._vaddr_to_file(0x1C8000)
        img.b[f - 2:f] = b'\x99\x41'                       # one glyph of a longer string
        img.text(0x1C8000, JP)                       # tail of a longer string, no pointer
        out, st = pool.add_pool_and_relocate(bytes(img.b), [(JP, EN)], log=None)
        self.assertEqual(img.read(out, 0x1DD000), pool.POOL_VADDR)
        self.assertEqual((st['relocated'], st['pointers_rewritten']), (1, 1))

    def test_data_pointer_still_rewritten(self):
        img = Image()
        img.text(0x1AB014, JP)
        img.word(0x1DD010, 0x1AB014)
        img.reloc(pool.R_MIPS_32, 0x1DD010)
        out, st = pool.add_pool_and_relocate(bytes(img.b), [(JP, EN)], log=None)
        self.assertEqual(img.read(out, 0x1DD010), pool.POOL_VADDR)
        self.assertEqual(st['code_pairs_rewritten'], 0)


if __name__ == '__main__':
    unittest.main()
