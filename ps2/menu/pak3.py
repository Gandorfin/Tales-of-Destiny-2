"""The .pak3 containers: a few compressed modules packed back to back.

Layout: u32 count, then `count` u32 offsets, then the members, each a
comptoe stream (see lzss.py). Every member starts on a 4-byte boundary
(the originals pad between members) and the file ends on one too.

00017.pak3 holds the battle module (08055), the world map module (08996)
and 06304. The game loads these from here, not from the loose .md1 copies,
so translating those modules means rebuilding this container.
"""
import csv, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lzss, md1text as M, md1patch as P


def parse(data):
    """-> list of (offset, blob) for each member (blob includes the 9-byte header)."""
    count = struct.unpack_from("<L", data, 0)[0]
    offs = [struct.unpack_from("<L", data, 4 + 4 * k)[0] for k in range(count)]
    out = []
    for k, o in enumerate(offs):
        inl = struct.unpack_from("<L", data, o + 1)[0]
        out.append((o, data[o:o + 9 + inl]))
    return out


def build(blobs):
    """Inverse of parse: container bytes from a list of member streams."""
    head = 4 + 4 * len(blobs)
    offs = []
    padded = []
    pos = head
    for b in blobs:
        offs.append(pos)
        pad = (-len(b)) % 4                      # keep every member 4-byte aligned
        padded.append(bytes(b) + b"\x00" * pad)
        pos += len(b) + pad
    return struct.pack("<L", len(blobs)) + b"".join(struct.pack("<L", o) for o in offs) + b"".join(padded)


def load_table(csv_path):
    """menu_translations.csv -> {file: [(offset, japanese, english), ...]}"""
    groups = {}
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups.setdefault(r["file"], []).append((int(r["offset"], 16), r["japanese"], r["english"]))
    return groups


def identify(module_bytes, groups):
    """Which translation table file does this decompressed member belong to?
    A module matches when every record reads as its Japanese or its English."""
    for name, recs in groups.items():
        if not recs:
            continue
        ok = 0
        for off, jp, en in recs:
            r = M.decode_at(module_bytes, off)
            if r and r[0] in (jp, en):
                ok += 1
            else:
                break
        if ok == len(recs):
            return name
    return None


def classify(module_bytes, recs):
    """-> (english, japanese, other) counts for one module."""
    c = [0, 0, 0]
    for off, jp, en in recs:
        r = M.decode_at(module_bytes, off)
        if r and r[0] == en:
            c[0] += 1
        elif r and r[0] == jp:
            c[1] += 1
        else:
            c[2] += 1
    return tuple(c)


def apply_records(module_bytes, recs):
    """Patch in place. -> (new_bytes, patched, already, errors)"""
    d = bytearray(module_bytes)
    pending = []
    done = 0
    errs = []
    for off, jp, en in recs:
        r = M.decode_at(module_bytes, off)
        if not r:
            errs.append("0x%X decode failed" % off); continue
        got, end, _ = r
        if got == en:
            done += 1; continue
        if got != jp:
            errs.append("0x%X expected %s found %s" % (off, ascii(jp[:16]), ascii(got[:16]))); continue
        avail = P.budget(module_bytes, off, end - off)
        enc = P.encode(en)
        if len(enc) > avail:
            errs.append("0x%X %d > %d bytes" % (off, len(enc), avail)); continue
        pending.append((off, avail, enc))
    if errs:
        return module_bytes, 0, done, errs
    for off, avail, enc in pending:
        region = avail + 1
        d[off:off + region] = enc + b"\x00" * (region - len(enc))
    return bytes(d), len(pending), done, []
