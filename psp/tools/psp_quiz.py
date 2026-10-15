#!/usr/bin/env python3
"""Quiz Book text for the PSP version (the SFM script modules).

    psp_quiz.py report BOOT.BIN file.fpb [OUT.tsv]
        dry run on a Japanese archive: how many strings get English, how
        many relocate, overflow or have no translation; OUT.tsv lists every
        string of every copy with the source of its English
    psp_quiz.py verify BOOT.BIN file.fpb NEW_BOOT.BIN new.fpb
        compares a built archive with the Japanese one: every reference to
        a translated string must lead to its English, the bytecode must be
        unchanged apart from those references
    psp_quiz.py check
        encodes every English line of both tables, reports long lines

build_psp.py calls build_changed_members() and hands the result to
psp_text.build as extra members, like psp_monsters.

Format. Every quiz is one `SFM_` script module, the same format as the PS2
members 06171..06301 that ps2/menu/sfm_text.py translates (header, 16-bit
bytecode with `03 00 <u32>` pushes, NUL separated strings in the data
section referenced by section relative offset), byte for byte the same
layout; only the PSP modules are deflate wrapped instead of LZSS packed.

Where the modules are. The disc holds every quiz module five times, and
which copy the game loads is not known, so all of them are translated:

* loose members 06335..06466 (one module each, 06366 excepted);
* 06333: a sizes pack (u32 n, n u32 sizes, children back to back, each
  deflate wrapped and padded to 4 bytes) with the three quiz pictures and
  then the 131 modules, identical to the loose members;
* 06334: the same pack built from the debug variant of the modules (longer
  bytecode, and real developer sample quizzes in the slots that are empty
  stubs elsewhere: those samples have no English and stay Japanese);
* 06366: a sizes pack of the modules 06335..06365;
* 06467: a sizes pack of the modules 06367..06466.

PSP module N (loose numbering) holds PS2 member N - 164 up to 06365 and
N - 165 from 06367 on. The module reader and writer are the PS2 tool's
(ps2/menu/sfm_text.py with md1text/md1patch), but their glyph table is
replaced by the PSP one (psp/text/TBL.json plus TBL_PSP.json, as in
psp_text): with the codes the PS2 table never listed, no string hides from
the pass (on the PS2, strings with unknown codes were invisible to the
extractor, the "hidden strings").

English comes from psp_quiz.tsv next to this script (the text the PSP
release rewrote or added, plus the rare PS2 line that does not fit its PSP
slot; matched by the exact Japanese, it wins) and otherwise from
psp/text/quiz_translations.csv, the PSP snapshot of the PS2 quiz table
(refreshed by sync_text_from_ps2.py; rows of the matching PS2 member,
matched by the exact Japanese). The writing is sfm_text.SFM.apply: English that
fits the Japanese slot is written in place, longer English is appended to
the data section and every reference redirected; strings whose references
are not provably pointers ("pinned") must fit in place or stay Japanese
(reported as overflow). ASCII `~` is written as the full-width `～` (the
PSP's ASCII table draws `~` as a dash).
"""
import csv, os, sys, struct, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'ps2', 'menu'))
import psp_fpb                      # noqa: E402
import psp_text                     # noqa: E402
import md1text                      # noqa: E402
import md1patch                     # noqa: E402
import sfm_text                     # noqa: E402

MEMBER_LO, MEMBER_HI = 6335, 6466
QUIZ_CSV = os.path.join(psp_text.TEXT, 'quiz_translations.csv')
PSP_TSV = os.path.join(HERE, 'psp_quiz.tsv')
LONG_LINE = 40          # longest English line check (the PS2 table stays under it bar a few)
MAX_LINES = 4           # the quiz box shows four rows (the PS2 English adds a row to
                        # 154 Japanese records, never a fifth)


def _full_pack_child(n):
    """Loose module number of child n of 06333/06334 (children 0..2 are pictures)."""
    if n < 3:
        return None
    return 6332 + n if n <= 33 else 6333 + n     # no copy of 06366 (not a module)


PACKS = {
    6333: _full_pack_child,
    6334: _full_pack_child,
    6366: lambda n: 6335 + n,
    6467: lambda n: 6367 + n,
}

# The glyph table is the PSP one (psp/text/TBL.json plus TBL_PSP.json, read
# by psp_text): the decoder sees the codes the PS2 table never listed, the
# encoder has the few symbols the English uses from them (the blank ○, α,
# β). md1text and md1patch keep only their own extra codes on top.
md1text.TBL.update(psp_text.TBL)
md1patch.REV.update({ch: struct.unpack('>H', code)[0] for ch, code in psp_text.ITBL.items()})


def ps2_file(index):
    """PS2 quiz member name for PSP (loose) module number index."""
    return '%05d.sfm' % (index - 164 if index <= 6365 else index - 165)


def esc(text):
    return text.replace('\n', '\\n')


def unesc(text):
    return text.replace('\\n', '\n')


def load_tables(quiz_csv=QUIZ_CSV, psp_tsv=PSP_TSV):
    """({ps2 file: {japanese: english}}, {japanese: english})."""
    ps2 = collections.defaultdict(dict)
    with open(quiz_csv, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['english']:
                ps2[r['file']].setdefault(r['japanese'], r['english'])
    psp = {}
    if os.path.exists(psp_tsv):
        with open(psp_tsv, encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or '\t' not in line:
                    continue
                jp, en = line.rstrip('\n').split('\t')[:2]
                if jp and en:
                    psp[unesc(jp)] = unesc(en)
    return ps2, psp


def psp_english(text):
    return text.replace('~', '～')

# ------------------------------------------------------------- containers

def sizes_pack(d):
    """Children of a sizes pack (u32 n, n u32 sizes, children back to back)."""
    n = struct.unpack_from('<I', d, 0)[0]
    sizes = struct.unpack_from('<%dI' % n, d, 4)
    if 4 + 4 * n + sum(sizes) != len(d):
        raise ValueError('not a sizes pack')
    kids, p = [], 4 + 4 * n
    for size in sizes:
        kids.append(d[p:p + size])
        p += size
    return kids


def build_sizes_pack(kids):
    return struct.pack('<%dI' % (len(kids) + 1), len(kids), *[len(k) for k in kids]) + b''.join(kids)


def modules(boot, fpb_path):
    """Yield (label, module number, member, child or None, SFM bytes) for every
    copy of every quiz module: the loose members, then the pack children."""
    for index in range(MEMBER_LO, MEMBER_HI + 1):
        data, _ = psp_fpb.read_member(fpb_path, boot, index)
        if data[:4] == b'SFM_':
            yield '%05d' % index, index, index, None, data
    for member, number in PACKS.items():
        raw, _ = psp_fpb.read_member(fpb_path, boot, member)
        for n, kid in enumerate(sizes_pack(raw)):
            index = number(n)
            if index is None:
                continue
            data, packed = psp_text.inflate(kid)
            if not packed or data[:4] != b'SFM_':
                raise ValueError('%05d child %d is not a deflate wrapped SFM module' % (member, n))
            yield '%05d/n%d' % (member, n), index, member, n, data

# ---------------------------------------------------------------- writing

def plan(index, data, tables):
    """[(rel, japanese, english, source)] and [(rel, japanese)] without English
    for one SFM module."""
    ps2, psp = tables
    mod = sfm_text.SFM(data)
    todo, missing = [], []
    own = ps2.get(ps2_file(index), {})
    for rel, s in sorted(mod.strings().items()):
        if s['jp'] < 1:
            continue
        jp = s['text']
        if jp in psp:
            todo.append((rel, jp, psp[jp], 'psp'))
        elif jp in own:
            todo.append((rel, jp, own[jp], 'ps2'))
        else:
            missing.append((rel, jp))
    return todo, missing


def patch_module(label, index, data, tables, stats, rows=None):
    """New SFM bytes for one module, or None when nothing changed."""
    mod = sfm_text.SFM(data)
    todo, missing = plan(index, data, tables)
    stats['untranslated'] += len(missing)
    if rows is not None:
        rows += [(label, '0x%X' % rel, src, esc(jp), esc(en)) for rel, jp, en, src in todo]
        rows += [(label, '0x%X' % rel, 'none', esc(jp), '') for rel, jp in missing]
    if not todo:
        return None
    log = []
    n, moved, overflow = mod.apply([(rel, jp, psp_english(en)) for rel, jp, en, _ in todo], log)
    for src in ('ps2', 'psp'):
        stats['from ' + src] += sum(1 for t in todo if t[3] == src)
    stats['patched'] += n
    stats['relocated'] += moved
    stats['overflow'] += len(overflow)
    for line in overflow + log:
        stats.setdefault('lines', []).append('%s %s' % (label, line.strip()))
    if not n:
        return None
    stats['modules'] += 1
    return mod.bytes()


def build_changed_members(boot_path, fpb_path, tables=None, log=print, rows=None):
    """({member: new decompressed member}, stats) for every quiz member or
    pack that changed. Packs keep every untouched child byte for byte."""
    tables = tables or load_tables()
    boot = open(boot_path, 'rb').read()
    stats, changed, kids = collections.Counter(), {}, {}
    for label, index, member, child, data in modules(boot, fpb_path):
        new = patch_module(label, index, data, tables, stats, rows)
        if new is None:
            continue
        if child is None:
            changed[member] = new
        else:
            if member not in kids:
                kids[member] = sizes_pack(psp_fpb.read_member(fpb_path, boot, member)[0])
            kids[member][child] = psp_text.deflate(new)
    for member, k in kids.items():
        changed[member] = build_sizes_pack(k)
    lines = stats.pop('lines', [])
    if log:
        log('quiz book: %d strings in %d module copies (%d from the PS2 table, %d from '
            'psp_quiz.tsv), %d relocated, %d overflow, %d without English, %d members changed'
            % (stats['patched'], stats['modules'], stats['from ps2'], stats['from psp'],
               stats['relocated'], stats['overflow'], stats['untranslated'], len(changed)))
        for line in lines:
            if 'OVERFLOW' in line:
                log('  ' + line)
    stats['lines'] = lines
    return changed, stats

# ------------------------------------------------------------- verifying

def verify_module(label, index, old, new, tables):
    """(references checked, [problem lines]) for one module: every reference
    the pass knew about (data table word or bytecode push) must now lead to
    the English (an overflow string to its Japanese), and the bytecode must
    be byte identical apart from those references."""
    todo, _ = plan(index, old, tables)
    if not todo:
        return 0, ([] if new == old else ['%s: changed although nothing was translated' % label])
    mod, nmod = sfm_text.SFM(old), sfm_text.SFM(new)
    strings = mod.strings()
    checked, problems, refs = 0, [], set()
    for rel, jp, en, _src in todo:
        s = strings[rel]
        want = psp_english(en)
        if s['pinned'] and len(md1patch.encode(want)) > mod.budget(rel, s['end']):
            want = jp                               # overflow: stays Japanese
        for pos, _kind, _prev in s['refs']:
            refs.add(pos)
            target = struct.unpack_from('<I', new, pos)[0]
            got = md1text.decode_at(new, nmod.data_start + target)
            checked += 1
            if not got or got[0] != want:
                problems.append('%s 0x%X: reference at 0x%X reads %r' % (
                    label, rel, pos, got[0] if got else None))
    for p in range(mod.code_start, mod.code_end):
        if new[p] != old[p] and not any(r <= p < r + 4 for r in refs):
            problems.append('%s: bytecode changed at 0x%X' % (label, p))
            break
    return checked, problems


def verify(retail_boot, retail_fpb, new_boot, new_fpb, tables=None):
    """Check every copy of every module in a built archive against the
    Japanese one (verify_module), and the picture children of the packs.
    Returns (references checked, [problem lines])."""
    tables = tables or load_tables()
    rboot, nboot = open(retail_boot, 'rb').read(), open(new_boot, 'rb').read()
    old = list(modules(rboot, retail_fpb))
    new = list(modules(nboot, new_fpb))
    if [m[:4] for m in old] != [m[:4] for m in new]:
        return 0, ['the built archive holds a different set of quiz modules']
    checked, problems = 0, []
    for (label, index, _m, _c, a), (_l, _i, _m2, _c2, b) in zip(old, new):
        n, bad = verify_module(label, index, a, b, tables)
        checked += n
        problems += bad
    for member, number in PACKS.items():
        a = sizes_pack(psp_fpb.read_member(retail_fpb, rboot, member)[0])
        b = sizes_pack(psp_fpb.read_member(new_fpb, nboot, member)[0])
        if [k for n, k in enumerate(a) if number(n) is None] != [k for n, k in enumerate(b) if number(n) is None]:
            problems.append('%05d: picture children changed' % member)
    return checked, problems


def check(tables=None):
    ps2, psp = tables or load_tables()
    bad = 0
    for name, table in [('psp_quiz.tsv', psp)] + [(f, t) for f, t in sorted(ps2.items())]:
        for jp, en in table.items():
            try:
                md1patch.encode(psp_english(en))
            except Exception as e:
                bad += 1
                print('%s: cannot encode %r (%s)' % (name, en, e))
                continue
            if name == 'psp_quiz.tsv':
                if en.count('\n') >= MAX_LINES:
                    print('%s: more than %d lines: %r' % (name, MAX_LINES, en))
                for line in en.split('\n'):
                    if len(line) > LONG_LINE:
                        print('%s: line of %d characters: %r' % (name, len(line), line))
    print('%d problems' % bad)
    return bad


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ['report'] and len(a) in (3, 4):
        rows = []
        _, stats = build_changed_members(a[1], a[2], rows=rows)
        for line in stats.pop('lines', []):
            print(line)
        print(dict(stats))
        if len(a) == 4:
            with open(a[3], 'w', encoding='utf-8') as f:
                f.write('copy\toffset\tsource\tjapanese\tenglish\n')
                for r in rows:
                    f.write('\t'.join(r) + '\n')
    elif a[:1] == ['verify'] and len(a) == 5:
        checked, problems = verify(*a[1:5])
        for line in problems:
            print(line)
        print('quiz book: %d references checked, %d problems' % (checked, len(problems)))
        sys.exit(1 if problems else 0)
    elif a[:1] == ['check'] and len(a) == 1:
        sys.exit(1 if check() else 0)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
