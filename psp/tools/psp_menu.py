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


def encode_keys(jp):
    """Byte forms a Japanese key can have in BOOT.BIN. Retail menu strings
    write the full-width space U+3000 as 0x9940, the TBL encodes it as the
    filler 0xE499; a key with a space was never found before this rule
    (the shop names, scene titles and others stayed Japanese until 0.3.2)."""
    out = [psp_text.encode_line(jp.replace('　', '{99}{40}'))]
    if '　' in jp:
        out.append(psp_text.encode_line(jp))
    return out


def patch_menu(boot, table=None):
    """boot bytes -> patched bytes; returns (bytes, stats)."""
    if table is None:
        table = load_table()
    b = bytearray(boot)
    st = collections.Counter()
    # de-dup by jp, longest english first is irrelevant; each jp overwrites its slots
    for jp, en in table:
        try:
            keys = encode_keys(jp)
            eb = encode_en(en)
        except Exception:
            st['encode_error'] += 1
            continue
        jb = keys[0]
        if not jb or len(eb) > len(jb):
            st['overflow_skipped'] += 1
            continue
        hit = 0
        for jb in keys:
            pad = jb + b'\x00'  # the stored string is NUL-terminated
            rep = eb + b'\x00' * (len(jb) - len(eb)) + b'\x00'
            i = 0
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
    b, st['fullwidth_to_ascii'] = fullwidth_to_ascii(bytes(b))
    return b, st


FULLWIDTH = ('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'
             '０１２３４５６７８９－．／：！？（）＆＋％＝，')


def _fullwidth_codes():
    """{2-byte code: ASCII byte} for the full-width Latin characters, plus
    the menu full-width space 0x9940."""
    out = {b'\x99\x40': b' '}
    for k, v in psp_text.TBL.items():
        if len(v) == 1 and v in FULLWIDTH:
            out[int(k).to_bytes(2, 'big')] = bytes([ord(v) - 0xFEE0])
    return out


STRING_AREAS = ((0x194840, 0x1DCCB0), (0x1DCD00, 0x29FB7C))   # .rodata, .data (file offsets)
MAX_LABEL = 16


def fullwidth_to_ascii(boot, areas=STRING_AREAS):
    """Rewrite every standalone string (NUL before and after) that consists
    only of full-width Latin letters, digits, punctuation and spaces as
    ASCII, in place (ASCII is half the bytes, so it always fits).

    Why: the variable width font gives ASCII proportional Latin glyphs, and
    full-width codes share those glyph cells but keep a full cell advance,
    so labels such as ＮＥＷ　ＧＡＭＥ, ＨＰ, ＧＲＡＤＥ would show narrow
    letters with wide gaps. As ASCII they take the proportional path.
    Returns (bytes, number of strings)."""
    codes = _fullwidth_codes()
    b = bytearray(boot)
    n = 0
    for start, end in areas:
        end = min(end, len(b))
        i = max(start, 1)
        while i < end - 2:
            if b[i - 1] != 0:
                i += 1
                continue
            j, out = i, bytearray()
            while j + 1 < end and bytes(b[j:j + 2]) in codes:
                out += codes[bytes(b[j:j + 2])]
                j += 2
            alnum = sum(1 for c in out if 48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122)
            # longer runs are data (the name entry keyboard's alphabet), not labels
            if j < end and b[j] == 0 and 2 <= alnum and len(out) <= MAX_LABEL:
                b[i:j] = bytes(out) + bytes(j - i - len(out))
                n += 1
                i = j
            else:
                i += 1
    return bytes(b), n


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    out, st = patch_menu(open(src, 'rb').read())
    open(dst, 'wb').write(out)
    print('menu patch:', dict(st))
