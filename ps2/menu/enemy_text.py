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

`build` also translates the enemy names themselves, from enemy_names.csv
(columns slot, japanese, english).  They live in two places:

* the name banner at the start of a battle reads the enemy's own pack:
  every `ENd` member of a .pak1 (members 1, 4, 5 or 7) carries a parameter
  block with a 24-byte name field, the TBL name padded with NULs and one
  data byte last (951 fields in 550 packs on the retail disc).  The English
  name is written into that field, the data byte and the rest of the block
  untouched, longest Japanese name first so デス never matches inside
  デスナイト.
* 08063.pak1 holds one LZSS member starting with `TEKI`, 256 slots of 0x1C
  bytes: a 24-byte name padded with ASCII spaces plus four data bytes.
  It is patched too so both lists agree.
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
NAMES_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'enemy_names.csv')
LITERAL = re.compile(rb'\x0a[\x00-\x0f]')
JP = re.compile(r'[぀-ヿ一-鿿]')

TEKI_FILE = '08063.pak1'
TEKI_STRIDE = 0x1C
TEKI_NAME_BYTES = 24
NAME_FIELD = 24          # enemy-pack name field: name, NUL padding, one data byte


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


# ------------------------------------------- enemy-name fields in packs

def find_name_fields(data, names):
    """Offsets of whole name fields in an unpacked ENd member.

    `names` maps Japanese name -> English.  A hit is the encoded Japanese
    name followed by NULs up to byte NAME_FIELD-1 (the last byte of the
    field is data).  Longer names are claimed first, so a shorter name that
    is only the tail or head of a longer one inside the same field is not
    reported.  Returns [(offset, japanese)] in file order.
    """
    pad_end = NAME_FIELD - 1
    claimed = []
    hits = []
    for jp in sorted(names, key=lambda s: -len(P.encode(s))):
        enc = P.encode(jp)
        if len(enc) >= pad_end:
            continue
        p = data.find(enc)
        while p >= 0:
            end = p + pad_end
            if end < len(data) and data[p + len(enc):end] == b'\0' * (pad_end - len(enc)) \
                    and not any(a <= p < b or a < end <= b for a, b in claimed):
                claimed.append((p, end))
                hits.append((p, jp))
            p = data.find(enc, p + 1)
    return sorted(hits)


def patch_name_fields(raw, names):
    """Translate the name fields in every ENd member of one .pak1.
    Returns (new pack bytes, fields changed); the pack is returned unchanged
    when nothing matched.  Raises ValueError for an English name that does
    not leave room for the terminating NUL."""
    members = parse_pak1(raw)
    if not members:
        return raw, 0
    members = list(members)
    changed = 0
    for i, blob in enumerate(members):
        if not lzss.is_packed(blob):
            continue
        try:
            data = lzss.unpack(blob)
        except Exception:
            continue
        if data[:3] != b'ENd':
            continue
        hits = find_name_fields(data, names)
        if not hits:
            continue
        data = bytearray(data)
        for off, jp in hits:
            enc = P.encode(names[jp])
            if len(enc) > NAME_FIELD - 2:
                raise ValueError('%r is %d bytes, the name field holds %d' % (names[jp], len(enc), NAME_FIELD - 2))
            data[off:off + NAME_FIELD - 1] = enc + b'\0' * (NAME_FIELD - 1 - len(enc))
            changed += 1
        members[i] = lzss.pack(bytes(data), blob[0])
    if not changed:
        return raw, 0
    return build_pak1(members), changed


def build_names(args, names=None):
    """Patch the name fields in every .pak1 of the folder.
    Returns (files patched, fields changed, errors)."""
    if names is None:
        names = {r['japanese']: r['english'] for r in load_csv(NAMES_CSV) if r['english']}
    files = fields = errors = 0
    for name in pak1_files(args.folder):
        path = os.path.join(args.folder, name)
        raw = open(path, 'rb').read()
        try:
            out, changed = patch_name_fields(raw, names)
        except ValueError as e:
            print('  %s: %s' % (name, e))
            errors += 1
            continue
        if not changed:
            continue
        files += 1
        fields += changed
        if args.dry_run:
            continue
        if not args.no_backup and not os.path.exists(path + '.bak'):
            os.replace(path, path + '.bak')
        open(path, 'wb').write(out)
    print('  %s%d enemy names in %d packs' % ('would patch ' if args.dry_run else 'patched ', fields, files))
    return files, fields, errors


# ---------------------------------------------------- enemy-name list

def teki_member(members):
    """Return (index, unpacked TEKI name list) or None."""
    for i, m in enumerate(members):
        if not lzss.is_packed(m):
            continue
        try:
            d = lzss.unpack(m)
        except Exception:
            continue
        if d[:4] == b'TEKI':
            return i, d
    return None


def teki_name(data, slot):
    """Decode the name of one slot (space padding stripped), or None."""
    off = 4 + slot * TEKI_STRIDE
    b = data[off:off + TEKI_NAME_BYTES]
    out = []
    p = 0
    while p < len(b) and b[p]:
        c = b[p]
        if M.LEAD(c):
            if p + 1 >= len(b):
                return None
            k = str((c << 8) | b[p + 1])
            if k not in M.TBL:
                return None
            out.append(M.TBL[k])
            p += 2
        elif 0x20 <= c < 0x7F:
            out.append(chr(c))
            p += 1
        else:
            return None
    return ''.join(out).rstrip()


def build_teki(args):
    """Patch the enemy names in the TEKI list of 08063.pak1. Returns error count."""
    rows = [r for r in load_csv(NAMES_CSV) if r['english']]
    if not rows:
        return 0
    path = os.path.join(args.folder, TEKI_FILE)
    if not os.path.exists(path):
        print('  missing %s (enemy-name list)' % TEKI_FILE)
        return 1
    raw = open(path, 'rb').read()
    members = parse_pak1(raw)
    found = teki_member(members) if members else None
    if found is None:
        print('  %s: no TEKI name list found' % TEKI_FILE)
        return 1
    idx, data = found
    data = bytearray(data)
    changed = skipped = errors = 0
    for r in rows:
        slot = int(r['slot'])
        cur = teki_name(data, slot)
        if cur is None:
            print('  %s slot %d: cannot decode' % (TEKI_FILE, slot))
            errors += 1
            continue
        if cur == r['english']:
            skipped += 1
            continue
        if cur != r['japanese']:
            print('  %s slot %d: file has %r, table expects %r' % (TEKI_FILE, slot, cur, r['japanese']))
            errors += 1
            continue
        try:
            enc = P.encode(r['english'])
        except ValueError as e:
            print('  %s slot %d: %s' % (TEKI_FILE, slot, e))
            errors += 1
            continue
        if len(enc) > TEKI_NAME_BYTES:
            print('  %s slot %d: %r is %d bytes, field is %d' % (TEKI_FILE, slot, r['english'], len(enc), TEKI_NAME_BYTES))
            errors += 1
            continue
        off = 4 + slot * TEKI_STRIDE
        data[off:off + TEKI_NAME_BYTES] = enc + b' ' * (TEKI_NAME_BYTES - len(enc))
        changed += 1
    if changed and not errors:
        members = list(members)
        members[idx] = lzss.pack(bytes(data), 3)
        out = build_pak1(members)
        if args.dry_run:
            print('  would patch %s: %d enemy names (%d -> %d bytes)' % (TEKI_FILE, changed, len(raw), len(out)))
        else:
            if not args.no_backup and not os.path.exists(path + '.bak'):
                os.replace(path, path + '.bak')
            open(path, 'wb').write(out)
            print('  patched %s: %d enemy names' % (TEKI_FILE, changed))
    elif errors:
        print('  %s left untouched (%d problems)' % (TEKI_FILE, errors))
    else:
        print('  %s: all %d enemy names already current' % (TEKI_FILE, skipped))
    return errors


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
    names = load_csv(NAMES_CSV)
    nbad = 0
    for r in names:
        if not r['english']:
            continue
        try:
            enc = P.encode(r['english'])
        except ValueError:
            enc = None
        if enc is None or len(enc) > TEKI_NAME_BYTES:
            nbad += 1
            print('  OVER  %s slot %s: %r' % (TEKI_FILE, r['slot'], r['english']))
    print('%d enemy names, %d with English, %d over the %d-byte field'
          % (len(names), sum(1 for r in names if r['english']), nbad, TEKI_NAME_BYTES))
    return bad + nbad


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
    errors += build_names(args)[2]
    errors += build_teki(args)
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
