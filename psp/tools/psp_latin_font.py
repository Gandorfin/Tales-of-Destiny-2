#!/usr/bin/env python3
"""One Latin typeface for all PSP text (font 1 and the bold menu font).

Why: the Latin letters of the PSP build came from three sources that never
matched: retail full-width capitals and digits, eleven retail lowercase
letters in high cells, and fifteen hand-made lowercase letters
(psp_lowercase). Their x-heights, baselines and stroke weights differed, so
with the variable width font (psp_vwf) a line visibly bounced up and down
and some letters were hard to read (the p of "orphanage").

What: every printable ASCII character is drawn from one TrueType font
(psp/fonts/FiraSans-SemiBold-ASCII.ttf, Fira Sans SemiBold, SIL Open Font
License, subset to ASCII) on one baseline, with one cap height and
x-height, in the retail glyph style: white fill, soft dark outline, 16
levels. Descenders are pulled up just enough to fit the cell. The advance
of each character is the font's own advance (plus a little tracking).

Two steps, so the build needs no Pillow and no font file:

    python psp/tools/psp_latin_font.py render     (Pillow; writes the table)

writes psp/fonts/latin_glyphs.json (committed). The build only reads that
table: stamp_font1() draws the glyphs into font 1 (FPB member 0) at the
slots the 8-bit slot table gives each character; font2_cells() gives the
glyphs for the bold menu font copy (psp_bold_lowercase). Characters that
share a slot (- ~ _, ( < {, ) > }, : ;, " `) get the first one listed in
PRIORITY. psp_vwf reads the advances from the same table.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
FONT = os.path.join(ROOT, 'psp', 'fonts', 'FiraSans-SemiBold-ASCII.ttf')
TABLE = os.path.join(ROOT, 'psp', 'fonts', 'latin_glyphs.json')

# cell geometry and design sizes (cell pixels)
FONT1 = dict(w=23, h=23, cap=13.0, base=18, bottom=21.5, outline=1.6, track=1.2, space=2.5)
FONT2 = dict(w=12, h=16, cap=10.6, base=12.6, bottom=16.0, outline=1.0, track=0.8, space=1.5)
PRIORITY = ('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
            '.,!?\'"-:()&*/%+=[]<>;~_{}`#$@\\^|')
SS = 8                                   # supersampling for rendering


def _render_set(font_path, g):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    W, H = g['w'], g['h']

    def font(size):
        return ImageFont.truetype(font_path, size)
    lo, hi = 2.0, 200.0                   # size whose 'H' is cap pixels tall
    for _ in range(40):
        mid = (lo + hi) / 2
        b = font(mid * SS).getbbox('H', anchor='ls')
        if (b[3] - b[1]) / SS < g['cap']:
            lo = mid
        else:
            hi = mid
    f = font(lo * SS)
    out = {}
    for c in range(0x20, 0x7F):
        ch = chr(c)
        adv = f.getlength(ch) / SS
        big = Image.new('L', (W * SS * 2, H * SS), 0)
        d = ImageDraw.Draw(big)
        d.text((W * SS // 2, g['base'] * SS), ch, font=f, fill=255, anchor='ls')
        box = big.getbbox()
        if box:
            # descenders: squeeze the part below the baseline into the cell
            below = box[3] / SS - g['base']
            room = g['bottom'] - g['outline'] - g['base']
            if below > room > 0:
                cut = int(round(g['base'] * SS))
                top = big.crop((0, 0, big.width, cut))
                low = big.crop((0, cut, big.width, box[3]))
                low = low.resize((low.width, max(1, int(room * SS))), Image.LANCZOS)
                big = Image.new('L', big.size, 0)
                big.paste(top, (0, 0))
                big.paste(low, (0, cut))
                box = big.getbbox()
            # too wide for the cell (W, M, m, w in font 2): narrow it
            ink = (box[2] - box[0]) / SS + 2 * g['outline']
            if ink > W:
                k = (W - 0.2) / ink
                part = big.crop((box[0], 0, box[2], big.height))
                part = part.resize((max(1, int(part.width * k)), part.height), Image.LANCZOS)
                big = Image.new('L', big.size, 0)
                big.paste(part, (box[0], 0))
                box = big.getbbox()
                adv = (box[2] - box[0]) / SS + 1.0   # narrowed shape + side bearings
            # pen at a whole pixel of the cell (no rounding between glyphs):
            # roughly centred, moved so the ink and its outline stay inside
            pen = W * SS // 2                        # pen x in the big image
            p = int(round((W - adv) / 2))
            o = g['outline']
            lo_p = int(-(-(o * SS - (box[0] - pen)) // SS))      # ink_l >= o
            hi_p = int((W * SS - o * SS - (box[2] - pen)) // SS)  # ink_r <= W - o
            if lo_p <= hi_p:
                p = min(max(p, lo_p), hi_p)
            else:
                p = (lo_p + hi_p) // 2
            left = p
            x0 = pen - p * SS
            cell = big.crop((x0, 0, x0 + W * SS, H * SS))
        else:
            cell = Image.new('L', (W * SS, H * SS), 0)
            left = 0
        fill = cell.resize((W, H), Image.BOX)
        r = max(1, int(round(g['outline'] * SS)))
        ring = cell.filter(ImageFilter.MaxFilter(2 * r + 1)).filter(
            ImageFilter.GaussianBlur(SS * 0.5)).resize((W, H), Image.BOX)
        rows = []
        for y in range(H):
            row = ''
            for x in range(W):
                fc = fill.getpixel((x, y)) / 255
                oc = ring.getpixel((x, y)) / 255
                v = 15 * fc + 4 * oc * (1 - fc)
                row += '%x' % max(0, min(15, int(round(v))))
            rows.append(row)
        extra = g['track'] + (g['space'] if ch == ' ' else 0)   # outlines eat the gaps
        out[ch] = {'left': int(round(left)), 'adv': int(round(adv + extra)), 'rows': rows}
    digits = max(out[d]['adv'] for d in '0123456789')
    for d in '0123456789':                # tabular figures for number columns
        out[d]['left'] += (digits - out[d]['adv']) // 2
        out[d]['adv'] = digits
    return out


def render(font_path=FONT, table=TABLE):
    data = {'source': os.path.basename(font_path), 'font1': FONT1, 'font2': FONT2,
            'glyphs1': _render_set(font_path, FONT1), 'glyphs2': _render_set(font_path, FONT2)}
    with open(table, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=0, sort_keys=True)
    return data


def load(table=TABLE):
    with open(table, encoding='utf-8') as f:
        return json.load(f)


def slot_chars(slot_table):
    """{slot: character drawn there}, first character of PRIORITY wins."""
    out = {}
    for ch in PRIORITY:
        s = slot_table[ord(ch)]
        if s and s not in out:
            out[s] = ch
    return out


def stamp_font1(gray, slot_table, data=None):
    """Draw the table's font 1 glyphs into gray (bytearray, 256 px wide,
    one byte per pixel, value = level * 17) at each character's slot.
    Returns {slot: (left, advance)}."""
    data = data or load()
    g, glyphs = data['font1'], data['glyphs1']
    W, H = g['w'], g['h']
    metrics = {}
    for slot, ch in slot_chars(slot_table).items():
        r, c = divmod(slot, 11)
        gl = glyphs[ch]
        for y in range(H):
            row = gl['rows'][y]
            at = (r * H + y) * 256 + c * W
            for x in range(W):
                gray[at + x] = int(row[x], 16) * 17
        metrics[slot] = (gl['left'], gl['adv'])
    sp = slot_table[0x20]
    metrics[sp] = (0, glyphs[' ']['adv'])
    return metrics


def build_font1(member, slot_table, data=None):
    """Font 1 member (FPB member 0, swizzled 4bpp) with the Latin glyphs
    drawn in. Returns (member bytes, {slot: (left, advance)})."""
    import psp_font
    gray = bytearray(psp_font.deswizzle(member))
    metrics = stamp_font1(gray, slot_table, data)
    return psp_font.reswizzle(bytes(gray)), metrics


def font2_cells(slot_table, data=None):
    """{cell: (rows, left, advance)} for the bold menu font copy."""
    data = data or load()
    glyphs = data['glyphs2']
    return {cell: (glyphs[ch]['rows'], glyphs[ch]['left'], glyphs[ch]['adv'])
            for cell, ch in slot_chars(slot_table).items()}


if __name__ == '__main__':
    if sys.argv[1:] == ['render']:
        d = render()
        print('wrote %s: %d + %d glyphs from %s' % (TABLE, len(d['glyphs1']), len(d['glyphs2']), d['source']))
    else:
        raise SystemExit(__doc__)
