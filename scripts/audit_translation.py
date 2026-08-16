#!/usr/bin/env python3
"""Automated quality audit for the translated .sced.txt script files.

Scans the third-pass output folders and reports problems in two severity
groups:

CRITICAL (these can crash the game or hide text, and should never grow):
  code-mismatch        Runtime/control codes in the English do not match the
                       Japanese source (missing, extra, or duplicated codes).
                       Per "Dialogue and Script Layout Restrictions.md" the
                       source code sequence is authoritative.
  untranslated         A record has Japanese source lines but no English
                       lines. Includes English lines accidentally prefixed
                       with '#', which the format treats as reference data.
  misplaced-japanese   A line containing Japanese text sits in English
                       position (usually a source line that lost its '#').
                       It would compile into the game as literal text.
  interleaved-english  An English line sits between two Japanese source
                       lines inside one record (usually a leftover draft
                       fragment).

INFO (quality signals, reported but not build-breaking):
  layout-width         A rendered segment exceeds 36 visible characters
                       ({02} page breaks are respected when measuring).
  layout-lines         An ordinary dialogue record exceeds 5 English lines.
  layout-page          The first four rows of a page exceed the 126 visible
                       character budget.
  term-drift           The same short Japanese source line is translated in
                       more than one way across the corpus.

Usage:
  python3 scripts/audit_translation.py [ROOT]           # human summary
  python3 scripts/audit_translation.py --json out.json  # machine output
  python3 scripts/audit_translation.py --strict         # exit 1 if any
                                                        # critical findings

Layout limits only apply to the scenario corpus; skits use a different
renderer with its own timing constraints.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

SCENARIO_DIR = 'Third pass Quality-Safe Output'
SKIT_DIR = 'third pass skits safe output'

DIVIDER = re.compile(r'^-{5,}\s*$')
CODE = re.compile(r'<[^<>\n]+>|\{[0-9A-Fa-f]{2}\}')
PAGE_BREAK = '{02}'
CJK = re.compile(r'[぀-ヿ一-鿿]')

MAX_WIDTH = 36
MAX_LINES = 5
MAX_PAGE = 126

CRITICAL = ('code-mismatch', 'untranslated', 'misplaced-japanese',
            'interleaved-english')
INFO = ('layout-width', 'layout-lines', 'layout-page', 'term-drift')


def visible_len(text):
    return len(CODE.sub('', text))


def codes_of(text):
    return Counter(CODE.findall(text))


def parse_blocks(path):
    lines = open(path, encoding='utf-8').read().split('\n')
    blocks, cur, start = [], [], 1
    for i, ln in enumerate(lines, 1):
        if DIVIDER.match(ln):
            if cur and any(s.strip() for s in cur):
                blocks.append((start, cur))
            cur, start = [], i + 1
        else:
            cur.append(ln)
    if cur and any(s.strip() for s in cur):
        blocks.append((start, cur))
    return blocks


def check_layout(en_lines, rec, findings):
    """Width / line-count / page-budget checks, respecting {02} breaks."""
    text = '\n'.join(en_lines)
    for page in text.split(PAGE_BREAK):
        rows = [r for r in page.split('\n') if r.strip()]
        wide = [r for r in rows if visible_len(r) > MAX_WIDTH]
        if wide:
            findings['layout-width'].append(
                {**rec, 'worst': max(visible_len(r) for r in rows),
                 'text': wide[0][:60]})
        if sum(visible_len(r) for r in rows[:4]) > MAX_PAGE:
            findings['layout-page'].append(
                {**rec, 'page_chars': sum(visible_len(r) for r in rows[:4])})
    if len(en_lines) > MAX_LINES:
        findings['layout-lines'].append({**rec, 'lines': len(en_lines)})


def audit_file(path, is_scenario, findings, term_map):
    for lineno, block in parse_blocks(path):
        jp_idx = [i for i, l in enumerate(block) if l.startswith('#')]
        en_idx = [i for i, l in enumerate(block)
                  if not l.startswith('#') and l.strip()]
        jp = [block[i][1:] for i in jp_idx]
        en = [block[i] for i in en_idx]
        rec = {'file': os.path.basename(path), 'line': lineno}

        # English-position line containing Japanese text
        for i in en_idx:
            if CJK.search(block[i]):
                findings['misplaced-japanese'].append(
                    {**rec, 'text': block[i][:60]})

        if not jp:
            continue  # command-only or bare speaker-tag block

        # English fragment wedged between Japanese source lines
        if jp_idx and en_idx:
            first_jp, last_jp = jp_idx[0], jp_idx[-1]
            for i in en_idx:
                if first_jp < i < last_jp:
                    findings['interleaved-english'].append(
                        {**rec, 'text': block[i][:60]})

        if not en:
            findings['untranslated'].append(
                {**rec, 'jp': ' / '.join(jp)[:60]})
            continue

        cj, ce = codes_of('\n'.join(jp)), codes_of('\n'.join(en))
        if cj != ce:
            findings['code-mismatch'].append(
                {**rec,
                 'missing_in_en': list((cj - ce).elements()),
                 'extra_in_en': list((ce - cj).elements()),
                 'en': en[0][:60]})

        if is_scenario:
            check_layout(en, rec, findings)

        jp_flat = ''.join(jp).strip()
        if len(jp) == 1 and 0 < len(CODE.sub('', jp_flat)) <= 14:
            term_map[jp_flat][' '.join(en).strip()] += 1


def run_audit(root):
    findings = defaultdict(list)
    term_map = defaultdict(Counter)
    counts = {}
    for folder, is_scen in ((SCENARIO_DIR, True), (SKIT_DIR, False)):
        fdir = os.path.join(root, folder)
        if not os.path.isdir(fdir):
            continue
        names = sorted(f for f in os.listdir(fdir) if f.endswith('.txt'))
        counts[folder] = len(names)
        for name in names:
            audit_file(os.path.join(fdir, name), is_scen, findings, term_map)

    drift = {jp: dict(ens) for jp, ens in term_map.items()
             if len(ens) > 1 and sum(ens.values()) >= 3}
    findings['term-drift'] = [
        {'jp': jp, 'variants': ens} for jp, ens in sorted(drift.items())]

    return {
        'files': counts,
        'critical': {k: len(findings[k]) for k in CRITICAL},
        'info': {k: len(findings[k]) for k in INFO},
        'findings': {k: v for k, v in findings.items() if v},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('root', nargs='?', default='.',
                    help='repository root to scan (default: current dir)')
    ap.add_argument('--json', metavar='PATH',
                    help='also write full results as JSON')
    ap.add_argument('--strict', action='store_true',
                    help='exit with status 1 if any critical findings exist')
    args = ap.parse_args()

    result = run_audit(args.root)

    print('Files scanned:', json.dumps(result['files']))
    print('Critical findings:')
    for k in CRITICAL:
        print(f'  {k:22s} {result["critical"][k]}')
    print('Info findings:')
    for k in INFO:
        print(f'  {k:22s} {result["info"][k]}')

    shown = 0
    for k in CRITICAL:
        for item in result['findings'].get(k, []):
            if shown >= 25:
                break
            print(f'  [{k}] {json.dumps(item, ensure_ascii=False)[:160]}')
            shown += 1

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)

    total_critical = sum(result['critical'].values())
    if args.strict and total_critical:
        print(f'STRICT MODE: {total_critical} critical finding(s).')
        sys.exit(1)


if __name__ == '__main__':
    main()
