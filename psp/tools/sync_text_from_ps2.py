#!/usr/bin/env python3
"""Copy the PS2 text sources into the PSP's own snapshot in psp/text.

    python psp/tools/sync_text_from_ps2.py           copy what changed
    python psp/tools/sync_text_from_ps2.py --check   only report it

The PSP build reads its text only from psp/text (and its own fixes from
psp/text/overrides.tsv), so an edit of the PS2 text reaches the PSP when
this tool runs, not before. Copied: the scenario and skit English, the
movie subtitles, the text encoding table and the skit time windows. Files
are copied byte for byte; contents are compared with line endings
normalised, so a Windows checkout (CRLF) never counts as a change.

Never edit the copies by hand: edit the PS2 folders and sync, and put
PSP only fixes into psp/text/overrides.tsv (the sync never touches it).
Writes nothing outside psp/text. --check exits with 1 when psp/text lags
behind the PS2 sources, 0 when it is up to date.
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
TEXT = os.path.join(ROOT, 'psp', 'text')
DIVIDER = '-----------------------'
CHOICE = '<03:'  # a choice record (menu), see changed_choices

# (name, PS2 source relative to the repository, copy relative to psp/text,
#  file pattern for a folder or None for a single file)
PAIRS = [
    ('scenario', 'Third pass Quality-Safe Output', 'scenario', r'.*\.txt$'),
    ('skits', 'third pass skits safe output', 'skits', r'.*\.txt$'),
    ('subtitles', 'ps2/movies/subtitles', 'subtitles', r'.*\.srt$'),
    ('encoding table', 'ps2/PyTOD2/TBL.json', 'TBL.json', None),
    ('skit time windows', 'ps2/PyTOD2/skit_speeds.json', 'skit_speeds.json', None),
]


def path_of(base, rel):
    return os.path.join(base, *rel.split('/'))


def names(folder, pattern):
    if not os.path.isdir(folder):
        return set()
    return {n for n in os.listdir(folder) if re.match(pattern, n) and os.path.isfile(os.path.join(folder, n))}


def content(path):
    with open(path, 'rb') as f:
        return f.read().replace(b'\r\n', b'\n')


def records(data):
    """Records of a TXT file (blocks between dashed lines)."""
    out, cur = [], []
    for line in data.decode('utf-8', errors='replace').split('\n'):
        if DIVIDER in line:
            out.append('\n'.join(cur))
            cur = []
        else:
            cur.append(line)
    return out


def changed_records(old, new):
    """Records that differ position by position (a record added or removed
    in the middle counts every record after it)."""
    a, b = records(old), records(new)
    return sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))


def changed_choices(old, new):
    """Changed records that hold a choice code <03:...>. A choice record must
    keep the Japanese line and code structure exactly, or its menu can stick
    (the Skit Hut, PR 107), so the sync names them for a second look."""
    a, b = records(old), records(new)
    return sum(1 for x, y in zip(a, b) if x != y and CHOICE in x + y)


def differences(root=None, text=None):
    """[(pair name, file name, state, records changed, choice records
    changed)] where state is 'changed', 'new' (only in the PS2 source) or
    'removed' (only in psp/text). Raises FileNotFoundError when a PS2 source
    is missing."""
    root = root or ROOT
    text = text or os.path.join(root, 'psp', 'text')
    out = []
    for name, src_rel, dst_rel, pattern in PAIRS:
        src, dst = path_of(root, src_rel), path_of(text, dst_rel)
        if pattern is None:
            if not os.path.isfile(src):
                raise FileNotFoundError(src)
            pairs = {os.path.basename(src): (src, dst)}
            gone = set()
        else:
            if not os.path.isdir(src):
                raise FileNotFoundError(src)
            have = names(src, pattern)
            pairs = {n: (os.path.join(src, n), os.path.join(dst, n)) for n in have}
            gone = names(dst, pattern) - have
        for n, (s, d) in sorted(pairs.items()):
            if not os.path.isfile(d):
                out.append((name, n, 'new', len(records(content(s))) if n.endswith('.txt') else 0, 0))
            else:
                old, new = content(d), content(s)
                if old != new:
                    txt = n.endswith('.txt')
                    out.append((name, n, 'changed', changed_records(old, new) if txt else 0,
                                changed_choices(old, new) if txt else 0))
        for n in sorted(gone):
            out.append((name, n, 'removed', 0, 0))
    return out


def apply(diffs, root=None, text=None):
    root = root or ROOT
    text = text or os.path.join(root, 'psp', 'text')
    spec = {name: (src_rel, dst_rel, pattern) for name, src_rel, dst_rel, pattern in PAIRS}
    for name, n, state, _, _ in diffs:
        src_rel, dst_rel, pattern = spec[name]
        if pattern is None:
            src, dst = path_of(root, src_rel), path_of(text, dst_rel)
        else:
            src, dst = os.path.join(path_of(root, src_rel), n), os.path.join(path_of(text, dst_rel), n)
        if state == 'removed':
            os.remove(dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)


def report(diffs):
    if not diffs:
        print('psp/text is up to date with the PS2 sources')
        return
    by = {}
    for name, n, state, recs, choices in diffs:
        by.setdefault(name, []).append((n, state, recs, choices))
    for name, rows in by.items():
        count = {s: sum(1 for _, st, _, _ in rows if st == s) for s in ('changed', 'new', 'removed')}
        recs = sum(r for _, st, r, _ in rows if st == 'changed')
        print('%s: %d changed (%d records), %d new, %d removed'
              % (name, count['changed'], recs, count['new'], count['removed']))
        for n, state, r, _ in rows[:20]:
            print('  %-8s %s%s' % (state, n, ' (%d records)' % r if state == 'changed' and r else ''))
        if len(rows) > 20:
            print('  ... %d more' % (len(rows) - 20))
    for name, n, state, _, choices in diffs:
        if choices:
            print('CHECK: %s %s changes %d choice record(s) (<03:...>); the English must keep the '
                  'Japanese line and code structure, or the menu can stick' % (name, n, choices))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='only report the difference, copy nothing')
    args = ap.parse_args(argv)
    try:
        diffs = differences(ROOT, TEXT)
    except FileNotFoundError as e:
        print('PS2 source not found: %s (run this inside a full clone of the repository)' % e)
        return 2
    report(diffs)
    if args.check:
        return 1 if diffs else 0
    if diffs:
        apply(diffs, ROOT, TEXT)
        print('updated %d file(s) in %s' % (len(diffs), TEXT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
