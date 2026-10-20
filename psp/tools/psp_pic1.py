#!/usr/bin/env python3
"""English XMB background (PSP_GAME/PIC1.PNG) with the patch version.

The 480 x 272 picture behind the game in the PSP menu has two Japanese
taglines, 未来は、ここにある / ここから、はじまる ("the future is here / it begins
here"), on a dark band at the bottom right, and the designer credit
"(c) いのまたむつみ" above the NBGI line at the bottom left. This tool fills the
Japanese text from the surrounding background, draws the English in the same
style (white, soft glow, Fira Sans SemiBold from psp/fonts) and adds a line
"Green Gel Group English Patch vX.Y.Z", so the version shows in the PSP menu
before the game starts (playtest document tab 12). The copyright sign of the
credit line and the NBGI line are the original pixels.

Needs Pillow. build_psp.py runs it when given --version.

    python psp/tools/psp_pic1.py PIC1.PNG out.png --version 0.3.3
"""
import argparse, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(os.path.dirname(HERE), 'fonts', 'FiraSans-SemiBold-ASCII.ttf')
SIZE = (480, 272)
SS = 4                                  # text is drawn at 4x and scaled down
TAGLINE = ('The future is here.', 'It all begins here.')
CREDIT = 'Mutsumi Inomata'
LABEL = 'Green Gel Group English Patch v%s'


def _erase_rows(img, box):
    """Rows y0..y1-1, x0..x1-1 interpolated per column between the row above
    and the row below (the tagline band is horizontal)."""
    x0, y0, x1, y1 = box
    px = img.load()
    for x in range(x0, x1):
        a, b = px[x, y0 - 1], px[x, y1]
        for y in range(y0, y1):
            t = (y - y0 + 1) / (y1 - y0 + 1)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(3))


def _erase_between(img, box, left_x, right_x):
    """Rows y0..y1-1, x0..x1-1 interpolated per row between the clean
    background at left_x and at right_x (the copyright sign in between stays)."""
    x0, y0, x1, y1 = box
    px = img.load()
    for y in range(y0, y1):
        a, b = px[left_x, y], px[right_x, y]
        for x in range(x0, x1):
            t = (x - left_x) / (right_x - left_x)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(3))


def _text(xy, txt, size, anchor):
    from PIL import Image, ImageDraw, ImageFont
    big = Image.new('L', (SIZE[0] * SS, SIZE[1] * SS), 0)
    ImageDraw.Draw(big).text((xy[0] * SS, xy[1] * SS), txt, fill=255, anchor=anchor,
                             font=ImageFont.truetype(FONT, size * SS))
    return big.resize(SIZE, Image.LANCZOS)


def _glow(base, layer, colour, blur, strength, grow):
    from PIL import Image, ImageFilter
    g = layer.filter(ImageFilter.MaxFilter(grow)) if grow > 1 else layer
    g = g.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: min(255, int(v * strength)))
    base = Image.composite(Image.new('RGB', SIZE, colour), base, g)
    return Image.composite(Image.new('RGB', SIZE, (255, 255, 255)), base, layer)


def build(png, version):
    """Retail PIC1.PNG bytes -> English PIC1.PNG bytes."""
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert('RGB')
    if img.size != SIZE:
        raise ValueError('PIC1.PNG is %dx%d, expected %dx%d' % (img.size + SIZE))
    _erase_rows(img, (298, 207, 474, 230))               # 未来は、ここにある
    _erase_rows(img, (298, 231, 474, 255))               # ここから、はじまる
    _erase_between(img, (25, 237, 114, 255), 11, 116)    # いのまたむつみ
    band = (40, 170, 255)
    img = _glow(img, _text((457, 224), TAGLINE[0], 16, 'rs'), band, 2.0, 2, 3)
    img = _glow(img, _text((468, 248), TAGLINE[1], 16, 'rs'), band, 2.0, 2, 3)
    small = (30, 90, 220)
    img = _glow(img, _text((27, 250), CREDIT, 10, 'ls'), small, 0.7, 1.3, 1)
    img = _glow(img, _text((14, 237), LABEL % version, 10, 'ls'), small, 0.7, 1.3, 1)
    out = io.BytesIO()
    img.save(out, 'PNG', optimize=True)
    return out.getvalue()


def available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('png')
    ap.add_argument('out')
    ap.add_argument('--version', required=True)
    a = ap.parse_args(argv)
    open(a.out, 'wb').write(build(open(a.png, 'rb').read(), a.version.lstrip('vV')))


if __name__ == '__main__':
    main()
