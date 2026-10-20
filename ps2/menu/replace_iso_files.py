#!/usr/bin/env python3
"""Write rebuilt files into a copy of the original PS2 ISO, in place.

    python replace_iso_files.py original.iso patched.iso FILE.FPB=FILE_NEW.FPB SLPS_251.72=new_SLPS_251.72 MOVIE.FPB=MOVIE.FPB

Every replaced file keeps its sector on the disc. A file may grow only if it
is the last file on the disc (FILE.FPB is, on Tales of Destiny 2) or still
fits before the next file; anything else is refused. The ISO9660 directory
record and the UDF File Entry of each replaced file get the new size, then
fix_disc_layout.fix gives the image the retail layout (closing anchor,
volume and partition size, whole 16-sector blocks).

Why not rebuild the ISO: a rebuilt image moves every file (the xdelta then
carries the whole disc) and, with Ps2IsoTools, needs fix_disc_layout to look
like retail again. Here everything that is not replaced stays byte for byte
the retail disc, the UDF names keep their retail spelling (file.FPB), and the
patch only carries what really changed. Standard library only.
"""
import argparse
import hashlib
import os
import shutil
import struct
import sys

import fix_disc_layout as layout

SECTOR = layout.SECTOR


class ReplaceError(ValueError):
    """The files cannot be written safely."""


def iso9660_records(image):
    """name -> (absolute byte offset of its directory record, extent, size)."""
    pvd = image.read(16)
    out = {}

    def walk(extent, size, prefix):
        count = (size + SECTOR - 1) // SECTOR
        data = image.read(extent, count)[:size]
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            ext, sz = struct.unpack_from('<I', data, pos + 2)[0], struct.unpack_from('<I', data, pos + 10)[0]
            flags, name_len = data[pos + 25], data[pos + 32]
            name = data[pos + 33:pos + 33 + name_len]
            if name not in (b'\0', b'\1'):
                path = prefix + '/' + name.decode('ascii').split(';')[0].upper()
                if flags & 2:
                    walk(ext, sz, path)
                else:
                    out[path] = (extent * SECTOR + pos, ext, sz)
            pos += length

    walk(struct.unpack_from('<I', pvd, 158)[0], struct.unpack_from('<I', pvd, 166)[0], '')
    return out


def sha1_of(fp, offset, size):
    h = hashlib.sha1()
    fp.seek(offset)
    left = size
    while left:
        chunk = fp.read(min(left, 1 << 24))
        if not chunk:
            break
        h.update(chunk)
        left -= len(chunk)
    return h.hexdigest()


def sha1_file(path):
    with open(path, 'rb') as fp:
        return sha1_of(fp, 0, os.path.getsize(path))


def replace(original, output, replacements):
    """replacements: {'FILE.FPB': source path, ...}. Returns a report dict."""
    names = {'/' + k.upper().lstrip('/'): v for k, v in replacements.items()}
    if os.path.abspath(original) == os.path.abspath(output):
        raise ReplaceError('Write to a copy, not over the original ISO.')
    with open(original, 'rb') as fp:
        image = layout.Image(fp)
        records = iso9660_records(image)
        info = layout.udf(image)
        kept = {p: sha1_of(fp, e * SECTOR, s) for p, (_, e, s) in records.items() if p not in names}
    for path in names:
        if path not in records:
            raise ReplaceError('%s is not on the disc.' % path)
    order = sorted(records, key=lambda p: records[p][1])
    plan = {}
    for path, source in names.items():
        _, ext, old = records[path]
        new = os.path.getsize(source)
        later = [records[p][1] for p in order if records[p][1] > ext]
        if later and ext + (new + SECTOR - 1) // SECTOR > min(later):
            raise ReplaceError('%s grows from %d to %d bytes and would run into the next file; '
                               'only the last file on the disc may grow past its sectors.'
                               % (path[1:], old, new))
        plan[path] = (source, ext, old, new)
    udf_entries = {e[2].upper(): e for e in info['entries'] if not e[3]}
    shutil.copyfile(original, output)
    with open(output, 'r+b') as fp:
        image = layout.Image(fp)
        end = image.sectors
        for path, (source, ext, old, new) in plan.items():
            fp.seek(ext * SECTOR)
            with open(source, 'rb') as src:
                shutil.copyfileobj(src, fp, 1 << 24)
            # zero the rest of the last sector and any sectors the old data used
            stop = max(old, new)
            stop = (stop + SECTOR - 1) // SECTOR * SECTOR
            fp.write(bytes(stop - new))
            end = max(end, ext + (new + SECTOR - 1) // SECTOR)
            rec = records[path][0]
            fp.seek(rec + 10)
            fp.write(struct.pack('<I', new) + struct.pack('>I', new))
            sector, lb, _, _, _ = udf_entries[path]
            fp.seek(sector * SECTOR)
            block = bytearray(fp.read(SECTOR))
            ident = struct.unpack_from('<H', block)[0]
            ea_len, ad_len = struct.unpack_from('<II', block, 168 if ident == layout.TAG_FE else 208)
            if ad_len != 8:
                raise ReplaceError('%s has %d UDF extents; only one is supported.' % (path[1:], ad_len // 8))
            base = (176 if ident == layout.TAG_FE else 216) + ea_len
            length, where = struct.unpack_from('<II', block, base)
            if where + info['start'] != ext:
                raise ReplaceError('ISO9660 and UDF disagree on where %s starts.' % path[1:])
            # retail writes the plain byte count here, also above 1 GB (file.FPB)
            struct.pack_into('<II', block, base, new, where)
            struct.pack_into('<QQ', block, 56, new, (new + SECTOR - 1) // SECTOR)
            fp.seek(sector * SECTOR)
            fp.write(layout.retag(block, lb))
        if end > image.sectors:
            fp.truncate(end * SECTOR)
    problems = layout.fix(output)
    with open(output, 'rb') as fp:
        image = layout.Image(fp)
        records = iso9660_records(image)
        layout_problems, _, _ = layout.plan(image)
        if layout_problems:
            raise ReplaceError('Layout still not retail: %s' % layout_problems)
        for path, (source, ext, old, new) in plan.items():
            _, e, s = records[path]
            if (e, s) != (ext, new) or sha1_of(fp, e * SECTOR, s) != sha1_file(source):
                raise ReplaceError('%s did not land on the disc intact.' % path[1:])
        for path, digest in kept.items():
            _, e, s = records[path]
            if sha1_of(fp, e * SECTOR, s) != digest:
                raise ReplaceError('%s changed although it was not replaced.' % path[1:])
    return {'replaced': {p[1:]: (old, new) for p, (_, _, old, new) in plan.items()},
            'layout_fixed': problems, 'sectors': os.path.getsize(output) // SECTOR}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('original')
    parser.add_argument('output')
    parser.add_argument('files', nargs='+', metavar='NAME=SOURCE')
    args = parser.parse_args(argv)
    pairs = {}
    for item in args.files:
        name, sep, source = item.partition('=')
        if not sep or not os.path.isfile(source):
            parser.error('expected NAME=SOURCE with an existing source file: %s' % item)
        pairs[name] = source
    try:
        report = replace(args.original, args.output, pairs)
    except (ReplaceError, layout.LayoutError, OSError) as exc:
        print('Error: %s' % exc, file=sys.stderr)
        return 2
    for name, (old, new) in report['replaced'].items():
        print('  %s: %d -> %d bytes' % (name, old, new))
    print('Wrote %s (%d sectors), retail disc layout OK' % (args.output, report['sectors']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
