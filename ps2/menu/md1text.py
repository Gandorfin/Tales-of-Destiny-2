"""Decode game-encoded text runs out of md1 overlay modules."""
import os, json, struct, string, os, sys
R=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..")
TBL=json.load(open(R+"/ps2/PyTOD2/TBL.json"))
PRINT=set(string.digits+string.ascii_letters+string.punctuation+' ')
TAGS={0x4:'color',0x5:'size',0x6:'num',0x7:'char',0x8:'item',0x9:'button'}
NAMES={1:'Kyle',2:'Reala',3:'Loni',4:'Judas',5:'Nanaly',6:'Harold'}
LEAD=lambda b: (0x99<=b<=0x9F) or (0xE0<=b<=0xE4)

def decode_at(d, p):
    """Decode one NUL-terminated string starting at p. Returns (text, endpos, jp_chars) or None."""
    out=[]; jp=0; n=len(d); start=p
    while p<n:
        b=d[p]
        if b==0: break
        if LEAD(b):
            if p+1>=n: return None
            c=(b<<8)+d[p+1]; k=str(c)
            if k not in TBL: return None
            out.append(TBL[k]); jp+=1; p+=2
        elif b==0x01: out.append('\n'); p+=1
        elif b in (0x3,0x4,0x5,0x6,0x7,0x8,0x9,0xB):
            if p+5>n: return None
            v=struct.unpack_from('<L',d,p+1)[0]
            if b==0x7 and v in NAMES: out.append('<%s>'%NAMES[v])
            elif b in TAGS: out.append('<%s:%08X>'%(TAGS[b],v))
            else: out.append('<%02X:%08X>'%(b,v))
            p+=5
        elif chr(b) in PRINT: out.append(chr(b)); p+=1
        elif 0xA1<=b<0xE0:
            out.append(bytes([b]).decode('cp932',errors='replace')); jp+=1; p+=1
        elif b in (0x12,0x14,0x15,0x16,0x17,0x18):
            out.append('{%02X}'%b); p+=1
            while p<n and d[p] not in (0xBC,0xC0):
                out.append('{%02X}'%d[p]); p+=1
            if p>=n: return None
            out.append('{%02X}'%d[p]); p+=1
        else: return None
        p+=0
    else:
        return None
    return (''.join(out), p, jp)

def scan(path, min_jp=1):
    d=open(path,'rb').read(); n=len(d); found=[]; i=0
    while i<n-1:
        # anchor: a valid 2-byte japanese char preceded by NUL (strings are NUL-terminated/aligned)
        if LEAD(d[i]) and str((d[i]<<8)+d[i+1]) in TBL:
            # walk back to the NUL that starts this string
            s=i
            while s>0 and d[s-1]!=0: s-=1
            r=decode_at(d,s)
            if r and r[2]>=min_jp and len(r[0].strip())>0:
                found.append((s,r[1],r[0],r[2]))
                i=r[1]+1; continue
        i+=1
    return found

if __name__=="__main__":
    W=R+"/somestuff/claude-menu-work"
    rows=[]
    for name in sorted(os.listdir(W+"/md1")):
        res=scan(W+"/md1/"+name)
        if res: rows.append((name,res))
    tot=sum(len(r[1]) for r in rows)
    print(f"modules with japanese text: {len(rows)} / 89 | total strings: {tot}\n")
    for name,res in rows:
        print(f"{name}: {len(res)} strings")
