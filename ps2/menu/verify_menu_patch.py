#!/usr/bin/env python3
"""Check which menu strings are actually English in a build.

Point it at whatever you are about to test and it reports, per file, how
many of the translated records read back as English, Japanese, or
something else. It reads only what it needs, so a 3 GB ISO is fine.

Usage:
    python3 verify_menu_patch.py <game.iso>
    python3 verify_menu_patch.py <FILE.FPB> <SLPS_251.72>
    python3 verify_menu_patch.py <FPB folder> [SLPS_251.72]

Nothing is written. Exit code 0 if everything is English, 1 otherwise.
"""
import csv, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md1text as M, pak3, lzss
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

HERE=os.path.dirname(os.path.abspath(__file__))
SECTOR=2048
PTR_BEGIN, PTR_END = 0xDD320, 0xE62EF
LOW, HIGH = 0x3F, 0xFFFFFFC0
BIAS=0xFF000

# ---------- ISO-9660 lookup (root directory only, which is all this disc uses) ----------
def iso_locate(f, wanted):
    f.seek(16*SECTOR); pvd=f.read(SECTOR)
    if pvd[1:6]!=b"CD001": raise RuntimeError("not an ISO-9660 image")
    root=pvd[156:156+pvd[156]]
    extent=struct.unpack_from("<I",root,2)[0]; size=struct.unpack_from("<I",root,10)[0]
    f.seek(extent*SECTOR); data=f.read(size); pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0: pos=((pos//SECTOR)+1)*SECTOR; continue
        rec=data[pos:pos+ln]; pos+=ln
        name=rec[33:33+rec[32]]
        if name in (b"\x00",b"\x01"): continue
        text=name.decode("ascii","replace").split(";",1)[0]
        if text.upper()==wanted.upper():
            return struct.unpack_from("<I",rec,2)[0]*SECTOR, struct.unpack_from("<I",rec,10)[0]
    raise FileNotFoundError(wanted)

class Source:
    """Uniform access to SLPS bytes and FPB member files."""
    def __init__(self, slps_bytes, fpb_reader):
        self.slps=slps_bytes; self.read_fpb=fpb_reader
        self.ptrs=[struct.unpack_from("<L",slps_bytes,o)[0] for o in range(PTR_BEGIN,PTR_END,4)]
    def member(self, index):
        rem=self.ptrs[index]&LOW; start=self.ptrs[index]&HIGH
        end=(self.ptrs[index+1]&HIGH)-rem
        return self.read_fpb(start,end-start)

def open_source(args):
    a=args[0]
    if os.path.isdir(a):                                  # FPB folder [+ SLPS]
        folder=a
        if not any(x.endswith((".md1",".pak0")) for x in os.listdir(folder)) and os.path.isdir(os.path.join(folder,"FPB")):
            folder=os.path.join(folder,"FPB")
        slps=None
        for cand in ([args[1]] if len(args)>1 else [])+[os.path.join(a,"SLPS_251.72"),os.path.join(a,"new_SLPS_251.72")]:
            if os.path.isfile(cand): slps=open(cand,"rb").read(); print(f"SLPS: {cand}"); break
        def member_by_name(name):
            p=os.path.join(folder,name)
            return open(p,"rb").read() if os.path.exists(p) else None
        return slps, member_by_name
    f=open(a,"rb"); head=f.read(0x8010)
    if head[0x8001:0x8006]==b"CD001":                      # ISO
        so,ss=iso_locate(f,"SLPS_251.72"); f.seek(so); slps=f.read(ss)
        fo,fs=iso_locate(f,"FILE.FPB")
        print(f"ISO: SLPS_251.72 at 0x{so:X}, FILE.FPB at 0x{fo:X} ({fs} bytes)")
        src=Source(slps, lambda start,n: (f.seek(fo+start), f.read(n))[1])
    else:                                                 # FILE.FPB + SLPS
        if len(args)<2: print("FILE.FPB needs the matching SLPS_251.72 as the second argument"); sys.exit(2)
        slps=open(args[1],"rb").read()
        src=Source(slps, lambda start,n: (f.seek(start), f.read(n))[1])
    def member_by_name(name):
        return src.member(int(name.split(".")[0]))
    return slps, member_by_name

def classify(data, off, jp, en):
    r=M.decode_at(data,off)
    if not r: return "other"
    if r[0]==en: return "en"
    if r[0]==jp: return "jp"
    return "other"

def main():
    args=sys.argv[1:]
    if not args: print(__doc__); return 2
    slps, member = open_source(args)
    rows={}
    with open(os.path.join(HERE,"menu_translations.csv"),encoding="utf-8") as fh:
        for r in csv.DictReader(fh): rows.setdefault(r["file"],[]).append(r)
    print(f"\n{'file':<12}{'english':>8}{'japanese':>10}{'other':>7}  verdict")
    total={"en":0,"jp":0,"other":0}; cache={}
    for name,recs in sorted(rows.items()):
        data=member(name)
        if data is None: print(f"{name:<12}  (missing)"); continue
        c={"en":0,"jp":0,"other":0}
        for r in recs: c[classify(data,int(r["offset"],16),r["japanese"],r["english"])]+=1
        for k in c: total[k]+=c[k]
        verdict="PATCHED" if c["en"]==len(recs) else ("NOT patched" if c["jp"]==len(recs) else "MIXED")
        print(f"{name:<12}{c['en']:>8}{c['jp']:>10}{c['other']:>7}  {verdict}")
    # compressed module containers: these are the copies the game actually loads
    groups={name:[(int(r["offset"],16),r["japanese"],r["english"]) for r in recs] for name,recs in rows.items()}
    for name in ("00017.pak3","00021.pak3"):
        data=member(name)
        if data is None: continue
        try: members=pak3.parse(data)
        except Exception: print(f"{name:<12}  (unreadable)"); continue
        for k,(off,blob) in enumerate(members):
            if not lzss.is_packed(blob): continue
            mod=lzss.unpack(blob); which=pak3.identify(mod,groups)
            if which is None: continue
            en,jp,other=pak3.classify(mod,groups[which])
            for key,val in (("en",en),("jp",jp),("other",other)): total[key]+=val
            n=en+jp+other
            verdict="PATCHED" if en==n else ("NOT patched" if jp==n else "MIXED")
            print(f"{name+' > '+which:<12}{en:>8}{jp:>10}{other:>7}  {verdict}   <- the copy the game loads")
    print(f"{'FPB total':<12}{total['en']:>8}{total['jp']:>10}{total['other']:>7}")
    ok = total["jp"]==0 and total["other"]==0
    if slps is not None:
        t={"en":0,"jp":0,"other":0}
        with open(os.path.join(HERE,"slps_title_translations.csv"),encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                po=int(r["pointers"].split(",")[0],16)
                tgt=struct.unpack_from("<L",slps,po)[0]-BIAS
                t[classify(slps,tgt,r["japanese"],r["english"])]+=1
        verdict="PATCHED" if t["jp"]==0 and t["other"]==0 else ("NOT patched" if t["en"]==0 else "MIXED")
        print(f"{'SLPS titles':<12}{t['en']:>8}{t['jp']:>10}{t['other']:>7}  {verdict}")
        ok = ok and t["jp"]==0 and t["other"]==0
    else:
        print("(no SLPS given, titles not checked)")
    print("\nEverything English." if ok else "\nSome strings are NOT English in this build.")
    return 0 if ok else 1

if __name__=="__main__": raise SystemExit(main())
