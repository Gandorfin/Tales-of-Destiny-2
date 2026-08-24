#!/usr/bin/env python3
"""Build a rendering test ISO: a few lines of the opening scene replaced by
ASCII and half-width kana, so we can see how the PSP engine draws them.

    python psp/tools/ascii_test.py "Tales of Destiny 2 (Japan).iso" test_ascii.iso

Reads BOOT.BIN and file.fpb straight from the ISO, patches four records in
scenario package 6470 (Cresta Forest, the first scene) in place, repacks
the archive, and writes the plain executable as both BOOT.BIN and EBOOT.BIN.
Nothing else changes. Start a new game and look at Cinnamon's first lines.
"""
import sys, os, json, struct, zlib, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_fpb, psp_iso

TBL = json.load(open(os.path.join(HERE, '..', '..', 'ps2', 'PyTOD2', 'TBL.json'), encoding='utf-8'))
INV = {}
for k, v in TBL.items():
    INV.setdefault(v, int(k))

def enc(s):
    return b''.join(struct.pack('>H', INV[c]) for c in s)

# (Japanese prefix to find, replacement bytes; fitted to the record length)
TESTS = [
    ('はやく、はやく', b'Hurry, hurry!'),
    ('だいじょぶかっ', b'abcdefghijklmnopqrstuvwxyz0123456789'),
    ('わかってる', b'ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789'),
    ('立てるな', b'\xb1\xb2\xb3\xb4\xb5 \xb6\xb7\xb8\xb9\xba \xcb\xdb\xa6'),  # ｱｲｳｴｵ ｶｷｸｹｺ ﾋﾛｦ
]
SCPK_INDEX = 6470

def patch_scpk(scpk):
    n = struct.unpack_from('<I', scpk, 8)[0]
    sizes = list(struct.unpack_from('<%dI' % n, scpk, 16))
    assert 16 + 4 * n + sum(sizes) == len(scpk)
    members = []
    p = 16 + 4 * n
    for s in sizes:
        members.append(scpk[p:p + s])
        p += s
    last = members[-1]
    packed = last[:1] == b'\x04'
    sced = bytearray(zlib.decompress(last[9:], wbits=-15) if packed else last)
    assert sced[:4] == b'SCED'
    for jp, new in TESTS:
        k = sced.find(enc(jp))
        assert k >= 0, jp
        e = sced.index(b'\x00', k)
        room = e - k
        new = new[:room]
        sced[k:e] = new + b'\x00' * (room - len(new))
        print('patched %-14s -> %r' % (jp, new))
    if packed:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        d = c.compress(bytes(sced)) + c.flush()
        members[-1] = b'\x04' + struct.pack('<II', len(d), len(sced)) + d
    else:
        members[-1] = bytes(sced)
    sizes[-1] = len(members[-1])
    return scpk[:16] + struct.pack('<%dI' % n, *sizes) + b''.join(members)

def main(iso, out_iso):
    work = tempfile.mkdtemp(prefix='tod2psp_')
    boot = os.path.join(work, 'BOOT.BIN')
    fpb = os.path.join(work, 'file.fpb')
    psp_iso.extract(iso, '/PSP_GAME/SYSDIR/BOOT.BIN', boot)
    psp_iso.extract(iso, '/PSP_GAME/USRDIR/file.fpb', fpb)
    scpk, kind = psp_fpb.read_member(fpb, open(boot, 'rb').read(), SCPK_INDEX)
    assert scpk[:4] == b'SCPK', 'member %d is not the expected scenario package' % SCPK_INDEX
    new_scpk = patch_scpk(scpk)
    new_fpb = os.path.join(work, 'new.fpb')
    new_boot = os.path.join(work, 'new_BOOT.BIN')
    psp_fpb.repack(boot, fpb, new_fpb, new_boot, lambda i, k: new_scpk if i == SCPK_INDEX else None)
    psp_iso.replace(iso, out_iso, [
        ('/PSP_GAME/USRDIR/file.fpb', new_fpb),
        ('/PSP_GAME/SYSDIR/BOOT.BIN', new_boot),
        ('/PSP_GAME/SYSDIR/EBOOT.BIN', new_boot),
    ])
    for f in (boot, fpb, new_fpb, new_boot):
        os.remove(f)
    os.rmdir(work)
    print('wrote', out_iso)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
