#!/usr/bin/env python3
"""Append a string pool to BOOT.BIN and relocate overflow menu strings.

Menu strings whose English is longer than the Japanese slot can't be
overwritten in place. This appends a new PT_LOAD segment (pool) at end of
file (a 4th program header fits the zero gap 0x94..0xC0 before .text), at a
fresh vaddr above bss, writes the English there, and repoints the string's
data pointer(s) to it.

The pointers are R_MIPS_32 relocations (base delta is added at load), so we
ONLY rewrite words that carry such a relocation and currently equal the
string's vaddr -- storing the pool vaddr, which the loader then relocates
onto the pool. Nothing existing is shifted (pool is purely appended).
"""
import struct, collections

POOL_VADDR = 0x881000          # page-aligned, above PH1 bss end (0x880848)
RELOC_OFF = 0x29fb80
RELOC_SIZE = 0xae0b0


def _phdr(d, i):
    return struct.unpack_from('<8I', d, 0x34 + i * 32)


def _vaddr_to_file(v):
    return v + (0x100 if v >= 0x1dcc00 else 0xc0)


def _reloc_pointer_map(d):
    """{stored_value: [file_offsets]} for every R_MIPS_32 (type 2) pointer word."""
    ph = [_phdr(d, i) for i in range(3)]
    m = collections.defaultdict(list)
    for p in range(RELOC_OFF, RELOC_OFF + RELOC_SIZE, 8):
        off, info = struct.unpack_from('<II', d, p)
        if info & 0xff != 2:
            continue
        vaddr = ph[(info >> 8) & 0xff][2] + off
        fo = _vaddr_to_file(vaddr)
        if 0 <= fo + 4 <= len(d):
            m[struct.unpack_from('<I', d, fo)[0]].append(fo)
    return m


def add_pool_and_relocate(boot, items):
    b = bytearray(boot)
    st = collections.Counter()
    ptr_map = _reloc_pointer_map(b)
    place = [(jp, en) for jp, en in items if len(en) > len(jp)]
    pool = bytearray(); en_off = {}
    for jp, en in place:
        if en not in en_off:
            en_off[en] = len(pool); pool += en + b'\x00'
    while len(pool) % 4:
        pool.append(0)
    pool_file = len(b)
    for jp, en in place:
        # find EVERY standalone (NUL-bounded) occurrence, not just the first:
        # single-kanji labels (elements, slots, tabs) and repeated stat labels
        # have 2-11 copies each, and every copy needs its data pointer(s)
        # repointed to the one pooled English string or that copy stays JP.
        newp = struct.pack('<I', POOL_VADDR + en_off[en])
        i = 0; occ = 0; rewritten = 0
        while True:
            j = b.find(jp + b'\x00', i)
            if j < 0:
                break
            i = j + 1
            if not (j == 0 or b[j - 1] == 0):
                continue
            occ += 1
            svaddr = j - (0x100 if j >= 0x1dcd00 else 0xc0)
            hits = ptr_map.get(svaddr, [])
            for fo in hits:
                b[fo:fo + 4] = newp
            rewritten += len(hits)
        if occ == 0:
            st['not_found'] += 1
        elif rewritten == 0:
            st['no_reloc_pointer'] += 1
        else:
            st['relocated'] += 1; st['pointers_rewritten'] += rewritten
    b += pool
    struct.pack_into('<8I', b, 0x34 + 3 * 32,
                     1, pool_file, POOL_VADDR, POOL_VADDR, len(pool), len(pool), 4, 0x40)
    struct.pack_into('<H', b, 0x2c, 4)   # e_phnum = 4
    st['pool_bytes'] = len(pool)
    return bytes(b), st


def relocate_menu(boot, table_path=None):
    import os, importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location('psp_text', os.path.join(here, 'psp_text.py'))
    pt = importlib.util.module_from_spec(spec); spec.loader.exec_module(pt)
    items = []
    for line in open(table_path or os.path.join(here, 'psp_menu.tsv'), encoding='utf-8'):
        if line.startswith('#'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) < 2:
            continue
        try:
            jb = pt.encode_line(p[0].replace('\\n', '\n')); eb = pt.encode_line(p[1].replace('\\n', '\n'), dte=True)
        except Exception:
            continue
        if len(eb) > len(jb):
            items.append((jb, eb))
    return add_pool_and_relocate(boot, items)


if __name__ == '__main__':
    import sys
    out, st = relocate_menu(open(sys.argv[1], 'rb').read())
    print('menu pool:', dict(st))
