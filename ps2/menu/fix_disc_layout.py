#!/usr/bin/env python3
"""Give a rebuilt Tales of Destiny 2 PS2 image the retail disc layout.

    python fix_disc_layout.py check patched.iso
    python fix_disc_layout.py fix patched.iso

Run `fix` on the finished patched ISO (after the font tool, before xdelta).
It changes only file system descriptors and may append up to 15 empty
sectors; no file data moves. `check` changes nothing and lists the problems.

Why: the ISO writer (Ps2IsoTools 1.1.3.0, used by Tod2IsoBuilder) rebuilds a
valid ISO9660 + UDF bridge, which PCSX2 and the PS2 read through ISO9660
without trouble. Its UDF side differs from the retail disc, and the UDF side
is what DVD readers outside the PS2 (a PS3 among them) look at first:

* every file's UDF File Entry says file type 0 ("unspecified"); retail says 5
  (a regular file), and a UDF reader may skip entries that are not files
* the partition is marked access type 0 (unspecified); retail says 1
  (read only, a pressed disc)
* the partition runs over the closing Anchor Volume Descriptor Pointer in the
  last sector; retail ends the partition just before it
* the image is not a whole number of 16-sector DVD ECC blocks; retail is
* the integrity descriptor counts 0 files and 0 directories; retail counts them

Retail layout rules this tool enforces (the retail image passes untouched):
image size is a multiple of 16 sectors and equals the ISO9660 volume size;
anchors at sector 256 and in the last sector; the partition ends right
before the last anchor and is read only; File Entries say 5 for files and 4
for directories; the integrity descriptor's partition size and file and
directory counts are right; ISO9660 and UDF list the same files at the same
sectors with the same sizes. Descriptor tags get their checksum and CRC
recomputed. Standard library only.
"""
import argparse
import struct
import sys

SECTOR = 2048
ECC_BLOCK = 16
TAG_AVDP, TAG_PD, TAG_LVD, TAG_TD, TAG_LVID = 2, 5, 6, 8, 9
TAG_FSD, TAG_FID, TAG_FE, TAG_EFE = 256, 257, 261, 266
FT_DIR, FT_FILE = 4, 5
ACCESS_READ_ONLY = 1


class LayoutError(ValueError):
    """The image cannot be checked or fixed safely."""


def require(ok, message):
    if not ok:
        raise LayoutError(message)


def crc_itu(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def tag_ok(block, location):
    ident, _, checksum, _, _, crc, crc_len, loc = struct.unpack_from('<HHBBHHHI', block)
    return (sum(block[0:4]) + sum(block[5:16])) & 0xFF == checksum \
        and 16 + crc_len <= len(block) and crc_itu(block[16:16 + crc_len]) == crc \
        and loc == location


def retag(block, location):
    """Set the tag location and recompute CRC and checksum (stored CRC length)."""
    block = bytearray(block)
    crc_len = struct.unpack_from('<H', block, 10)[0]
    struct.pack_into('<I', block, 12, location)
    struct.pack_into('<H', block, 8, crc_itu(block[16:16 + crc_len]))
    block[4] = (sum(block[0:4]) + sum(block[5:16])) & 0xFF
    return bytes(block)


class Image:
    def __init__(self, fp):
        self.fp = fp
        fp.seek(0, 2)
        size = fp.tell()
        require(size % SECTOR == 0 and size >= 300 * SECTOR, 'Not a 2048-byte sector image.')
        self.sectors = size // SECTOR
        self.patches = {}

    def read(self, sector, count=1):
        require(0 <= sector and sector + count <= self.sectors, 'Read past the end of the image.')
        if count == 1 and sector in self.patches:
            return self.patches[sector]
        self.fp.seek(sector * SECTOR)
        return self.fp.read(count * SECTOR)

    def tagged(self, sector, ident, what):
        block = self.read(sector)
        require(struct.unpack_from('<H', block)[0] == ident and tag_ok(block, sector),
                '%s at sector %d is missing or damaged.' % (what, sector))
        return block


def iso9660(image):
    """Primary volume space size and every file: name -> (sector, size)."""
    pvd = image.read(16)
    require(pvd[0] == 1 and pvd[1:6] == b'CD001', 'No ISO9660 primary volume descriptor.')
    files, dirs = {}, 1
    def walk(extent, size, prefix):
        nonlocal dirs
        data = image.read(extent, (size + SECTOR - 1) // SECTOR)[:size]
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            ext, sz = struct.unpack_from('<I', data, pos + 2)[0], struct.unpack_from('<I', data, pos + 10)[0]
            flags, name_len = data[pos + 25], data[pos + 32]
            name = data[pos + 33:pos + 33 + name_len]
            pos += length
            if name in (b'\0', b'\1'):
                continue
            path = prefix + '/' + name.decode('ascii').split(';')[0].upper()
            if flags & 2:
                dirs += 1
                walk(ext, sz, path)
            else:
                files[path] = (ext, sz)
    walk(struct.unpack_from('<I', pvd, 158)[0], struct.unpack_from('<I', pvd, 166)[0], '')
    return struct.unpack_from('<I', pvd, 80)[0], files, dirs


def udf_name(raw):
    if not raw:
        return ''
    if raw[0] == 8:
        return raw[1:].decode('latin-1')
    require(raw[0] == 16, 'Unknown UDF name encoding.')
    return raw[1:].decode('utf-16-be')


def udf(image):
    """Parse the UDF bridge; returns a dict describing it."""
    avdp = image.tagged(256, TAG_AVDP, 'UDF anchor')
    main_len, main_loc, res_len, res_loc = struct.unpack_from('<IIII', avdp, 16)
    info = {'anchor': avdp, 'pds': [], 'lvds': []}
    for loc, length in ((main_loc, main_len), (res_loc, res_len)):
        for sector in range(loc, loc + length // SECTOR):
            block = image.read(sector)
            ident = struct.unpack_from('<H', block)[0]
            if ident == 0:
                break
            require(tag_ok(block, sector), 'UDF descriptor at sector %d is damaged.' % sector)
            if ident == TAG_PD:
                info['pds'].append(sector)
            elif ident == TAG_LVD:
                info['lvds'].append(sector)
            elif ident == TAG_TD:
                break
    require(info['pds'] and info['lvds'], 'UDF partition or logical volume descriptor missing.')
    pd = image.read(info['pds'][0])
    info['access'], info['start'], info['length'] = struct.unpack_from('<III', pd, 184)
    lvd = image.read(info['lvds'][0])
    require(struct.unpack_from('<I', lvd, 212)[0] == SECTOR, 'UDF block size is not 2048.')
    fsd_lb = struct.unpack_from('<I', lvd, 252)[0]
    int_len, int_loc = struct.unpack_from('<II', lvd, 432)
    info['lvid'] = None
    for sector in range(int_loc, int_loc + int_len // SECTOR):
        if struct.unpack_from('<H', image.read(sector))[0] == TAG_LVID:
            image.tagged(sector, TAG_LVID, 'UDF integrity descriptor')
            info['lvid'] = sector
    start = info['start']
    fsd = image.read(start + fsd_lb)       # tags inside the partition carry block numbers
    require(struct.unpack_from('<H', fsd)[0] == TAG_FSD and tag_ok(fsd, fsd_lb),
            'UDF file set descriptor is missing or damaged.')
    entries, files = [], {}

    def entry(lb, path, is_dir):
        sector = start + lb
        block = image.read(sector)
        ident = struct.unpack_from('<H', block)[0]
        require(ident in (TAG_FE, TAG_EFE) and tag_ok(block, lb),
                'UDF file entry for %s is missing or damaged.' % (path or '/'))
        size = struct.unpack_from('<Q', block, 56)[0]
        ea_len, ad_len = struct.unpack_from('<II', block, 168 if ident == TAG_FE else 208)
        base = (176 if ident == TAG_FE else 216) + ea_len
        ad_type = struct.unpack_from('<H', block, 34)[0] & 7
        require(ad_type == 0, 'UDF entry %s does not use short allocation descriptors.' % path)
        extents = []
        for pos in range(base, base + ad_len, 8):
            length, where = struct.unpack_from('<II', block, pos)
            extents.append((where, length))
        entries.append((sector, lb, path, is_dir, block[27]))
        if not is_dir:
            require(extents, 'UDF entry %s has no data.' % path)
            files[path.upper()] = (start + extents[0][0], size)
            return
        data = b''.join(image.read(start + where, ((length & 0x3FFFFFFF) + SECTOR - 1) // SECTOR)
                        [:length & 0x3FFFFFFF] for where, length in extents)
        pos = 0
        while pos + 38 <= len(data) and struct.unpack_from('<H', data, pos)[0] == TAG_FID:
            chars, name_len = data[pos + 18], data[pos + 19]
            icb_lb = struct.unpack_from('<I', data, pos + 24)[0]
            iu_len = struct.unpack_from('<H', data, pos + 36)[0]
            name = udf_name(data[pos + 38 + iu_len:pos + 38 + iu_len + name_len])
            pos += (38 + iu_len + name_len + 3) & ~3
            if not chars & 8:
                entry(icb_lb, path + '/' + name, bool(chars & 2))

    entry(struct.unpack_from('<I', fsd, 404)[0], '', True)
    info['entries'], info['files'] = entries, files
    return info


def plan(image):
    """Problems found and the sector patches + new size that fix them."""
    volume, iso_files, iso_dirs = iso9660(image)
    info = udf(image)
    problems = []
    require(set(iso_files) == set(info['files']),
            'ISO9660 and UDF list different files: %s'
            % sorted(set(iso_files) ^ set(info['files'])))
    for path, where in iso_files.items():
        require(info['files'][path] == where,
                'ISO9660 and UDF disagree on %s: %s vs %s' % (path, where, info['files'][path]))
    data_end = max(ext + (size + SECTOR - 1) // SECTOR for ext, size in iso_files.values())
    if volume != image.sectors:
        problems.append('ISO9660 volume size %d, image has %d sectors' % (volume, image.sectors))
    sectors = -(-max(image.sectors, data_end + 1) // ECC_BLOCK) * ECC_BLOCK
    if sectors != image.sectors:
        problems.append('image is %d sectors, not whole 16-sector DVD blocks (needs %d)'
                        % (image.sectors, sectors))
    last = sectors - 1
    patches = {}
    old_last = image.sectors - 1
    old_anchor = image.read(old_last)
    old_is_anchor = struct.unpack_from('<H', old_anchor)[0] == TAG_AVDP and tag_ok(old_anchor, old_last)
    if last != old_last or not old_is_anchor:
        if not old_is_anchor:
            problems.append('no UDF anchor in the last sector')
        elif old_last >= data_end:
            patches[old_last] = bytes(SECTOR)
        patches[last] = retag(info['anchor'], last)
    length = last - info['start']
    require(length >= data_end - info['start'], 'File data runs into the last sector.')
    if info['length'] != length:
        problems.append('UDF partition length %d, retail layout ends it before the last anchor (%d)'
                        % (info['length'], length))
    if info['access'] != ACCESS_READ_ONLY:
        problems.append('UDF partition access type %d, retail is 1 (read only)' % info['access'])
    for sector in info['pds']:
        block = bytearray(image.read(sector))
        struct.pack_into('<II', block, 184, ACCESS_READ_ONLY, info['start'])
        struct.pack_into('<I', block, 192, length)
        patched = retag(block, sector)
        if patched != image.read(sector):
            patches[sector] = patched
    wrong = 0
    for sector, lb, path, is_dir, ftype in info['entries']:
        want = FT_DIR if is_dir else FT_FILE
        if ftype != want:
            wrong += 1
            block = bytearray(image.read(sector))
            block[27] = want
            patches[sector] = retag(block, lb)
    if wrong:
        problems.append('%d UDF file entries have the wrong file type' % wrong)
    n_files = sum(1 for e in info['entries'] if not e[3])
    n_dirs = sum(1 for e in info['entries'] if e[3])
    if info['lvid'] is not None:
        block = bytearray(image.read(info['lvid']))
        parts, iu_len = struct.unpack_from('<II', block, 72)
        require(parts == 1 and iu_len >= 40, 'Unexpected UDF integrity descriptor layout.')
        struct.pack_into('<I', block, 80 + 4, length)
        struct.pack_into('<II', block, 80 + 8 + 32, n_files, n_dirs)
        patched = retag(block, info['lvid'])
        if patched != image.read(info['lvid']):
            problems.append('UDF integrity descriptor sizes or counts are stale')
            patches[info['lvid']] = patched
    if volume != sectors:
        sector = 16
        while True:
            block = bytearray(image.read(sector))
            if block[1:6] != b'CD001' or block[0] == 255:
                break
            if block[0] in (1, 2):
                struct.pack_into('<I', block, 80, sectors)
                struct.pack_into('>I', block, 84, sectors)
                patches[sector] = bytes(block)
            sector += 1
    return problems, patches, sectors


def fix(path):
    with open(path, 'r+b') as fp:
        image = Image(fp)
        problems, patches, sectors = plan(image)
        if not problems and not patches:
            return []
        if sectors > image.sectors:
            fp.truncate(sectors * SECTOR)
        for sector, block in sorted(patches.items()):
            require(len(block) == SECTOR, 'Internal error: bad patch size.')
            fp.seek(sector * SECTOR)
            fp.write(block)
        fp.flush()
        image = Image(fp)
        left, again, _ = plan(image)
        require(not left and not again, 'Image still differs after fixing: %s' % left)
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('check', 'fix'))
    parser.add_argument('iso')
    args = parser.parse_args(argv)
    try:
        if args.command == 'check':
            with open(args.iso, 'rb') as fp:
                problems, _, _ = plan(Image(fp))
            for problem in problems:
                print('  ' + problem)
            print('Retail disc layout: %s' % ('OK' if not problems else 'NOT MET, run fix'))
            return 1 if problems else 0
        problems = fix(args.iso)
        for problem in problems:
            print('  fixed: ' + problem)
        print('Retail disc layout: OK' + ('' if problems else ' (nothing to change)'))
        return 0
    except (LayoutError, OSError, struct.error, UnicodeDecodeError) as exc:
        print('Error: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
