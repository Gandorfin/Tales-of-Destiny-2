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
  4. Every pooled string that sits on bytes the game overwrites while it
     runs (LIVE below) is moved to free pool space, with its pointers.
  5. The Latin font (slps_font.py): '&' and '~' had no glyph and '*' was a
     star, so an ampersand, a tilde and an asterisk are drawn into the font
     texture and the two ASCII table entries are pointed at them.

Re-running is safe. The file size never changes.
"""
import argparse, csv, hashlib, os, shutil, struct, sys
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P, slps_menu, slps_artes, slps_font
BIAS = 0xFF000
# The spare string pool, 0xFAB10..0xFC508. It is not unused memory: the
# zeros are the work area of the game's CD/DVD library (the "PsIIlibcdvd"
# data, just before "PsIIlibkernl"). The game calls two functions of that
# library, sceCdInit and sceCdMmode, both while it boots, and they write to
# the ranges in LIVE. A string stored there is damaged in memory: Kyle's
# arte Kyoueisou read "Lyoueisou", the Battle Rank "Normal+" and the item
# "Pickaxe" drew as nothing. The rest of the area belongs to library
# functions the game never calls, which is why pooled text works at all.
#   0xFAB10  4 bytes   init counter, incremented by every sceCdInit
#   0xFBCC0  16 bytes  reply buffer of the init and media mode commands
#   0xFC100  4 bytes   parameter buffer of the media mode command
#   0xFC508  40 bytes  RPC client record of the command channel
# New strings are placed below 0xFC508 and never on a LIVE range.
POOL_START, POOL_END = 0xFAB10, 0xFC508
LIVE = ((0xFAB10, 0xFAB14), (0xFBCC0, 0xFBCD0), (0xFC100, 0xFC104), (0xFC508, 0xFC530))
DATA_START, DATA_END = 0xB7580, 0x135328      # .data and .rodata: where pointers live

FORMER_TITLE_TRANSLATIONS = {
    0x113CE1: 'Meeting a Holy Woman',
    0x1135CE: 'Chase the Flying Dragon!',
    0x1135A0: 'Inside the Flying Dragon',
    0x113524: 'Escape the Flying Dragon 1',
    0x113511: 'Escape the Flying Dragon 2',
    0x1134A8: 'Escape the Flying Dragon 3',
    0x113495: 'Escape the Flying Dragon 4',
    0x113168: 'Untamed Forest 1',
    0x11315D: 'Untamed Forest 2',
    0x112268: "God's Egg Is\\\\\\\\",
    0x111E03: "Depths of God's Egg",
}


def pool_free_start(d):
    """First free byte of the spare string pool: one past the terminator of
    the last string in it (+2 from the last non-zero byte, never +1)."""
    seg = d[POOL_START:POOL_END]
    used = [i for i, b in enumerate(seg) if b != 0]
    return POOL_START + (used[-1] + 2 if used else 0)


def _on_live(start, end):
    return any(start < hi and end > lo for lo, hi in LIVE)


def evacuate_live(src):
    """-> (bytes, [moved texts]). Move every pooled string that touches a
    LIVE range to free pool space and zero the bytes it leaves.

    A pooled string without a pointer of its own belongs to the string in
    front of it (a cut-in name follows its reading), so the two move as one
    unit. The strings of slps_menu_patch.json have fixed places outside
    LIVE; this pass is for the titles and cut-in names, whose places depend
    on how much text went into the pool before them."""
    data = bytearray(src)
    pointers = {}
    for at in range(DATA_START, DATA_END - 3, 4):
        value = struct.unpack_from("<L", data, at)[0] - BIAS
        if POOL_START <= value < LIVE[-1][1]:
            pointers.setdefault(value, []).append(at)
    units = []                              # [start, end) with every NUL but the last
    p = POOL_START
    while p < LIVE[-1][1]:
        if data[p] == 0:
            p += 1
            continue
        e = data.index(b"\0", p)
        if p in pointers or not units or units[-1][1] + 1 != p:
            units.append([p, e])
        else:
            units[-1][1] = e
        p = e + 1
    moved = []
    for start, end in units:
        # end is the final NUL; that byte must survive library writes too.
        if not _on_live(start, end + 1):
            continue
        if not any(start <= t < end for t in pointers):
            data[start:end] = bytes(end - start)        # nothing points at it
            continue
        need = end - start + 1
        new = pool_free_start(bytes(data))
        for lo, hi in LIVE:
            if new < hi and new + need > lo:
                new = hi
        if new + need > POOL_END:
            raise RuntimeError("no pool space left to move the string at 0x%X" % start)
        block = bytes(data[start:end])
        data[start:end] = bytes(end - start)
        data[new:new + need] = block + b"\0"
        for target in [t for t in pointers if start <= t < end]:
            for at in pointers[target]:
                struct.pack_into("<L", data, at, target - start + new + BIAS)
        moved.append(block.split(b"\0")[0].decode("ascii", "replace"))
    return bytes(data), moved


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


def migrate_former_titles(src, recs):
    """Update older English title strings through their existing pointers."""
    data = bytearray(src)
    changed = 0
    for off, ptrs, _jp, en in recs:
        former = FORMER_TITLE_TRANSLATIONS.get(off)
        if not former:
            continue
        po = int(ptrs.split(',')[0], 16)
        target = struct.unpack_from('<L', data, po)[0] - BIAS
        current = M.decode_at(data, target) if 0 <= target < len(data) else None
        if not current or current[0] != former:
            continue
        available = P.budget(data, target, current[1] - target)
        encoded = P.encode(en)
        if len(encoded) > available:
            # no room where the old wording sits: move it to the pool and
            # clear the old bytes (its own NUL keeps the previous string)
            need = len(encoded) + 1
            new = pool_free_start(bytes(data))
            if new + need > POOL_END:
                raise RuntimeError(
                    "former title 0x%X needs %d bytes; only %d available "
                    "in place and the pool is full" % (off, len(encoded), available))
            data[new:new + need] = encoded + b'\0'
            data[target:target + available] = b'\0' * available
            for ph in ptrs.split(','):
                struct.pack_into('<L', data, int(ph, 16), new + BIAS)
            changed += 1
            continue
        region = available + 1
        data[target:target + region] = encoded + b'\0' * (region - len(encoded))
        changed += 1
    return bytes(data), changed


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
    try:
        src, migrated = migrate_former_titles(src, recs)
    except RuntimeError as e:
        print(f"titles: {e}. Nothing written.")
        return 1
    if migrated:
        print(f"titles: migrated {migrated} former English name(s)")
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

    # Step 4: nothing may stay on the bytes the game overwrites.
    try:
        src, moved = evacuate_live(src)
    except RuntimeError as e:
        print(f"pool: {e}. Nothing written."); return 1
    if moved:
        print("pool: moved off the bytes the game overwrites: " + ", ".join(moved))

    # Step 5: '&', '~' and '*' glyphs in the Latin font.
    try:
        src, changes = slps_font.apply(src)
    except slps_font.FontError as e:
        print(f"font: {e}. Nothing written."); return 1
    print("font: " + (", ".join(changes) if changes else "'&', '~' and '*' glyphs already in place"))

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
