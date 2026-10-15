#!/usr/bin/env python3
"""Find the Japanese text a PSP build still shows, including missed copies.

    psp_jpscan.py RETAIL PATCHED OUTDIR [--min-jp N] [--members A-B] [--jobs N]

RETAIL and PATCHED are each a PSP ISO, a folder holding BOOT.BIN (or
new_BOOT.BIN) and file.fpb (or new.fpb), or an explicit BOOT,FPB pair.
A `build_psp.py --keep WORK` folder works directly as PATCHED.

How it works:

1. Both images are unpacked in lockstep: BOOT.BIN, then every FILE.FPB
   member, recursively through the deflate wrapper (0x04 + raw deflate,
   with 4..16 byte alignment padding), SCPK, every validated PAK level,
   offsets packs (u32 n, n offsets, deflate children: the title pack
   00002), sizes packs (u32 n, n sizes, children back to back: the Quiz
   Book packs 06333, 06334, 06366, 06467, also 07310, 09272..09276 and most
   of 09347..09565) and comptoe LZSS v1/v3 streams (202 members, 08331
   onward). Each leaf gets a stable path such as 06470/z/s2/z (s = SCPK
   entry, p = PAK entry, o = offsets pack entry, n = sizes pack entry,
   z = deflate, l = LZSS). Media leaves (RIFF, VAG, MIDI, TIM2, GIM, PNG)
   are listed in graphics.tsv instead of being read as text. Data embedded
   at an offset inside a leaf (map chunks, models, SFM modules) needs no
   unpacking: the string search below reads every offset of every leaf.
2. Every other retail leaf is searched for NUL terminated strings in three
   encodings: the game's glyph table (TBL.json + TBL_PSP.json, with the
   inline control codes), Shift JIS (kana required) and UTF-8.
3. Strings are tied to what references them. BOOT.BIN: every R_MIPS_32
   data pointer and every HI16/LO16 address pair, with the segment base
   each relocation names (data segment relative pointers included).
   SCED scripts: every validated F8 text operand. SFM modules (Quiz Book):
   every data table word and bytecode push that ps2/menu/sfm_text.py
   proves to point at a string. A reference site whose retail target is
   Japanese is compared with the same site in the patched image: same
   text means the game still shows Japanese there.
4. Strings nothing points at are compared by bytes (same offset, then
   anywhere in the patched leaf).
5. All occurrences are grouped by their text. A group where one copy was
   translated and another copy is still Japanese is a MISSED COPY: the
   English already exists, only that second (or third) location was never
   patched. Groups are ranked:
     missed_copy      translated somewhere, still Japanese elsewhere
     known_unapplied  never translated in the build, but a translation
                      exists in a project table (PSP or PS2)
     untranslated     live or unknown Japanese, no translation anywhere
     residue          every copy translated, redirected or unreferenced

Duplicates (Gandorff's main question: which copies did the patch miss):
     duplicates.tsv        every text at 2+ locations (duplicate, triplicate,
                           N copies) with the state of every copy
     leaf_duplicates.tsv   byte identical leaves and raw FPB members stored
                           2+ times, partially patched clusters first
     table_duplicates.tsv  the same ordered run of 3+ strings in two places
                           (the "game reads a second table" case)
     boot_partial.tsv      BOOT strings where some reference sites reach the
                           English and others still the Japanese

Other outputs: summary.md (duplicates section first), groups.tsv (one row
per text), occurrences.tsv (one row per location), graphics.tsv. Reference
kinds in ref_sites: f8 = SCED text operand, sfm = SFM string reference,
ptr0/ptr1 = R_MIPS_32 word relative to segment 0/1, code0/code1 = HI16/LO16
address pair. Only
reading; nothing is written into either image. A full disc takes about 10
minutes with one worker per CPU (--jobs).
"""
import sys, os, re, io, csv, json, struct, zlib, bisect, hashlib, argparse, collections, contextlib, multiprocessing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
with contextlib.redirect_stdout(io.StringIO()):
    import psp_fpb, psp_iso, psp_sced, psp_text
ROOT = psp_text.ROOT
sys.path.insert(0, os.path.join(ROOT, 'ps2', 'menu'))
import lzss     # noqa: E402  comptoe LZSS codec shared with the PS2 tools
import md1text, sfm_text    # noqa: E402  SFM (Quiz Book) module reader of the PS2 tools
TBL = psp_text.TBL
for _k, _v in TBL.items():          # the PSP only codes, so no SFM string hides
    md1text.TBL.setdefault(_k, _v)

# ----------------------------------------------------------------- images

class Image:
    """BOOT.BIN bytes plus random access to FILE.FPB (inside an ISO or not)."""

    def __init__(self, spec):
        self.label = spec
        if ',' in spec:
            boot, fpb = spec.split(',', 1)
            self._open(open(boot, 'rb').read(), fpb, 0)
        elif os.path.isdir(spec):
            def pick(*names):
                for n in names:
                    if os.path.exists(os.path.join(spec, n)):
                        return os.path.join(spec, n)
                raise SystemExit('%s: none of %s' % (spec, ', '.join(names)))
            boot = pick('new_BOOT.BIN', 'BOOT.BIN')
            self._open(open(boot, 'rb').read(), pick('new.fpb', 'file.fpb'), 0)
        else:
            with open(spec, 'rb') as f:
                files = {p: (l, s) for p, l, s, r in psp_iso.listing(f)}
                lba, size = files['/PSP_GAME/SYSDIR/BOOT.BIN']
                f.seek(lba * psp_iso.SECTOR)
                boot = f.read(size)
            self.iso_files = files
            self._open(boot, spec, files['/PSP_GAME/USRDIR/file.fpb'][0] * psp_iso.SECTOR)

    def _open(self, boot, fpb_path, base):
        self.boot = boot
        self.fpb = open(fpb_path, 'rb')
        self.base = base
        self.ranges = psp_fpb.member_ranges(psp_fpb.read_table(boot))

    def iso_file(self, path):
        lba, size = self.iso_files[path]
        self.fpb.seek(lba * psp_iso.SECTOR)
        return self.fpb.read(size)

    def member(self, i):
        start, size = self.ranges[i]
        self.fpb.seek(self.base + start)
        return self.fpb.read(size)

# ------------------------------------------------------------- containers

MEDIA = {b'RIFF': 'wave', b'VAGp': 'vag', b'MThd': 'midi', b'TM2#': 'tim2', b'TM2@': 'tim2',
         b'MIG.': 'gim', b'\x89PNG': 'png', b'PSMF': 'pmf'}
NAMED = {b'SCED': 'sced', b'MCD\0': 'mcd', b'ENd\0': 'enemy-script', b'anp2': 'anp2',
         b'MFH\0': 'mfh', b'MDL@': 'model', b'VCD@': 'vcd', b'SFM_': 'sfm', b'SMO_': 'smo',
         b'BATM': 'batm', b'GR\x14\0': 'gr', b'efD\0': 'efd', b'd2_s': 'd2s'}


def inflate(d):
    if d[:1] == b'\x04' and len(d) > 9:
        plen, ulen = struct.unpack_from('<II', d, 1)
        if 9 + plen <= len(d) < 9 + plen + 16:
            try:
                out = zlib.decompress(d[9:9 + plen], wbits=-15)
            except zlib.error:
                return None
            if len(out) == ulen:
                return out
    return None


def pak(d):
    if len(d) < 12:
        return None
    n = struct.unpack_from('<I', d, 0)[0]
    if not 1 <= n <= 4096 or 4 + 8 * n > len(d):
        return None
    prev, out = 4 + 8 * n, []
    for i in range(n):
        o, s = struct.unpack_from('<II', d, 4 + 8 * i)
        if o < prev or o + s > len(d):
            return None
        prev = o + s
        out.append(d[o:o + s])
    return out


def scpk(d):
    if d[:4] != b'SCPK' or len(d) < 16:
        return None
    n = struct.unpack_from('<I', d, 8)[0]
    if 16 + 4 * n > len(d):
        return None
    sizes = struct.unpack_from('<%dI' % n, d, 16)
    if 16 + 4 * n + sum(sizes) > len(d):
        return None
    out, p = [], 16 + 4 * n
    for s in sizes:
        out.append(d[p:p + s])
        p += s
    return out


def _packed(k):
    """True for a deflate wrapper or a comptoe LZSS header that fits k."""
    if inflate(k) is not None:
        return True
    if k[:1] in (b'\x01', b'\x03') and len(k) > 9:
        inl = struct.unpack_from('<I', k, 1)[0]
        return 9 + inl <= len(k) <= 25 + inl
    return False


def offpack(d):
    """Offsets pack: u32 n, n u32 child offsets (the first right after the
    table, ascending), children up to the next offset. Accepted only when a
    child is deflate wrapped (the title pack 00002)."""
    if len(d) < 12:
        return None
    n = struct.unpack_from('<I', d, 0)[0]
    if not 1 <= n <= 1024 or 4 + 4 * n > len(d):
        return None
    offs = list(struct.unpack_from('<%dI' % n, d, 4))
    if not 4 + 4 * n <= offs[0] <= 4 + 4 * n + 16:
        return None
    offs.append(len(d))
    if any(offs[i] > offs[i + 1] for i in range(n)):
        return None
    kids = [d[offs[i]:offs[i + 1]] for i in range(n)]
    return kids if any(inflate(k) is not None for k in kids) else None


def sizepack(d):
    """Sizes pack: u32 n, n u32 child sizes, children back to back (up to 16
    bytes of padding at the end). Accepted only when a child is compressed."""
    if len(d) < 12:
        return None
    n = struct.unpack_from('<I', d, 0)[0]
    if not 1 <= n <= 1024 or 4 + 4 * n > len(d):
        return None
    sizes = struct.unpack_from('<%dI' % n, d, 4)
    total = 4 + 4 * n + sum(sizes)
    if not total <= len(d) <= total + 16:
        return None
    kids, p = [], 4 + 4 * n
    for size in sizes:
        kids.append(d[p:p + size])
        p += size
    return kids if any(_packed(k) for k in kids) else None


def unlzss(d):
    """Decoded comptoe LZSS v1/v3 stream (9 byte header), or None. The header
    lengths must fit the leaf and the decoder must produce exactly the
    stated length."""
    if len(d) > 9 and d[0] in (1, 3):
        inl, outl = struct.unpack_from('<II', d, 1)
        if inl > 8 and 9 + inl <= len(d) <= 9 + inl + 16 and 16 <= outl <= 16 << 20:
            try:
                out = lzss.decode(d[9:9 + inl], d[0], outl)
            except Exception:
                return None
            if len(out) == outl:
                return out
    return None


def leaves(d, path):
    """Yield (path, bytes) for every leaf below one member."""
    x = inflate(d)
    if x is not None:
        yield from leaves(x, path + '/z')
        return
    for tag, fn in (('s', scpk), ('p', pak), ('o', offpack), ('n', sizepack)):
        m = fn(d)
        if m:
            for i, c in enumerate(m):
                yield from leaves(c, '%s/%s%d' % (path, tag, i))
            return
    x = unlzss(d)
    if x is not None:
        yield from leaves(x, path + '/l')
        return
    yield path, d


def leaf_kind(d):
    return MEDIA.get(d[:4]) or NAMED.get(d[:4]) or 'data'

# ---------------------------------------------------------------- decoding

def is_jp(ch):
    o = ord(ch)
    return 0x3041 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0x3005 <= o <= 0x3007


def decode(d, p, limit=2048):
    """Tolerant game-encoding decoder (unknown codes kept as {XXXX})."""
    out, n, end = [], len(d), min(len(d), p + limit)
    while p < end and d[p] != 0:
        b = d[p]
        if (0x99 <= b <= 0x9F or 0xE0 <= b <= 0xE4) and p + 1 < n:
            code = (b << 8) | d[p + 1]
            out.append(TBL.get(str(code), '{%04X}' % code))
            p += 2
        elif b == 0x01:
            out.append('\n'); p += 1
        elif 0x03 <= b <= 0x0B and p + 5 <= n:
            v = struct.unpack_from('<I', d, p + 1)[0]
            if b == 0x07 and v in psp_text.NAMES:
                out.append('<%s>' % psp_text.NAMES[v])
            else:
                out.append('<%s:%08X>' % (psp_text.TAGS.get(b, '%02X' % b), v))
            p += 5
        elif 0x20 <= b < 0x7F:
            out.append(chr(b)); p += 1
        elif 0xA1 <= b < 0xE0:
            out.append(bytes([b]).decode('cp932')); p += 1
        else:
            out.append('{%02X}' % b); p += 1
    return ''.join(out)


# one string in the game encoding, NUL terminated
_TOK = (rb'[\x99-\x9f\xe0-\xe4][\x40-\xff]|[\x20-\x7e]|\x01|[\xa1-\xdf]'
        rb'|[\x03-\x0b][\x00-\xff]\x00\x00\x00|[\x12\x14-\x18][\x01-\xbb\xbd-\xbf\xc1-\xff]{0,8}[\xbc\xc0]')
RX_TBL = re.compile(rb'(?:' + _TOK + rb')+(?=\x00)')
RX_SJIS = re.compile(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]|[\x20-\x7e])+(?=\x00)')
RX_UTF8 = re.compile(rb'(?:[\xe3-\xe9][\x80-\xbf][\x80-\xbf]|[\x20-\x7e])+(?=\x00)')
RX_JPCODE = re.compile(rb'[\x99-\x9f\xe0-\xe4]')


class Plausible:
    """Character and character pair frequencies from real Japanese (the PS2
    corpus and the project tables): real text uses common characters in
    common pairs, binary noise decoded through the glyph table does not."""

    def __init__(self, texts):
        self.freq, self.pairs, self.known = collections.Counter(), set(), set()
        for t in texts:
            self.known.add(t)
            self.freq.update(ch for ch in t if is_jp(ch))
            self.pairs.update(t[i:i + 2] for i in range(len(t) - 1) if is_jp(t[i]) and is_jp(t[i + 1]))

    def score(self, text):
        jp = [ch for ch in text if is_jp(ch)]
        if not jp:
            return 0.0
        return sum(1 for ch in jp if self.freq[ch] >= 5) / len(jp)

    def ok(self, text, min_jp):
        jp = [ch for ch in text if is_jp(ch)]
        if len(jp) < min_jp or '{' in text.replace('{99}{40}', ''):
            return False
        if norm(text) in self.known:
            return True
        if len(jp) < 2:
            return False        # single characters only as known labels
        if any(0xFF61 <= ord(ch) <= 0xFF9F for ch in text):
            return False        # halfwidth kana: almost always binary noise
        if self.score(text) < 0.85:
            return False
        pairs = [text[i:i + 2] for i in range(len(text) - 1) if is_jp(text[i]) and is_jp(text[i + 1])]
        if len(jp) >= 2 and not pairs:
            return False        # Japanese characters scattered between bytes
        if pairs and sum(1 for x in pairs if x in self.pairs) < 0.8 * len(pairs):
            return False
        # mostly kana or mostly kanji, but not a soup of rare kanji
        kana = sum(1 for ch in jp if ord(ch) < 0x3100)
        if kana == 0 and len(jp) > 6:
            return False
        other = sum(1 for ch in text if not is_jp(ch) and ch not in ' \n\u3000ー、。！？「」・…')
        return other <= len(jp)


def scan_strings(d, plaus, min_jp):
    """[(offset, end, encoding, text)] for Japanese strings in one leaf."""
    found = []

    def keep(start, text):
        if not plaus.ok(text, min_jp):
            return False
        # a short fragment counts only where a string can start (after a NUL)
        return jp_count(text) >= 4 or norm(text) in plaus.known or start == 0 or d[start - 1] == 0

    if RX_JPCODE.search(d):
        for m in RX_TBL.finditer(d):
            s, e = m.span()
            # restart inside the run at every lead byte so a binary prefix
            # does not hide the real string start
            for start in _starts(d, s, e):
                text = decode(d, start)
                if keep(start, text):
                    found.append((start, e, 'tbl', text))
                    break
    for m in RX_SJIS.finditer(d):
        s, e = m.span()
        try:
            text = d[s:e].decode('cp932')
        except UnicodeDecodeError:
            continue
        kana = sum(1 for ch in text if 0x3041 <= ord(ch) <= 0x30FF)
        if kana >= max(2, min_jp) and kana * 2 >= jp_count(text) and keep(s, text):
            found.append((s, e, 'sjis', text))
    for m in RX_UTF8.finditer(d):
        s, e = m.span()
        try:
            text = d[s:e].decode('utf-8')
        except UnicodeDecodeError:
            continue
        if jp_count(text) >= max(2, min_jp) and keep(s, text):
            found.append((s, e, 'utf8', text))
    return found


def _starts(d, s, e):
    yield s
    p = s + 1
    while p < e:
        if d[p - 1] == 0 or (0x99 <= d[p] <= 0x9F or 0xE0 <= d[p] <= 0xE4):
            yield p
        p += 1


def jp_count(text):
    return sum(1 for ch in text if is_jp(ch))

# --------------------------------------------------------------- references

def boot_sites(boot):
    """{site: target file offset} for every R_MIPS_32 word and HI16/LO16 pair
    in BOOT.BIN. The site is the file offset of the word (or LO16 opcode)."""
    nph = struct.unpack_from('<H', boot, 0x2C)[0]
    ph = [struct.unpack_from('<8I', boot, 0x34 + i * 32) for i in range(nph)]
    loads = [(p[2], p[1], p[4]) for p in ph if p[0] == 1]       # vaddr, file, filesz

    def to_file(v):
        for va, fo, sz in loads:
            if va <= v < va + sz:
                return fo + v - va
        return None

    rel = [p for p in ph if p[0] == 0x700000A0][0]
    sites, hi = {}, None
    for p in range(rel[1], rel[1] + rel[4], 8):
        off, info = struct.unpack_from('<II', boot, p)
        typ, ofsb, adrb = info & 0xFF, (info >> 8) & 0xFF, (info >> 16) & 0xFF
        if max(ofsb, adrb) >= len(ph):
            continue
        at = to_file(ph[ofsb][2] + off)
        if at is None or at + 4 > len(boot):
            continue
        word = struct.unpack_from('<I', boot, at)[0]
        if typ == 2:
            t, how = to_file(word + ph[adrb][2]), 'ptr%d' % adrb
        elif typ == 5:
            hi = (word & 0xFFFF) << 16
            continue
        elif typ == 6 and hi is not None:
            lo = word & 0xFFFF
            t = to_file(((hi + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF) + ph[adrb][2])
            how = 'code%d' % adrb
        else:
            continue
        if t is not None:
            sites[at] = (t, how)
    return sites


def sced_sites(d):
    try:
        tb, ptrs = psp_text.sced_pointers(d)
    except Exception:
        return {}
    return {at: (tb + addr, 'f8') for at, addr in ptrs}


def sfm_sites(r, p):
    """Reference sites of an SFM module (Quiz Book): every data table word
    and every `03 00 <u32>` bytecode push that sfm_text proves to point at a
    string, as {site: (target, 'sfm')} for the Japanese module r and for the
    same sites in the patched module p (whose strings may have moved)."""
    try:
        mod = sfm_text.SFM(r)
        strings = mod.strings()
    except Exception:
        return {}, {}
    rs = {pos: (mod.data_start + rel, 'sfm') for rel, s in strings.items() for pos, _k, _p in s['refs']}
    ps = {}
    if p is not None and p[:4] == b'SFM_' and len(p) >= mod.data_start:
        base = struct.unpack_from('<I', p, 0x18)[0]
        ps = {pos: (base + struct.unpack_from('<I', p, pos)[0], 'sfm') for pos in rs if pos + 4 <= len(p)}
    return rs, ps

# ----------------------------------------------------------------- tables

def known_translations():
    """{normalized Japanese: (English, source)} from every project table."""
    known = {}

    def add(jp, en, src):
        k = norm(jp)
        if k and en and k not in known:
            known[k] = (en.replace('\n', '\\n'), src)

    for jp, en in _tsv(os.path.join(HERE, 'psp_menu.tsv')):
        add(jp.replace('{99}{40}', '\u3000'), en, 'psp_menu.tsv')
    for row in _tsv(os.path.join(HERE, 'psp_supplement.tsv'), 3):
        add(row[1], row[2], 'psp_supplement.tsv')
    for name in ('psp_monsters.tsv', 'psp_quiz.tsv'):
        for jp, en in _tsv(os.path.join(HERE, name)):
            add(jp, en, name)
    menu = os.path.join(ROOT, 'ps2', 'menu')
    for fn, jcol, ecol in (('menu_translations.csv', 'japanese', 'english'),
                           ('enemy_translations.csv', 'japanese', 'english'),
                           ('enemy_names.csv', 'japanese', 'english'),
                           ('slps_title_translations.csv', 'japanese', 'english'),
                           ('quiz_translations.csv', 'japanese', 'english')):
        path = os.path.join(menu, fn)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    add(row[jcol], row[ecol], 'ps2/menu/' + fn)
    with contextlib.redirect_stdout(io.StringIO()):
        corpus = psp_text.load_ps2_corpus()     # the PSP text snapshot, psp/text
    for kind, table in corpus.items():
        for jp, en in table.items():
            add(jp, '\n'.join(en), 'psp/text ' + kind)
    return known, corpus


def _tsv(path, width=2):
    if not os.path.exists(path):
        return
    for line in open(path, encoding='utf-8'):
        if line.startswith('#'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) >= width and p[0]:
            yield [x.replace('\\n', '\n') for x in p[:max(width, 2)]] if width > 2 else (
                p[0].replace('\\n', '\n'), p[1].replace('\\n', '\n'))


def norm(text):
    return '\n'.join(l.rstrip(' \u3000') for l in text.split('\n')).strip('\n')

# ------------------------------------------------------------------- areas

FONT_MEMBER = 0
BATTLE_MEMBERS = range(8378, 9566)   # per enemy battle resources (psp_monsters.py)


def member_role(index, paths, kinds):
    """What one FPB member is, judged from its leaves."""
    if index == FONT_MEMBER:
        return 'font'
    if any('/s' in p for p in paths):
        return 'scenario'           # SCPK: one map or event (script + resources)
    if index in BATTLE_MEMBERS:
        return 'battle'             # 09225..09276 also hold map scripts in sizes packs
    if 'sced' in kinds:
        return 'skit'               # PAK holding a skit script and its pictures
    return 'other'


def area(role, kind):
    """Report label: member role and leaf kind, e.g. scenario:sced, battle:enemy-script."""
    return 'boot' if role == 'boot' else '%s:%s' % (role, kind)


# -------------------------------------------------------------------- scan

class Occ:
    __slots__ = ('path', 'area', 'off', 'enc', 'text', 'status', 'sites', 'patched')

    def __init__(self, path, area, off, enc, text, status, sites='', patched=''):
        self.path, self.area, self.off, self.enc = path, area, off, enc
        self.text, self.status, self.sites, self.patched = text, status, sites, patched


def compare_leaf(path, r, p, plaus, min_jp, out, leafinfo, role='other'):
    kind = leaf_kind(r)
    where = area(role, kind)
    leafinfo.append((path, where, len(r), hashlib.sha1(r).hexdigest(),
                     'same' if r == p else ('missing' if p is None else 'changed')))
    if kind in MEDIA.values():
        return
    if kind == 'sced':
        rs, ps = sced_sites(r), (sced_sites(p) if p is not None else {})
    elif kind == 'sfm':
        rs, ps = sfm_sites(r, p)
    elif path == 'BOOT':
        rs, ps = boot_sites(r), boot_sites(p)
    else:
        rs, ps = {}, {}
    referenced = collections.defaultdict(list)
    for site, (t, how) in rs.items():
        referenced[t].append(site)
    done, spans = set(), []
    # 1. reference sites: what the game actually draws
    for t, sites in referenced.items():
        if t >= len(r) or r[t] == 0 or (t and r[t - 1] != 0 and path != 'BOOT' and kind not in ('sced', 'sfm')):
            continue
        text = decode(r, t)
        if jp_count(text) == 0 or '{' in text.replace('{99}{40}', '').replace('{C0}', '').replace('{BC}', ''):
            if kind != 'sced' or jp_count(text) == 0:
                continue
        still, moved = [], []
        for site in sites:
            pt = ps.get(site, (None, ''))[0]
            ptext = decode(p, pt) if (p is not None and pt is not None and pt < len(p)) else None
            (still if ptext == text else moved).append((site, ptext))
        if still:
            out.append(Occ(path, where, t, 'tbl', text, 'live_jp', still_sites(still, rs)))
        if moved:
            eng = next((x for _, x in moved if x and jp_count(x) < jp_count(text)), moved[0][1] or '')
            out.append(Occ(path, where, t, 'tbl', text, 'translated', still_sites(moved, rs), eng))
        done.add(t)
        spans.append((t, r.find(b'\0', t)))
    spans.sort()
    starts = [a for a, _ in spans]
    # 2. everything else Japanese in the leaf
    for s, e, enc, text in scan_strings(r, plaus, min_jp):
        if s in done:
            continue
        k = bisect.bisect_right(starts, s) - 1
        if k >= 0 and spans[k][0] < s < spans[k][1]:
            continue        # tail of a string the game points at (already counted)
        raw = r[s:e]
        if p is None:
            status = 'leaf_missing'
        elif p[s:e] == raw:
            status = 'unreferenced_jp' if (rs and enc == 'tbl') else 'jp'
        elif p.find(raw) >= 0:
            status = 'moved_jp'
        elif kind == 'sced':
            status = 'gone'     # script text block rebuilt, orphan dropped
        else:
            status = 'changed'
        out.append(Occ(path, where, s, enc, text, status, '', decode(p, s) if status == 'changed' and enc == 'tbl' else ''))


def still_sites(pairs, rs):
    """'site:how ...' for the reference sites of one string."""
    return ' '.join('0x%X:%s' % (site, rs[site][1]) for site, _ in pairs)


_W = {}


def _init(rspec, pspec, min_jp, texts):
    _W.update(retail=Image(rspec), patched=Image(pspec), min_jp=min_jp, plaus=Plausible(texts))


def _scan_members(chunk):
    """Worker: compare every leaf of the members in chunk."""
    retail, patched, occs, graphics = _W['retail'], _W['patched'], [], []
    for i in chunk:
        raw, praw = retail.member(i), (patched.member(i) if patched.ranges[i][1] else None)
        rl = dict(leaves(raw, '%05d' % i))
        pl = dict(leaves(praw, '%05d' % i)) if praw is not None else {}
        role = member_role(i, rl, {leaf_kind(r) for r in rl.values()})
        graphics.append(('%05d' % i, role + ':member', len(raw), hashlib.sha1(raw).hexdigest(),
                         'same' if raw == praw else ('missing' if praw is None else 'changed')))
        for path, r in rl.items():
            compare_leaf(path, r, pl.get(path), _W['plaus'], _W['min_jp'], occs, graphics, role)
    return occs, graphics


def run(retail, patched, outdir, min_jp=2, members=None, jobs=None, progress=True):
    known, corpus = known_translations()
    texts = [norm(k) for t in corpus.values() for k in t] + list(known)
    plaus = Plausible(texts)
    occs, graphics = [], []
    compare_leaf('BOOT', retail.boot, patched.boot, plaus, 1, occs, graphics, 'boot')
    for name in ('/PSP_GAME/PARAM.SFO', '/PSP_GAME/SYSDIR/UPDATE/PARAM.SFO'):
        if hasattr(retail, 'iso_files') and hasattr(patched, 'iso_files'):
            compare_leaf(name, retail.iso_file(name), patched.iso_file(name), plaus, min_jp, occs, graphics, 'iso')
    lo, hi = members or (0, len(retail.ranges) - 1)
    todo = [i for i in range(lo, min(hi, len(retail.ranges) - 1) + 1) if retail.ranges[i][1]]
    chunks = [todo[k:k + 40] for k in range(0, len(todo), 40)]
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    with multiprocessing.Pool(jobs, _init, (retail.label, patched.label, min_jp, texts)) as pool:
        for n, (o, g) in enumerate(pool.imap(_scan_members, chunks), 1):
            occs += o
            graphics += g
            if progress and n % 25 == 0:
                print('%d/%d chunks  occurrences %d' % (n, len(chunks), len(occs)), file=sys.stderr)
    return report(occs, graphics, known, outdir, retail.label, patched.label)

# ------------------------------------------------------------------ report

LIVE = ('live_jp', 'jp', 'moved_jp', 'unreferenced_jp')
CATEGORY_ORDER = ('missed_copy', 'known_unapplied', 'untranslated', 'residue')


def report(occs, graphics, known, outdir, rlabel, plabel):
    os.makedirs(outdir, exist_ok=True)
    groups = collections.OrderedDict()
    for o in occs:
        groups.setdefault(norm(o.text), []).append(o)
    rows = []
    for key, g in groups.items():
        st = collections.Counter(o.status for o in g)
        translated = [o for o in g if o.status in ('translated', 'changed')]
        live = st['live_jp'] + st['jp'] + st['moved_jp']
        unref = st['unreferenced_jp']
        english = next((o.patched for o in translated if o.patched and jp_count(o.patched) == 0), '')
        kn = known.get(key)
        if translated and (live or unref):
            cat = 'missed_copy'
        elif (live or unref) and kn:
            cat = 'known_unapplied'
        elif live or unref:
            cat = 'untranslated'
        else:
            cat = 'residue'
        stillo = [o for o in g if o.status in LIVE]
        rows.append({
            'category': cat,
            'confidence': confidence(g),
            'japanese': key.replace('\n', '\\n'),
            'copies': len(copies_of(g)),
            'copy_label': copy_label(len(copies_of(g))),
            'translated': len(translated),
            'live_jp': live,
            'unreferenced_jp': unref,
            'english_in_build': english.replace('\n', '\\n'),
            'known_translation': kn[0] if kn else '',
            'known_source': kn[1] if kn else '',
            'areas': ','.join(sorted({o.area for o in g})),
            'still_jp_at': ' '.join('%s@0x%X' % (o.path, o.off) for o in stillo[:12]) + (' ...' if len(stillo) > 12 else ''),
            'translated_at': ' '.join('%s@0x%X' % (o.path, o.off) for o in translated[:6]) + (' ...' if len(translated) > 6 else ''),
        })
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    conf = {'high': 0, 'medium': 1, 'low': 2}
    rows.sort(key=lambda r: (rank[r['category']], conf[r['confidence']], r['areas'], -r['live_jp'] - r['unreferenced_jp']))
    cols = list(rows[0]) if rows else ['category']
    with open(os.path.join(outdir, 'groups.tsv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(outdir, 'occurrences.tsv'), 'w', encoding='utf-8') as f:
        f.write('path\tarea\tkind\toffset\tencoding\tstatus\tref_sites\tjapanese\tpatched_text\n')
        for o in occs:
            f.write('%s\t%s\t%s\t0x%X\t%s\t%s\t%s\t%s\t%s\n' % (
                o.path, o.area, o.area.split(':')[-1], o.off, o.enc, o.status, o.sites,
                o.text.replace('\n', '\\n').replace('\t', ' '), o.patched.replace('\n', '\\n').replace('\t', ' ')))
    with open(os.path.join(outdir, 'graphics.tsv'), 'w', encoding='utf-8') as f:
        f.write('path\tarea\tbytes\tvs_retail\n')
        for g in graphics:
            if g[1].split(':')[-1] in MEDIA.values():
                f.write('%s\t%s\t%d\t%s\n' % (g[0], g[1], g[2], g[4]))
    dups = {'text': write_duplicates(groups, rows, outdir),
            'leaf': write_leaf_duplicates(graphics, outdir),
            'table': write_table_duplicates(occs, outdir),
            'boot': write_boot_partial(occs, outdir)}
    write_summary(rows, occs, graphics, outdir, rlabel, plabel, dups)
    return rows


def confidence(g):
    """high: the game provably points at it (reference site); medium: real
    looking text in a scanned leaf (4+ Japanese characters, or 2+ stored
    twice); low: short fragments."""
    if any(o.sites for o in g):
        return 'high'
    t = g[0].text
    n = jp_count(t)
    if n >= 4 or (n >= 2 and len(g) >= 2):
        return 'medium'
    return 'low'


# ------------------------------------------------------------- duplicates

COPY_STATE = {'translated': 'translated', 'changed': 'translated', 'live_jp': 'live_jp',
              'unreferenced_jp': 'unreferenced', 'jp': 'no_ref_model', 'moved_jp': 'no_ref_model',
              'gone': 'gone', 'leaf_missing': 'gone'}
STILL = ('live_jp', 'unreferenced', 'no_ref_model', 'partial')


def copies_of(group):
    """{(path, offset): state} for one text; a location whose reference sites
    were only partly redirected is 'partial'."""
    out = {}
    for o in group:
        k, st = (o.path, o.off), COPY_STATE[o.status]
        if k in out and out[k] != st:
            st = 'partial'
        out[k] = st
    return out


def copy_label(n):
    return {1: 'single', 2: 'duplicate', 3: 'triplicate'}.get(n, '%d copies' % n)


def write_duplicates(groups, rows, outdir):
    """duplicates.tsv: every text stored at 2+ locations, with every copy."""
    cat = {r['japanese']: r for r in rows}
    out = []
    for key, g in groups.items():
        c = copies_of(g)
        if len(c) < 2:
            continue
        st = collections.Counter(c.values())
        r = cat[key.replace('\n', '\\n')]
        still = sum(st[x] for x in STILL)
        out.append({
            'copies': len(c), 'label': copy_label(len(c)),
            'state': 'partly_patched' if (st['translated'] or st['partial']) and still else
                     ('all_japanese' if still else 'all_patched'),
            'category': r['category'], 'confidence': r['confidence'], 'japanese': r['japanese'],
            'translated': st['translated'], 'partial': st['partial'], 'live_jp': st['live_jp'],
            'unreferenced': st['unreferenced'], 'no_ref_model': st['no_ref_model'], 'gone': st['gone'],
            'english_in_build': r['english_in_build'], 'known_translation': r['known_translation'],
            'areas': r['areas'],
            'every_copy': ' '.join('%s@0x%X:%s' % (p, o, v) for (p, o), v in sorted(c.items())),
        })
    order = {'partly_patched': 0, 'all_japanese': 1, 'all_patched': 2}
    out.sort(key=lambda x: (-x['copies'], order[x['state']], x['japanese']))
    _write_rows(os.path.join(outdir, 'duplicates.tsv'), out)
    return out


def write_leaf_duplicates(leafinfo, outdir):
    """leaf_duplicates.tsv: byte identical leaves (and raw FPB members) stored
    2+ times; partially patched clusters (one copy changed, another still
    retail) first."""
    by = collections.defaultdict(list)
    for path, where, size, h, status in leafinfo:
        if size >= 16:
            by[(h, where.endswith(':member'))].append((path, where, size, status))
    out = []
    for (h, member), items in by.items():
        if len(items) < 2:
            continue
        changed = [x[0] for x in items if x[3] == 'changed']
        same = [x[0] for x in items if x[3] == 'same']
        out.append({
            'state': 'partially_patched' if changed and same else ('all_patched' if changed else 'all_retail'),
            'level': 'member' if member else 'leaf', 'sha1': h, 'bytes': items[0][2],
            'kind': ','.join(sorted({x[1] for x in items})), 'copies': len(items),
            'changed': ' '.join(changed), 'unchanged': ' '.join(same),
        })
    order = {'partially_patched': 0, 'all_patched': 1, 'all_retail': 2}
    out.sort(key=lambda x: (order[x['state']], x['level'] != 'leaf', -x['copies'], -x['bytes']))
    _write_rows(os.path.join(outdir, 'leaf_duplicates.tsv'), out)
    return out


def write_table_duplicates(occs, outdir, min_run=3, max_fanout=200):
    """table_duplicates.tsv: the same ordered run of 3+ Japanese strings in
    two locations (two leaves, BOOT and a leaf, or twice in one leaf). The
    typical "the game reads a second table" case. Leaves whose whole string
    list and patch state are identical count once (leaf_duplicates.tsv lists
    the copies)."""
    seqs = collections.defaultdict(dict)
    for o in occs:
        st = COPY_STATE[o.status]
        prev = seqs[o.path].get(o.off)
        seqs[o.path][o.off] = (norm(o.text), 'partial' if prev and prev[1] != st else st)
    uniq, seen = [], set()
    for path, d in seqs.items():
        items = [(off,) + d[off] for off in sorted(d)]
        key = tuple(x[1:] for x in items)     # same strings, same patch state
        if len(items) >= min_run and key not in seen:
            seen.add(key)
            uniq.append((path, items))
    index = collections.defaultdict(list)
    for a, (path, items) in enumerate(uniq):
        for i in range(len(items) - min_run + 1):
            index[tuple(x[1] for x in items[i:i + min_run])].append((a, i))
    runs = {}
    for key, ents in index.items():
        if len(ents) < 2 or len(ents) > max_fanout:
            continue
        for x in range(len(ents)):
            for y in range(x + 1, len(ents)):
                (a, i), (b, j) = ents[x], ents[y]
                A, B = uniq[a][1], uniq[b][1]
                if a == b and abs(i - j) < min_run:
                    continue
                if i and j and A[i - 1][1] == B[j - 1][1]:
                    continue            # not the start of the shared run
                n = 0
                while i + n < len(A) and j + n < len(B) and A[i + n][1] == B[j + n][1] and not (a == b and i + n == j):
                    n += 1
                if n >= min_run and len({x[1] for x in A[i:i + n]}) >= 2:
                    runs[(a, i, b, j)] = n
    out = []
    for (a, i, b, j), n in runs.items():
        A, B = uniq[a][1][i:i + n], uniq[b][1][j:j + n]
        ta = sum(1 for x in A if x[2] == 'translated')
        tb = sum(1 for x in B if x[2] == 'translated')
        out.append({
            'state': 'partly_patched' if ta != tb else ('all_patched' if ta == n else 'both_japanese' if ta == 0 else 'same_mix'),
            'run': n,
            'copy_a': '%s@0x%X..0x%X' % (uniq[a][0], A[0][0], A[-1][0]), 'a_translated': ta,
            'copy_b': '%s@0x%X..0x%X' % (uniq[b][0], B[0][0], B[-1][0]), 'b_translated': tb,
            'strings': ' | '.join(x[1].replace('\n', '\\n') for x in A[:8]) + (' ...' if n > 8 else ''),
        })
    order = {'partly_patched': 0, 'both_japanese': 1, 'same_mix': 2, 'all_patched': 3}
    out.sort(key=lambda x: (order[x['state']], -x['run']))
    _write_rows(os.path.join(outdir, 'table_duplicates.tsv'), out)
    return out


def write_boot_partial(occs, outdir):
    """boot_partial.tsv: BOOT strings where some reference sites now reach the
    English and others still reach the Japanese (pointer redirect missed
    them). Site kinds: ptr0/ptr1 = R_MIPS_32 word relative to segment 0/1,
    code0/code1 = HI16/LO16 address pair."""
    by = collections.defaultdict(dict)
    for o in occs:
        if o.path == 'BOOT' and o.status in ('live_jp', 'translated'):
            by[o.off][o.status] = o
    out = []
    for off, d in sorted(by.items()):
        if len(d) == 2:
            out.append({'offset': '0x%X' % off, 'japanese': d['live_jp'].text.replace('\n', '\\n'),
                        'english': d['translated'].patched.replace('\n', '\\n'),
                        'still_jp_sites': d['live_jp'].sites, 'redirected_sites': d['translated'].sites})
    _write_rows(os.path.join(outdir, 'boot_partial.tsv'), out)
    return out


def _write_rows(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        if not rows:
            f.write('(none)\n')
            return
        w = csv.DictWriter(f, list(rows[0]), delimiter='\t', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def duplicate_summary(dups):
    text, leaf, table, boot = dups['text'], dups['leaf'], dups['table'], dups['boot']
    tc = collections.Counter((x['label'] if x['copies'] <= 3 else '4+ copies', x['state']) for x in text)
    lines = ['## Duplicates and triplicates', '',
             'text copies | partly patched | all Japanese | all patched', '--- | --- | --- | ---']
    for lab in ('duplicate', 'triplicate', '4+ copies'):
        lines.append('%s | %d | %d | %d' % (lab, tc[(lab, 'partly_patched')], tc[(lab, 'all_japanese')], tc[(lab, 'all_patched')]))
    lc = collections.Counter((x['level'], x['state']) for x in leaf)
    lines += ['', 'byte identical | partially patched | all retail | all patched', '--- | --- | --- | ---']
    for lev in ('leaf', 'member'):
        lines.append('%s clusters | %d | %d | %d' % (lev, lc[(lev, 'partially_patched')], lc[(lev, 'all_retail')], lc[(lev, 'all_patched')]))
    tbc = collections.Counter(x['state'] for x in table)
    lines += ['', '* duplicated string tables (3+ strings in the same order): %d, partly patched %d, both Japanese %d'
              % (len(table), tbc['partly_patched'], tbc['both_japanese']),
              '* BOOT strings with some pointers redirected and some not: %d (boot_partial.tsv)' % len(boot), '']
    part = [x for x in text if x['state'] == 'partly_patched' and x['confidence'] != 'low']
    part.sort(key=lambda x: -x['copies'])
    if part:
        lines += ['Top partly patched texts (translated in one place, Japanese in another):', '']
        for x in part[:25]:
            lines.append('* %s `%s` -> %s (still JP: %d live, %d unreferenced, %d no ref model)' % (
                x['label'], x['japanese'][:40], (x['english_in_build'] or x['known_translation'])[:40],
                x['live_jp'] + x['partial'], x['unreferenced'], x['no_ref_model']))
        lines.append('')
    pl = [x for x in leaf if x['state'] == 'partially_patched']
    if pl:
        lines += ['Partially patched byte identical leaves:', '']
        for x in pl[:15]:
            lines.append('* %s %s, %d bytes, changed %s, unchanged %s' % (x['level'], x['kind'], x['bytes'],
                                                                        x['changed'][:80], x['unchanged'][:80]))
        lines.append('')
    pt = [x for x in table if x['state'] == 'partly_patched']
    if pt:
        lines += ['Partly patched duplicated tables:', '']
        for x in pt[:15]:
            lines.append('* %d strings: %s (%d translated) vs %s (%d translated): %s' % (
                x['run'], x['copy_a'], x['a_translated'], x['copy_b'], x['b_translated'], x['strings'][:80]))
        lines.append('')
    return lines


def write_summary(rows, occs, graphics, outdir, rlabel, plabel, dups):
    by = collections.Counter((r['category'], r['confidence']) for r in rows)
    ar = collections.defaultdict(collections.Counter)
    for r in rows:
        if r['category'] != 'residue':
            for a in r['areas'].split(','):
                ar[a][r['category']] += 1
    lines = ['# PSP Japanese scan', '',
             '* retail: `%s`' % rlabel, '* patched: `%s`' % plabel,
             '* occurrences: %d, distinct texts: %d' % (len(occs), len(rows)), '']
    lines += duplicate_summary(dups)
    lines += [
             '## Groups by category and confidence', '',
             'category | high | medium | low', '--- | --- | --- | ---']
    for c in CATEGORY_ORDER:
        lines.append('%s | %d | %d | %d' % (c, by[(c, 'high')], by[(c, 'medium')], by[(c, 'low')]))
    lines += ['', '## Open groups by area', '', 'area | missed_copy | known_unapplied | untranslated',
              '--- | --- | --- | ---']
    for a in sorted(ar):
        lines.append('%s | %d | %d | %d' % (a, ar[a]['missed_copy'], ar[a]['known_unapplied'], ar[a]['untranslated']))
    gk = collections.Counter((g[1], g[4]) for g in graphics if g[1].split(':')[-1] in MEDIA.values())
    lines += ['', '## Graphics leaves (Japanese baked into pixels is not text; review visually)', '']
    for (k, s), n in sorted(gk.items()):
        lines.append('* %s %s: %d' % (k, s, n))
    for c in ('missed_copy', 'known_unapplied'):
        top = [r for r in rows if r['category'] == c and r['confidence'] == 'high'][:40]
        if top:
            lines += ['', '## %s, high confidence (first %d)' % (c, len(top)), '']
            for r in top:
                lines.append('* `%s` -> %s  (%s; still JP at %s)' % (
                    r['japanese'][:60], (r['english_in_build'] or r['known_translation'])[:60] or '?',
                    r['areas'], r['still_jp_at'][:120]))
    with open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('retail')
    ap.add_argument('patched')
    ap.add_argument('outdir')
    ap.add_argument('--min-jp', type=int, default=2, help='Japanese characters a scanned string needs (default 2)')
    ap.add_argument('--members', help='only FPB members A-B or one member N (BOOT.BIN is always scanned)')
    ap.add_argument('--jobs', type=int, help='worker processes (default: CPU count - 1)')
    a = ap.parse_args(argv)
    members = None
    if a.members:
        lo, _, hi = a.members.partition('-')
        members = (int(lo), int(hi or lo))
    rows = run(Image(a.retail), Image(a.patched), a.outdir, a.min_jp, members, a.jobs)
    c = collections.Counter(r['category'] for r in rows)
    print('groups:', ', '.join('%s %d' % (k, c[k]) for k in CATEGORY_ORDER), '->', a.outdir)


if __name__ == '__main__':
    main()
