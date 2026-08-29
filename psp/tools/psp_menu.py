#!/usr/bin/env python3
"""Patch menu strings in BOOT.BIN to English (in-place, v1).

3,808 menu strings live in BOOT.BIN .rodata/.data; ~55% have a reuse
translation from the PS2 work (psp_menu.tsv). Because kanji encode to 2
bytes, ~70% of those fit in the original slot, so v1 overwrites each
NUL-terminated occurrence in place (NUL-padded) and leaves the longer ones
Japanese. Overflow relocation (pool + data-pointer rewrite) is a later pass;
~80% of strings do have a rewritable data pointer.
"""
import os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_text

TABLE = os.path.join(HERE, 'psp_menu.tsv')


def load_table(path=TABLE):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding='utf-8'):
        if line.startswith('#'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) >= 2:
            out.append((p[0].replace('\\n', '\n'), p[1].replace('\\n', '\n')))
    return out


def encode_en(en):
    """Encode an English menu string. The full-width space U+3000 must be the
    BOOT code 0x9940 (what every retail menu string uses, a blank cell in both
    fonts); the TBL's own entry for it is a filler code (0xE499) that the menu
    renderers draw as a garbage tile (Battle Memo indent, tactics lines)."""
    return psp_text.encode_line(en.replace('　', '{99}{40}'))


def patch_menu(boot, table=None):
    """boot bytes -> patched bytes; returns (bytes, stats)."""
    if table is None:
        table = load_table()
    b = bytearray(boot)
    st = collections.Counter()
    # de-dup by jp, longest english first is irrelevant; each jp overwrites its slots
    for jp, en in table:
        try:
            jb = psp_text.encode_line(jp)
            eb = encode_en(en)
        except Exception:
            st['encode_error'] += 1
            continue
        if not jb or len(eb) > len(jb):
            st['overflow_skipped'] += 1
            continue
        pad = jb + b'\x00'  # the stored string is NUL-terminated
        rep = eb + b'\x00' * (len(jb) - len(eb)) + b'\x00'
        i = 0
        hit = 0
        while True:
            idx = b.find(pad, i)
            if idx < 0:
                break
            i = idx + 1
            if idx == 0 or b[idx - 1] == 0:      # standalone (NUL before)
                b[idx:idx + len(pad)] = rep
                hit += 1
        if hit:
            st['patched'] += 1
            st['occurrences'] += hit
        else:
            st['not_found'] += 1
    return bytes(b), st


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    out, st = patch_menu(open(src, 'rb').read())
    open(dst, 'wb').write(out)
    print('menu patch:', dict(st))
