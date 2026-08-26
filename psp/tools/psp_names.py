#!/usr/bin/env python3
"""Patch the party-member <name> table in BOOT.BIN to English.

The scenario/skit text uses the `<name>` tag (0x07 + u32 id 1..6) for party
members; the game resolves each id through a 6-entry pointer table to a name
string in .rodata that ships in Japanese (カイル, リアラ ...). NPC speaker
names are literal strings handled by the text pass, but party names come
from this table, so without this they render as katakana in every box.

English names are all <= the Japanese byte length, so each string is
overwritten in place (NUL-padded) and the pointers stay valid.
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_text

NAME_PTR_TABLE = 0x21BD08          # file offset; 6 u32 vaddr pointers, 8-byte stride
EXPECT = ['カイル', 'リアラ', 'ロニ', 'ジューダス', 'ナナリー', 'ハロルド']
ENGLISH = ['Kyle', 'Reala', 'Loni', 'Judas', 'Nanaly', 'Harold']


def patch_names(boot):
    """boot: bytes or bytearray of BOOT.BIN. Returns a patched bytearray."""
    b = bytearray(boot)
    done = 0
    for i, (jp, en) in enumerate(zip(EXPECT, ENGLISH)):
        ptr = struct.unpack_from('<I', b, NAME_PTR_TABLE + i * 8)[0]
        off = ptr + 0xC0
        got = psp_text.decode_string(bytes(b), off)
        if got != jp:
            raise SystemExit('name slot %d: expected %r at 0x%X, found %r '
                             '(offsets shifted; update NAME_PTR_TABLE)' % (i, jp, off, got))
        end = b.index(0, off)
        old_len = end - off
        nb = en.encode('ascii')
        assert len(nb) <= old_len, '%s longer than %s' % (en, jp)
        b[off:off + old_len] = nb + b'\x00' * (old_len - len(nb))
        done += 1
    return b, done


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    out, n = patch_names(open(src, 'rb').read())
    open(dst, 'wb').write(out)
    print('patched %d party names -> %s' % (n, dst))
