"""Patch name and version on the PSP title screen.

    python3 psp/tools/psp_title.py BOOT.BIN file.fpb --version 0.1.0 [--out 00002.bin] [--preview strip.png]

build_psp.py calls this when given --version. The copyright strip under the
title menu is a 128x32 4-bit TM2 texture, member 1 of archive member 00002
(the title pack: u32 count, u32 offsets, then deflate-wrapped members, the
same eight textures as the PS2 00021.pak3). The Japanese designer credit on
line one is redrawn as "Green Gel Patch vX.Y.Z" with the condensed style of
ps2/menu/title_credit.py; the NBGI line stays as it is. Only pixel data
changes, the texture keeps its size and palette.
"""
import os, sys, struct, zlib, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'ps2', 'menu'))
import psp_fpb
import title_credit as T

PAK_INDEX = 2        # file.fpb member holding the title pack
STRIP_MEMBER = 1     # pack member with the copyright strip
STRIP_SIZE = (128, 32)
DEFAULT_LABEL = 'Green Gel Patch v%s'

def parse_pak(data):
    """[(offset, exact member bytes)] of an offsets-only pack."""
    n = struct.unpack_from('<I', data, 0)[0]
    if not 1 <= n <= 256 or 4 + 4 * n > len(data):
        raise T.TitleError('not an offsets pack')
    offs = [struct.unpack_from('<I', data, 4 + 4 * k)[0] for k in range(n)] + [len(data)]
    out = []
    for k in range(n):
        a, b = offs[k], offs[k + 1]
        if not (4 + 4 * n <= a <= b <= len(data)):
            raise T.TitleError('bad pack offsets')
        blob = data[a:b]
        if len(blob) > 9 and blob[0] == 4:                 # deflate wrapper: cut the padding
            plen = struct.unpack_from('<I', blob, 1)[0]
            if 9 + plen <= len(blob):
                blob = blob[:9 + plen]
        out.append((a, blob))
    return out

def build_pak(blobs):
    """Inverse of parse_pak: members 4-byte aligned, like the originals."""
    pos = 4 + 4 * len(blobs)
    offs, body = [], bytearray()
    for b in blobs:
        offs.append(pos)
        pad = (-len(b)) % 4
        body += b + b'\x00' * pad
        pos += len(b) + pad
    return struct.pack('<I', len(blobs)) + b''.join(struct.pack('<I', o) for o in offs) + bytes(body)

def patch_pak(pak, label):
    """Title pack bytes -> (new pack, new strip, info)."""
    members = parse_pak(pak)
    if len(members) <= STRIP_MEMBER:
        raise T.TitleError('title pack has only %d members' % len(members))
    blob = members[STRIP_MEMBER][1]
    if not psp_fpb.is_compressed(blob):
        raise T.TitleError('strip member is not deflate-wrapped')
    strip = psp_fpb.decompress(blob)
    pal, idx, w, h = T.decode_strip(strip)
    if (w, h) != STRIP_SIZE:
        raise T.TitleError('member %d is %dx%d, not the %dx%d copyright strip'
                           % (STRIP_MEMBER, w, h, STRIP_SIZE[0], STRIP_SIZE[1]))
    new_strip, info = T.draw_label(strip, label, 'psp')
    new_blob = psp_fpb.compress(new_strip)
    if psp_fpb.decompress(new_blob) != new_strip:
        raise T.TitleError('compression round trip failed')
    blobs = [b for _, b in members]
    blobs[STRIP_MEMBER] = new_blob
    out = build_pak(blobs)
    rebuilt = parse_pak(out)
    for k, ((_, a), (_, b)) in enumerate(zip(members, rebuilt)):
        if k != STRIP_MEMBER and a != b:
            raise T.TitleError('member %d changed unexpectedly' % k)
    if T.rows_below_band(psp_fpb.decompress(rebuilt[STRIP_MEMBER][1])) != T.rows_below_band(strip):
        raise T.TitleError('the copyright line changed, refusing to write')
    info.update(members=len(members), old_size=len(pak), new_size=len(out))
    return out, new_strip, info

def build_member(boot_path, fpb_path, label, log=print):
    """New (raw) bytes for archive member PAK_INDEX, for build_psp's extra dict."""
    boot = open(boot_path, 'rb').read()
    pak, kind = psp_fpb.read_member(fpb_path, boot, PAK_INDEX)
    if kind != 'raw':
        raise T.TitleError('member %05d is %s, expected a raw pack' % (PAK_INDEX, kind))
    out, strip, info = patch_pak(pak, label)
    log('title credit: drew %r (%d of %d px), pack %d -> %d bytes'
        % (info['label'], info['right'], info['width'], info['old_size'], info['new_size']))
    return out, strip

def label_for(version=None, label=None):
    if label:
        return label
    if not version:
        raise T.TitleError('give a version or a label')
    return DEFAULT_LABEL % version.lstrip('vV')

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[1])
    ap.add_argument('boot'); ap.add_argument('fpb')
    ap.add_argument('--version'); ap.add_argument('--label')
    ap.add_argument('--out', help='write the new member 00002 here')
    ap.add_argument('--preview', metavar='PNG', help='write the new strip as a PNG (3x)')
    a = ap.parse_args(argv)
    try:
        out, strip = build_member(a.boot, a.fpb, label_for(a.version, a.label))
    except T.TitleError as e:
        print('error:', e)
        return 1
    if a.out:
        open(a.out, 'wb').write(out); print('wrote', a.out)
    if a.preview:
        T.write_png(a.preview, strip, 3); print('preview', a.preview)
    return 0

if __name__ == '__main__':
    sys.exit(main())
