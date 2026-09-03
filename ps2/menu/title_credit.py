"""Put the patch name and version on the title screen (PS2).

    python3 ps2/menu/title_credit.py ps2/PyTOD2/FPB --version 1.1.8
    python3 ps2/menu/title_credit.py ps2/PyTOD2/FPB --label "Green Gel Patch v1.1.8"
    options: --dry-run (change nothing)  --preview out.png (write the strip as PNG)

The two copyright lines under the title menu are not text: they are one
384x32 4-bit texture, member 1 of 00021.pak3 (the title-screen pack, eight
TM2 textures compressed back to back). Line one is the character designer's
credit in Japanese, line two is the Namco copyright in English. This tool
redraws line one as "Green Gel Patch vX.Y.Z" and leaves line two untouched,
then recompresses the member and rebuilds the pack in the FPB folder. Run
it before Pack FPB, like the other menu tools; running it twice is harmless
(the line is cleared and redrawn every time).

Nothing but the pixel data changes: same texture size, same palette, same
member count, so the game code that draws the strip is unaffected. The
glyphs come from title_glyphs.py (baked from Liberation Sans Bold, SIL Open
Font License), so no extra Python packages are needed.

The PSP build uses the same drawing code through psp/tools/psp_title.py.
"""
import os, sys, struct, zlib, argparse, base64

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import title_glyphs as G

MAGIC = b"TM2@"
PS2_PAK = "00021.pak3"
PS2_MEMBER = 1
PS2_SIZE = (384, 32)
LEFT_MARGIN = 2          # pen x of the first glyph, like the original (c) mark
RIGHT_MARGIN = 2         # pixels that must stay clear on the right

class TitleError(Exception):
    pass

# ---------------------------------------------------------------- TM2@ strip

def parse_blocks(data):
    """[(offset, size, psm, pos, w, h)] for the blocks after the 16-byte header."""
    if data[:4] != MAGIC:
        raise TitleError("not a TM2@ texture (magic %r)" % data[:4])
    p = 0x10
    out = []
    while p + 16 <= len(data):
        size, psm, pos, w, h = struct.unpack_from("<IIIHH", data, p)
        if size < 16 or p + size > len(data):
            break
        out.append((p, size, psm, pos, w, h))
        p += size
    return out

def decode_strip(data):
    """-> (palette [16 x (r,g,b,a)], pixel indices, w, h) of a 16-colour 4bpp TM2@."""
    blocks = parse_blocks(data)
    if len(blocks) != 2:
        raise TitleError("expected one palette and one image block, got %d" % len(blocks))
    (po, ps, ppsm, _, pw, ph), (io, isz, ipsm, _, w, h) = blocks
    if ppsm != 0 or pw * ph != 16:
        raise TitleError("expected a 16-colour RGBA palette")
    if ipsm != 0x14 or isz != 16 + w * h // 2:
        raise TitleError("expected a 4bpp image block")
    pal = [tuple(data[po + 16 + 4 * i: po + 20 + 4 * i]) for i in range(16)]
    idx = []
    for b in data[io + 16: io + 16 + w * h // 2]:
        idx.append(b & 15)
        idx.append(b >> 4)
    return pal, idx, w, h

def encode_strip(data, idx):
    """Same texture with the pixel indices replaced (size unchanged)."""
    blocks = parse_blocks(data)
    io, isz, ipsm, _, w, h = blocks[1]
    if len(idx) != w * h:
        raise TitleError("pixel count mismatch")
    body = bytearray(w * h // 2)
    for i in range(0, len(idx), 2):
        body[i // 2] = (idx[i] & 15) | ((idx[i + 1] & 15) << 4)
    return data[:io + 16] + bytes(body) + data[io + 16 + len(body):]

# ------------------------------------------------------------------- drawing

def _glyph(style, ch):
    g = G.STYLES[style].get(ch)
    if g is None:
        raise TitleError("no glyph for %r in the title font" % ch)
    adv, x, y, w, h, b64 = g
    return adv, x, y, w, h, (base64.b64decode(b64) if b64 else b"")

def layout(label, style, width, x0=LEFT_MARGIN):
    """Coverage mask (BAND rows x width) of the label. -> (rows, right_edge)."""
    rows = [bytearray(width) for _ in range(G.BAND)]
    pen = float(x0)
    right = x0
    for ch in label:
        adv, gx, gy, gw, gh, bits = _glyph(style, ch)
        px = int(round(pen)) + gx
        for yy in range(gh):
            row = rows[gy + yy] if 0 <= gy + yy < G.BAND else None
            for xx in range(gw):
                v = bits[yy * gw + xx]
                x = px + xx
                if v and row is not None and 0 <= x < width:
                    if v > row[x]:
                        row[x] = v
                    right = max(right, x + 1)
        pen += adv
    return rows, right

def _dilate(rows, width):
    """3x3 max filter (the one-pixel outline around the letters)."""
    h = len(rows)
    out = [bytearray(width) for _ in range(h)]
    for y in range(h):
        for x in range(width):
            m = 0
            for dy in (-1, 0, 1):
                yy = y + dy
                if 0 <= yy < h:
                    r = rows[yy]
                    for dx in (-1, 0, 1):
                        xx = x + dx
                        if 0 <= xx < width and r[xx] > m:
                            m = r[xx]
            out[y][x] = m
    return out

def _nearest(pal, r, g, b, a):
    """Palette index closest to premultiplied (r,g,b,a); palette alpha is 0..128."""
    best = None
    for i, (pr, pg, pb, pa) in enumerate(pal):
        pa2 = min(255, pa * 2)
        d = ((pr * pa2 - r * a) ** 2 + (pg * pa2 - g * a) ** 2 + (pb * pa2 - b * a) ** 2
             + ((pa2 - a) ** 2) * 8)
        if best is None or d < best[0]:
            best = (d, i)
    return best[1]

def draw_label(strip, label, style, x0=LEFT_MARGIN):
    """Redraw the first text line of a 32-row copyright strip with `label`.
    Returns (new strip bytes, info dict). Raises TitleError if it does not fit."""
    pal, idx, w, h = decode_strip(strip)
    if h != 32:
        raise TitleError("strip is %dx%d, expected 32 rows" % (w, h))
    transparent = [i for i, c in enumerate(pal) if c[3] == 0]
    opaque = [c for c in pal if c[3] >= 0x70]
    if not transparent or not opaque:
        raise TitleError("palette has no transparent or no opaque entry")
    transparent = transparent[0]
    text = max(opaque, key=lambda c: c[0] + c[1] + c[2])
    outline = min(opaque, key=lambda c: c[0] + c[1] + c[2])
    rows, right = layout(label, style, w, x0)
    if right > w - RIGHT_MARGIN:
        raise TitleError("label %r needs %d px but the strip is %d px wide; use a shorter label"
                         % (label, right + RIGHT_MARGIN, w))
    halo = _dilate(rows, w)
    idx = list(idx)
    for y in range(G.BAND):
        for x in range(w):
            t = rows[y][x]
            o = halo[y][x]
            if o == 0:
                idx[y * w + x] = transparent
                continue
            f = t / 255.0
            r = int(text[0] * f + outline[0] * (1 - f))
            g = int(text[1] * f + outline[1] * (1 - f))
            b = int(text[2] * f + outline[2] * (1 - f))
            idx[y * w + x] = _nearest(pal, r, g, b, max(t, o))
    return encode_strip(strip, idx), {"width": w, "right": right, "label": label}

def rows_below_band(strip):
    """Pixel indices of rows BAND..h-1 (the untouched second line), for checks."""
    pal, idx, w, h = decode_strip(strip)
    return idx[G.BAND * w:]

# --------------------------------------------------------------- PNG preview

def write_png(path, strip, scale=1):
    pal, idx, w, h = decode_strip(strip)
    raw = bytearray()
    for y in range(h):
        for _ in range(scale):
            raw.append(0)
            for x in range(w):
                r, g, b, a = pal[idx[y * w + x]]
                raw += bytes((r, g, b, min(255, a * 2))) * scale
    def chunk(tag, body):
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)

# ------------------------------------------------------------------ PS2 pack

def patch_pak3(container, label):
    """00021.pak3 bytes -> (new container bytes, info)."""
    import pak3, lzss
    members = pak3.parse(container)
    if len(members) <= PS2_MEMBER:
        raise TitleError("pack has only %d members" % len(members))
    blob = members[PS2_MEMBER][1]
    strip = lzss.unpack(blob)
    pal, idx, w, h = decode_strip(strip)
    if (w, h) != PS2_SIZE:
        raise TitleError("member %d is %dx%d, not the %dx%d copyright strip"
                         % (PS2_MEMBER, w, h, PS2_SIZE[0], PS2_SIZE[1]))
    new_strip, info = draw_label(strip, label, "ps2")
    new_blob = lzss.pack(new_strip, version=blob[0])
    if lzss.unpack(new_blob) != new_strip:
        raise TitleError("compression round trip failed")
    blobs = [b for _, b in members]
    blobs[PS2_MEMBER] = new_blob
    out = pak3.build(blobs)
    # self check: every other member identical, second line untouched
    rebuilt = pak3.parse(out)
    for k, ((_, a), (_, b)) in enumerate(zip(members, rebuilt)):
        if k != PS2_MEMBER and a != b:
            raise TitleError("member %d changed unexpectedly" % k)
    if rows_below_band(lzss.unpack(rebuilt[PS2_MEMBER][1])) != rows_below_band(strip):
        raise TitleError("the copyright line changed, refusing to write")
    info.update(members=len(members), old_size=len(container), new_size=len(out))
    return out, new_strip, info

def resolve_folder(given):
    from patch_menu_text import resolve_folder as r
    return r(given)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("folder", help="the extracted FPB folder (holds 00021.pak3)")
    ap.add_argument("--version", help="patch version, drawn as 'Green Gel Patch v<version>'")
    ap.add_argument("--label", help="exact text to draw instead of the default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview", metavar="PNG", help="also write the new strip as a PNG (3x)")
    a = ap.parse_args(argv)
    if not a.label and not a.version:
        ap.error("give --version X.Y.Z or --label TEXT")
    label = a.label or "Green Gel Patch v%s" % a.version.lstrip("vV")
    folder = resolve_folder(a.folder)
    if folder is None:
        return 1
    path = os.path.join(folder, PS2_PAK)
    if not os.path.isfile(path):
        print("missing", path)
        return 1
    data = open(path, "rb").read()
    try:
        out, strip, info = patch_pak3(data, label)
    except TitleError as e:
        print("error:", e)
        return 1
    print("%s: drew %r (%d of %d px), pack %d -> %d bytes"
          % (PS2_PAK, info["label"], info["right"], info["width"], info["old_size"], info["new_size"]))
    if a.preview:
        write_png(a.preview, strip, 3)
        print("preview", a.preview)
    if a.dry_run:
        print("dry run, nothing written")
        return 0
    open(path, "wb").write(out)
    print("wrote", path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
