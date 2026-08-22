"""Encode translated text back into the game's byte format, and validate fit."""
import os, json, struct, re, string
R=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..")
TBL=json.load(open(R+"/ps2/PyTOD2/TBL.json"))
TBL.setdefault("39549","＜"); TBL.setdefault("39550","＞"); TBL.setdefault("40405","熟")
REV={v:int(k) for k,v in TBL.items()}
PRINT=set(string.digits+string.ascii_letters+string.punctuation+' ')
TAGCODE={'color':0x4,'size':0x5,'num':0x6,'char':0x7,'item':0x8,'button':0x9}
NAMES={'Kyle':1,'Reala':2,'Loni':3,'Judas':4,'Nanaly':5,'Harold':6}
TOKEN=re.compile(r'<([A-Za-z0-9]+):([0-9A-Fa-f]{8})>|<([A-Za-z]+)>|\{([0-9A-F]{2})\}')

def encode(text):
    """Text with <tag:XXXXXXXX>, <Name>, {HH} and \\n -> game bytes."""
    out=bytearray(); i=0
    while i<len(text):
        m=TOKEN.match(text,i)
        if m:
            if m.group(1):
                name,val=m.group(1),int(m.group(2),16)
                if name in TAGCODE: out.append(TAGCODE[name])
                else: out.append(int(name,16))
                out+=struct.pack('<L',val)
            elif m.group(3):
                nm=m.group(3)
                if nm not in NAMES: raise ValueError("unknown name tag "+nm)
                out.append(0x7); out+=struct.pack('<L',NAMES[nm])
            else:
                out.append(int(m.group(4),16))
            i=m.end(); continue
        ch=text[i]
        if ch=='\n': out.append(0x01)
        elif ch in PRINT: out.append(ord(ch))
        elif ch in REV:
            c=REV[ch]; out+=bytes([c>>8,c&0xFF])
        elif 0xFF61<=ord(ch)<=0xFF9F: out.append(0xA1+ord(ch)-0xFF61)   # half-width kana
        else: raise ValueError(f"cannot encode {ch!r}")
        i+=1
    return bytes(out)

def budget(data, off, jp_bytes):
    """Bytes usable at off: string length plus trailing NUL padding, minus terminator."""
    p=off+jp_bytes; n=0
    while p+n<len(data) and data[p+n]==0: n+=1
    return jp_bytes+n-1

def check(data, off, japanese, english):
    """Verify the file really holds `japanese` at off; return (fits, used, avail)."""
    import md1text as M
    r=M.decode_at(data,off)
    if not r: return (None,None,None,"decode failed")
    got,end,_=r
    if got!=japanese: return (None,None,None,f"mismatch: file has {got!r}")
    avail=budget(data,off,end-off)
    used=len(encode(english))
    return (used<=avail, used, avail, "")
