#!/usr/bin/env python3
"""Scenario and skit text for the PSP version: extract, match against the
PS2 translation, insert, rebuild the archive.

    psp_text.py extract BOOT.BIN file.fpb WORK
        WORK/scenario/06470.txt, WORK/skit/00213.txt (PS2 TXT format: one
        record per block, blocks separated by a dashed line) and
        WORK/pointers.json (which member holds the SCED and where each
        record's pointer sits, so build never rescans)
    psp_text.py verify BOOT.BIN file.fpb WORK
        decodes a built archive with the saved pointers and compares every
        record with WORK/*_en/*.txt
    psp_text.py match WORK [ps2root]
        writes WORK/scenario_en/*.txt and WORK/skit_en/*.txt: every record
        whose Japanese exists in the translated PS2 files ("Third pass
        Quality-Safe Output", "third pass skits safe output") gets the English
        from there (Japanese kept as '#' lines), the rest stays Japanese;
        prints coverage and writes WORK/unmatched.tsv
    psp_text.py build BOOT.BIN file.fpb WORK NEW.fpb NEW_BOOT.BIN
        inserts WORK/*_en/*.txt into the SCEDs, rebuilds the SCPK and skit
        packs, repacks the archive (psp_fpb.repack)

Insertion keeps the original text block and appends changed records, redirecting
only instruction-validated text pointers. Files where that would exceed the
64 KB pointer range rebuild the text block. Legacy pointer lists containing
operand-byte false positives are rejected: re-extract them before building.
"""
import sys, os, re, json, struct, zlib, string, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_fpb
import psp_sced

ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
TBL = json.load(open(os.path.join(ROOT, 'ps2', 'PyTOD2', 'TBL.json'), encoding='utf-8'))
ITBL = {v: struct.pack('>H', int(k)) for k, v in TBL.items()}   # last code wins, as in PyTOD2
# codes the PS2 table never listed, derived from the PSP glyph list (member
# 00001) and the game's decoder; decode only, so encoding stays PS2-identical
for k, v in json.load(open(os.path.join(HERE, 'TBL_PSP.json'), encoding='utf-8')).items():
    TBL.setdefault(k, v)
    ITBL.setdefault(v, struct.pack('>H', int(k)))
TAGS = {0x4: 'color', 0x5: 'size', 0x6: 'num', 0x7: 'char', 0x8: 'item', 0x9: 'button'}
ITAGS = {v: k for k, v in TAGS.items()}
NAMES = {1: 'Kyle', 2: 'Reala', 3: 'Loni', 4: 'Judas', 5: 'Nanaly', 6: 'Harold'}
INAMES = {v: k for k, v in NAMES.items()}
COM_TAG = r'(<\w+:?\w+>)'
HEX_TAG = r'(\{[0-9A-F]{2}\})'
PRINTABLE = set(string.digits + string.ascii_letters + string.punctuation + ' ')
DIVIDER = '-----------------------'
JP = re.compile(r'[぀-ヿ一-鿿]')

# ---------------------------------------------------------------- SCED

def sced_pointers(d):
    """Real F8 instructions whose text targets sit right after a NUL.

    An F8 inside a branch, constant, or variable operand is not an opcode.
    Scene 06524's old scan rewrote F3 F8 33 24 into F3 F8 B3 5D, damaging
    a branch and the following instruction and freezing the scene.
    """
    _, tb = psp_sced.regions(d)
    n = len(d)
    out = []
    for p, op, _ in psp_sced.instructions(d):
        if op == 0xF8:
            addr = struct.unpack_from('<H', d, p + 1)[0]
            if 0 < addr < n - tb and d[tb + addr - 1] == 0:
                out.append((p + 1, addr))
    return tb, out


def validate_pointer_addrs(d, addrs):
    """Reject old/corrupt metadata before reading or writing its operands."""
    valid = psp_sced.text_operands(d)
    invalid = [a for a in addrs if a not in valid]
    if invalid or len(addrs) != len(set(addrs)):
        raise ValueError('invalid SCED text-pointer metadata; re-extract before building: '
                         + ', '.join(hex(a) for a in invalid[:12]))
    _, tb = psp_sced.regions(d)
    for at in addrs:
        target = tb + struct.unpack_from('<H', d, at)[0]
        if target >= len(d) or d.find(b'\0', target) < 0:
            raise ValueError(f'invalid SCED text target at operand 0x{at:X}')

def decode_string(d, p):
    out = []
    n = len(d)
    while p < n and d[p] != 0:
        b = d[p]
        if (0x99 <= b <= 0x9F) or (0xE0 <= b <= 0xE4):
            out.append(TBL[str((b << 8) + d[p + 1])])
            p += 2
        elif b == 0x01:
            out.append('\n')
            p += 1
        elif b in (0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xB):
            v = struct.unpack_from('<I', d, p + 1)[0]
            if b == 0x7 and v in NAMES:
                out.append('<%s>' % NAMES[v])
            elif b in TAGS:
                out.append('<%s:%08X>' % (TAGS[b], v))
            else:
                out.append('<%02X:%08X>' % (b, v))
            p += 5
        elif chr(b) in PRINTABLE:
            out.append(chr(b))
            p += 1
        elif 0xA1 <= b < 0xE0:
            out.append(bytes([b]).decode('cp932'))
            p += 1
        elif b in (0x12, 0x14, 0x15, 0x16, 0x17, 0x18):
            out.append('{%02X}' % b)
            p += 1
            while d[p] not in (0xBC, 0xC0):
                out.append('{%02X}' % d[p])
                p += 1
            out.append('{%02X}' % d[p])
            p += 1
        else:
            out.append('{%02X}' % b)
            p += 1
    return ''.join(out)

def encode_line(line):
    txt = bytearray()
    for s in filter(None, re.split(HEX_TAG, line)):
        if re.match(HEX_TAG, s):
            txt.append(int(s[1:3], 16))
            continue
        for c in filter(None, re.split(COM_TAG, s)):
            if re.match(COM_TAG, c):
                if ':' in c:
                    tag, val = c[1:-1].split(':')
                    txt.append(ITAGS[tag] if tag in ITAGS else int(tag, 16))
                    txt += struct.pack('<I', int(val[:8], 16))
                else:
                    name = c[1:-1]
                    if name not in INAMES:
                        name = {k.lower(): k for k in INAMES}.get(name.lower())
                    if name is None:
                        raise ValueError('unknown tag %s in line %r' % (c, line))
                    txt.append(0x7)
                    txt += struct.pack('<I', INAMES[name])
            else:
                for ch in c:
                    txt += ITBL[ch] if ch in ITBL else ch.encode('cp932')
    return bytes(txt)

def encode_record(lines):
    return b'\x01'.join(encode_line(l) for l in lines) + b'\x00'

def read_txt(path):
    """List of records; each record = list of text lines (no '#' lines)."""
    recs, cur = [], []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('#'):
            continue
        if DIVIDER in line:
            recs.append(cur)
            cur = []
        else:
            cur.append(line)
    return recs

def read_txt_pairs(path):
    """List of (japanese lines, english lines) per record."""
    recs, jp, en = [], [], []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if DIVIDER in line:
            recs.append((jp, en))
            jp, en = [], []
        elif line.startswith('#'):
            jp.append(line[1:])
        else:
            en.append(line)
    return recs

def extract_sced(d, addrs=None):
    """Records in pointer order. `addrs` (from a previous extraction) pins the
    pointer list, after validating instruction boundaries. Without it,
    instruction decoding determines the genuine F8 text references."""
    tb = struct.unpack_from('<I', d, 8)[0]
    if addrs is None:
        ptrs = sced_pointers(d)[1]
    else:
        validate_pointer_addrs(d, addrs)
        ptrs = [(at, struct.unpack_from('<H', d, at)[0]) for at in addrs]
    return [decode_string(d, tb + addr) for at, addr in ptrs], [at for at, addr in ptrs]

def suspicious_pointers(d, addrs):
    """Legacy translation-selection policy, NOT instruction validation.

    Retain the previous handling of empty/out-of-order strings to avoid
    unrelated translation changes. False opcode hits are rejected separately
    by validate_pointer_addrs; this ordering heuristic alone is not safe.
    """
    tb = struct.unpack_from('<I', d, 8)[0]
    seq = [struct.unpack_from('<H', d, at)[0] for at in addrs]
    out = set()
    for i, a in enumerate(seq):
        if d[tb + a] == 0:
            out.add(i)
            continue
        prev_ok = i == 0 or a >= seq[i - 1]
        next_ok = i + 1 < len(seq) and seq[i + 1] >= a
        if not prev_ok and not next_ok:
            out.add(i)
    return out

def insert_sced(d, records, addrs):
    """Insert `records` (list of line lists, one per pointer address in
    `addrs`, the list saved at extraction).

    Append mode (default): the original text block stays where it is; only
    records whose bytes changed get appended and their pointer redirected.
    Untouched and suspicious pointers keep pointing at the original text.
    Rebuild mode (when append would exceed the 64 KB pointer range): the
    text block is rewritten from scratch, as the PS2 tools do.
    Returns (bytes, mode, skipped)."""
    tb = struct.unpack_from('<I', d, 8)[0]
    validate_pointer_addrs(d, addrs)
    assert len(records) == len(addrs), 'record count %d != pointer count %d' % (len(records), len(addrs))
    susp = suspicious_pointers(d, addrs)
    enc = [encode_record(r) for r in records]
    orig = []
    for at in addrs:
        a = tb + struct.unpack_from('<H', d, at)[0]
        orig.append(d[a:d.index(b'\x00', a) + 1])
    changed = [i for i in range(len(addrs)) if enc[i] != orig[i]]
    out = bytearray(d)
    if out[-1:] != b'\x00':
        out += b'\x00'
    pos = len(out) - tb
    skipped = 0
    if pos + sum(len(enc[i]) for i in changed if i not in susp) < 0x10000:
        for i in changed:
            if i in susp:
                skipped += 1
                continue
            struct.pack_into('<H', out, addrs[i], pos)
            out += enc[i]
            pos += len(enc[i])
        psp_sced.validate_code_changes(d, out)
        return bytes(out), 'append', skipped
    out = bytearray(d[:tb]) + b'\x00'
    pos = 1
    for at, b in zip(addrs, enc):
        assert pos < 0x10000, 'text block over 64 KB'
        struct.pack_into('<H', out, at, pos)
        out += b
        pos += len(b)
    psp_sced.validate_code_changes(d, out)
    return bytes(out), 'rebuild', len(susp)

# ------------------------------------------------------------ containers

def scpk_members(d):
    n = struct.unpack_from('<I', d, 8)[0]
    sizes = struct.unpack_from('<%dI' % n, d, 16)
    assert 16 + 4 * n + sum(sizes) == len(d)
    mem, p = [], 16 + 4 * n
    for s in sizes:
        mem.append(d[p:p + s])
        p += s
    return mem

def scpk_pack(head, members):
    n = len(members)
    return head[:16] + struct.pack('<%dI' % n, *[len(m) for m in members]) + b''.join(members)

def inflate(m):
    """SCPK members are stored 4-byte aligned, so up to 3 bytes of padding may
    follow the deflate stream."""
    if m[:1] == b'\x04' and len(m) > 9:
        plen, ulen = struct.unpack_from('<II', m, 1)
        if 9 + plen <= len(m) < 9 + plen + 4:
            data = zlib.decompress(m[9:9 + plen], wbits=-15)
            if len(data) == ulen:
                return data, True
    return m, False

def deflate(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    d = c.compress(data) + c.flush()
    out = b'\x04' + struct.pack('<II', len(d), len(data)) + d
    return out + b'\x00' * ((-len(out)) % 4)

def pak_members(d):
    n = struct.unpack_from('<I', d, 0)[0]
    ents = [struct.unpack_from('<II', d, 4 + 8 * i) for i in range(n)]
    return [d[o:o + s] for o, s in ents]

def pak_pack(members):
    n = len(members)
    off = 4 + n * 8
    off += (-off) % 16
    out = bytearray(struct.pack('<I', n))
    pos = off
    for m in members:
        out += struct.pack('<II', pos, len(m))
        pos += len(m) + (-len(m)) % 16
    out += b'\x00' * (off - len(out))
    for m in members:
        out += m + b'\x00' * ((-len(m)) % 16)
    return bytes(out)

def is_scpk(d):
    return d[:4] == b'SCPK'

def is_skit_pak(d):
    if len(d) < 8:
        return False
    n = struct.unpack_from('<I', d, 0)[0]
    if not 1 <= n <= 64 or 4 + 8 * n > len(d):
        return False
    for i in range(n):
        o, s = struct.unpack_from('<II', d, 4 + 8 * i)
        if o + 4 <= len(d) and d[o:o + 4] == b'SCED':
            return True
    return False

def find_sced(members):
    for i, m in enumerate(members):
        data, packed = inflate(m)
        if data[:4] == b'SCED':
            return i, data, packed
    return None, None, None

# --------------------------------------------------------------- commands

def write_txt(path, records):
    with open(path, 'w', encoding='utf-8') as o:
        for r in records:
            o.write(r + '\n' + DIVIDER + '\n')

def extract(boot_path, fpb_path, work):
    boot = open(boot_path, 'rb').read()
    ranges = psp_fpb.member_ranges(psp_fpb.read_table(boot))
    os.makedirs(os.path.join(work, 'scenario'), exist_ok=True)
    os.makedirs(os.path.join(work, 'skit'), exist_ok=True)
    pointers = {}
    counts = collections.Counter()
    with open(fpb_path, 'rb') as f:
        for i, (start, size) in enumerate(ranges):
            if size == 0:
                continue
            f.seek(start)
            data, _ = inflate(f.read(size))
            if is_scpk(data):
                kind, members = 'scenario', scpk_members(data)
            elif is_skit_pak(data):
                kind, members = 'skit', pak_members(data)
            else:
                continue
            idx, sced, packed = find_sced(members)
            if sced is None:
                continue
            records, addrs = extract_sced(sced)
            write_txt(os.path.join(work, kind, '%05d.txt' % i), records)
            pointers['%05d' % i] = {'kind': kind, 'member': idx, 'records': len(records), 'addrs': addrs}
            counts[kind] += 1
    json.dump(pointers, open(os.path.join(work, 'pointers.json'), 'w'), indent=0)
    print('extracted', dict(counts))

def load_ps2_corpus(ps2root):
    """{kind: {japanese record text: english lines}} from ps2/scenarios and ps2/skits."""
    corpus = {'scenario': {}, 'skit': {}}
    dup = 0
    for kind, folder in (('scenario', 'Third pass Quality-Safe Output'), ('skit', 'third pass skits safe output')):
        d = os.path.join(ps2root, folder)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.txt'):
                continue
            for jp, en in read_txt_pairs(os.path.join(d, fn)):
                if not jp or not en:
                    continue
                key = '\n'.join(jp)
                if key in corpus[kind] and corpus[kind][key] != en:
                    dup += 1
                corpus[kind].setdefault(key, en)
    print('ps2 corpus: %d scenario records, %d skit records (%d translated differently in two places, first kept)'
          % (len(corpus['scenario']), len(corpus['skit']), dup))
    return corpus

def norm_key(lines):
    """Matching key: trailing empty lines and trailing spaces ignored."""
    ls = [l.rstrip(' \u3000') for l in lines]
    while ls and not ls[-1]:
        ls.pop()
    return '\n'.join(ls)

def load_supplement(path):
    """Extra JP-key -> English lines, consulted after the PS2 corpus.
    Rows: kind \t jp_key(\\n escaped) \t english(\\n escaped) \t source."""
    sup = {'scenario': {}, 'skit': {}}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            if len(p) >= 3 and p[0] in sup:
                sup[p[0]][p[1].replace('\\n', '\n')] = p[2].split('\\n')
    return sup


def match(work, ps2root=ROOT):
    corpus = load_ps2_corpus(ps2root)
    corpus = {k: {norm_key(jp.split('\n')): en for jp, en in v.items()} for k, v in corpus.items()}
    supplement = load_supplement(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'psp_supplement.tsv'))
    pointers = json.load(open(os.path.join(work, 'pointers.json')))
    unmatched = open(os.path.join(work, 'unmatched.tsv'), 'w', encoding='utf-8')
    tot = collections.Counter()
    for name, info in sorted(pointers.items()):
        kind = info['kind']
        records = read_txt(os.path.join(work, kind, name + '.txt'))
        dst_dir = os.path.join(work, kind + '_en')
        os.makedirs(dst_dir, exist_ok=True)
        out = []
        for lines in records:
            key = norm_key(lines)
            hit = corpus[kind].get(key)
            if hit is None:
                hit = supplement[kind].get(key)
                if hit is not None:
                    tot['supplement'] += 1
            if hit is not None:
                out.append(['#' + l for l in lines] + hit)
                tot['matched'] += 1
            else:
                out.append(lines)
                if any(JP.search(l) for l in lines):
                    tot['unmatched japanese'] += 1
                    unmatched.write('%s\t%s\t%s\n' % (kind, name, key.replace('\n', '\\n')))
                else:
                    tot['no japanese'] += 1
        with open(os.path.join(dst_dir, name + '.txt'), 'w', encoding='utf-8') as o:
            for r in out:
                o.write('\n'.join(r) + '\n' + DIVIDER + '\n')
    unmatched.close()
    print('records:', dict(tot))

def build(boot_path, fpb_path, work, new_fpb, new_boot, extra=None):
    pointers = json.load(open(os.path.join(work, 'pointers.json')))
    boot = open(boot_path, 'rb').read()
    ranges = psp_fpb.member_ranges(psp_fpb.read_table(boot))
    src = open(fpb_path, 'rb')
    stats = collections.Counter()

    def get_new(i, kind_stored):
        if extra and i in extra:
            return extra[i]
        name = '%05d' % i
        if name not in pointers:
            return None
        info = pointers[name]
        path = os.path.join(work, info['kind'] + '_en', name + '.txt')
        if not os.path.exists(path):
            return None
        records = read_txt(path)
        start, size = ranges[i]
        src.seek(start)
        data, _ = inflate(src.read(size))
        members = scpk_members(data) if info['kind'] == 'scenario' else pak_members(data)
        idx, sced, packed = find_sced(members)
        new_sced, mode, skipped = insert_sced(sced, records, info['addrs'])
        members[idx] = deflate(new_sced) if packed else new_sced
        stats[info['kind']] += 1
        stats[mode] += 1
        if skipped:
            stats['pointers left untranslated (suspicious)' if mode == 'append' else 'suspicious pointers rewritten (rebuild)'] += skipped
            print('  %s %s: %d suspicious pointer(s) %s' % (name, mode, skipped, 'kept on the original text' if mode == 'append' else 'REWRITTEN, check in game'))
        return scpk_pack(data, members) if info['kind'] == 'scenario' else pak_pack(members)

    psp_fpb.repack(boot_path, fpb_path, new_fpb, new_boot, get_new)
    src.close()
    print('rebuilt', dict(stats))

def _canon(lines):
    """decode_string prints a raw byte 0xA1..0xDF as its cp932 halfwidth kana
    while the English may spell the same byte as {XX} (a tag payload such as
    {16}{34}{C0}{C0}). Both mean the same byte, so compare them as {XX}."""
    return [re.sub(r'[｡-ﾟ]', lambda m: '{%02X}' % m.group()[0:1].encode('cp932')[0], l) for l in lines]

def verify(boot_path, fpb_path, work):
    pointers = json.load(open(os.path.join(work, 'pointers.json')))
    boot = open(boot_path, 'rb').read()
    bad = n = 0
    for name, info in sorted(pointers.items()):
        path = os.path.join(work, info['kind'] + '_en', name + '.txt')
        if not os.path.exists(path):
            continue
        data, _ = inflate(psp_fpb.read_member(fpb_path, boot, int(name))[0])
        members = scpk_members(data) if info['kind'] == 'scenario' else pak_members(data)
        idx, sced, packed = find_sced(members)
        got = [_canon(r.split('\n')) for r in extract_sced(sced, info['addrs'])[0]]
        want = [_canon(r) for r in read_txt(path)]
        orig = [_canon(r) for r in read_txt(os.path.join(work, info['kind'], name + '.txt'))]
        susp = suspicious_pointers(sced, info['addrs'])
        n += 1
        ok = len(got) == len(want) and all(g == w or (i in susp and g == o) for i, (g, w, o) in enumerate(zip(got, want, orig)))
        if not ok:
            bad += 1
            print('MISMATCH', name)
    print('verified', n, 'files,', bad, 'mismatching')
    return bad == 0

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'verify' and len(a) == 4:
        sys.exit(0 if verify(a[1], a[2], a[3]) else 1)
    elif a and a[0] == 'extract' and len(a) == 4:
        extract(a[1], a[2], a[3])
    elif a and a[0] == 'match' and len(a) in (2, 3):
        match(a[1], a[2] if len(a) == 3 else ROOT)
    elif a and a[0] == 'build' and len(a) == 6:
        build(a[1], a[2], a[3], a[4], a[5])
    else:
        print(__doc__)
        sys.exit(1)
