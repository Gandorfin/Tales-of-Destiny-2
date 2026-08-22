#!/usr/bin/env python3
"""Extract and rebuild the text of the enemy script packs (enemy arte names
and the lines bosses shout in battle).

Every enemy has a `pak1` pack in FILE.FPB (08063 onward).  A pak1 is

    u32 count
    count x (u32 offset, u32 size)      members 16-byte aligned

and member 1 is a comptoe v3 LZSS stream holding an `ENd` script: a
header with a table of (u32 count, u32 offset) sections, then bytecode.
The script shows text with the opcode `0A`: one argument byte, then a
NUL-terminated string in the usual TBL encoding, inline in the code.
Nothing points at these strings, so moving or growing them would shift
the bytecode that follows.  English is therefore written in place: it
must fit in the Japanese byte count and is padded with spaces to exactly
that length, which leaves every offset in the script untouched.

Usage:
    python enemy_text.py extract <FPB folder> [--csv enemy_translations.csv]
    python enemy_text.py build   <FPB folder> [--csv enemy_translations.csv] [--dry-run] [--no-backup]
    python enemy_text.py check   [--csv enemy_translations.csv]

The CSV columns are file, offset (hex, inside the unpacked member 1),
bytes (the budget), japanese, english.  Rows with an empty english
column are left alone.
"""
import argparse
import csv
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lzss            # noqa: E402
import md1text as M    # noqa: E402
import md1patch as P   # noqa: E402

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'enemy_translations.csv')
LITERAL = re.compile(rb'\x0a[\x00-\x0f]')
JP = re.compile(r'[぀-ヿ一-鿿]')


# ---------------------------------------------------------------- pak1

def parse_pak1(raw):
    n = struct.unpack_from('<L', raw, 0)[0]
    if not (1 <= n <= 64) or len(raw) < 4 + 8 * n:
        return None
    tab = struct.unpack_from('<%dL' % (2 * n), raw, 4)
    members = []
    for k in range(n):
        o, s = tab[2 * k], tab[2 * k + 1]
        if o + s > len(raw):
            return None
        members.append(raw[o:o + s])
    return members


def build_pak1(members):
    n = len(members)
    head = 4 + 8 * n
    pos = (head + 15) & ~15
    out = bytearray(struct.pack('<L', n))
    table = []
    body = bytearray()
    for m in members:
        table.append((pos, len(m)))
        body += m
        pad = (-len(m)) & 15
        body += b'\0' * pad
        pos += len(m) + pad
    for o, s in table:
        out += struct.pack('<LL', o, s)
    out += b'\0' * ((-len(out)) & 15)
    out += body
    return bytes(out)


def script_of(members):
    """Return (index, unpacked ENd script) or None."""
    if len(members) < 2:
        return None
    blob = members[1]
    if not lzss.is_packed(blob):
        return None
    data = lzss.unpack(blob)
    if data[:3] != b'ENd':
        return None
    return data


# ------------------------------------------------------------- strings

def decode_literal(data, p):
    """Decode the NUL-terminated literal at p. Returns (text, end) or None."""
    out = []
    n = len(data)
    while p < n and data[p] != 0:
        b = data[p]
        if M.LEAD(b):
            if p + 1 >= n:
                return None
            k = str((b << 8) | data[p + 1])
            if k not in M.TBL:
                return None
            out.append(M.TBL[k])
            p += 2
        elif b == 0x01:
            out.append('\n')
            p += 1
        elif 0x20 <= b < 0x7F:
            out.append(chr(b))
            p += 1
        else:
            return None
    if p >= n:
        return None
    return ''.join(out), p


def find_literals(data):
    """Yield (offset, byte_count, text) for every 0A-literal with Japanese in it."""
    for m in LITERAL.finditer(data):
        p = m.end()
        r = decode_literal(data, p)
        if not r:
            continue
        text, end = r
        if end - p < 4 or not JP.search(text):
            continue
        yield p, end - p, text


# ----------------------------------------------------------------- CSV

def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'offset', 'bytes', 'japanese', 'english'], lineterminator='\r\n')
        w.writeheader()
        w.writerows(rows)


def pak1_files(folder):
    return sorted(n for n in os.listdir(folder) if n.endswith('.pak1'))


# ------------------------------------------------------------ commands

def cmd_extract(args):
    old = {(r['file'], r['offset']): r['english'] for r in load_csv(args.csv)}
    by_text = {r['japanese']: r['english'] for r in load_csv(args.csv) if r['english']}
    rows = []
    files = 0
    for name in pak1_files(args.folder):
        members = parse_pak1(open(os.path.join(args.folder, name), 'rb').read())
        data = script_of(members) if members else None
        if data is None:
            continue
        found = list(find_literals(data))
        if not found:
            continue
        files += 1
        for off, size, text in found:
            key = (name, '0x%X' % off)
            rows.append({'file': name, 'offset': key[1], 'bytes': size, 'japanese': text,
                         'english': old.get(key) or by_text.get(text, '')})
    write_csv(args.csv, rows)
    print('%d strings in %d files -> %s' % (len(rows), files, args.csv))


def fit(english, budget):
    enc = P.encode(english)
    if len(enc) > budget:
        return None
    return enc + b' ' * (budget - len(enc))


def cmd_check(args):
    rows = load_csv(args.csv)
    bad = 0
    for r in rows:
        if not r['english']:
            continue
        if fit(r['english'], int(r['bytes'])) is None:
            bad += 1
            print('  OVER  %s %s: %d > %s  %r' % (r['file'], r['offset'], len(P.encode(r['english'])), r['bytes'], r['english']))
    print('%d rows, %d with English, %d over budget' % (len(rows), sum(1 for r in rows if r['english']), bad))
    return bad


def cmd_build(args):
    rows = [r for r in load_csv(args.csv) if r['english']]
    by_file = {}
    for r in rows:
        by_file.setdefault(r['file'], []).append(r)
    patched = files = skipped = 0
    errors = 0
    for name, recs in sorted(by_file.items()):
        path = os.path.join(args.folder, name)
        if not os.path.exists(path):
            print('  missing %s' % name)
            errors += 1
            continue
        raw = open(path, 'rb').read()
        members = parse_pak1(raw)
        data = script_of(members) if members else None
        if data is None:
            print('  %s: not an enemy pack' % name)
            errors += 1
            continue
        data = bytearray(data)
        changed = 0
        for r in recs:
            off = int(r['offset'], 16)
            budget = int(r['bytes'])
            cur = decode_literal(data, off)
            if cur is None:
                print('  %s %s: cannot decode' % (name, r['offset']))
                errors += 1
                continue
            if cur[0] == r['japanese']:
                pass
            elif cur[0].rstrip() == r['english']:
                skipped += 1
                continue
            else:
                print('  %s %s: file has %r, table expects %r' % (name, r['offset'], cur[0], r['japanese']))
                errors += 1
                continue
            if cur[1] - off != budget:
                print('  %s %s: budget %d but string is %d bytes' % (name, r['offset'], budget, cur[1] - off))
                errors += 1
                continue
            enc = fit(r['english'], budget)
            if enc is None:
                print('  %s %s: %r does not fit in %d bytes' % (name, r['offset'], r['english'], budget))
                errors += 1
                continue
            data[off:off + budget] = enc
            changed += 1
        if not changed:
            continue
        members = list(members)
        members[1] = lzss.pack(bytes(data), 3)
        out = build_pak1(members)
        patched += changed
        files += 1
        if args.dry_run:
            print('  would patch %s: %d strings (%d -> %d bytes)' % (name, changed, len(raw), len(out)))
            continue
        if not args.no_backup and not os.path.exists(path + '.bak'):
            os.replace(path, path + '.bak')
        open(path, 'wb').write(out)
        print('  patched %s: %d strings' % (name, changed))
    print('%d strings patched in %d files, %d already current, %d errors' % (patched, files, skipped, errors))
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('extract')
    a.add_argument('folder')
    a.add_argument('--csv', default=DEFAULT_CSV)
    a.set_defaults(fn=cmd_extract)
    b = sub.add_parser('build')
    b.add_argument('folder')
    b.add_argument('--csv', default=DEFAULT_CSV)
    b.add_argument('--dry-run', action='store_true')
    b.add_argument('--no-backup', action='store_true')
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser('check')
    c.add_argument('--csv', default=DEFAULT_CSV)
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    rc = args.fn(args)
    sys.exit(1 if rc else 0)


if __name__ == '__main__':
    main()
