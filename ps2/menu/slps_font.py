"""Add an ampersand and a tilde to the game's Latin font (PS2).

    python3 ps2/menu/slps_font.py ps2/PyTOD2/SLPS_251.72            # patch in place
    python3 ps2/menu/slps_font.py ps2/PyTOD2/SLPS_251.72 --dry-run
    python3 ps2/menu/slps_font.py <SLPS or font.bin> --export font.png [--grid]

The Latin glyphs the game draws in dialogue and menus come from one
compressed TM2@ texture inside the executable (file offset 0xCA238, LZSS
"comptoe" stream, 128x512 pixels, 4 bits per pixel, cells 12x16 in rows of
ten).  Single-byte text goes through a 96-entry table at 0xC9D00 (one glyph
index per ASCII code 0x20..0x7F).  The retail table sends '&' to cell 0xC3
and '~' to cell 0xD2, and both cells are empty, so the two characters showed
as blank gaps; '*' goes to cell 0x4E, which holds a star.  This step draws
an ampersand over cell 0x4B and a tilde over cell 0x4C (the curly quotes
that only '#' and '$' reach, characters no text of the patch uses), redraws
cell 0x4E as an asterisk, packs the texture again into the room the
original occupied, and points '&' and '~' at the new cells.  Replacing
existing cells instead of painting into the empty rows keeps the packed
size within the original 10,242 bytes.  Everything else in the texture and
the table is untouched; running it twice changes nothing.

The 2008 fan patch's alternative font (ps2/PyTOD2/font.bin, PyTOD2's
optional "Insert FONT") has never been part of a Green Gel release; the
patched retail font is what players see.  --export writes the texture as a
PNG (Pillow needed) so the glyphs can be inspected or edited.
"""
import os, sys, struct, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lzss

FONT_OFF = 0xCA238        # packed TM2@ texture in SLPS_251.72
MAP_OFF = 0xC9D00         # ASCII 0x20..0x7F -> glyph cell
CELL_W, CELL_H, COLS = 12, 16, 10
TEX_W, TEX_H = 128, 512
MAGIC = b"TM2@"

# glyph art, rows 0..15 of a 12x16 cell; '#' = ink.  The outline is derived.
GLYPHS = {
    0x4B: ('&', [
        "............",
        "............",
        "...####.....",
        "..######....",
        "..##..##....",
        "..##..##....",
        "..######....",
        "...####.....",
        "..####..##..",
        ".###.##.##..",
        ".##...###...",
        ".##...###...",
        ".###.#####..",
        "..####..###.",
        "............",
        "............"]),
    0x4C: ('~', [
        "............",
        "............",
        "............",
        "............",
        "............",
        "............",
        "...###...##.",
        "..#####.###.",
        ".###.#####..",
        ".##...###...",
        "............",
        "............",
        "............",
        "............",
        "............",
        "............"]),
    0x4E: ('*', [
        "............",
        "............",
        "............",
        ".....##.....",
        "..##.##.##..",
        "...######...",
        "....####....",
        "...######...",
        "..##.##.##..",
        ".....##.....",
        "............",
        "............",
        "............",
        "............",
        "............",
        "............"]),
}
MAP = {0x26: 0x4B, 0x7E: 0x4C}      # '&' and '~'; '*' already reaches 0x4E

# palette indices of the retail glyphs: white ink, grey stroke tips, dark outline
INK, EDGE, OUTLINE, CORNER = 0xF, 0xB, 0x4, 0x2


class FontError(Exception):
    pass


# ---------------------------------------------------------------- texture

def packed_blob(d):
    """The compressed font stream at FONT_OFF (header + payload)."""
    if d[FONT_OFF] not in (1, 3):
        raise FontError("no compressed stream at 0x%X" % FONT_OFF)
    n = struct.unpack_from("<I", d, FONT_OFF + 1)[0]
    return bytes(d[FONT_OFF:FONT_OFF + 9 + n])


def image_block(tex):
    """-> (pixel offset, w, h) of the 4bpp image block of a TM2@ texture."""
    if tex[:4] != MAGIC:
        raise FontError("not a TM2@ texture")
    p = 0x10
    while p + 16 <= len(tex):
        size, psm, pos, w, h = struct.unpack_from("<IIIHH", tex, p)
        if size < 16 or p + size > len(tex):
            break
        if psm == 0x14 and size == 16 + w * h // 2:
            return p + 16, w, h
        p += size
    raise FontError("no 4bpp image block in the font texture")


def get_pixel(tex, base, w, x, y):
    b = tex[base + (y * w + x) // 2]
    return b & 15 if x % 2 == 0 else b >> 4


def set_pixel(tex, base, w, x, y, v):
    i = base + (y * w + x) // 2
    tex[i] = (tex[i] & 0xF0) | v if x % 2 == 0 else (tex[i] & 0x0F) | (v << 4)


def cell_origin(cell):
    r, c = divmod(cell, COLS)
    return c * CELL_W, r * CELL_H


def rendered(art):
    """Ink rows -> 12x16 list of palette indices with the outline added."""
    ink = [[ch == '#' for ch in row] for row in art]
    out = [[0] * CELL_W for _ in range(CELL_H)]
    def at(x, y):
        return 0 <= x < CELL_W and 0 <= y < CELL_H and ink[y][x]
    for y in range(CELL_H):
        for x in range(CELL_W):
            n4 = sum(at(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            n8 = n4 + sum(at(x + dx, y + dy) for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)))
            if ink[y][x]:
                out[y][x] = EDGE if n4 <= 1 else INK
            elif n4:
                out[y][x] = OUTLINE
            elif n8:
                out[y][x] = CORNER
    return out


def read_cell(tex, base, w, cell):
    x0, y0 = cell_origin(cell)
    return [[get_pixel(tex, base, w, x0 + x, y0 + y) for x in range(CELL_W)] for y in range(CELL_H)]


def write_cell(tex, base, w, cell, px):
    x0, y0 = cell_origin(cell)
    for y in range(CELL_H):
        for x in range(CELL_W):
            set_pixel(tex, base, w, x0 + x, y0 + y, px[y][x])


# ---------------------------------------------------------------- patch

def state(d):
    """-> (font_done, map_done) for an executable."""
    tex = lzss.unpack(packed_blob(d))
    base, w, h = image_block(tex)
    if (w, h) != (TEX_W, TEX_H):
        raise FontError("unexpected font texture size %dx%d" % (w, h))
    font_done = all(read_cell(tex, base, w, c) == rendered(art) for c, (_, art) in GLYPHS.items())
    map_done = all(d[MAP_OFF + code - 0x20] == cell for code, cell in MAP.items())
    return font_done, map_done


def apply(src):
    """-> (new executable bytes, list of what changed)."""
    d = bytearray(src)
    blob = packed_blob(d)
    tex = bytearray(lzss.unpack(blob))
    base, w, h = image_block(tex)
    if (w, h) != (TEX_W, TEX_H):
        raise FontError("unexpected font texture size %dx%d" % (w, h))
    changes = []
    for cell, (ch, art) in GLYPHS.items():
        want = rendered(art)
        have = read_cell(tex, base, w, cell)
        if have == want:
            continue
        write_cell(tex, base, w, cell, want)
        changes.append("glyph %r in cell 0x%02X" % (ch, cell))
    if changes:
        packed = lzss.pack(bytes(tex), 3)
        if len(packed) > len(blob):
            raise FontError("packed font grew from %d to %d bytes" % (len(blob), len(packed)))
        if lzss.unpack(packed) != bytes(tex):
            raise FontError("font did not survive the round trip")
        d[FONT_OFF:FONT_OFF + len(blob)] = packed + b"\0" * (len(blob) - len(packed))
    for code, cell in MAP.items():
        off = MAP_OFF + code - 0x20
        if d[off] != cell:
            changes.append("'%s' -> cell 0x%02X (was 0x%02X)" % (chr(code), cell, d[off]))
            d[off] = cell
    return bytes(d), changes


# ---------------------------------------------------------------- export

def export_png(data, out, grid=False):
    from PIL import Image, ImageDraw
    blob = packed_blob(data) if len(data) > FONT_OFF + 9 and data[:4] != MAGIC and data[0] not in (1, 3) else data
    tex = lzss.unpack(blob) if blob[0] in (1, 3) else blob
    base, w, h = image_block(tex)
    p = 0x10
    pal = None
    while p + 16 <= len(tex):
        size, psm, pos, pw, ph = struct.unpack_from("<IIIHH", tex, p)
        if psm == 0 and pw * ph == 16 and pal is None:
            pal = [tuple(tex[p + 16 + 4 * i: p + 20 + 4 * i]) for i in range(16)]
        p += size
    pal = pal or [(v * 17, v * 17, v * 17, 255 if v else 0) for v in range(16)]
    im = Image.new("RGBA", (w, h))
    im.putdata([pal[get_pixel(tex, base, w, x, y)] for y in range(h) for x in range(w)])
    if grid:
        z = 4
        big = im.resize((w * z, h * z), Image.NEAREST)
        bg = Image.new("RGBA", big.size, (30, 30, 60, 255))
        bg.alpha_composite(big)
        dr = ImageDraw.Draw(bg)
        for x in range(0, COLS * CELL_W + 1, CELL_W):
            dr.line([(x * z, 0), (x * z, h * z)], fill=(255, 0, 0, 140))
        for y in range(0, h, CELL_H):
            dr.line([(0, y * z), (COLS * CELL_W * z, y * z)], fill=(255, 0, 0, 140))
        for cy in range(h // CELL_H):
            for cx in range(COLS):
                dr.text((cx * CELL_W * z + 1, cy * CELL_H * z + 1), "%02X" % (cy * COLS + cx), fill=(0, 255, 0, 255))
        im = bg
    im.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", help="SLPS_251.72 (or a packed font blob for --export)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export", metavar="PNG", help="write the font texture as a PNG and stop")
    ap.add_argument("--grid", action="store_true", help="with --export: zoom, cell grid and indices")
    a = ap.parse_args(argv)
    data = open(a.target, "rb").read()
    if a.export:
        export_png(data, a.export, a.grid)
        print("written: %s" % a.export)
        return 0
    try:
        new, changes = apply(data)
    except FontError as e:
        print("font: %s. Nothing written." % e)
        return 1
    if not changes:
        print("font: '&' and '~' glyphs already in place")
        return 0
    print("font: " + ", ".join(changes))
    if a.dry_run:
        print("(dry run) would write %s" % a.target)
        return 0
    open(a.target, "wb").write(new)
    print("written: %s" % a.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
