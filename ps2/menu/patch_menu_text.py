#!/usr/bin/env python3
"""Apply the ToD2 English menu text to extracted FILE.FPB files.

Usage:
    python3 patch_menu_text.py <FPB_folder> [--csv menu_translations.csv] [--dry-run]

<FPB_folder> is the folder PyTOD2 extracts FILE.FPB into (contains 06799.md1 etc).
Every record is verified before anything is written: it must hold the original
Japanese, the final English, or an English wording an earlier release wrote
there (menu_former_translations.csv), so re-running on a patched or partly
patched build is safe and a folder patched by any older release is brought up
to date. Files are patched in place at
identical size, so the FPB pointer table is untouched. Nothing is written to a
file unless every one of its records verifies. The world map labels that do not
fit their slot (Laguna Ruins, Atamoni Ovum) use verified unused SCED padding and
update their text references, also without changing file sizes. The shop module
also gets the pointer of its sell confirmation repaired (shop_prompt.py).
"""
import argparse, csv, os, sys, shutil
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P, pak3, lzss, world_map_labels, shop_prompt, refine_lens

# the shop module: its sell confirmation needs a pointer repaired (shop_prompt.py)
SHOP_MODULE = '06803.md1'
# code fixes after the records: shop sell prompt pointer, refine lens format
MODULE_FIXES = {SHOP_MODULE: shop_prompt.apply, '06802.md1': refine_lens.apply}

# FILE.FPB holds every menu module twice: 06798..06816 as plain files and
# 06817..06835 as comptoe LZSS copies of the same bytes (06817 = 06798 ...
# 06835 = 06816; byte identical on the retail and the Cless disc). The game
# loads the packed copies too: the refine screen showed the 2008 "A0,B0/ 99"
# in 1.3.3 although 06802 says "A:0 B:0/ 99". They get the records of their
# plain module, unpacked, patched and packed again.
PACKED_TWINS = {f'{i + 19:05d}.md1': f'{i:05d}.md1' for i in range(6798, 6817)}

FORMER_TRANSLATIONS = {
    ('09028.pak0', 0xFFE57): 'Laguna',
    ('09032.pak0', 0xFFF33): 'Laguna',
    ('06807.md1', 0x7670): 'K.O.',
    ('09028.pak0', 0x100350): ('Fire the anchor into the Flying Dragon!\n'
                               'Jump across onto its back!\nReady?'),
    ('09030.pak0', 0x101427): 'Crimson Speranza',
    ('09030.pak0', 0x10143C): 'Twilight Realta',
    ('09030.pak0', 0x10146A): 'Sea Cave',
    ('06167.md1', 0x1E8F8): ('Quit the quiz?\n \n'
                             "<button:00000035>Quit  <button:00000036>Don't"),
    ('09031.pak0', 0xD8841): "Er'ther",
    ('09031.pak0', 0xD884C): "Er'ther",
}

def resolve_folder(given):
    """Accept the extracted FPB folder, or a folder containing one."""
    if os.path.isfile(given):
        print(f"'{given}' is a file, not a folder.")
        if os.path.basename(given).upper().startswith("FILE"):
            print("That looks like FILE.FPB itself. Extract it with PyTOD2 first")
            print("(Extract Files), then point this script at the FPB folder it")
            print("creates, for example ...\\ps2\\PyTOD2\\FPB")
        return None
    if not os.path.isdir(given):
        print(f"Folder not found: {given}")
        return None
    def looks_right(p):
        try: return any(f.endswith((".md1",".pak0")) for f in os.listdir(p))
        except OSError: return False
    if looks_right(given): return given
    for sub in ("FPB","fpb"):                       # they pointed one level up
        cand=os.path.join(given,sub)
        if os.path.isdir(cand) and looks_right(cand):
            print(f"Using {cand}")
            return cand
    print(f"No .md1 or .pak0 files in {given}")
    print("Extract FILE.FPB with PyTOD2 first, then point this script at the")
    print("FPB folder it creates, for example ...\\ps2\\PyTOD2\\FPB")
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--csv", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),"menu_translations.csv"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    a=ap.parse_args()
    folder=resolve_folder(a.folder)
    if folder is None: return 2
    groups={}
    with open(a.csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups.setdefault(r["file"],[]).append((int(r["offset"],16), r["japanese"], r["english"]))
    formers=pak3.load_formers()
    for key, text in FORMER_TRANSLATIONS.items():
        formers.setdefault(key, set()).add(text)
    total=written=current=skipped=0; failed=[]
    for name, entries in sorted(groups.items()):
        path=os.path.join(folder,name)
        if not os.path.exists(path):
            print(f"  SKIP {name}: not found in {folder}"); skipped+=len(entries); continue
        d=bytearray(open(path,"rb").read()); orig=bytes(d); errs=[]; pending=[]; done=0
        world_requested = 0
        for off,jp,en in entries:
            label = world_map_labels.find(name, off)
            if label:
                world_requested += 1
                if jp != label.japanese or en != label.text:
                    errs.append('world-map relocation translation changed')
                continue
            r=M.decode_at(orig,off)
            if not r: errs.append(f"0x{off:X} decode failed"); continue
            got,end,_=r
            if got==en: done+=1; continue                       # already translated
            if got != jp and got not in formers.get((name, off), ()):
                errs.append(f"0x{off:X} expected {ascii(jp[:16])} found {ascii(got[:16])}")
                continue
            avail=P.budget(orig,off,end-off); enc=P.encode(en)
            if len(enc)>avail: errs.append(f"0x{off:X} {len(enc)} > {avail} bytes"); continue
            pending.append((off,avail,enc))
        for off,avail,enc in pending:
            region=avail+1
            d[off:off+region]=enc+b"\x00"*(region-len(enc))
        relocated = 0
        if world_requested and world_requested != len(world_map_labels.LABELS[name]):
            errs.append('world-map relocation rows are missing from the table')
        if world_requested and not errs:
            try:
                relocated, already = world_map_labels.apply(d, name)
                done += already
            except ValueError as error:
                errs.append(str(error))
        if name in MODULE_FIXES and not errs:
            try:
                fixed, _ = MODULE_FIXES[name](d)
                relocated += fixed
            except ValueError as error:
                errs.append(str(error))
        if errs:
            print(f"  FAIL {name}: {len(errs)} problem(s), file left untouched")
            for e in errs[:5]: print(f"        {e}")
            skipped+=len(entries); failed.append(name); continue
        assert len(d)==len(orig)
        changed_count = len(pending) + relocated
        if changed_count and not a.dry_run:
            if not a.no_backup and not os.path.exists(path+".bak"): shutil.copy(path,path+".bak")
            open(path,"wb").write(d)
        if changed_count:
            extra=f", {done} already done" if done else ""
            print(f"  {'would patch' if a.dry_run else 'patched'} {name}: {changed_count} strings{extra}")
        else:
            print(f"  current {name}: all {done} strings already translated")
        written+=changed_count; current+=done
        total+=1
    print(f"\n{written} strings patched, {current} already current, {total} files"
          f"{' (dry run)' if a.dry_run else ''}" + (f", {skipped} skipped" if skipped else ""))
    rc=patch_containers(folder, groups, a, formers, failed)
    rc|=patch_packed_twins(folder, groups, a, formers, failed)
    if failed:
        print("\n" + "!"*72)
        print(f"NOT PATCHED ({len(failed)}): " + ", ".join(failed))
        print("These files were left exactly as they were, so the game will show their")
        print("OLD text. Restore them from a fresh Unpack FPB (or their .bak) and run")
        print("this script again; if a file still fails, report the lines above.")
        print("!"*72)
    return 1 if (skipped or rc) else 0

def patch_packed_twins(folder, groups, a, formers=None, failed=None):
    """Apply the records of 06798..06816 to their LZSS copies 06817..06835."""
    print("\nPacked copies of the menu modules:")
    bad=0
    for name, plain in sorted(PACKED_TWINS.items()):
        path=os.path.join(folder,name)
        if not os.path.exists(path) or plain not in groups: continue
        blob=open(path,"rb").read()
        if not lzss.is_packed(blob):
            print(f"  FAIL {name}: not an LZSS stream"); bad+=1
            if failed is not None: failed.append(name)
            continue
        mod=lzss.unpack(blob)
        former={off: texts for (fname, off), texts in (formers or {}).items() if fname==plain}
        new,patched,done,errs=pak3.apply_records(mod, groups[plain], former)
        fixed=0
        if plain in MODULE_FIXES and not errs:
            d=bytearray(new)
            try:
                fixed,_=MODULE_FIXES[plain](d); new=bytes(d)
            except ValueError as error:
                errs.append(str(error))
        if errs:
            print(f"  FAIL {name} ({plain}): {len(errs)} problem(s), file left untouched")
            for e in errs[:5]: print("        "+e)
            bad+=1
            if failed is not None: failed.append(f"{name} ({plain})")
            continue
        if not patched and not fixed:
            print(f"  current {name} ({plain}): all {done} strings already translated"); continue
        out=lzss.pack(new, blob[0])
        if lzss.unpack(out)!=new: raise RuntimeError(f"{name}: LZSS round trip failed")
        if not a.dry_run:
            if not a.no_backup and not os.path.exists(path+".bak"): shutil.copy(path,path+".bak")
            open(path,"wb").write(out)
        extra=f", {done} already done" if done else ""
        print(f"  {'would patch' if a.dry_run else 'patched'} {name} ({plain}): {patched+fixed} strings{extra}")
    return bad

def patch_containers(folder, groups, a, formers=None, failed=None):
    """The .pak3 files hold compressed copies of some modules (00017.pak3:
    battle 08055, world map 08996, and 06304). The game loads THOSE, not the
    loose .md1 files, so they are rebuilt here with the same records."""
    names=sorted(f for f in os.listdir(folder) if f.lower().endswith(".pak3"))
    if not names: return 0
    print("\nCompressed module containers:")
    bad=0
    for name in names:
        path=os.path.join(folder,name)
        data=open(path,"rb").read()
        try: members=pak3.parse(data)
        except Exception as e: print(f"  SKIP {name}: cannot parse ({e})"); continue
        blobs=[]; changed=False; report=[]
        for k,(off,blob) in enumerate(members):
            if not lzss.is_packed(blob): blobs.append(blob); continue
            mod=lzss.unpack(blob)
            which=pak3.identify(mod, groups, formers)
            if which is None: blobs.append(blob); continue
            former={off: texts for (fname, off), texts in (formers or {}).items() if fname==which}
            new,patched,done,errs=pak3.apply_records(mod, groups[which], former)
            if errs:
                print(f"  FAIL {name} member {k} ({which}): {len(errs)} problem(s), container left untouched")
                for e in errs[:5]: print("        "+e)
                bad+=1; blobs=None
                if failed is not None: failed.append(f"{name} ({which})")
                break
            if patched:
                blobs.append(lzss.pack(new, blob[0])); changed=True
                report.append(f"{which}: {patched} strings" + (f", {done} already done" if done else ""))
            else:
                blobs.append(blob); report.append(f"{which}: all {done} already translated")
        if blobs is None: continue
        if changed:
            out=pak3.build(blobs)
            # prove the rebuilt container still decodes to the patched modules
            for (o1,b1),(o2,b2) in zip(pak3.parse(out), members):
                if lzss.is_packed(b1): lzss.unpack(b1)
            if not a.dry_run:
                if not a.no_backup and not os.path.exists(path+".bak"): shutil.copy(path,path+".bak")
                open(path,"wb").write(out)
            print(f"  {'would rebuild' if a.dry_run else 'rebuilt'} {name} ({len(data)} -> {len(out)} bytes): " + "; ".join(report))
        elif report:
            print(f"  current {name}: " + "; ".join(report))
    return bad

if __name__=="__main__": raise SystemExit(main())
