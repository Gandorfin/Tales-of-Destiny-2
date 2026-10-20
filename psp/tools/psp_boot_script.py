#!/usr/bin/env python3
"""English for the event script embedded in BOOT.BIN.

BOOT.BIN carries one SCED script of its own at file offset 0x282F40 (the
scenario scripts all live in file.fpb). It is the shared event for treasure
chests and pickups: item obtained, inventory full, empty chest, Gald and Lens
found, the "take N, discard M / put back" choice for Lens, the game over
epilogue and the title earned message. Its strings are reached only through
the script's own F8 text operands (no relocation points at them), so
psp_menu and the pool never saw them and every chest said 手にいれました
until October 2026.

The table psp_boot_script.tsv maps each decoded Japanese string (line breaks
as {01}) to its English. The text area is rebuilt in place: equal strings are
stored once, the F8 operands are rewritten, and the result must fit the
original text area (it is padded with NUL bytes).

    python psp/tools/psp_boot_script.py BOOT.BIN [OUT.BIN]
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_menu, psp_sced, psp_text

SCED_FILE = 0x282F40
TABLE = os.path.join(HERE, 'psp_boot_script.tsv')


def load_table(path=TABLE):
    out = {}
    for line in open(path, encoding='utf-8'):
        if line.startswith('#') or not line.strip():
            continue
        jp, en = line.rstrip('\n').split('\t')[:2]
        out[jp] = en
    return out


def _end(d, p):
    """Offset of the NUL that ends the string at p, stepping over control
    codes the way psp_text.decode_string does ({16}{A0}{00}... in the title
    message carries a zero byte inside its argument)."""
    while d[p] != 0:
        c = d[p]
        if 0x99 <= c <= 0x9F or 0xE0 <= c <= 0xE4:
            p += 2
        elif c in (0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xB):
            p += 5
        elif c in (0x12, 0x14, 0x15, 0x16, 0x17, 0x18):
            p += 1
            while d[p] not in (0xBC, 0xC0):
                p += 1
            p += 1
        else:
            p += 1
    return p


def _key(d, at):
    return psp_text.decode_string(d, at).replace('\n', '{01}')


def strings(boot):
    """(script bytes, text area start, [(operand offset, string offset)]),
    offsets relative to the script."""
    if boot[SCED_FILE:SCED_FILE + 4] != b'SCED':
        raise ValueError('no SCED script at BOOT 0x%X' % SCED_FILE)
    code, text = struct.unpack_from('<II', boot, SCED_FILE + 4)
    d = boot[SCED_FILE:SCED_FILE + text]
    ops = sorted(psp_sced.text_operands(d))
    d = boot[SCED_FILE:]
    refs = [(at, text + struct.unpack_from('<H', d, at)[0]) for at in ops]
    return d, text, refs


def patch(boot, table=None):
    """boot bytes -> (patched bytes, stats). Strings without an entry keep
    their Japanese bytes."""
    table = load_table() if table is None else table
    d, text, refs = strings(boot)
    end = max(_end(d, t) + 1 for _, t in refs)
    area = end - text
    new = bytearray(); placed = {}; ops = {}; translated = 0
    for at, t in refs:
        jp = d[t:_end(d, t)]
        en = table.get(_key(d, t))
        data = psp_menu.encode_en(en) if en is not None else jp
        translated += en is not None
        if data not in placed:
            placed[data] = len(new)
            new += data + b'\0'
        ops[at] = placed[data]
    if len(new) > area:
        raise ValueError('English event text is %d bytes, the script has room for %d' % (len(new), area))
    b = bytearray(boot)
    base = SCED_FILE
    for at, off in ops.items():
        struct.pack_into('<H', b, base + at, off)
    b[base + text:base + end] = new + bytes(area - len(new))
    return bytes(b), {'strings': len(refs), 'translated': translated, 'bytes': len(new), 'room': area}


def verify(boot, table=None):
    """Decode the patched script and compare with the table."""
    table = load_table() if table is None else table
    d, text, refs = strings(boot)
    want = {psp_text.decode_string(psp_text.encode_line(en.replace('　', '{99}{40}')) + b'\0', 0)
            for en in table.values()}
    return [_key(d, t) for _, t in refs if psp_text.decode_string(d, t) not in want]


if __name__ == '__main__':
    src = open(sys.argv[1], 'rb').read()
    out, st = patch(src)
    print('boot event script:', st)
    if len(sys.argv) > 2:
        open(sys.argv[2], 'wb').write(out)
