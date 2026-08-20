#!/usr/bin/env python3
"""Apply the ToD2 English menu text to extracted FILE.FPB files.

Usage:
    python3 patch_menu_text.py <FPB_folder> [--csv menu_translations.csv] [--dry-run]

<FPB_folder> is the folder PyTOD2 extracts FILE.FPB into (contains 06799.md1 etc).
Every record is verified against the original Japanese before anything is written.
Files are patched in place at identical size, so the FPB pointer table is untouched.
Nothing is written unless every record for that file verifies.
"""
import argparse, csv, os, sys, shutil
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P

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
    total=written=skipped=0
    for name, entries in sorted(groups.items()):
        path=os.path.join(folder,name)
        if not os.path.exists(path):
            print(f"  SKIP {name}: not found in {folder}"); skipped+=len(entries); continue
        d=bytearray(open(path,"rb").read()); orig=bytes(d); errs=[]
        for off,jp,en in entries:
            r=M.decode_at(orig,off)
            if not r: errs.append(f"0x{off:X} decode failed"); continue
            got,end,_=r
            if got!=jp: errs.append(f"0x{off:X} expected {ascii(jp[:16])} found {ascii(got[:16])}"); continue
            avail=P.budget(orig,off,end-off); enc=P.encode(en)
            if len(enc)>avail: errs.append(f"0x{off:X} {len(enc)} > {avail} bytes"); continue
            region=avail+1
            d[off:off+region]=enc+b"\x00"*(region-len(enc))
        if errs:
            print(f"  FAIL {name}: {len(errs)} problem(s), file left untouched")
            for e in errs[:5]: print(f"        {e}")
            skipped+=len(entries); continue
        assert len(d)==len(orig)
        if not a.dry_run:
            if not a.no_backup and not os.path.exists(path+".bak"): shutil.copy(path,path+".bak")
            open(path,"wb").write(d)
        print(f"  {'would patch' if a.dry_run else 'patched'} {name}: {len(entries)} strings")
        written+=len(entries)
        total+=1
    print(f"\n{written} strings in {total} files{' (dry run)' if a.dry_run else ''}"
          + (f", {skipped} skipped" if skipped else ""))
    return 1 if skipped else 0

if __name__=="__main__": raise SystemExit(main())
