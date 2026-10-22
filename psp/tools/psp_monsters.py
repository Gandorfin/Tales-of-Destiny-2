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

The encounter banner at the start of a battle ("Owlbear  1") and, most likely,
the Monster Book's own name list read a different source: the TEKI list in
member 08331 (PAK child 2, comptoe LZSS): "TEKI", then 256 records of 28
bytes, a 24 byte name field (game encoding, space padded) and 4 bytes of
data. Slot n is the same enemy as row n of ps2/menu/enemy_names.csv.
patch_teki() writes the English names into it (2026-10-16).

The Mystic Arte cut-in banners (蒼龍滅牙斬, ファイナルプレイヤー, ...) are
inline 0A strings in the efD effect scripts of members 09029..09075: PAK
child 0, comptoe LZSS (type 3), argument bytes 0x00..0xFF. The walker
unpacks LZSS leaves that start with "efD", writes the English centred in
the Japanese byte count (as the PS2 enemy_text.fit does) and packs them
again (October 2026; before that they stayed Japanese).
"""
import os, struct, zlib, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('psp_text', os.path.join(HERE, 'psp_text.py'))
psp_text = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(psp_text)
TBL = psp_text.TBL

# Enemy-resource member window (inclusive), from the scan's findings.
MEMBER_LO, MEMBER_HI = 8378, 9565
TEKI_MEMBER, TEKI_CHILD = 8331, 2
TEKI_COUNT, TEKI_RECORD, TEKI_NAME = 256, 28, 24


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


def _is_literal(b, i, any_arg=False):
    """True when the string at i is inline ENd text: opcode 0A, one argument
    byte, then the NUL-terminated string (enemy arte names, Mystic Arte
    banners, boss lines; the PS2 enemy_text.py format). The efD effect
    scripts use argument bytes up to 0xFF (any_arg)."""
    return i >= 2 and b[i - 2] == 0x0A and (any_arg or b[i - 1] <= 0x0F)


def _patch_leaf(data, names, stats, efd=False):
    """Overwrite any target name in a decoded leaf, in place. Returns new bytes
    or None if unchanged. English must fit the Japanese bytes (longer English
    is reported and skipped to stay in-place-safe). Name fields are padded
    with NULs. Inline ENd text is padded with spaces, as the PS2 enemy_text.py
    does: the script continues right after that string's own terminator, so
    the slot keeps exactly one NUL, where the Japanese had it."""
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
                literal = _is_literal(b, i, efd)
                pad = slot - len(en)
                if efd and literal:
                    # cut-in banners are drawn centred on their full length,
                    # so split the padding (as the PS2 enemy_text.fit does)
                    en = b' ' * (pad // 2) + en + b' ' * (pad - pad // 2)
                    pad = 0
                b[i:end] = en + (b' ' if literal else b'\x00') * pad
                changed = True
                stats['patched'] += 1
                stats['inline_text'] += literal
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
    # LZSS packed efD effect script (the Mystic Arte cut-in banners, PAK
    # child 0 of members 09029..09075): its inline 0A strings
    if len(data) > 9 and data[0] in (1, 3):
        inl, outl = struct.unpack_from('<II', data, 1)
        if 9 + inl <= len(data) <= 9 + inl + 3:
            lzss = _lzss()
            try:
                inner = lzss.decode(data[9:9 + inl], data[0], outl)
            except Exception:
                inner = None
            if inner is not None and len(inner) == outl and inner[:3] == b'efD':
                new = _patch_leaf(inner, names, stats, efd=True)
                if new is None:
                    return None
                stats['efd'] = stats.get('efd', 0) + 1
                packed = lzss.pack(new, data[0])
                if lzss.unpack(packed) != new:
                    raise ValueError('efD LZSS round trip failed')
                return packed + b'\x00' * ((-len(packed)) % 4)
    # leaf
    return _patch_leaf(data, names, stats)


def patch_member(member_bytes, names, stats):
    return _walk(member_bytes, names, stats)


def _lzss():
    import sys
    path = os.path.join(HERE, '..', '..', 'ps2', 'menu')
    if path not in sys.path:
        sys.path.insert(0, path)
    import lzss
    return lzss


def patch_teki(member_bytes, names, stats):
    """English names in the TEKI list of member 08331. Returns new member
    bytes, or None when nothing changed. Names longer than the 24 byte field
    are left Japanese and counted."""
    lzss = _lzss()
    ents = _pak_entries(member_bytes)
    if ents is None or len(ents) <= TEKI_CHILD:
        raise ValueError('member %d is not the expected PAK' % TEKI_MEMBER)
    blobs = [member_bytes[o:o + n] for o, n in ents]
    packed = blobs[TEKI_CHILD]
    version = packed[0]
    inl, outl = struct.unpack_from('<II', packed, 1)
    if version not in (1, 3):
        raise ValueError('TEKI list is not LZSS packed')
    raw = bytearray(lzss.decode(packed[9:9 + inl], version, outl))
    if raw[:4] != b'TEKI' or len(raw) != 4 + TEKI_COUNT * TEKI_RECORD:
        raise ValueError('unexpected TEKI list layout')
    changed = False
    for i in range(TEKI_COUNT):
        at = 4 + i * TEKI_RECORD
        field = bytes(raw[at:at + TEKI_NAME])
        jp, _ = _decode(field.rstrip(b' ') + b'\x00', 0)
        en = names.get(jp) if jp else None
        if not en:
            if jp and any(ord(ch) > 0x7F for ch in jp):
                stats['teki_untranslated'] = stats.get('teki_untranslated', 0) + 1
            continue
        eb = psp_text.encode_line(en)
        if len(eb) > TEKI_NAME:
            stats['teki_too_long'] = stats.get('teki_too_long', 0) + 1
            continue
        raw[at:at + TEKI_NAME] = eb + b' ' * (TEKI_NAME - len(eb))
        stats['teki_patched'] = stats.get('teki_patched', 0) + 1
        changed = True
    if not changed:
        return None
    new = lzss.pack(bytes(raw), version)
    new += b'\x00' * ((-len(new)) % 4)
    if lzss.decode(new[9:9 + struct.unpack_from('<I', new, 1)[0]], version, len(raw)) != bytes(raw):
        raise ValueError('TEKI list LZSS round trip failed')
    blobs[TEKI_CHILD] = new
    return _rebuild_pak(blobs)


def build_changed_members(boot_path, fpb_path, names=None, log=print):
    """Return {index: new_decompressed_bytes} for every enemy member that
    changed. Read straight from the archive via psp_fpb.read_member."""
    _s = importlib.util.spec_from_file_location('psp_fpb', os.path.join(HERE, 'psp_fpb.py'))
    psp_fpb = importlib.util.module_from_spec(_s); _s.loader.exec_module(psp_fpb)
    names = names or load_names()
    boot = open(boot_path, 'rb').read()
    stats = {'patched': 0, 'too_long': 0, 'members': 0, 'inline_text': 0}
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
    data, _kind = psp_fpb.read_member(fpb_path, boot, TEKI_MEMBER)
    new = patch_teki(data, names, stats)
    if new is not None:
        changed[TEKI_MEMBER] = new
    if log:
        log('monster names: %d strings patched across %d members (%d of them inline ENd text, '
            'space padded; %d too long, skipped; %d efD effect scripts)'
            % (stats['patched'], stats['members'], stats['inline_text'], stats['too_long'], stats.get('efd', 0)))
        log('TEKI list (encounter banner, member %d): %d names English, %d without a translation'
            % (TEKI_MEMBER, stats.get('teki_patched', 0), stats.get('teki_untranslated', 0)))
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
