#!/usr/bin/env python3
"""Translate Monster Book / enemy names in the battle-resource FPB members.

Located by pnvnd's env8 scanner: enemy names live inside FPB members
~8378..9565 (per-enemy battle resources), nested one PAK level deep and then
in a raw-deflate blob, encoded in the game's own glyph table ("tod2-custom",
same TBL as scenario text). A plain byte search never found them because the
text sits below a PAK container and a deflate wrapper.

This walks each enemy member's containers exactly like the scanner
(deflate -> PAK -> deflate ...), decodes every NUL-bounded tod2-custom string,
and rewrites any string whose Japanese is in psp_monsters.tsv to its English.
English ASCII is one byte per character vs two for katakana, so most names fit
in the original slot; if longer, the enclosing PAK is rebuilt (offsets are a
plain count-prefixed, ascending, tightly-packed table). Re-deflating a changed
entry changes its size, so the PAK is rebuilt whenever any child changed.

Only the members that actually change are returned, for psp_fpb.replace.
"""
import os, struct, zlib, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('psp_text', os.path.join(HERE, 'psp_text.py'))
psp_text = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(psp_text)
TBL = psp_text.TBL

# Enemy-resource member window (inclusive), from the scan's findings.
MEMBER_LO, MEMBER_HI = 8378, 9565


def load_names(path=None):
    names = {}
    for line in open(path or os.path.join(HERE, 'psp_monsters.tsv'), encoding='utf-8'):
        if line.startswith('#') or '\t' not in line:
            continue
        jp, en = line.rstrip('\n').split('\t')[:2]
        if jp and en:
            names[jp] = en
    return names


def _decode(b, p):
    """Decode one NUL-bounded tod2-custom run starting at p; return (text, end)
    where end is the NUL index. None if a byte is undecodable (not our string)."""
    out = []
    i = p
    n = len(b)
    while i < n and b[i] != 0:
        c = b[i]
        if 0x20 <= c <= 0x7e:
            out.append(chr(c)); i += 1
        elif (0x99 <= c <= 0x9f or 0xe0 <= c <= 0xe4) and i + 1 < n:
            ch = TBL.get(str((c << 8) | b[i + 1]))
            if ch is None:
                return None, i
            out.append(ch); i += 2
        elif 0xa1 <= c <= 0xdf:
            out.append(bytes([c]).decode('cp932', 'replace')); i += 1
        else:
            return None, i
    return ''.join(out), i


def _patch_leaf(data, names, stats):
    """Overwrite any target name in a decoded leaf, in place. Returns new bytes
    or None if unchanged. Grows are handled by the caller's container rebuild
    only when the slot is too small (here we NUL-pad within the original slot;
    longer English is reported and skipped to stay in-place-safe)."""
    b = bytearray(data)
    changed = False
    i = 0
    n = len(b)
    while i < n:
        if b[i] == 0:
            i += 1; continue
        text, end = _decode(b, i)
        if text is not None and text in names:
            en = names[text].encode('cp932', 'replace')
            slot = end - i
            if len(en) <= slot:
                b[i:end] = en + b'\x00' * (slot - len(en))
                changed = True
                stats['patched'] += 1
            else:
                stats['too_long'] += 1
        i = end + 1 if end >= i else i + 1
    return bytes(b) if changed else None


def _inflate04(b):
    plen, ulen = struct.unpack_from('<II', b, 1)
    out = zlib.decompress(b[9:9 + plen], wbits=-15)
    return out if len(out) == ulen else None


def _deflate04(raw, align=4):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    pk = c.compress(raw) + c.flush()
    out = b'\x04' + struct.pack('<II', len(pk), len(raw)) + pk
    if align:                       # PAK entries are 4-byte aligned; keep them so
        out += b'\x00' * ((-len(out)) % align)
    return out


def _pak_entries(d):
    count = struct.unpack_from('<I', d, 0)[0]
    if not (1 <= count <= 4096) or 4 + count * 8 > len(d):
        return None
    ents = []
    last = 4 + count * 8
    for i in range(count):
        off, size = struct.unpack_from('<II', d, 4 + i * 8)
        if off < last or off + size > len(d):
            return None
        last = off
        ents.append((off, size))
    return ents


def _rebuild_pak(blobs):
    n = len(blobs)
    head = bytearray(struct.pack('<I', n))
    off = 4 + n * 8
    body = bytearray()
    for b in blobs:
        head += struct.pack('<II', off, len(b))
        body += b
        off += len(b)
    return bytes(head + body)


def _walk(data, names, stats, depth=0):
    """Recurse containers; return new bytes if anything changed, else None."""
    if depth > 6:
        return None
    # deflate wrapper. PAK entries pad the blob to 4 bytes, so the stored size
    # is 9+packed rounded up, NOT exactly 9+packed -- accept a few pad bytes.
    if len(data) > 9 and data[0] == 4:
        plen, ulen = struct.unpack_from('<II', data, 1)
        if 9 + plen <= len(data) <= 9 + plen + 3:
            try:
                inner = zlib.decompress(data[9:9 + plen], wbits=-15)
            except zlib.error:
                inner = None
            if inner is not None and len(inner) == ulen:
                new = _walk(inner, names, stats, depth + 1)
                return _deflate04(new) if new is not None else None
    # PAK container
    ents = _pak_entries(data)
    if ents is not None:
        blobs = [bytearray(data[o:o + s]) for o, s in ents]
        any_change = False
        for k in range(len(blobs)):
            new = _walk(bytes(blobs[k]), names, stats, depth + 1)
            if new is not None:
                blobs[k] = new; any_change = True
        return _rebuild_pak(blobs) if any_change else None
    # leaf
    return _patch_leaf(data, names, stats)


def patch_member(member_bytes, names, stats):
    return _walk(member_bytes, names, stats)


def build_changed_members(boot_path, fpb_path, names=None, log=print):
    """Return {index: new_decompressed_bytes} for every enemy member that
    changed. Read straight from the archive via psp_fpb.read_member."""
    _s = importlib.util.spec_from_file_location('psp_fpb', os.path.join(HERE, 'psp_fpb.py'))
    psp_fpb = importlib.util.module_from_spec(_s); _s.loader.exec_module(psp_fpb)
    names = names or load_names()
    boot = open(boot_path, 'rb').read()
    stats = {'patched': 0, 'too_long': 0, 'members': 0}
    changed = {}
    for idx in range(MEMBER_LO, MEMBER_HI + 1):
        try:
            data, kind = psp_fpb.read_member(fpb_path, boot, idx)
        except Exception:
            continue
        if not data:
            continue
        new = patch_member(data, names, stats)
        if new is not None:
            changed[idx] = new
            stats['members'] += 1
    if log:
        log('monster names: %d strings patched across %d members (%d too long, skipped)'
            % (stats['patched'], stats['members'], stats['too_long']))
    return changed, stats


if __name__ == '__main__':
    import sys, json, tempfile
    boot, fpb = sys.argv[1], sys.argv[2]
    changed, stats = build_changed_members(boot, fpb)
    print(json.dumps(stats))
    if len(sys.argv) > 3:  # dump changed member bytes to a dir for inspection
        d = sys.argv[3]; os.makedirs(d, exist_ok=True)
        for i, b in changed.items():
            open(os.path.join(d, '%05d.bin' % i), 'wb').write(b)
        print('wrote', len(changed), 'members to', d)
