#!/usr/bin/env python3
"""Extract and rebuild the text of the SFM script modules (Quiz Book).

The Quiz Book minigame keeps all of its text in FPB members 06171..06301
(type `sfm`).  Each member is a comptoe v3 LZSS stream holding an `SFM_`
module:

    0x00  'SFM_'
    0x04  u32 0x3FC            (constant)
    0x08  u32 total size
    0x0C  u32 code end
    0x10  u32 data section length
    0x14  u32 code start (0x20)
    0x18  u32 data section start
    0x1C  u32 0

The bytecode is a stream of 16-bit words; the word `03 xx` is followed by
a 32-bit immediate.  Strings live in the data section and are referenced
by their section-relative offset, either from aligned u32 pointers inside
data-section tables or from `03 00 <u32>` immediates in the bytecode.
Strings are NUL-separated with no padding, so English that is longer than
the Japanese is appended to the end of the data section and every
reference to the old offset is redirected (header sizes are updated).

Usage:
    python sfm_text.py extract <FPB folder> [--csv quiz_translations.csv]
    python sfm_text.py build   <FPB folder> [--csv quiz_translations.csv] [--dry-run] [--no-backup]
    python sfm_text.py check   [--csv quiz_translations.csv]   # encode every English line

The CSV columns are file, offset (hex, section-relative), japanese,
english.  Rows with an empty english column are left alone.
"""
import argparse
import csv
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lzss            # noqa: E402
import md1text as M    # noqa: E402
import md1patch as P   # noqa: E402

SFM_FILES = ['%05d.sfm' % i for i in range(6171, 6302)]
HDR = struct.Struct('<4s7L')
DEFAULT_CSV = os.path.join(HERE, 'quiz_translations.csv')
# bytecode words that precede the overwhelming majority of string pushes
SAFE_PREV = {b'\x02\x0c', b'\x01\x00', b'\x10\x04'}
STRAY_KANA = re.compile(r'[\uff61-\uff64\uff66-\uff6f\uff71-\uff9f]')
FULLWIDTH = re.compile(r'[\u3000-\u30ff\u4e00-\u9fff\uff01-\uff60]')
PRINTABLE = re.compile(r'^[ -~\n]{2,}$')


class SFM:
    def __init__(self, data):
        magic, ver, total, code_end, data_len, code_start, data_start, zero = HDR.unpack_from(data, 0)
        if magic != b'SFM_' or total != len(data):
            raise ValueError('not an SFM module')
        self.d = bytearray(data)
        self.code_start, self.code_end = code_start, code_end
        self.data_start, self.data_len = data_start, data_len

    @property
    def data_end(self):
        return self.data_start + self.data_len

    def text_at(self, rel):
        """Decode the NUL-terminated string at data offset rel, or None."""
        p = self.data_start + rel
        r = M.decode_at(self.d, p)
        if not r:
            return None
        text, end, jp = r
        if end <= p or end >= self.data_end or self.d[end] != 0:
            return None
        core = re.sub(r'<[^>]*>', '', text)
        if '{' in core or any(ord(c) < 0x20 and c != '\n' for c in core):
            return None
        # binary data decodes as stray half-width kana; real text uses only the
        # half-width dot and long-vowel mark from that range
        if STRAY_KANA.search(core):
            return None
        jp = len(FULLWIDTH.findall(core))
        if jp == 0 and not PRINTABLE.match(core):
            return None
        return text, end, jp

    def strings(self):
        """Map rel offset -> dict(text, end, jp, refs=[(abs pos, kind, prev word)])."""
        out = {}

        def add(rel, pos, kind, prev):
            if rel < 0x20 or rel >= self.data_len:
                return
            if rel not in out:
                r = self.text_at(rel)
                if not r:
                    return
                out[rel] = {'text': r[0], 'end': r[1], 'jp': r[2], 'refs': []}
            out[rel]['refs'].append((pos, kind, prev))

        d = self.d
        for p in range(self.data_start, self.data_end - 3, 4):
            add(struct.unpack_from('<L', d, p)[0], p, 'data', b'')
        p = self.code_start
        prev = b''
        while p < self.code_end - 1:
            if d[p] == 0x03:
                if d[p + 1] == 0x00 and p + 6 <= self.code_end:
                    add(struct.unpack_from('<L', d, p + 2)[0], p + 2, 'code', prev)
                prev = bytes(d[p:p + 2])
                p += 6
            else:
                prev = bytes(d[p:p + 2])
                p += 2
        # drop candidates that start inside another candidate: those "pointers"
        # are plain integers (coordinates etc.) that happen to land mid-string
        outer_end = -1
        for rel in sorted(out):
            if rel < outer_end:
                del out[rel]
            else:
                outer_end = out[rel]['end'] - self.data_start
        # a string may only be relocated when every reference is clearly a
        # pointer: part of a pointer run in a data table, a big offset (ints
        # that large are implausible), or a bytecode push in a known string
        # context.  Anything else is pinned to its in-place budget.
        for rel, s in out.items():
            confident = True
            for pos, kind, prev in s['refs']:
                if rel >= 0x800:
                    continue
                if kind == 'data':
                    near = [struct.unpack_from('<L', d, q)[0] for q in (pos - 4, pos + 4)
                            if self.data_start <= q <= self.data_end - 4]
                    if not any(v in out and v != rel for v in near):
                        confident = False
                elif prev not in SAFE_PREV:
                    confident = False
            s['pinned'] = not confident
        return out

    def budget(self, rel, end):
        """Bytes usable in place: up to the next non-NUL byte, minus the terminator."""
        n = end
        while n < self.data_end and self.d[n] == 0:
            n += 1
        return n - (self.data_start + rel) - 1

    def apply(self, records, log):
        """records: list of (rel, japanese, english). Returns (patched, relocated, overflow)."""
        strs = self.strings()
        moved = []
        count = 0
        overflow = []
        for rel, jp, en in records:
            s = strs.get(rel)
            if s is None or s['text'] != jp:
                raise ValueError('offset 0x%X does not hold %r' % (rel, jp))
            enc = P.encode(en)
            start = self.data_start + rel
            avail = self.budget(rel, s['end'])
            if len(enc) > avail and s['pinned']:
                overflow.append('    OVERFLOW 0x%X: %d > %d bytes (pinned) %r' % (rel, len(enc), avail, en))
                continue
            if len(enc) <= avail:
                slot_end = start
                while slot_end < self.data_end and (slot_end < s['end'] or self.d[slot_end] == 0):
                    slot_end += 1
                self.d[start:slot_end] = enc + b'\0' * (slot_end - start - len(enc))
            else:
                moved.append((rel, enc, s))
            count += 1
        if moved:
            # the old bytes stay as they are: nothing we know of points there,
            # and blanking could only ever destroy something we do not know of
            tail = bytearray()
            for rel, enc, s in moved:
                while (self.data_len + len(tail)) % 4:
                    tail.append(0)
                new_rel = self.data_len + len(tail)
                tail += enc + b'\0'
                for pos, kind, prev in s['refs']:
                    struct.pack_into('<L', self.d, pos, new_rel)
                    if kind == 'code' and prev not in SAFE_PREV:
                        log.append('    review: code ref at 0x%X (prev word %s) 0x%X -> 0x%X %r'
                                   % (pos, prev.hex(), rel, new_rel, s['text'][:20]))
            self.d[self.data_end:self.data_end] = tail
            self.data_len += len(tail)
            struct.pack_into('<L', self.d, 0x08, len(self.d))
            struct.pack_into('<L', self.d, 0x10, self.data_len)
        return count, len(moved), overflow

    def bytes(self):
        return bytes(self.d)


def load_csv(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def write_csv(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'offset', 'budget', 'pinned', 'japanese', 'english'], lineterminator='\r\n')
        w.writeheader()
        w.writerows(rows)


def read_module(path):
    raw = open(path, 'rb').read()
    packed = lzss.is_packed(raw)
    data = lzss.unpack(raw) if packed else raw
    return raw, packed, data


def cmd_extract(args):
    old = {(r['file'], r['offset']): r['english'] for r in load_csv(args.csv)}
    rows = []
    for name in SFM_FILES:
        path = os.path.join(args.folder, name)
        if not os.path.exists(path):
            continue
        try:
            raw, packed, data = read_module(path)
            mod = SFM(data)
        except Exception:
            continue
        strs = mod.strings()
        n = 0
        for rel in sorted(strs):
            s = strs[rel]
            if s['jp'] < 1:
                continue
            off = '0x%X' % rel
            rows.append({'file': name, 'offset': off, 'budget': mod.budget(rel, s['end']),
                         'pinned': 'yes' if s['pinned'] else '', 'japanese': s['text'],
                         'english': old.get((name, off), '')})
            n += 1
        print('%s: %d strings' % (name, n))
    write_csv(args.csv, rows)
    print('%d rows written to %s' % (len(rows), args.csv))


def cmd_check(args):
    bad = 0
    for r in load_csv(args.csv):
        if not r['english']:
            continue
        try:
            P.encode(r['english'])
        except Exception as e:
            bad += 1
            print('%s %s: cannot encode %r (%s)' % (r['file'], r['offset'], r['english'], e))
    print('%d problems' % bad)


def cmd_build(args):
    by_file = {}
    for r in load_csv(args.csv):
        if r['english']:
            by_file.setdefault(r['file'], []).append((int(r['offset'], 16), r['japanese'], r['english']))
    total = moved_total = files = skipped = overflow_total = 0
    for name in SFM_FILES:
        recs = by_file.get(name)
        path = os.path.join(args.folder, name)
        if not recs or not os.path.exists(path):
            continue
        raw, packed, data = read_module(path)
        mod = SFM(data)
        log = []
        try:
            n, moved, overflow = mod.apply(recs, log)
        except ValueError as e:
            strs = mod.strings()
            if any(strs.get(rel) is None or strs[rel]['text'] != jp for rel, jp, en in recs) and \
               all(strs.get(rel) is None or strs[rel]['text'] != jp for rel, jp, en in recs):
                print('  SKIP %s: already patched' % name)
                skipped += 1
                continue
            print('  REFUSE %s: %s' % (name, e))
            skipped += 1
            continue
        out = mod.bytes()
        if packed:
            out = lzss.pack(out, 3)
        print('  %s %s: %d strings, %d relocated, %d -> %d bytes' % (
            'would patch' if args.dry_run else 'patched', name, n, moved, len(raw), len(out)))
        for line in log + overflow:
            print(line)
        overflow_total += len(overflow)
        if not args.dry_run:
            if not args.no_backup and not os.path.exists(path + '.bak'):
                os.rename(path, path + '.bak')
            with open(path, 'wb') as f:
                f.write(out)
        total += n
        moved_total += moved
        files += 1
    print('%d strings patched (%d relocated) in %d files%s, %d files skipped, %d overflow' % (
        total, moved_total, files, ' (dry run)' if args.dry_run else '', skipped, overflow_total))
    if overflow_total:
        sys.exit(1)


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
    args.fn(args)


if __name__ == '__main__':
    main()
