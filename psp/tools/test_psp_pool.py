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


BASE = 0x08804000


def load_module(b, kernel):
    """Tiny model of the two loaders. kernel=True follows the PSP kernel
    (loadcore sceKernelLoadExecutableObject): PT_LOAD headers are taken from
    the first one while they are consecutive, the next header must be the
    relocation header, relocation indices count loaded segments, and only the
    last loaded segment gets its bss zeroed. kernel=False follows PPSSPP
    (ElfReader::LoadInto): every PT_LOAD header is loaded, indices are header
    indices. Memory that nothing wrote reads as 0xEE (stale RAM).
    Returns read(vaddr, n) over the loaded image."""
    ph = pool._headers(b)
    if kernel:
        loaded, rel = pool.hardware_segments(b)
    else:
        loaded = [i for i, p in enumerate(ph) if p[0] == pool.PT_LOAD]
        rel = [i for i, p in enumerate(ph) if p[0] == pool.PT_PSP_REL][0]
    mem = {}
    seg_addr = {}
    for n, i in enumerate(loaded):
        _, off, va, _, filesz, memsz, _, _ = ph[i]
        seg_addr[n if kernel else i] = va
        for k in range(filesz):
            mem[va + k] = b[off + k]
        if (not kernel or n == len(loaded) - 1) and memsz > filesz:
            for k in range(filesz, memsz):
                mem[va + k] = 0
    _, off, _, _, size, _, _, _ = ph[rel]
    for p in range(off, off + size, 8):
        r_off, info = struct.unpack_from('<II', b, p)
        typ, ofsb, adrb = info & 0xff, (info >> 8) & 0xff, (info >> 16) & 0xff
        if typ != pool.R_MIPS_32:
            continue
        at = seg_addr[ofsb] + r_off
        word = int.from_bytes(bytes(mem[at + k] for k in range(4)), 'little')
        word = (word + seg_addr[adrb] + BASE) & 0xffffffff
        for k in range(4):
            mem[at + k] = (word >> (8 * k)) & 0xff

    def read(vaddr, n):
        return bytes(mem.get(vaddr + k, 0xEE) for k in range(n))
    return read


class HardwareLayoutTests(unittest.TestCase):
    """The pool must be loaded by the PSP kernel, not only by PPSSPP."""

    def built(self):
        img = Image()
        # a data segment with bss, like the retail one (file 0xC3000, memory 0x6A3C48)
        struct.pack_into('<8I', img.b, 0x54, 1, 0x1DCD00, 0x1DCC00, 0x1DCC00, 0x100, 0x6A3C48, 6, 0x40)
        img.text(0x1AB014, JP)
        img.word(0x1DCC10, 0x1AB014)               # data pointer (offset base 1) to the string
        img.reloc(pool.R_MIPS_32, 0x1DCC10)
        img.word(0x1DCC20, 0x30)                    # pointer into the data segment (address base 1)
        img.reloc(pool.R_MIPS_32, 0x1DCC20, seg=1)
        out, _ = pool.add_pool_and_relocate(bytes(img.b), [(JP, EN)], log=None)
        return out

    def follow(self, read, at):
        ptr = int.from_bytes(read(at, 4), 'little') - BASE
        return read(ptr, len(EN) + 1)

    def test_old_layout_loses_the_pool_on_hardware(self):
        out = self.built()
        self.assertEqual(self.follow(load_module(out, kernel=False), 0x1DCC10), EN + b'\0')
        self.assertNotEqual(self.follow(load_module(out, kernel=True), 0x1DCC10), EN + b'\0')
        with self.assertRaisesRegex(ValueError, 'not consecutive'):
            pool.check_hardware_layout(out)

    def test_reordered_layout_loads_the_pool_everywhere(self):
        out, info = pool.make_hardware_loadable(self.built())
        self.assertTrue(info['reordered'])
        self.assertEqual([p[0] for p in pool._headers(out)], [1, 1, 1, pool.PT_PSP_REL])
        self.assertEqual([p[2] for p in pool._headers(out)[:3]], [0, pool.POOL_VADDR, 0x1DCC00])
        self.assertEqual(pool.check_hardware_layout(out)['pool_header'], 1)
        for kernel in (False, True):
            read = load_module(out, kernel)
            self.assertEqual(self.follow(read, 0x1DCC10), EN + b'\0')
            # the data-relative pointer still lands in the data segment
            self.assertEqual(int.from_bytes(read(0x1DCC20, 4), 'little'), BASE + 0x1DCC00 + 0x30)
            # the data segment keeps its zeroed bss (it is the last loaded segment)
            self.assertEqual(read(0x1DCC00 + 0x200, 4), b'\0' * 4)

    def test_reorder_is_idempotent_and_keeps_file_bytes(self):
        before = self.built()
        once, _ = pool.make_hardware_loadable(before)
        twice, info = pool.make_hardware_loadable(once)
        self.assertFalse(info['reordered'])
        self.assertEqual(once, twice)
        self.assertEqual(len(once), len(before))
        # only the header table and the relocation info words change
        rel = pool._headers(before)[2]
        diff = [i for i in range(len(before)) if before[i] != once[i]]
        self.assertTrue(all(0x34 <= i < 0xB4 or rel[1] <= i < rel[1] + rel[4] for i in diff))

    def test_pool_step_refuses_a_reordered_image(self):
        out, _ = pool.make_hardware_loadable(self.built())
        with self.assertRaises(ValueError):
            pool.add_pool_and_relocate(out, [(JP, EN)], log=None)


if __name__ == '__main__':
    unittest.main()
