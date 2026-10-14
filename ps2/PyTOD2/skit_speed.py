"""Per line text speed for PS2 skits.

SkyBladeCloud found the speed byte (retrogametalk thread, 2026-10-12).
Each skit line in a SCED code section is

    push character, push line number, push 0, push SPEED, F8 <u16 text offset>

SPEED is a push immediate: 0x80+N for N <= 7, or 0x90 NN. It is the number
of frames between two glyphs: SLPS 0x10CF68 stores it at record+0x32, the
layout copies it to every glyph and the update at 0x10C674 waits that many
frames before it spawns the next glyph. Smaller is faster; 8 is about 7.5
glyphs per second.

English lines are longer than the Japanese ones, so each line gets
    window // English glyphs
which reveals the English inside the line's time window (never slower than
the original, never below MIN_SPEED). The window in frames is the larger of
the time the Japanese took (original speed * Japanese glyphs) and the time
the PR 18 text needed at 8 glyphs per second (commit 60bc9aaf, every line
checked against the measured voice window then). The value only ever
shrinks, so it is rewritten in place and the code section keeps its length.

skit_speeds.json holds [pointer field, original speed, Japanese glyphs,
window] per line, generated from the retail ISO, because a reused
FILE/pak1 folder holds SCEDs that an earlier build already retimed.

    python skit_speed.py table <Japanese ISO> skit_speeds.json [<PR 18 skit TXT_EN folder>]
    python skit_speed.py report <skit TXT_EN folder>
"""
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, 'skit_speeds.json')

MIN_SPEED = 1
MAX_GLYPHS = 384  # glyph slots per skit line (record+0x1BC .. +0xDBC)

# Translation budget: a line may not need a speed below READABLE_SPEED
# (20 glyphs per second). A row shows about 60 glyphs; longer lines scroll
# sideways and their start leaves the screen, so for them the reveal speed
# is the reading speed. 00054_02 is the untimed opening diary.
READABLE_SPEED = 3
EXEMPT = {'00054_02.sced'}

# Names as the game draws them: Japanese in the retail table, English in
# the patched executable. Unknown character ids count as 5 glyphs.
JP_NAMES = {1: 3, 2: 3, 3: 2, 4: 5, 5: 4, 6: 4}
EN_NAMES = {'Kyle': 4, 'Reala': 5, 'Loni': 4, 'Judas': 5, 'Nanaly': 6,
            'Harold': 6}
OTHER_NAME = 5
BUTTON = 0x09
CHARACTER = 0x07


def speed_site(code, pointer_field):
    """Offset and form of the speed push before the F8 whose u16 operand
    sits at pointer_field. Returns (offset, short) or None."""
    if code[pointer_field - 1] != 0xF8:
        return None
    b = code[pointer_field - 2]
    if 0x80 <= b <= 0x87:
        return pointer_field - 2, True
    if code[pointer_field - 3] == 0x90:
        return pointer_field - 2, False
    return None


def read_speed(code, pointer_field):
    site = speed_site(code, pointer_field)
    if site is None:
        return None
    offset, short = site
    return code[offset] - 0x80 if short else code[offset]


def write_speed(code, pointer_field, value):
    offset, short = speed_site(code, pointer_field)
    if short:
        if not 0 <= value <= 7:
            raise ValueError(f'speed {value} does not fit the 4-bit push')
        code[offset] = 0x80 + value
    else:
        if not 0 <= value <= 0x7F:
            raise ValueError(f'speed {value} does not fit the byte push')
        code[offset] = value


def jp_glyphs(text_block, start):
    """Glyphs the game draws for the retail record starting at start."""
    n = 0
    p = start
    while text_block[p] != 0:
        b = text_block[p]
        if 0x99 <= b <= 0x9F or 0xE0 <= b <= 0xE4:
            n += 1
            p += 2
        elif b in (0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xB):
            arg = struct.unpack_from('<I', text_block, p + 1)[0]
            if b == CHARACTER:
                n += JP_NAMES.get(arg, OTHER_NAME)
            elif b == BUTTON:
                n += 1
            p += 5
        elif 0x20 <= b <= 0x7E or 0xA1 <= b <= 0xDF:
            n += 1
            p += 1
        else:
            p += 1
    return n


TAG = re.compile(r'<(\w+)(?::\w+)?>|\{[0-9A-F]{2}\}|\n')


def en_glyphs(text):
    """Glyphs the game draws for one English record in TXT_EN notation."""
    n = 0
    pos = 0
    for m in TAG.finditer(text):
        n += m.start() - pos
        pos = m.end()
        tag = m.group(1)
        if tag in EN_NAMES:
            n += EN_NAMES[tag]
        elif tag == 'button':
            n += 1
        elif tag == 'char':
            n += OTHER_NAME
    return n + len(text) - pos


def window(row):
    """Frames a line may take; rows without a window use the Japanese time."""
    return row[3] if len(row) > 3 else row[1] * row[2]


def new_speed(original, japanese, english, frames=None):
    if english <= 0:
        return original
    frames = original * japanese if frames is None else frames
    return max(MIN_SPEED, min(original, frames // english))


def budget(row):
    """Most English glyphs a line may have."""
    return min(MAX_GLYPHS, max(row[2], window(row) // READABLE_SPEED))


def problems(name, rows, texts):
    """Lines of one skit that break the translation budget, as
    (line, message). rows from skit_speeds.json, texts from records()."""
    if name in EXEMPT:
        return []
    if len(rows) != len(texts):
        return [(None, f'{len(texts)} records, skit_speeds.json has {len(rows)}')]
    out = []
    for i, (row, text) in enumerate(zip(rows, texts)):
        if '\n' in text.strip('\n'):
            out.append((i, 'more than one English line (a skit shows one)'))
        english = en_glyphs(text.strip('\n'))
        limit = budget(row)
        if english > limit:
            out.append((i, f'{english} glyphs, budget {limit}'))
    return out


def load_table(path=TABLE):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def retime(name, code, pointer_fields, texts, table):
    """Rewrite the speed of every line of one skit in code (bytearray,
    the SCED up to its text block). texts are the English records in
    order. Returns a list of (line, original, new, english glyphs)."""
    if name not in table:
        raise RuntimeError(f'{name}: not in skit_speeds.json')
    rows = table[name]
    if len(rows) != len(pointer_fields) or len(rows) != len(texts):
        raise RuntimeError(
            f'{name}: skit_speeds.json has {len(rows)} lines, the SCED '
            f'{len(pointer_fields)} pointers, TXT_EN {len(texts)} records')
    out = []
    for i, (row, actual, text) in enumerate(zip(rows, pointer_fields, texts)):
        field, original = row[0], row[1]
        if field != actual:
            raise RuntimeError(
                f'{name} line {i}: pointer at 0x{actual:X}, '
                f'skit_speeds.json expects 0x{field:X}')
        if speed_site(code, field) is None:
            raise RuntimeError(f'{name} line {i}: no speed push before F8')
        english = en_glyphs(text)
        value = new_speed(original, row[2], english, window(row))
        write_speed(code, field, value)
        out.append((i, original, value, english))
    return out


def records(path):
    """English records of one TXT_EN file, Japanese (#) lines dropped."""
    out = []
    lines = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if '-----------------------' in line:
                out.append('\n'.join(lines))
                lines = []
            elif not line.startswith('#'):
                lines.append(line)
    return out


def skit_pointer_fields(sced):
    """Pointer fields of the text lines, the way PyTOD2 extracts them."""
    text_block = struct.unpack_from('<L', sced, 8)[0]
    code_start = struct.unpack_from('<L', sced, 4)[0]
    size = len(sced) - text_block
    fields = []
    for p in range(code_start, text_block - 2):
        if sced[p] != 0xF8:
            continue
        addr = struct.unpack_from('<H', sced, p + 1)[0]
        if 0 < addr < size and sced[text_block + addr - 1] == 0:
            fields.append(p + 1)
    return fields


def table_from_sced(sced):
    text_block = struct.unpack_from('<L', sced, 8)[0]
    rows = []
    for field in skit_pointer_fields(sced):
        speed = read_speed(sced, field)
        if speed is None:
            raise RuntimeError(f'no speed push before F8 at 0x{field - 1:X}')
        addr = struct.unpack_from('<H', sced, field)[0]
        rows.append([field, speed, jp_glyphs(sced, text_block + addr)])
    return rows


def retail_skits(iso):
    """{'00056_02.sced': bytes} for every skit SCED in the retail ISO."""
    sys.path.insert(0, os.path.join(HERE, '..', 'menu'))
    import lzss
    sector = 2048
    f = open(iso, 'rb')
    f.seek(16 * sector)
    pvd = f.read(sector)
    files = {}

    def walk(extent, length, path=''):
        f.seek(extent * sector)
        d = f.read(length)
        p = 0
        while p < len(d):
            n = d[p]
            if n == 0:
                p = (p // sector + 1) * sector
                continue
            e = d[p:p + n]
            x, sz = struct.unpack_from('<L', e, 2)[0], struct.unpack_from('<L', e, 10)[0]
            nm = e[33:33 + e[32]].decode('latin1').split(';')[0]
            if nm not in ('\x00', '\x01'):
                if e[25] & 2:
                    walk(x, sz, path + nm + '/')
                else:
                    files[path + nm] = (x, sz)
            p += n
    root = pvd[156:190]
    walk(struct.unpack_from('<L', root, 2)[0], struct.unpack_from('<L', root, 10)[0])
    x, sz = files['SLPS_251.72']
    f.seek(x * sector)
    slps = f.read(sz)
    pointers = [struct.unpack_from('<L', slps, o)[0] for o in range(0xDD320, 0xE62EF, 4)]
    with open(os.path.join(HERE, 'FPB.json'), 'r', encoding='utf-8') as t:
        types = json.load(t)
    fpb = files['FILE.FPB'][0] * sector
    out = {}
    for i in range(len(pointers) - 1):
        if types.get('%05d' % i) != 'pak1':
            continue
        rem = pointers[i] & 0x3F
        start = pointers[i] & ~0x3F
        end = (pointers[i + 1] & ~0x3F) - rem
        f.seek(fpb + start)
        d = f.read(end - start)
        if lzss.is_packed(d):
            d = lzss.unpack(d)
        count = struct.unpack_from('<I', d, 0)[0]
        if 4 + 8 * count > len(d):
            continue
        for m in range(count):
            off, size = struct.unpack_from('<II', d, 4 + 8 * m)
            member = d[off:off + size]
            if lzss.is_packed(member):
                member = lzss.unpack(member)
            if member[:4] == b'SCED':
                out['%05d_%02d.sced' % (i, m)] = member
    return out


def main(argv):
    if len(argv) in (3, 4) and argv[0] == 'table':
        skits = retail_skits(argv[1])
        table = {}
        for name, sced in sorted(skits.items()):
            rows = table_from_sced(sced)
            if not rows:
                continue
            validated = os.path.join(argv[3], name + '.txt') if len(argv) == 4 else None
            if validated and os.path.exists(validated) and name not in EXEMPT:
                texts = records(validated)
                if len(texts) != len(rows):
                    raise RuntimeError(f'{name}: {len(texts)} validated records, {len(rows)} lines')
                for row, text in zip(rows, texts):
                    # 8 glyphs per second = 7.5 frames per glyph
                    row.append(max(row[1] * row[2], (en_glyphs(text.strip('\n')) * 15 + 1) // 2))
            table[name] = rows
        with open(argv[2], 'w', encoding='utf-8', newline='\n') as f:
            f.write('{\n')
            f.write(',\n'.join(f'"{k}": {json.dumps(v)}' for k, v in table.items()))
            f.write('\n}\n')
        print(f'{len(table)} skits, {sum(map(len, table.values()))} lines')
        return 0
    if len(argv) == 2 and argv[0] == 'report':
        table = load_table()
        hist = {}
        long_lines = []
        over = []
        for name, rows in sorted(table.items()):
            path = os.path.join(argv[1], name + '.txt')
            if not os.path.exists(path):
                continue
            texts = records(path)
            if len(texts) != len(rows):
                print(f'{name}: {len(texts)} records, table has {len(rows)}')
                continue
            for i, (row, text) in enumerate(zip(rows, texts)):
                english = en_glyphs(text)
                value = new_speed(row[1], row[2], english, window(row))
                hist[value] = hist.get(value, 0) + 1
                if english > MAX_GLYPHS:
                    long_lines.append(f'{name} line {i}: {english} glyphs')
            over += [f'{name} line {i}: {msg}' for i, msg in problems(name, rows, texts)]
        for value in sorted(hist):
            print(f'speed {value:2d} ({60 / value:5.1f} glyphs/s): {hist[value]} lines')
        for line in long_lines:
            print(f'over {MAX_GLYPHS} glyphs: {line}')
        print(f'{len(over)} lines over budget (speed below {READABLE_SPEED}):')
        for line in over:
            print('  ' + line)
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
