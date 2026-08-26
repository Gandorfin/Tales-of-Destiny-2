#!/usr/bin/env python3
"""PSP font texture (FPB member 00000) codec + lowercase groundwork.

The texture is 4bpp, PSP-swizzled in 16-byte x 8-row blocks, 512x2200 px
(256 bytes/row). Verified round-trip: reswizzle(deswizzle(m)) == m.

deswizzle -> 8bpp gray (nibble value * 17, low nibble first, 512x2200).
Glyph order and codes are in member 00001 (big-endian SJIS per glyph);
the retail font has only 11 of 26 Latin lowercase glyphs (a e g h k m o r
t y z), so a full lowercase pass needs the other 15 drawn to match, then:
(1) place them in free cells (glyph index 2095..2559 are blank), (2) give
those cells codes in member 00001, (3) remap bytes 0x61..0x7A in the u16
ASCII map (BOOT.BIN, near vaddr 0x27DA40) to the new lowercase glyph codes.
"""
W_BYTES = 256
H = 2200


def _swizzle(lin):
    out = bytearray(len(lin)); i = 0
    for by in range(H // 8):
        for bx in range(W_BYTES // 16):
            for ry in range(8):
                base = (by * 8 + ry) * W_BYTES + bx * 16
                out[i:i + 16] = lin[base:base + 16]; i += 16
    return bytes(out)


def _unswizzle(s):
    out = bytearray(len(s)); i = 0
    for by in range(H // 8):
        for bx in range(W_BYTES // 16):
            for ry in range(8):
                base = (by * 8 + ry) * W_BYTES + bx * 16
                out[base:base + 16] = s[i:i + 16]; i += 16
    return bytes(out)


def deswizzle(member):
    """member 00000 bytes -> 8bpp gray bytes (512*2200)."""
    lin = _unswizzle(member)
    out = bytearray(len(lin) * 2)
    for j, b in enumerate(lin):
        out[2 * j] = (b & 0xF) * 17
        out[2 * j + 1] = (b >> 4) * 17
    return bytes(out)


def reswizzle(gray):
    """8bpp gray bytes -> member 00000 bytes."""
    lin = bytearray(len(gray) // 2)
    for j in range(len(lin)):
        lin[j] = ((gray[2 * j + 1] // 17) << 4) | (gray[2 * j] // 17)
    return _swizzle(bytes(lin))


if __name__ == '__main__':
    import sys
    m = open(sys.argv[1], 'rb').read()
    assert reswizzle(deswizzle(m)) == m, 'codec round-trip failed'
    print('font codec OK, round-trip verified on', sys.argv[1])
