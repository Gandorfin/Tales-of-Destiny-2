#!/usr/bin/env python3
"""Recover PSP records that have no exact PS2 twin but ARE mechanically
derivable from one, and append them to the supplement table (no translation):

  1. Template records: identical prose after stripping control codes, same
     number of codes, only the code VALUES differ (item-pickup / gald lines
     where the PSP uses a different item id). English = the PS2 line with its
     codes positionally remapped to the PSP line's codes.
  2. Near-identical records: difflib ratio >= 0.94 with the same code layout
     (small JP typos: 一所/一生, ぐらい/くらい, アトワイト/アトワト). English copied
     verbatim.

Usage: psp_recover.py WORK [ps2root]  ->  writes/updates psp/tools/psp_supplement.tsv
"""
import os, re, sys, csv, collections, difflib, json
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..')
sys.path.insert(0, HERE); import psp_text
CODE = re.compile(r'<[^>]*>|\{[0-9A-F]{2}\}')
def strip_codes(s): return CODE.sub('\x00', s)      # placeholder keeps token positions
def codes(s): return CODE.findall(s)
def trig(s):
    z = re.sub(r'[\x00]', '', strip_codes(s)); return {z[i:i+3] for i in range(len(z)-2)} or {z}

def recover(work, ps2root=ROOT):
    corpus = psp_text.load_ps2_corpus(ps2root)
    corpus = {k: {psp_text.norm_key(jp.split('\n')): en for jp, en in v.items()} for k, v in corpus.items()}
    keys = {k: list(v) for k, v in corpus.items()}
    idx = {k: collections.defaultdict(list) for k in keys}
    for k, ks in keys.items():
        for i, key in enumerate(ks):
            for t in trig(key): idx[k][t].append(i)
    JP = re.compile(r'[぀-ヿ一-鿿]')
    rows = list(csv.reader(open(os.path.join(work, 'unmatched.tsv'), encoding='utf-8'), delimiter='\t'))
    out = []; stats = collections.Counter(); samples = collections.defaultdict(list)
    for r in rows:
        if len(r) < 3: continue
        kind, fid, raw = r[0], r[1], r[2]; psp = raw.replace('\\n', '\n')
        if not JP.search(psp): continue
        tg = trig(psp); cand = collections.Counter()
        for t in tg:
            for i in idx[kind].get(t, ()): cand[i] += 1
        best_i, best_r = -1, 0.0
        for i, _ in cand.most_common(8):
            rr = difflib.SequenceMatcher(None, psp, keys[kind][i]).ratio()
            if rr > best_r: best_r, best_i = rr, i
        if best_i < 0: continue
        ps2 = keys[kind][best_i]; en = corpus[kind][ps2]
        pc, sc = codes(psp), codes(ps2)
        # 1. template: same prose skeleton, same code count, values differ
        if strip_codes(psp) == strip_codes(ps2) and len(pc) == len(sc) and pc != sc:
            enj = '\n'.join(en); ecodes = codes(enj)
            # remap: each PS2 code -> the PSP code at the same position in the JP token order
            m = {s: p for s, p in zip(sc, pc)}
            new_en = CODE.sub(lambda mo: m.get(mo.group(0), mo.group(0)), enj)
            out.append((kind, psp, new_en)); stats['template'] += 1
            if len(samples['template']) < 4: samples['template'].append((psp[:40], new_en[:50]))
            continue
        # 2. near-identical prose, same code layout, high ratio -> verbatim english
        if pc == sc and best_r >= 0.94 and strip_codes(psp) != strip_codes(ps2):
            out.append((kind, psp, '\n'.join(en))); stats['verbatim'] += 1
            if len(samples['verbatim']) < 6: samples['verbatim'].append((psp[:44], ps2[:44]))
    # merge into supplement, keyed by (kind, jp) with source tag
    sup_path = os.path.join(HERE, 'psp_supplement.tsv')
    existing = {}
    if os.path.exists(sup_path):
        for line in open(sup_path, encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            if len(p) >= 4: existing[(p[0], p[1])] = p  # kind, jpkey, en, source
    for kind, psp, en in out:
        key = (kind, psp.replace('\n', '\\n'))
        existing.setdefault(key, [kind, key[1], en.replace('\n', '\\n'), 'recover'])
    with open(sup_path, 'w', encoding='utf-8') as f:
        for p in sorted(existing.values()): f.write('\t'.join(p) + '\n')
    print('recovered:', dict(stats), '| supplement now', len(existing), 'rows')
    for cat, ex in samples.items():
        print('--', cat); [print('   ', a, '->', b) for a, b in ex]

if __name__ == '__main__':
    recover(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ROOT)
