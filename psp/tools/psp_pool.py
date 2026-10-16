#!/usr/bin/env python3
"""Append a string pool to BOOT.BIN and relocate overflow menu strings.

Menu strings whose English is longer than the Japanese slot can't be
overwritten in place. This appends a new PT_LOAD segment (pool) at end of
file (a 4th program header fits the zero gap 0x94..0xC0 before .text), at a
fresh vaddr above bss, writes the English there, and repoints the string's
references to it.

The references are relocations (base delta is added at load), so we ONLY
rewrite words that carry one:

* R_MIPS_32 data pointers that currently equal the string's vaddr: they
  get the pool vaddr, which the loader then relocates onto the pool;
* HI16/LO16 code pairs (lui + addiu) that build the string's address in a
  register. A run of HI16 relocations and the LO16 run after it form one
  group: they share the upper half, so a group is rewritten only when every
  LO16 in it is an addiu that builds the address of a relocated string and
  all the new addresses have the same upper half. Other groups that reach a
  relocated string are left on the Japanese and reported.

A string is normally found as a NUL-bounded run; a run that starts right
after other bytes (the tail of a binary record, e.g. 名前入力 at file
0x1C79F8) counts only when a relocation points exactly at it.
Nothing existing is shifted (pool is purely appended).

The pool header is appended as header 3, after the relocation header. That
order only works in PPSSPP: the PSP kernel stops loading at the relocation
header. make_hardware_loadable() reorders the headers for real hardware; the
build runs it last, after every tool that reads the relocation table with
the fixed header indices used here.
"""
import struct, collections

POOL_VADDR = 0x881000          # page-aligned, above PH1 bss end (0x880848)
RELOC_OFF = 0x29fb80
RELOC_SIZE = 0xae0b0
R_MIPS_32, R_MIPS_HI16, R_MIPS_LO16 = 2, 5, 6
ADDIU = 0x09


def _phdr(d, i):
    return struct.unpack_from('<8I', d, 0x34 + i * 32)


def _vaddr_to_file(v):
    return v + (0x100 if v >= 0x1dcc00 else 0xc0)


def _file_to_vaddr(f):
    return f - (0x100 if f >= 0x1dcd00 else 0xc0)


def _relocs(d):
    """(type, file offset of the relocated word, address segment) per entry."""
    ph = [_phdr(d, i) for i in range(3)]
    for p in range(RELOC_OFF, RELOC_OFF + RELOC_SIZE, 8):
        off, info = struct.unpack_from('<II', d, p)
        typ, ofsb, adrb = info & 0xff, (info >> 8) & 0xff, (info >> 16) & 0xff
        if ofsb > 2:
            continue
        fo = _vaddr_to_file(ph[ofsb][2] + off)
        if 0 <= fo + 4 <= len(d):
            yield typ, fo, adrb


def _reloc_pointer_map(d):
    """{stored_value: [file_offsets]} for every R_MIPS_32 (type 2) pointer word."""
    m = collections.defaultdict(list)
    for typ, fo, adrb in _relocs(d):
        if typ == R_MIPS_32:
            m[struct.unpack_from('<I', d, fo)[0]].append(fo)
    return m


def _code_pair_groups(d):
    """[(hi file offsets, [(lo file offset, target vaddr, opcode)])] for every
    run of HI16 relocations and the LO16 run that completes it, addresses in
    segment 0 only (the pool is addressed the same way)."""
    groups, his, los, seg0 = [], [], [], True

    def close():
        if his and los and seg0:
            groups.append((list(his), list(los)))

    for typ, fo, adrb in _relocs(d):
        if typ == R_MIPS_HI16:
            if los:
                close()
                his.clear(); los.clear(); seg0 = True
            his.append(fo)
            seg0 = seg0 and adrb == 0
        elif typ == R_MIPS_LO16 and his:
            hi = struct.unpack_from('<I', d, his[-1])[0] & 0xffff
            word = struct.unpack_from('<I', d, fo)[0]
            lo = word & 0xffff
            target = ((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xffffffff
            los.append((fo, target, word >> 26))
            seg0 = seg0 and adrb == 0
    close()
    return groups


def _rewrite_code_pairs(b, groups, moved, st, log):
    """Point every code pair group that builds only relocated strings at the
    pool; report groups that also build something else."""
    for his, los in groups:
        if not any(t in moved for _, t, _ in los):
            continue
        new = [moved.get(t) for _, t, _ in los]
        highs = {(n + 0x8000) >> 16 for n in new if n is not None}
        same_lui = len({struct.unpack_from('<I', b, fo)[0] & 0xffff for fo in his}) == 1
        if None in new or any(op != ADDIU for _, _, op in los) or len(highs) != 1 or not same_lui:
            st['code_pairs_left'] += 1
            if log:
                log('menu pool: lui at 0x%X left on the Japanese (its group also builds %s)' % (
                    his[0], ', '.join('0x%X' % _vaddr_to_file(t) for (_, t, _), n in zip(los, new) if n is None)
                    or 'a non-addiu address'))
            continue
        high = highs.pop()
        for fo in his:
            w = struct.unpack_from('<I', b, fo)[0]
            struct.pack_into('<I', b, fo, (w & 0xffff0000) | high)
        for (fo, _, _), n in zip(los, new):
            w = struct.unpack_from('<I', b, fo)[0]
            struct.pack_into('<I', b, fo, (w & 0xffff0000) | (n & 0xffff))
        st['code_pairs_rewritten'] += len(los)


def add_pool_and_relocate(boot, items, log=print):
    b = bytearray(boot)
    if struct.unpack_from('<H', b, 0x2c)[0] != 3:
        raise ValueError('add_pool_and_relocate expects the retail three program headers')
    st = collections.Counter()
    ptr_map = _reloc_pointer_map(b)
    groups = _code_pair_groups(b)
    code_targets = {t for _, los in groups for _, t, _ in los}
    place = [(jp, en) for jp, en in items if len(en) > len(jp)]
    pool = bytearray(); en_off = {}
    for jp, en in place:
        if en not in en_off:
            en_off[en] = len(pool); pool += en + b'\x00'
    while len(pool) % 4:
        pool.append(0)
    pool_file = len(b)
    moved = {}                     # string vaddr -> pool vaddr, for the code pairs
    for jp, en in place:
        # find EVERY standalone occurrence, not just the first: single-kanji
        # labels (elements, slots, tabs) and repeated stat labels have 2-11
        # copies each, and every copy needs its references repointed to the
        # one pooled English string or that copy stays JP.
        newv = POOL_VADDR + en_off[en]
        newp = struct.pack('<I', newv)
        i = 0; occ = 0; rewritten = 0; in_code = 0
        while True:
            j = b.find(jp + b'\x00', i)
            if j < 0:
                break
            i = j + 1
            svaddr = _file_to_vaddr(j)
            hits = ptr_map.get(svaddr, [])
            if not (j == 0 or b[j - 1] == 0) and not hits and svaddr not in code_targets:
                continue           # inside another string, and nothing points here
            occ += 1
            for fo in hits:
                b[fo:fo + 4] = newp
            rewritten += len(hits)
            if svaddr in code_targets:
                moved[svaddr] = newv
                in_code += 1
        if occ == 0:
            st['not_found'] += 1
        elif rewritten == 0 and in_code == 0:
            st['no_reloc_pointer'] += 1
        else:
            st['relocated'] += 1; st['pointers_rewritten'] += rewritten
    _rewrite_code_pairs(b, groups, moved, st, log)
    b += pool
    struct.pack_into('<8I', b, 0x34 + 3 * 32,
                     1, pool_file, POOL_VADDR, POOL_VADDR, len(pool), len(pool), 4, 0x40)
    struct.pack_into('<H', b, 0x2c, 4)   # e_phnum = 4
    st['pool_bytes'] = len(pool)
    return bytes(b), st


PT_LOAD, PT_PSP_REL = 1, 0x700000A0
HW_ORDER = (0, 3, 1, 2)        # new header i comes from old header HW_ORDER[i]


def _headers(b):
    n = struct.unpack_from('<H', b, 0x2c)[0]
    return [list(struct.unpack_from('<8I', b, 0x34 + 32 * i)) for i in range(n)]


def hardware_segments(b):
    """The segments the PSP kernel itself loads, following loadcore's
    sceKernelLoadExecutableObject: starting at the first PT_LOAD header it
    takes PT_LOAD headers while they are CONSECUTIVE and stops at the first
    other header, which must be the relocation header. PPSSPP instead loads
    every PT_LOAD header wherever it sits, so a layout can work in PPSSPP and
    fail on a PSP or a PS Vita (Adrenaline runs the real PSP kernel).
    Returns (list of loaded header indices, index of the relocation header)."""
    ph = _headers(b)
    i = 0
    while i < len(ph) and ph[i][0] != PT_LOAD:
        i += 1
    loaded = []
    while i < len(ph) and ph[i][0] == PT_LOAD:
        loaded.append(i)
        i += 1
    return loaded, (i if i < len(ph) else None)


def check_hardware_layout(boot):
    """Raise ValueError unless the PSP kernel would load every PT_LOAD
    segment (the pool included) and apply every relocation. Returns a short
    summary dict."""
    b = boot
    ph = _headers(b)
    loaded, rel = hardware_segments(b)
    all_loads = [i for i, p in enumerate(ph) if p[0] == PT_LOAD]
    if loaded != all_loads:
        raise ValueError('PT_LOAD headers %s are not consecutive: the PSP kernel only loads %s'
                         % (all_loads, loaded))
    if len(loaded) > 3:
        raise ValueError('%d PT_LOAD segments: loadcore refuses 4 or more' % len(loaded))
    if rel is None or ph[rel][0] != PT_PSP_REL:
        raise ValueError('the header after the last PT_LOAD must be the relocation header')
    off, size = ph[rel][1], ph[rel][4]
    used = set()
    for p in range(off, off + size, 8):
        info = struct.unpack_from('<I', b, p + 4)[0]
        used.add((info >> 8) & 0xff)
        used.add((info >> 16) & 0xff)
    bad = sorted(x for x in used if x >= len(loaded))
    if bad:
        raise ValueError('relocations name segment(s) %s; the kernel loads only %d' % (bad, len(loaded)))
    pool = [i for i in loaded if ph[i][2] == POOL_VADDR]
    return {'loaded_segments': len(loaded), 'pool_header': pool[0] if pool else None,
            'relocations': size // 8}


def make_hardware_loadable(boot):
    """Reorder the program headers from the build's [text, data, relocation,
    pool] to [text, pool, data, relocation] so the PSP kernel loads the pool.

    Why: psp_pool appends the pool as header 3, after the relocation header.
    The kernel stops at the relocation header, so on a PSP or a Vita the pool
    was never copied into memory and every pooled string (about 1,800 menu,
    item and arte strings, plus the bold routine's slot table) read whatever
    the game had in that memory: blank labels, random characters, freezes.
    PPSSPP loads every PT_LOAD header and never showed it.

    Why this order: the kernel zero-fills the bss of the LAST loaded segment
    only (loadcore memsets p_memsz - p_filesz for i >= numSegments - 1), so
    the data segment with its 6 MB bss has to stay last; the pool, which has
    no bss, goes between text and data.

    Relocation entries name segments by header index (offset base and
    address base), so every index is remapped with the headers: data 1 -> 2,
    pool 3 -> 1, relocation 2 -> 3. Segment addresses do not change, so the
    loaded image is byte for byte what PPSSPP loaded before. File offsets do
    not move either. Idempotent: an image already in this order is returned
    unchanged. Returns (bytes, info)."""
    b = bytearray(boot)
    ph = _headers(b)
    types = [p[0] for p in ph]
    if types == [PT_LOAD, PT_LOAD, PT_LOAD, PT_PSP_REL] and ph[1][2] == POOL_VADDR:
        return bytes(b), {'reordered': False}
    if types != [PT_LOAD, PT_LOAD, PT_PSP_REL, PT_LOAD] or ph[3][2] != POOL_VADDR:
        raise ValueError('unexpected program headers %s' % ['0x%X' % t for t in types])
    new_index = {old: new for new, old in enumerate(HW_ORDER)}
    for i, old in enumerate(HW_ORDER):
        struct.pack_into('<8I', b, 0x34 + 32 * i, *ph[old])
    off, size = ph[2][1], ph[2][4]
    remapped = 0
    for p in range(off, off + size, 8):
        info = struct.unpack_from('<I', b, p + 4)[0]
        ofsb, adrb = (info >> 8) & 0xff, (info >> 16) & 0xff
        n_ofsb, n_adrb = new_index.get(ofsb, ofsb), new_index.get(adrb, adrb)
        if (n_ofsb, n_adrb) != (ofsb, adrb):
            info = (info & 0xff0000ff) | (n_ofsb << 8) | (n_adrb << 16)
            struct.pack_into('<I', b, p + 4, info)
            remapped += 1
    return bytes(b), {'reordered': True, 'relocations_remapped': remapped}


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
        jp = p[0].replace('\\n', '\n')
        try:
            # U+3000 -> retail code 0x9940 on both sides, same rule as
            # psp_menu.encode_keys / encode_en (the TBL form 0xE499 is kept
            # as a second key)
            keys = [pt.encode_line(jp.replace('　', '{99}{40}'))]
            if '　' in jp:
                keys.append(pt.encode_line(jp))
            eb = pt.encode_line(p[1].replace('\\n', '\n').replace('　', '{99}{40}'))
        except Exception:
            continue
        for jb in keys:
            if len(eb) > len(jb):
                items.append((jb, eb))
    return add_pool_and_relocate(boot, items)


if __name__ == '__main__':
    import sys
    out, st = relocate_menu(open(sys.argv[1], 'rb').read())
    print('menu pool:', dict(st))
