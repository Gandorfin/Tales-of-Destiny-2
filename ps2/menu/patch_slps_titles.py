#!/usr/bin/env python3
"""Produce the complete English SLPS_251.72: menu patch plus character titles.

Usage:
    python3 patch_slps_titles.py <SLPS_251.72 or the folder holding it>
                                 [--csv slps_title_translations.csv] [--out FILE] [--dry-run]

Given the PyTOD2 folder, both SLPS_251.72 and new_SLPS_251.72 are patched
(Pack FPB writes the ISO executable as new_SLPS_251.72).

Steps, in order, on one in-memory copy; the file is written once at the end:
  0. If the titles are already in, repair a pooled title that an earlier
     version of this tool glued onto the previous string.
  1. The earlier Arte / Status / Enchant / Cooking-help menu patch
     (slps_menu_patch.json): every operation verified, already-applied ones
     skipped, the untouched Japanese executable rejected.
  2. The character titles: packed into contiguous arenas, so each arena is
     repacked and its pointers rewritten, spilling into the spare pool only
     when an arena fills. Pointers are 32-bit LE values of (offset + 0xFF000).
  3. The battle cut-in names of the party's artes (slps_artes.py): the banner
     shows the string after an arte's reading; 27 of those were still the
     kanji. Each gets "reading + menu name" in the pool or in a slot another
     record freed, and its reading pointer is redirected.

Re-running is safe. The file size never changes.
"""
import argparse, csv, hashlib, os, shutil, struct, sys
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P, slps_menu, slps_artes
BIAS = 0xFF000
POOL_START, POOL_END = 1026832, 1033520


def pool_free_start(d):
    """First free byte of the spare string pool: one past the terminator of
    the last string in it (+2 from the last non-zero byte, never +1)."""
    seg = d[POOL_START:POOL_END]
    used = [i for i, b in enumerate(seg) if b != 0]
    return POOL_START + (used[-1] + 2 if used else 0)


def load_records(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            recs.append((int(r["offset"], 16), r["pointers"], r["japanese"], r["english"]))
    return recs


def classify(src, recs):
    jp_ok = en_ok = 0
    for off, ptrs, jp, en in recs:
        d = M.decode_at(src, off)
        if d and d[0] == jp:
            jp_ok += 1
            continue
        po = int(ptrs.split(",")[0], 16)
        tgt = struct.unpack_from("<L", src, po)[0] - BIAS
        d2 = M.decode_at(src, tgt) if 0 <= tgt < len(src) else None
        if d2 and d2[0] == en:
            en_ok += 1
    return jp_ok, en_ok


def repair_glued(src, recs):
    """-> (bytes, fixed_count). A pooled title whose preceding byte is not
    zero overwrote the previous string's terminator; relocate it."""
    data = bytearray(src)
    fixed = 0
    for off, ptrs, jp, en in recs:
        po = int(ptrs.split(",")[0], 16)
        tgt = struct.unpack_from("<L", data, po)[0] - BIAS
        if not (POOL_START < tgt < POOL_END) or data[tgt - 1] == 0:
            continue
        enc = P.encode(en)
        need = len(enc) + 1
        new = pool_free_start(bytes(data))
        if new + need > POOL_END:
            raise RuntimeError("cannot relocate 0x%X: pool full" % off)
        data[new:new + need] = enc + b"\x00"
        data[tgt:tgt + len(enc)] = b"\x00" * len(enc)     # its own NUL now terminates the previous string
        for ph in ptrs.split(","):
            struct.pack_into("<L", data, int(ph, 16), new + BIAS)
        print(f"repaired: '{en}' was glued onto the previous string at 0x{tgt:X}, moved to 0x{new:X}")
        fixed += 1
    return bytes(data), fixed


def patch_titles(src, recs):
    """-> (bytes, inplace, spilled, pool_left). Caller verified all records are Japanese."""
    for off, ptrs, jp, en in recs:
        for ph in ptrs.split(","):
            po = int(ph, 16)
            if struct.unpack_from("<L", src, po)[0] != off + BIAS:
                raise RuntimeError("0x%X: pointer 0x%X does not point here" % (off, po))
    info = {off: (ptrs, en, M.decode_at(src, off)[1]) for off, ptrs, jp, en in recs}
    order = sorted(info)
    runs = []
    cur = [order[0]]
    for prev, off in zip(order, order[1:]):
        pv = info[prev]
        if prev + P.budget(src, prev, pv[2] - prev) + 1 == off:
            cur.append(off)
        else:
            runs.append(cur); cur = [off]
    runs.append(cur)
    data = bytearray(src)
    pool = pool_free_start(src)
    inplace = spill = 0
    for run in runs:
        last = run[-1]
        lo, hi = run[0], last + P.budget(src, last, info[last][2] - last) + 1
        pos = lo
        for off in run:
            enc = P.encode(info[off][1]); need = len(enc) + 1
            if pos + need <= hi:
                data[pos:pos + need] = enc + b"\x00"; new = pos; pos += need; inplace += 1
            elif pool + need <= POOL_END:
                data[pool:pool + need] = enc + b"\x00"; new = pool; pool += need; spill += 1
            else:
                raise RuntimeError("no space left for 0x%X" % off)
            for ph in info[off][0].split(","):
                struct.pack_into("<L", data, int(ph, 16), new + BIAS)
        if pos < hi:
            data[pos:hi] = b"\x00" * (hi - pos)
    return bytes(data), inplace, spill, POOL_END - pool


def patch_one(target, a):
    original = open(target, "rb").read()
    src = original
    recs = load_records(a.csv)
    jp_ok, en_ok = classify(src, recs)
    titles_done = en_ok == len(recs)

    # Step 0: repair, so the pool is sane before anything checks it.
    if titles_done:
        src, fixed = repair_glued(src, recs)

    # Step 1: the earlier menu patch.
    try:
        manifest = slps_menu.load()
        if slps_menu.is_applied(src, manifest):
            print("menu patch (artes, status, enchant, cooking help): already applied")
        else:
            src, n = slps_menu.apply(src, manifest)
            print(f"menu patch (artes, status, enchant, cooking help): {n} operation(s) applied")
    except slps_menu.GuardError as e:
        print(f"menu patch: {e}. Nothing written."); return 1
    except FileNotFoundError:
        print("menu patch manifest not found next to this script, skipping that step")

    # Step 2: the titles.
    pool = pool_free_start(src)
    print(f"SLPS {hashlib.sha256(original).hexdigest()[:8].upper()}, {len(original)} bytes; "
          f"spare pool: {pool - POOL_START} bytes in use, {POOL_END - pool} free")
    if titles_done:
        print(f"titles: all {len(recs)} already English")
    elif jp_ok != len(recs):
        print(f"{len(recs) - jp_ok - en_ok} title record(s) are neither the original Japanese nor the "
              f"final English ({en_ok} English, {jp_ok} Japanese). Nothing written.")
        return 1
    else:
        try:
            src, inplace, spill, left = patch_titles(src, recs)
        except RuntimeError as e:
            print(f"titles: {e}. Nothing written."); return 1
        print(f"patched {len(recs)} titles ({inplace} repacked in place, {spill} moved to the pool, {left} pool bytes left)")

    # Step 3: the battle cut-in names of the party artes.
    pend = slps_artes.pending(src)
    if not pend:
        print("arte cut-in names: all English")
    else:
        try:
            src, slots, pooled, left = slps_artes.apply(src, pool_free_start(src), POOL_END)
        except RuntimeError as e:
            print(f"arte cut-in names: {e}. Nothing written."); return 1
        print(f"arte cut-in names: {len(pend)} redirected ({slots} into freed slots, {pooled} into the pool, {left} pool bytes left)")

    assert len(src) == len(original)
    if src == original:
        print("nothing to change")
        return 0
    out = a.out or target
    if a.dry_run:
        print(f"(dry run) would write {out}")
        return 0
    if out == target and not os.path.exists(target + ".bak"):
        shutil.copy(target, target + ".bak")
    open(out, "wb").write(src)
    print(f"written: {out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slps")
    ap.add_argument("--csv", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "slps_title_translations.csv"))
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    targets = []
    if os.path.isdir(a.slps):
        for name in ("SLPS_251.72", "new_SLPS_251.72"):
            cand = os.path.join(a.slps, name)
            if os.path.isfile(cand):
                targets.append(cand)
        if not targets:
            print(f"No SLPS_251.72 in {a.slps}"); return 2
    elif os.path.isfile(a.slps):
        targets = [a.slps]
        base = os.path.basename(a.slps)
        sib = os.path.join(os.path.dirname(os.path.abspath(a.slps)),
                           "new_SLPS_251.72" if base != "new_SLPS_251.72" else "SLPS_251.72")
        if os.path.isfile(sib) and not a.out:
            print(f"Note: {os.path.basename(sib)} also exists next to this file. PyTOD2's Pack FPB")
            print("writes the ISO executable as new_SLPS_251.72, so make sure the copy that")
            print("goes into the ISO is the patched one (pass the folder to patch both).")
    else:
        print(f"File not found: {a.slps}"); return 2
    rc = 0
    for target in targets:
        print(f"\n== {target} ==")
        rc |= patch_one(target, a)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
