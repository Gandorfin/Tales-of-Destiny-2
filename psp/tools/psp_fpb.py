#!/usr/bin/env python3
"""FILE.FPB (PSP, ULJS-00097) extract and pack.

The member table lives in the decrypted executable (BOOT.BIN on the UMD is
already the plain PRX): u32 per member at 0x29531C..0x29E9AC, high bits =
start (sector * 0x800), low 11 bits = remainder; the member ends `remainder`
bytes before the next member's start. Compressed members start with byte
0x04, u32 packed length, u32 unpacked length, then a raw deflate stream.

    psp_fpb.py extract BOOT.BIN file.fpb OUTDIR
        writes OUTDIR/00000.bin ... (decompressed) and OUTDIR/manifest.json
    psp_fpb.py pack BOOT.BIN file.fpb OUTDIR NEW.fpb NEW_BOOT.BIN
        rebuilds the archive; members whose file is unchanged are copied
        byte for byte from the original archive (the game's compressor is
        not stock zlib, so only edited members get recompressed); writes
        the new table into a copy of BOOT.BIN
"""
import sys, os, json, struct, zlib, hashlib

TABLE_START, TABLE_END = 0x29531C, 0x29E9AC
SECTOR = 0x800

def read_table(boot):
    n = (TABLE_END - TABLE_START) // 4
    return list(struct.unpack_from('<%dI' % n, boot, TABLE_START))

def member_ranges(ptrs):
    out = []
    for i in range(len(ptrs) - 1):
        rem = ptrs[i] & 0x7FF
        start = ptrs[i] & 0xFFFFF800
        end = (ptrs[i + 1] & 0xFFFFF800) - rem
        out.append((start, max(0, end - start)))
    return out

def is_compressed(raw):
    if len(raw) > 9 and raw[0] == 4:
        plen, ulen = struct.unpack_from('<II', raw, 1)
        return 9 + plen == len(raw)
    return False

def decompress(raw):
    plen, ulen = struct.unpack_from('<II', raw, 1)
    data = zlib.decompress(raw[9:9 + plen], wbits=-15)
    assert len(data) == ulen
    return data

def compress(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = c.compress(data) + c.flush()
    return b'\x04' + struct.pack('<II', len(packed), len(data)) + packed

def sha1(b):
    return hashlib.sha1(b).hexdigest()

def extract(boot_path, fpb_path, outdir):
    boot = open(boot_path, 'rb').read()
    ptrs = read_table(boot)
    os.makedirs(outdir, exist_ok=True)
    manifest = []
    with open(fpb_path, 'rb') as f:
        for i, (start, size) in enumerate(member_ranges(ptrs)):
            entry = {'index': i, 'start': start, 'stored_size': size}
            if size == 0:
                entry['kind'] = 'dummy'
                manifest.append(entry)
                continue
            f.seek(start)
            raw = f.read(size)
            if is_compressed(raw):
                data = decompress(raw)
                entry['kind'] = 'zlib'
            else:
                data = raw
                entry['kind'] = 'raw'
            entry['sha1'] = sha1(data)
            entry['size'] = len(data)
            with open(os.path.join(outdir, '%05d.bin' % i), 'wb') as o:
                o.write(data)
            manifest.append(entry)
    json.dump(manifest, open(os.path.join(outdir, 'manifest.json'), 'w'), indent=0)
    kinds = {}
    for e in manifest:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
    print('extracted', len(manifest), 'members', kinds)

def pack(boot_path, fpb_path, outdir, new_fpb, new_boot):
    boot = bytearray(open(boot_path, 'rb').read())
    manifest = json.load(open(os.path.join(outdir, 'manifest.json')))
    src = open(fpb_path, 'rb')
    out = open(new_fpb, 'wb')
    entries = []
    pos = 0
    changed = 0
    for e in manifest:
        i = e['index']
        if e['kind'] == 'dummy':
            entries.append((pos, 0))
            continue
        path = os.path.join(outdir, '%05d.bin' % i)
        data = open(path, 'rb').read()
        if sha1(data) == e['sha1']:
            src.seek(e['start'])
            stored = src.read(e['stored_size'])
        else:
            changed += 1
            stored = compress(data) if e['kind'] == 'zlib' else data
        out.write(stored)
        pad = (-len(stored)) % SECTOR
        out.write(b'\x00' * pad)
        entries.append((pos, len(stored)))
        pos += len(stored) + pad
    out.close()
    # table: entry i = start_i | remainder_i, where remainder_i = bytes between
    # the end of member i and the start of member i+1 (0 for dummies)
    ptrs = []
    for k, (start, size) in enumerate(entries):
        nxt = entries[k + 1][0] if k + 1 < len(entries) else pos
        rem = (nxt - (start + size)) if size else 0
        assert 0 <= rem < SECTOR and start % SECTOR == 0
        ptrs.append(start | rem)
    ptrs.append(pos)
    assert len(ptrs) == (TABLE_END - TABLE_START) // 4
    struct.pack_into('<%dI' % len(ptrs), boot, TABLE_START, *ptrs)
    open(new_boot, 'wb').write(boot)
    print('packed', len(entries), 'members,', changed, 'recompressed, archive', pos, 'bytes')

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'extract' and len(a) == 4:
        extract(a[1], a[2], a[3])
    elif a and a[0] == 'pack' and len(a) == 6:
        pack(a[1], a[2], a[3], a[4], a[5])
    else:
        print(__doc__)
        sys.exit(1)
