#!/usr/bin/env python3
"""Enchant level rows in fixed columns (PSP, with the variable width font).

build_psp.py calls patch_boot() on BOOT.BIN after the variable width font
(psp_vwf). Without that font the retail rows are already monospaced and
this step is not needed.

The Enchant menu lists an arte's enchantments as rows such as
"Increase Accuracy   1 2 3 4". The builder at vaddr 0x110700 (file offset
= vaddr + 0xC0, runtime = vaddr + 0x08804000) fills a 0x80 byte row with
spaces, copies the name to its start and writes the level part from byte
20 on: per level three 5 byte colour tags (from 0x1C46BC), one ASCII space
(0x1C46F8) and a full-width digit (0x994E..0x9951), then a NUL. The rows are
widgets drawn centred in a 16 cell wide column (4864 units at their glyph
size 0x130, 304 units per font 1 cell). The cursor of the level columns
does not follow the text: its x comes from a fixed table, halfwords at
vaddr 0x23D3CC (index 0 and 1 = level 1, then 2..4; retail 3200, 3200,
3664, 4128, 4592).

Retail names are kanji, two bytes and one full cell each, so "name + spaces
to byte 20" was always 10 cells and every row 16 cells wide: the names
started at the same x and the digits sat under the cursor. With English
and the variable width font every row has another width, so the names
start at different x, the digits drift from row to row and away from the
cursor (playtest tab 15, pnvnd, PSP 0.3.8).

What this step does:

* A hook at 0x1107D0 (where the builder sets the write pointer to byte 20)
  measures the name with the font 1 advances of psp/fonts/latin_glyphs.json
  (the table psp_vwf draws with) and pads it to NAME_PX font pixels: whole
  spaces (8 px each) and, for the rest, one space inside <size:N> ..
  <size:100> tags (N = rest * 32, so that space is rest pixels wide; the
  text box measurer and printer scale the advance with the size tag). The
  level part follows as before. Every row is now as wide as every other
  one, so the centred rows start at one x (names left aligned) and the
  digits share four columns. The longest name, "Penetrate Elemental", is
  196 px; a row needs at most 112 of its 128 bytes ("Critical"). check_names
  (run by patch_boot) refuses a table name that would not fit.
* The cursor table gets the x of those columns: retail value + the shift
  of the digit (CURSOR_TABLE), so the cursor keeps its retail place next
  to each digit.

The hook is reached like the psp_vwf hooks, without a new relocation:
s4 holds the runtime address of vaddr 0x1C46BC at that point, the call
site adds the distance to the hook. The five words it replaces
(addiu s1,s1,0x14 / fp,s4,5 / s7,s4,0xA / s0,s6,0x740 / s2,zero,3) are
done again by the hook, which then sets s1 to the end of the padding.

The arte grid of the same menu (Enchant > character) is one list of
widgets (descriptor and runtime object at vaddr 0x23BF3C, glyph size
0x130 x 0x170 at +0x3E/+0x40): the upper block (artes, flag bit 0 clear)
is drawn by the text printer, the lower block (flag bit 0 set by the item
callback 0x112490 at 0x11254C) by the bold routine, bigger. Its labels are
centred in their column by the bold measurer; psp_vwf now measures them
with the bold advances, so they sit under the upper columns and inside the
box. This step also draws that lower block a little smaller (LOWER_SIZE):
the callback's jump back at 0x112550 (j 0x1124C4, relocation R_MIPS_26
against the text segment, so it may get another target in the module)
goes to a hook that writes the size into the item descriptor (s0 + 0x20 /
+ 0x22, which the widget creator 0xF0E34 copies) and jumps on to 0x1124C4
through its own return address (bal). The callback reloads ra from its
stack before it returns.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mips_asm  # noqa: E402

TEXT_BIAS = 0xC0
DATA_BIAS = 0x100
POOL_VADDR = 0x881000
SLOTTAB = 0x27DC40               # 8-bit slot table (vaddr)
SLOTTAB_FILE = 0x27DD40
S4_VADDR = 0x1C46BC              # what s4 holds at the call site (colour tags)
SITE = 0x1107D0
RETAIL_SITE = [0x26310014, 0x269E0005, 0x2697000A, 0x26D00740, 0x24120003]
CURSOR_TABLE = 0x23D3CC          # vaddr, 5 halfwords
RETAIL_CURSOR = (3200, 3200, 3664, 4128, 4592)
NAME_PX = 230                    # 10 font 1 cells of 23 px, as the retail rows
SPACE_PX = 8                     # font 1 advance of ' ' (latin_glyphs.json)
CELL_PX = 23
LOWER_JUMP = 0x112550            # j 0x1124C4 in the arte list item callback
LOWER_BACK = 0x1124C4
LOWER_SIZE = (0x108, 0x140)      # retail 0x130 x 0x170 (87 %)
UNIT = 304                       # layout units per cell (row glyph size 0x130)
COLUMN_CELLS = 16                # the row widgets are 4864 units wide


# The enchantment names of the table at BOOT 0x1A147C..0x1A2384 (the PS2 list
# in the SLPS at 0xB8820, 8 byte records); their English is in psp_menu.tsv.
ENCHANT_KEYS = (
    '命中率アップ', '攻撃力アップ', 'SP減少軽減', 'クリティカル', '詠唱速度－', '知性－',
    '地耐性－', '水耐性－', '火耐性－', '風耐性－', '光耐性－', '闇耐性－', '属性攻撃貫通',
    '属性晶術貫通', 'ブラスター', '詠唱速度上昇', 'アイテム強奪', '瞬間完全回避', '追加特技',
    '秘奥義', '反撃発動', 'ガード発動', '空中発動', 'ガードブレイク', 'ふっ飛ばし', '通常技連携',
    '攻撃後前進', '攻撃後後退', '背面取り', '晶術追撃', '特技連携', '効果上昇', '詠唱加速',
    'TP減少軽減', '属性抵抗上昇', '攻撃力－', '命中－', '防御力－', '回避力－', 'SP－', 'TP－',
    '毒効果', '凍結効果', '麻痺効果', '鈍足効果', '硬直時間加算', 'リカバー', 'ゲットアイテム',
    'スピリッツ', 'メンタル', '追加晶術', '具現結晶', '連携発動', '４倍速詠唱', 'HP吸収', 'SP転換',
    'TP転換', 'SP分与', '引き寄せ', '一定完全回避', '硬直解除', '気絶攻撃')
LEVEL_BYTES = 4 * (15 + 1 + 2) + 1   # level part + NUL
ROW_BYTES = 0x80


def padding(name, glyphs=None):
    """The bytes the hook writes after the name (Python model of the hook)."""
    if glyphs is None:
        import psp_latin_font
        glyphs = psp_latin_font.load()['glyphs1']
    width = sum(glyphs[c]['adv'] if c in glyphs else CELL_PX // 2 for c in name.rstrip(' '))
    pad = max(NAME_PX - width, SPACE_PX)
    out = b' ' * (pad // SPACE_PX)
    if pad % SPACE_PX:
        out += bytes([5, (pad % SPACE_PX) * 32, 0, 0, 0, 0x20, 5, 0, 1, 0, 0])
    return width, out


def check_names(table=None, glyphs=None):
    """Problems with the English enchantment names: wider than the name
    area (NAME_PX) or a row longer than its 0x80 bytes."""
    import psp_menu
    table = dict(psp_menu.load_table()) if table is None else table
    errs = []
    for jp in ENCHANT_KEYS:
        en = table.get(jp)
        if en is None:
            errs.append('%s: no English in psp_menu.tsv' % jp)
            continue
        width, pad = padding(en, glyphs)
        if width > NAME_PX - SPACE_PX:
            errs.append('%s: %r is %d px, the name area is %d px' % (jp, en, width, NAME_PX - SPACE_PX))
        if len(en.rstrip(' ')) + len(pad) + LEVEL_BYTES > ROW_BYTES:
            errs.append('%s: %r needs %d row bytes, the row has %d'
                        % (jp, en, len(en.rstrip(' ')) + len(pad) + LEVEL_BYTES, ROW_BYTES))
    return errs


def cursor_table(space_px=SPACE_PX):
    """The five cursor x values for rows of NAME_PX name + 4 x (space,
    digit). Retail rows: name area 10 cells, half cell spaces, row as wide
    as the column (offset 0)."""
    name = NAME_PX / CELL_PX
    sp = space_px / CELL_PX
    width = name + 4 * (sp + 1)
    offset = (COLUMN_CELLS - width) / 2
    out = []
    for i, retail in enumerate(RETAIL_CURSOR):
        k = max(i, 1)
        new_left = offset + name + k * sp + (k - 1)
        old_left = 10 + k * 0.5 + (k - 1)
        out.append(int(round(retail + (new_left - old_left) * UNIT)))
    return tuple(out)


def hook_code(base, widths):
    """Assemble the hook + its copy of the width table at vaddr base."""
    a = mips_asm.Asm(base)
    a.label('row')
    a.op('addiu', 'fp', 's4', 5)                      # the five retail words
    a.op('addiu', 's7', 's4', 0xA)
    a.op('addiu', 's0', 's6', 0x740)
    a.op('addiu', 's2', 'zero', 3)
    # end of the name: last byte that is not a space (the row was filled
    # with spaces before the name was copied in, without its NUL)
    a.op('addiu', 't0', 's1', 0x80)
    a.label('scan')
    a.op('addiu', 't0', 't0', -1)
    a.op('slt', 't3', 't0', 's1')
    a.op('bnez', 't3', 'empty')
    a.op('nop')
    a.op('lbu', 't1', 0, 't0')
    a.op('addiu', 't2', 'zero', 0x20)
    a.op('beq', 't1', 't2', 'scan')
    a.op('nop')
    a.op('b', 'measure')
    a.op('addiu', 't0', 't0', 1)
    a.label('empty')
    a.op('move', 't0', 's1')
    # width of [s1, t0) in font 1 pixels
    a.label('measure')
    a.op('move', 't4', 'zero')
    a.op('move', 't5', 's1')
    a.op('lui', 't6', ('hi', SLOTTAB - S4_VADDR))
    a.op('addiu', 't6', 't6', ('lo', SLOTTAB - S4_VADDR))
    a.op('addu', 't6', 't6', 's4')
    a.op('lui', 't7', ('hi', 'widths', S4_VADDR))
    a.op('addiu', 't7', 't7', ('lo', 'widths', S4_VADDR))
    a.op('addu', 't7', 't7', 's4')
    a.label('wloop')
    a.op('beq', 't5', 't0', 'wdone')
    a.op('nop')
    a.op('lbu', 't1', 0, 't5')
    a.op('sltiu', 't3', 't1', 0x80)
    a.op('beqz', 't3', 'wtwo')
    a.op('nop')
    a.op('addu', 't3', 't6', 't1')
    a.op('lbu', 't3', 0, 't3')                        # slot
    a.op('sll', 't3', 't3', 1)
    a.op('addu', 't3', 't3', 't7')
    a.op('lbu', 't3', 1, 't3')                        # advance
    a.op('bnez', 't3', 'wadd')
    a.op('nop')
    a.op('addiu', 't3', 'zero', CELL_PX // 2)         # no Latin glyph: half cell
    a.label('wadd')
    a.op('addu', 't4', 't4', 't3')
    a.op('b', 'wloop')
    a.op('addiu', 't5', 't5', 1)
    a.label('wtwo')                                   # two-byte code: full cell
    a.op('addiu', 't4', 't4', CELL_PX)
    a.op('b', 'wloop')
    a.op('addiu', 't5', 't5', 2)
    a.label('wdone')
    # pad = NAME_PX - width, at least one space
    a.op('addiu', 't1', 'zero', NAME_PX)
    a.op('subu', 't1', 't1', 't4')
    a.op('slti', 't3', 't1', SPACE_PX)
    a.op('beqz', 't3', 'padok')
    a.op('nop')
    a.op('addiu', 't1', 'zero', SPACE_PX)
    a.label('padok')
    a.op('srl', 't2', 't1', 3)                        # whole spaces
    a.op('andi', 't3', 't1', SPACE_PX - 1)            # pixels left
    a.op('addiu', 't8', 'zero', 0x20)
    a.label('spaces')
    a.op('beqz', 't2', 'rest')
    a.op('nop')
    a.op('sb', 't8', 0, 't0')
    a.op('addiu', 't0', 't0', 1)
    a.op('b', 'spaces')
    a.op('addiu', 't2', 't2', -1)
    a.label('rest')                                   # <size:rest*32> ' ' <size:100>
    a.op('beqz', 't3', 'out')
    a.op('nop')
    a.op('addiu', 't9', 'zero', 5)
    a.op('sb', 't9', 0, 't0')
    a.op('sll', 't3', 't3', 5)
    a.op('sb', 't3', 1, 't0')
    a.op('sb', 'zero', 2, 't0')
    a.op('sb', 'zero', 3, 't0')
    a.op('sb', 'zero', 4, 't0')
    a.op('sb', 't8', 5, 't0')
    a.op('sb', 't9', 6, 't0')
    a.op('sb', 'zero', 7, 't0')
    a.op('addiu', 't9', 'zero', 1)
    a.op('sb', 't9', 8, 't0')
    a.op('sb', 'zero', 9, 't0')
    a.op('sb', 'zero', 10, 't0')
    a.op('addiu', 't0', 't0', 11)
    a.label('out')
    a.op('jr', 'ra')
    a.op('move', 's1', 't0')
    a.align(4)
    a.label('widths')
    a.data(widths)
    return a.assemble(), a.labels


def lower_code(base):
    """Hook for the lower block of the arte grid: item size, then back."""
    a = mips_asm.Asm(base)
    a.label('lower')
    a.op('addiu', 't4', 'zero', LOWER_SIZE[0])
    a.op('sh', 't4', 0x20, 's0')
    a.op('addiu', 't4', 'zero', LOWER_SIZE[1])
    a.op('sh', 't4', 0x22, 's0')
    a.op('bal', 'here')
    a.op('nop')
    a.label('here')
    a.op('lui', 't5', ('hi', LOWER_BACK, 'here'))
    a.op('addiu', 't5', 't5', ('lo', LOWER_BACK, 'here'))
    a.op('addu', 't5', 't5', 'ra')
    a.op('jr', 't5')
    a.op('nop')
    return a.assemble(), a.labels


def jump_word(target):
    return 0x08000000 | ((target >> 2) & 0x3FFFFFF)


def site_words(hook_vaddr):
    s = mips_asm.Asm(SITE)
    s.op('lui', 'at', ('hi', hook_vaddr - S4_VADDR))
    s.op('addiu', 'at', 'at', ('lo', hook_vaddr - S4_VADDR))
    s.op('addu', 'at', 'at', 's4')
    s.op('jalr', 'at')
    s.op('nop')
    return s.words()


def _pool_header(b):
    phoff = struct.unpack_from('<I', b, 0x1C)[0]
    phnum = struct.unpack_from('<H', b, 0x2C)[0]
    for i in range(phnum):
        o = phoff + 32 * i
        p = list(struct.unpack_from('<8I', b, o))
        if p[0] == 1 and p[2] == POOL_VADDR:
            return o, p
    raise ValueError('no pool segment (run psp_pool first)')


def patch_boot(boot):
    """Append the hook to the pool, patch the call site and the cursor
    table. boot: BOOT.BIN after psp_vwf (the pool ends the file).
    Returns (bytes, info)."""
    import psp_pool
    import psp_vwf
    errs = check_names()
    if errs:
        raise ValueError('enchantment names (psp_menu.tsv):\n  ' + '\n  '.join(errs))
    b = bytearray(boot)
    got = list(struct.unpack_from('<5I', b, SITE + TEXT_BIAS))
    if got != RETAIL_SITE:
        raise ValueError('unexpected words at vaddr %#x (enchant rows already patched, or not a retail BOOT.BIN)' % SITE)
    cur = struct.unpack_from('<5H', b, CURSOR_TABLE + DATA_BIAS)
    if cur != RETAIL_CURSOR:
        raise ValueError('unexpected enchant cursor table %r' % (cur,))
    relocs = list(psp_pool._relocs(bytes(b)))
    relocated = {fo for _, fo, _ in relocs}
    if any(SITE + 4 * i + TEXT_BIAS in relocated for i in range(5)):
        raise ValueError('enchant row call site holds a relocated word')
    if struct.unpack_from('<I', b, LOWER_JUMP + TEXT_BIAS)[0] != jump_word(LOWER_BACK) \
            or (4, LOWER_JUMP + TEXT_BIAS, 0) not in relocs:
        raise ValueError('unexpected jump at vaddr %#x (arte list callback)' % LOWER_JUMP)
    off, p = _pool_header(b)
    if p[1] + p[4] != len(b) or p[4] != p[5]:
        raise ValueError('the pool segment must end the file')
    widths = psp_vwf.build_widths(b[SLOTTAB_FILE:SLOTTAB_FILE + 256])
    space = b[SLOTTAB_FILE + 0x20]
    if widths[2 * space + 1] != SPACE_PX:
        raise ValueError('the font 1 space is %d px, the padding expects %d' % (widths[2 * space + 1], SPACE_PX))
    pad = (-p[4]) % 16
    base = POOL_VADDR + p[4] + pad
    code, labels = hook_code(base, widths)
    lcode, llabels = lower_code(base + len(code))
    code += lcode
    b += bytes(pad) + code
    p[4] = p[5] = p[4] + pad + len(code)
    struct.pack_into('<8I', b, off, *p)
    words = site_words(labels['row'])
    psp_vwf.check_entries(bytes(b), words)
    for va, word in words:
        struct.pack_into('<I', b, va + TEXT_BIAS, word)
    struct.pack_into('<I', b, LOWER_JUMP + TEXT_BIAS, jump_word(llabels['lower']))
    table = cursor_table()
    struct.pack_into('<5H', b, CURSOR_TABLE + DATA_BIAS, *table)
    return bytes(b), {'hook_vaddr': hex(base), 'bytes': len(code), 'cursor': table,
                      'lower_block_size': '%#x x %#x' % LOWER_SIZE}


if __name__ == '__main__':
    print('cursor columns:', cursor_table())
    problems = check_names()
    print('\n'.join(problems) if problems else 'enchantment names: all fit')
    sys.exit(1 if problems else 0)
