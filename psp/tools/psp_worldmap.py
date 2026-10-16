#!/usr/bin/env python3
"""World map text for the PSP version (the field scripts of members 09272..09276).

    psp_worldmap.py report BOOT.BIN file.fpb
        dry run on a Japanese archive: per member how many strings get
        English, which Japanese strings have no row in psp_worldmap.tsv
    psp_worldmap.py verify BOOT.BIN file.fpb NEW_BOOT.BIN new.fpb
        compares a built archive with the Japanese one: every text
        reference must lead to its English, the bytecode and every other
        child of the pack must be unchanged
    psp_worldmap.py check
        encodes every English row of psp_worldmap.tsv

build_psp.py calls build_changed_members() and hands the result to
psp_text.build as extra members, like psp_quiz and psp_monsters.

What it fixes. The big yellow location name that appears when the party
walks up to a town or dungeon on the world map ("ラグナ遺跡", "クレスタの街",
reported by Gandorff on PSP 0.3.0) was still Japanese, and so was all
other text of the world map scripts: signposts, mine entrance labels, the
inn on the map, treasure messages, the box puzzle, the Draconis anchor
scene and the ending monologue ("What is a hero, anyway?"). The English
"Cresta" / "Laguna" in BOOT.BIN (psp_menu.tsv) is a different list that
these labels never read.

Format. Members 09272..09276 are sizes packs (u32 n, n u32 sizes, children
back to back, every size a multiple of 4), one per era of the world map:

    09272  present day           09275  the Great War (Er'ther, Dycroft)
    09273  the future            09276  the final present (ending, Ixifoslar)
    09274  the altered present

Child 19 of each pack is the world map field script, an uncompressed SCED
(the other children are deflate wrapped data). The labels and messages are
ordinary SCED strings reached through F8 text operands, so the scenario
writer psp_text.insert_sced does the work: English is appended after the
text block and each F8 operand redirected, the bytecode keeps its length.
These are the PSP twins of the PS2 world map scripts 09028..09032.pak0,
which ps2/menu/patch_menu_text.py translates from menu_translations.csv.

English comes from psp_worldmap.tsv next to this script (Japanese<TAB>
English<TAB>source, `\\n` = line break), matched by the exact decoded
record, control codes included. Source column: ps2-menu (the PS2 world
map row, with the PS2 slot cuts undone: "Laguna Ruins", "Lienea",
"Crimson City Speranza"), ps2-scenario or psp-supplement (the same
Japanese in the scenario text), translated (PSP only text: the box puzzle
help that names the SELECT menu, the Ixifoslar controls, the Shrine of
Light sign, debug lines).
"""
import os, sys, struct, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_fpb                      # noqa: E402
import psp_sced                     # noqa: E402
import psp_text                     # noqa: E402

MEMBERS = (9272, 9273, 9274, 9275, 9276)
TSV = os.path.join(HERE, 'psp_worldmap.tsv')


def esc(text):
    return text.replace('\n', '\\n')


def unesc(text):
    return text.replace('\\n', '\n')


def load_table(path=TSV):
    """{japanese record: english record}."""
    table = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or '\t' not in line:
                continue
            jp, en = line.rstrip('\n').split('\t')[:2]
            if jp and en:
                table[unesc(jp)] = unesc(en)
    return table

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


def script(kids):
    """(child index, SCED bytes) of the one uncompressed SCED child."""
    found = [(n, k) for n, k in enumerate(kids) if k[:4] == b'SCED']
    if len(found) != 1:
        raise ValueError('expected one SCED child, found %d' % len(found))
    return found[0]


def scripts(boot, fpb_path):
    """Yield (member, kids, child index, SCED bytes) for every world map pack."""
    for member in MEMBERS:
        raw, _ = psp_fpb.read_member(fpb_path, boot, member)
        kids = sizes_pack(raw)
        n, sced = script(kids)
        yield member, kids, n, sced

# ---------------------------------------------------------------- writing

def plan(sced, table):
    """(records with English filled in, F8 operand addresses, translated
    record indexes, [(index, japanese)] without English)."""
    records, addrs = psp_text.extract_sced(sced)
    out, done, missing = [], [], []
    for i, text in enumerate(records):
        if text in table:
            out.append(table[text].split('\n'))
            done.append(i)
        else:
            out.append(text.split('\n'))
            if psp_text.JP.search(text):
                missing.append((i, text))
    return out, addrs, done, missing


def patch_script(member, sced, table, stats):
    """New SCED bytes, or None when nothing changed."""
    records, addrs, done, missing = plan(sced, table)
    stats['translated'] += len(done)
    stats['without English'] += len(missing)
    for i, text in missing:
        stats.setdefault('lines', []).append('%05d record %d has no English: %s' % (member, i, esc(text)))
    if not done:
        return None
    new, mode, skipped = psp_text.insert_sced(sced, records, addrs)
    if mode != 'append' or skipped:
        raise ValueError('%05d: %s mode, %d suspicious pointers (expected append, 0)' % (member, mode, skipped))
    return new + b'\0' * (-len(new) % 4)          # children stay 4 byte sized


def build_changed_members(boot_path, fpb_path, table=None, log=print):
    """({member: new member bytes}, stats). Only the script child changes;
    every other child is kept byte for byte."""
    table = table if table is not None else load_table()
    boot = open(boot_path, 'rb').read()
    stats, changed = collections.Counter(), {}
    for member, kids, n, sced in scripts(boot, fpb_path):
        new = patch_script(member, sced, table, stats)
        if new is None:
            continue
        kids = list(kids)
        kids[n] = new
        changed[member] = build_sizes_pack(kids)
        stats['grown bytes'] += len(new) - len(sced)
    lines = stats.pop('lines', [])
    if log:
        log('world map: %d strings in %d scripts, %d without English, script text grew by %d bytes'
            % (stats['translated'], len(changed), stats['without English'], stats['grown bytes']))
        for line in lines:
            log('  ' + line)
    stats['lines'] = lines
    return changed, stats

# ------------------------------------------------------------- verifying

def verify(retail_boot, retail_fpb, new_boot, new_fpb, table=None):
    """(text references checked, [problem lines]) for a built archive."""
    table = table if table is not None else load_table()
    rboot, nboot = open(retail_boot, 'rb').read(), open(new_boot, 'rb').read()
    checked, problems = 0, []
    for (member, okids, n, old), (_m, nkids, n2, new) in zip(scripts(rboot, retail_fpb), scripts(nboot, new_fpb)):
        if n != n2 or len(okids) != len(nkids):
            problems.append('%05d: pack layout changed' % member)
            continue
        if any(a != b for i, (a, b) in enumerate(zip(okids, nkids)) if i != n):
            problems.append('%05d: a child other than the script changed' % member)
        records, addrs, done, _missing = plan(old, table)
        try:
            psp_sced.validate_code_changes(old, new)
        except Exception as e:
            problems.append('%05d: bytecode check failed: %s' % (member, e))
            continue
        _, tb = psp_sced.regions(new)
        for i, at in enumerate(addrs):
            got = psp_text.decode_string(new, tb + struct.unpack_from('<H', new, at)[0])
            want = '\n'.join(records[i])
            checked += 1
            if got != want:
                problems.append('%05d record %d reads %r, expected %r' % (member, i, got, want))
    return checked, problems


def check(table=None):
    table = table if table is not None else load_table()
    bad = 0
    for jp, en in table.items():
        try:
            psp_text.encode_record(en.split('\n'))
        except Exception as e:
            bad += 1
            print('cannot encode %r (%s)' % (en, e))
    print('%d rows, %d problems' % (len(table), bad))
    return bad


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ['report'] and len(a) == 3:
        _, stats = build_changed_members(a[1], a[2])
        stats.pop('lines', None)
        print(dict(stats))
    elif a[:1] == ['verify'] and len(a) == 5:
        checked, problems = verify(*a[1:5])
        for line in problems:
            print(line)
        print('world map: %d references checked, %d problems' % (checked, len(problems)))
        sys.exit(1 if problems else 0)
    elif a[:1] == ['check'] and len(a) == 1:
        sys.exit(1 if check() else 0)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
