#!/usr/bin/env python3
"""Apply the ToD2 English menu text to extracted FILE.FPB files.

Usage:
    python3 patch_menu_text.py <FPB_folder> [--csv menu_translations.csv] [--dry-run]

<FPB_folder> is the folder PyTOD2 extracts FILE.FPB into (contains 06799.md1 etc).
Every record is verified before anything is written: it must hold either the
original Japanese or the final English (so re-running on a patched or partly
patched build is safe and only fills the gaps). Files are patched in place at
identical size, so the FPB pointer table is untouched. Nothing is written to a
file unless every one of its records verifies.
"""
import argparse, csv, os, sys, shutil
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P, pak3, lzss

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
    total=written=current=skipped=0
    for name, entries in sorted(groups.items()):
        path=os.path.join(folder,name)
        if not os.path.exists(path):
            print(f"  SKIP {name}: not found in {folder}"); skipped+=len(entries); continue
        d=bytearray(open(path,"rb").read()); orig=bytes(d); errs=[]; pending=[]; done=0
        for off,jp,en in entries:
            r=M.decode_at(orig,off)
            if not r: errs.append(f"0x{off:X} decode failed"); continue
            got,end,_=r
            if got==en: done+=1; continue                       # already translated
            if got!=jp: errs.append(f"0x{off:X} expected {ascii(jp[:16])} found {ascii(got[:16])}"); continue
            avail=P.budget(orig,off,end-off); enc=P.encode(en)
            if len(enc)>avail: errs.append(f"0x{off:X} {len(enc)} > {avail} bytes"); continue
            pending.append((off,avail,enc))
        for off,avail,enc in pending:
            region=avail+1
            d[off:off+region]=enc+b"\x00"*(region-len(enc))
        if errs:
            print(f"  FAIL {name}: {len(errs)} problem(s), file left untouched")
            for e in errs[:5]: print(f"        {e}")
            skipped+=len(entries); continue
        assert len(d)==len(orig)
        if pending and not a.dry_run:
            if not a.no_backup and not os.path.exists(path+".bak"): shutil.copy(path,path+".bak")
            open(path,"wb").write(d)
        if pending:
            extra=f", {done} already done" if done else ""
            print(f"  {'would patch' if a.dry_run else 'patched'} {name}: {len(pending)} strings{extra}")
        else:
            print(f"  current {name}: all {done} strings already translated")
        written+=len(pending); current+=done
        total+=1
    print(f"\n{written} strings patched, {current} already current, {total} files"
          f"{' (dry run)' if a.dry_run else ''}" + (f", {skipped} skipped" if skipped else ""))
    rc=patch_containers(folder, groups, a)
    return 1 if (skipped or rc) else 0

def patch_containers(folder, groups, a):
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
            which=pak3.identify(mod, groups)
            if which is None: blobs.append(blob); continue
            new,patched,done,errs=pak3.apply_records(mod, groups[which])
            if errs:
                print(f"  FAIL {name} member {k} ({which}): {len(errs)} problem(s), container left untouched")
                for e in errs[:5]: print("        "+e)
                bad+=1; blobs=None; break
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
