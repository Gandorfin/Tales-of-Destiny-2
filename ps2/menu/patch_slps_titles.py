#!/usr/bin/env python3
"""Apply the English character titles to SLPS_251.72.

Usage:
    python3 patch_slps_titles.py <SLPS_251.72> [--csv slps_title_translations.csv]
                                 [--out FILE] [--dry-run]

Titles are stored packed into contiguous NUL-terminated arenas. English is
repacked into the same arenas and every pointer is rewritten; anything that no
longer fits spills into the spare string pool. Pointers are plain 32-bit
little-endian values holding (file offset + 0xFF000). The file size never
changes. Every record is verified against the original Japanese before any
byte is written, and nothing is written at all if any record fails.
"""
import argparse, csv, hashlib, os, shutil, struct, sys
try:                                   # Windows consoles are often not UTF-8
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, md1patch as P
BIAS=0xFF000
POOL_START, POOL_END = 1026832, 1033520

def pool_free_start(d):
    """First free byte of the spare string pool.

    The pool may be completely empty (nothing else has used it yet) or already
    hold strings from the earlier Arte/Status/Enchant menu patch, in which case
    we append after them rather than overwrite them.
    """
    seg=d[POOL_START:POOL_END]
    used=[i for i,b in enumerate(seg) if b!=0]
    return POOL_START+(used[-1]+1 if used else 0)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("slps"); ap.add_argument("--csv", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),"slps_title_translations.csv"))
    ap.add_argument("--out"); ap.add_argument("--dry-run", action="store_true")
    a=ap.parse_args()
    targets=[]
    if os.path.isdir(a.slps):                       # folder: patch every copy present
        for name in ("SLPS_251.72","new_SLPS_251.72"):
            cand=os.path.join(a.slps,name)
            if os.path.isfile(cand): targets.append(cand)
        if not targets: print(f"No SLPS_251.72 in {a.slps}"); return 2
    elif os.path.isfile(a.slps):
        targets=[a.slps]
        sib=os.path.join(os.path.dirname(os.path.abspath(a.slps)),
                         "new_SLPS_251.72" if os.path.basename(a.slps)!="new_SLPS_251.72" else "SLPS_251.72")
        if os.path.isfile(sib) and not a.out:
            print(f"Note: {os.path.basename(sib)} also exists next to this file. PyTOD2's Pack FPB")
            print("writes the ISO executable as new_SLPS_251.72, so make sure the copy that")
            print("goes into the ISO is the patched one (pass the folder to patch both).")
    else:
        print(f"File not found: {a.slps}"); return 2
    rc=0
    for target in targets:
        print(f"\n== {target} ==")
        rc|=patch_one(target, a)
    return rc

def patch_one(target, a):
    src=open(target,"rb").read()
    recs=[]
    with open(a.csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            recs.append((int(r["offset"],16), r["pointers"], r["japanese"], r["english"]))
    errs=[]
    for off,ptrs,jp,en in recs:
        d=M.decode_at(src,off)
        if not d or d[0]!=jp: errs.append(f"0x{off:X}: japanese mismatch"); continue
        for ph in ptrs.split(','):
            po=int(ph,16)
            if struct.unpack_from('<L',src,po)[0]!=off+BIAS:
                errs.append(f"0x{off:X}: pointer 0x{po:X} does not point here")
    if errs:
        print(f"{len(errs)} problem(s); nothing written:")
        for e in errs[:10]: print("   ",e)
        return 1
    # group into contiguous arenas
    info={off:(ptrs,jp,en,M.decode_at(src,off)[1]) for off,ptrs,jp,en in recs}
    order=sorted(info)
    runs=[]; cur=[order[0]]
    for prev,off in zip(order,order[1:]):
        pv=info[prev]; avail=P.budget(src,prev,pv[3]-prev)
        if prev+avail+1==off: cur.append(off)
        else: runs.append(cur); cur=[off]
    runs.append(cur)
    pool=pool_free_start(src)
    in_use=pool-POOL_START
    print(f"SLPS {hashlib.sha256(src).hexdigest()[:8].upper()}, "
          f"{len(src)} bytes; spare pool: {in_use} bytes already in use, "
          f"{POOL_END-pool} free")
    if in_use==0:
        print("Note: the spare pool is empty, so the earlier Arte/Status/Enchant")
        print("menu patch is not applied to this file. That is fine here, but if")
        print("you apply that patch too, apply it BEFORE this one: both use the")
        print("same pool, and running it afterwards would overwrite these titles.")
    data=bytearray(src); inplace=spill=0
    for run in runs:
        last=run[-1]; lav=P.budget(src,last,info[last][3]-last)
        lo, hi = run[0], last+lav+1
        cur=lo
        for off in run:
            enc=P.encode(info[off][2]); need=len(enc)+1
            if cur+need<=hi: data[cur:cur+need]=enc+b'\x00'; new=cur; cur+=need; inplace+=1
            elif pool+need<=POOL_END: data[pool:pool+need]=enc+b'\x00'; new=pool; pool+=need; spill+=1
            else: print(f"no space for 0x{off:X}"); return 1
            for ph in info[off][0].split(','): struct.pack_into('<L',data,int(ph,16),new+BIAS)
        if cur<hi: data[cur:hi]=b'\x00'*(hi-cur)
    assert len(data)==len(src)
    out=a.out or target
    if not a.dry_run:
        if out==target and not os.path.exists(target+".bak"): shutil.copy(target,target+".bak")
        open(out,"wb").write(bytes(data))
    print(f"{'would patch' if a.dry_run else 'patched'} {len(recs)} titles "
          f"({inplace} repacked in place, {spill} moved to the pool, "
          f"{POOL_END-pool} pool bytes left)")
    return 0

if __name__=="__main__": raise SystemExit(main())
