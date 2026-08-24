#!/usr/bin/env python3
"""Replace files inside a PSP UMD ISO (plain ISO9660, no Joliet), in Python.

    psp_iso.py replace IN.iso OUT.iso /PSP_GAME/USRDIR/file.fpb=new.fpb [/PSP_GAME/SYSDIR/EBOOT.BIN=boot.bin ...]
    psp_iso.py list IN.iso
    psp_iso.py extract IN.iso /PSP_GAME/SYSDIR/BOOT.BIN OUTFILE

A replacement that fits in the file's original sector span is written in
place (rest of the span zeroed). A larger one is appended at the end of the
image, sector aligned, and the directory record's extent and the volume
space size in the primary volume descriptor are updated. Same idea as
UMDReplace, but cross-platform.
"""
import sys, os, struct, shutil

SECTOR = 0x800

def read_dir(f, lba, size):
    f.seek(lba * SECTOR)
    data = f.read(size)
    pos = 0
    while pos < len(data):
        rl = data[pos]
        if rl == 0:
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        rec = data[pos:pos + rl]
        ext_lba = struct.unpack_from('<I', rec, 2)[0]
        ext_size = struct.unpack_from('<I', rec, 10)[0]
        flags = rec[25]
        nl = rec[32]
        name = rec[33:33 + nl]
        if name in (b'\x00', b'\x01'):
            name = b'.' if name == b'\x00' else b'..'
        name = name.decode('ascii', 'replace').split(';')[0]
        yield name, ext_lba, ext_size, flags, lba * SECTOR + pos
        pos += rl

def walk(f, lba, size, prefix=''):
    for name, l, s, flags, recpos in read_dir(f, lba, size):
        if name in ('.', '..'):
            continue
        p = prefix + '/' + name
        if flags & 2:
            yield from walk(f, l, s, p)
        else:
            yield p, l, s, recpos

def listing(f):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    assert pvd[1:6] == b'CD001', 'not an ISO9660 image'
    root = pvd[156:190]
    rl = struct.unpack_from('<I', root, 2)[0]
    rs = struct.unpack_from('<I', root, 10)[0]
    return list(walk(f, rl, rs))

def extract(src, path, outfile):
    with open(src, 'rb') as f:
        files = {p: (l, s) for p, l, s, r in listing(f)}
        if path not in files:
            raise SystemExit('not in image: ' + path)
        lba, size = files[path]
        f.seek(lba * SECTOR)
        with open(outfile, 'wb') as o:
            left = size
            while left:
                chunk = f.read(min(left, 1 << 24))
                o.write(chunk)
                left -= len(chunk)
    print(path, '->', outfile, size, 'bytes')

def both(v):
    return struct.pack('<I', v) + struct.pack('>I', v)

def replace(src, dst, pairs):
    shutil.copyfile(src, dst)
    with open(dst, 'r+b') as f:
        files = {p: (l, s, r) for p, l, s, r in listing(f)}
        f.seek(0, 2)
        image_end = f.tell()
        f.seek(16 * SECTOR + 80)
        vol_sectors = struct.unpack('<I', f.read(4))[0]
        for path, newfile in pairs:
            if path not in files:
                raise SystemExit('not in image: ' + path)
            lba, size, recpos = files[path]
            data = open(newfile, 'rb').read()
            cap = -(-size // SECTOR) * SECTOR
            if len(data) <= cap:
                f.seek(lba * SECTOR)
                f.write(data)
                f.write(b'\x00' * (cap - len(data)))
                where = 'in place'
            else:
                lba = -(-image_end // SECTOR)
                f.seek(lba * SECTOR)
                f.write(data)
                pad = (-len(data)) % SECTOR
                f.write(b'\x00' * pad)
                image_end = f.tell()
                vol_sectors = image_end // SECTOR
                where = 'appended at LBA %d' % lba
            f.seek(recpos + 2)
            f.write(both(lba))
            f.seek(recpos + 10)
            f.write(both(len(data)))
            print(path, '<-', newfile, len(data), 'bytes,', where)
        f.seek(16 * SECTOR + 80)
        f.write(both(vol_sectors))

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'list' and len(a) == 2:
        with open(a[1], 'rb') as f:
            for p, l, s, r in listing(f):
                print('%8d %12d %s' % (l, s, p))
    elif a and a[0] == 'extract' and len(a) == 4:
        extract(a[1], a[2], a[3])
    elif a and a[0] == 'replace' and len(a) >= 4:
        pairs = [x.split('=', 1) for x in a[3:]]
        replace(a[1], a[2], pairs)
    else:
        print(__doc__)
        sys.exit(1)
