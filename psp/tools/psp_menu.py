#!/usr/bin/env python3
"""Patch menu strings in BOOT.BIN to English (in-place, v1).

3,808 menu strings live in BOOT.BIN .rodata/.data; ~55% have a reuse
translation from the PS2 work (psp_menu.tsv). Because kanji encode to 2
bytes, ~70% of those fit in the original slot, so v1 overwrites each
NUL-terminated occurrence in place (NUL-padded) and leaves the longer ones
Japanese. Overflow relocation (pool + data-pointer rewrite) is a later pass;
~80% of strings do have a rewritable data pointer.
"""
import os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_text

TABLE = os.path.join(HERE, 'psp_menu.tsv')


def load_table(path=TABLE):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding='utf-8'):
        if line.startswith('#'):
            continue
        p = line.rstrip('\n').split('\t')
        if len(p) >= 2:
            out.append((p[0].replace('\\n', '\n'), p[1].replace('\\n', '\n')))
    bad = [jp for jp, en in out if pinned_code_moved(jp, en)]
    if bad:
        raise SystemExit('psp_menu.tsv: a <0A:..> code must keep its retail '
                         'byte position: ' + ', '.join(map(repr, bad)))
    return out


PINNED_CODES = (0x0A,)


def _codes(b):
    """(offset, code, argument) of every argument code in an encoded string."""
    out, i = [], 0
    while i < len(b):
        c = b[i]
        if c in ARG_CODES:
            out.append((i, c, bytes(b[i + 1:i + 5])))
            i += 5
        elif c >= 0x80:
            i += 2
        else:
            i += 1
    return out


def pinned_code_moved(jp, en):
    """True if a <0A:..> code sits at another byte offset in the English.
    The dungeon exit banner "<button:35> <0A:0>を出る" (BOOT 0x1D57B0, the
    0A code inserts the place name) hung the game in PSP 0.3.3/0.3.4 when
    the English moved the code to the end ("Leave <0A:0>"), also with text
    after it; the game needs it at byte 6 as in retail. Colour, name and size
    codes move freely."""
    try:
        cj = [c for c in _codes(encode_keys(jp)[0]) if c[1] in PINNED_CODES]
        ce = [c for c in _codes(encode_en(en)) if c[1] in PINNED_CODES]
    except Exception:
        return False
    return cj != ce


def encode_en(en):
    """Encode an English menu string. The full-width space U+3000 must be the
    BOOT code 0x9940 (what every retail menu string uses, a blank cell in both
    fonts); the TBL's own entry for it is a filler code (0xE499) that the menu
    renderers draw as a garbage tile (Battle Memo indent, tactics lines)."""
    return psp_text.encode_line(en.replace('　', '{99}{40}'))


def encode_keys(jp):
    """Byte forms a Japanese key can have in BOOT.BIN. Retail menu strings
    write the full-width space U+3000 as 0x9940, the TBL encodes it as the
    filler 0xE499; a key with a space was never found before this rule
    (the shop names, scene titles and others stayed Japanese until 0.3.2)."""
    out = [psp_text.encode_line(jp.replace('　', '{99}{40}'))]
    if '　' in jp:
        out.append(psp_text.encode_line(jp))
    return out


ARG_CODES = range(0x03, 0x11)   # control codes followed by a 4-byte argument


def string_start(b, idx):
    """True if a string can start at idx: at the file start, or after a NUL
    that terminates the previous string. The NUL bytes at the end of a
    control code's 4-byte argument (<button:00000036> = 09 36 00 00 00) are
    not terminators: the text after them is the middle of a record. Taking
    them for one patched the fragment やめる inside the shop confirmation in
    place, after which the full record never matched (the button legends
    showed 決定 / Back the same way)."""
    if idx == 0:
        return True
    if b[idx - 1] != 0:
        return False
    if idx >= 5 and b[idx - 5] in ARG_CODES and not (idx >= 6 and b[idx - 6] in ARG_CODES):
        return False
    return True


def referenced_offsets(boot):
    """File offsets the executable points at: targets of 32-bit data pointers
    and of lui/addiu address pairs. A string placed right after binary data
    (リファイン after a float at 0x1C3A8C) has no NUL in front of it but is
    still a string start."""
    import psp_pool
    if boot[:4] != b'\x7fELF':
        return set()               # synthetic test data, no relocation table
    targets = set(psp_pool._reloc_pointer_map(boot))
    targets.update(t for _, los in psp_pool._code_pair_groups(boot) for _, t, _ in los)
    return {psp_pool._vaddr_to_file(v) for v in targets}


# Strings patched at one address only, because the same text elsewhere needs
# another English. The battle result table at 0x1F2390 builds the enchant
# line from fragments ("<name>" の エンチャント スキル|スペル <enchant> を習得);
# with every fragment in English it read "Loni:EnchantSkillIncrease Accu"
# and clipped. Like the PS2 (08055.md1) the fragments go empty and の becomes
# ": ", so the line reads "Loni: Increase Accuracy".
ADDRESSED = [
    (0x199F98, 'エンチャント', ''),
    (0x199FA8, 'スキル', ''),
    (0x199FB0, 'スペル', ''),
    (0x199FB8, 'を習得', ''),
    (0x199FD8, 'の', ': '),
    # skill cost line under an Enchant/Skill description, built from
    # SPを %d 、 TPを %d 消費 。 -> " SP 12, TP 5 used." (SPを and TPを are
    # Shift-JIS, see SJIS_ADDRESSED; 消費 is a table row, pooled)
    (0x19BEE8, '。', '.'),
    (0x19BEF0, '、', ','),
]


# Added Arte (追加特技) banners: names inside the battle scripts compiled into
# BOOT.BIN (file 0x1EE4A2..0x1EEE6B, 14 names as on the PS2), opcode 0A, an
# argument byte (0x00, 0x04, 0x06 or 0xFF), then the
# name inline and NUL terminated, like the PS2 ENd scripts. Nothing points at
# them and the bytecode goes on after the NUL, so the English must have the
# exact Japanese byte length (8 bytes, space padded). Names follow the PS2
# banners (08055 literals); 霧氷鎚閃 takes the name of its PS2 twin 霧氷槍閃.
INLINE_BANNERS = [
    (0x1EE4A2, '蒼破追蓮', 'Pursuit '),
    (0x1EE50B, '雷神光燐', 'Kourin  '),
    (0x1EE57F, '散葉枯葉', 'Wither  '),
    (0x1EE639, '空翔裂風', 'Windrend'),
    (0x1EE762, '閃光翔墜', 'Skyfall '),
    (0x1EE80C, '爆炎連焼', 'Hellfire'),
    (0x1EE9C5, '爆灰猛追', 'Stampede'),
    (0x1EEAB5, '放墜砲墜', 'Dropshot'),
    (0x1EEB2A, '双打連蹴', 'Renshuu '),
    (0x1EEBAC, '霧氷鎚閃', 'Frostray'),
    (0x1EED1F, '幻影回帰', 'Recall  '),
    (0x1EEDBB, '双連衝破', 'Impact  '),
    (0x1EEE19, '飛連双閃', 'Twin Ray'),
    (0x1EEE6B, '月閃虚崩', 'Moonfall'),
]


# Shift-JIS strings (not the game's TBL encoding): the save title, the save
# detail line and the Memory Stick dialogs, which the game hands to the
# system save and message dialogs. In place only; the format specifiers keep
# their order.
SJIS_ADDRESSED = [
    (0x19865C, 'ロードを中止しますか？', 'Cancel loading?'),
    (0x198674, 'セーブを中止しますか？', 'Cancel saving?'),
    (0x19868C, '削除を中止しますか？', 'Cancel deleting?'),
    (0x1986CC, '中断データ', 'Suspend'),
    (0x1986D8, 'セーブデータ', 'Save data'),
    (0x19874C, '中断:', 'Susp:'),
    (0x198758, 'ガルド %s／レンズ %3d／クリア %2d', 'Gald %s / Lens %3d / Clears %2d'),
    (0x1DFAC8, 'テイルズ オブ デスティニー２', 'Tales of Destiny 2'),
    (0x19BED8, 'SPを', ' SP '),         # skill cost line, see ADDRESSED
    (0x19BEE0, 'TPを', ' TP '),
    (0x1DFAE8, '新規データ', 'New Data'),
    (0x1DFAF4, 'ゲームを中断しますか？\n（中断データは、\n　１つのメモリースティックTMに\n　１つしか作成できません）\n　\n'
               '中断セーブが完了したら、\nタイトル画面に戻ります',
     'Suspend the game?\n(Only one suspend save fits\n on a Memory Stick.)\n\nAfter suspending, you return\nto the title screen.'),
    (0x1DFB8C, 'メモリースティックTMが見つかりません', 'No Memory Stick found.'),
    (0x1DFBB4, 'メモリースティックTMのアクセスに失敗しました', 'Could not access the Memory Stick.'),
    (0x1DFBE4, 'メモリースティックTMの空き容量が不足しています', 'Not enough free space on the Memory Stick.'),
    (0x1DFC14, '本タイトルには\n・セーブデータ　%uKB\n・中断データ　　%uKB\nの空き容量(合計　%uKB以上)が必要です',
     'This game needs free space:\n save data %uKB\n suspend data %uKB\n(%uKB or more in total)'),
    (0x1DFC74, 'このままゲームを開始しますか？', 'Start the game anyway?'),
    (0x1DFC94, 'メモリースティックTMの空き容量が不足しています\n\n%s作成には\n%uKB以上の空き容量が必要です\n\n不要なセーブデータを削除しますか？',
     'Not enough space on the\nMemory Stick.\n\n%s needs %uKB or more\nof free space.\n\nDelete unneeded save data?'),
    (0x1DFD1C, '%s\n\n%s作成に必要な\n%uKB以上の空き容量のある\nメモリースティックTMを差して下さい',
     '%s\n\nFor %s, insert a Memory\nStick with %uKB or more free.'),
    (0x1DFD6C, 'ロード画面に移りますか？\n（ロードを実行すると、\n　現在のゲーム進行は失われます）',
     'Go to the load screen?\n(Loading loses your\n current game progress.)'),
]


# Refine prefixes (psp_refine.tsv). The table at file 0x21A678 holds per
# enchant six pointers: the effect line, then five prefixes, all strings in
# REFINE_AREA. A refined item's name is built at display time: strcpy of the
# prefix, then the item name right behind it (0xECEA4), so the English
# prefix carries its own trailing space ("Rune Axe", not "RuneAxe"). Patched
# by address, because the same katakana words are other things elsewhere
# (マスター is the Bartender NPC, プリースト the Priestess, ナイツ...). A
# prefix whose English with the space is longer than the Japanese goes to
# the pool by address (psp_pool.relocate_menu, refine_prefixes on the boot it
# gets); the key based passes leave every prefix address alone.
REFINE_TABLE = os.path.join(HERE, 'psp_refine.tsv')
REFINE_AREA = (0x1A23C8, 0x1A4190)
_KATAKANA = set('ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノ'
                'ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴー・')


def load_refine(path=REFINE_TABLE):
    out = {}
    for line in open(path, encoding='utf-8'):
        if line.startswith('#') or not line.strip():
            continue
        p = line.rstrip('\n').split('\t')
        out[p[0]] = p[1].strip() + ' '
    return out


def refine_prefixes(boot, table=None):
    """[(file offset, japanese, english with the space)] for every prefix of
    REFINE_AREA that is still Japanese (katakana only) in this boot."""
    if boot[:4] != b'\x7fELF' or len(boot) < REFINE_AREA[1]:
        return []              # synthetic test data
    table = load_refine() if table is None else table
    out = []
    p, end = REFINE_AREA
    while p < end:
        if boot[p] == 0:
            p += 1
            continue
        e = boot.index(b'\0', p)
        try:
            s = psp_text.decode_string(boot, p)
        except Exception:
            s = ''
        if s and set(s) <= _KATAKANA and s in table:
            out.append((p, s, table[s]))
        p = e + 1
    return out


# Code changes by address: (file offset, retail word, new word, why).
CODE_PATCHES = [
    # Save list detail line "Reala    r Lv:114" (playtest tab 13). 0x169E94
    # copies the party name into a 13 byte field (record +1..+0xD, level at
    # +0xE) and pads it with full-width spaces two bytes at a time while the
    # write pointer is below record +0xC. Japanese names are even byte
    # lengths; an odd ASCII name (Reala, Judas: 5 bytes) makes the last pair
    # land on +0xC/+0xD and the NUL on +0xE, which the level byte then
    # overwrites (114 = 'r'), so the name ran into the level. The bound
    # +0xB keeps even names exactly as retail and stops odd ones one pair
    # earlier (NUL at +0xC).
    (0x16A020, 0x2625000C, 0x2625000B, 'addiu $a1, $s1, 0xc -> 0xb (save detail name padding)'),
]


def patch_code(b, st):
    import struct
    for fo, old, new, _ in CODE_PATCHES:
        w = struct.unpack_from('<I', b, fo)[0]
        if w == old:
            struct.pack_into('<I', b, fo, new)
            st['code'] += 1
        elif w != new:
            st['code_skipped'] += 1


def patch_addressed(b, st):
    patch_code(b, st)
    for fo, jp, en in refine_prefixes(bytes(b)):
        jb, eb = encode_keys(jp)[0], encode_en(en)
        if len(eb) <= len(jb) and bytes(b[fo:fo + len(jb) + 1]) == jb + b'\x00':
            b[fo:fo + len(jb)] = eb + b'\x00' * (len(jb) - len(eb))
            st['refine'] += 1
        else:
            st['refine_to_pool'] += 1
    for fo, jp, en in SJIS_ADDRESSED:
        jb, eb = jp.encode('cp932'), en.encode('ascii')
        if bytes(b[fo:fo + len(jb) + 1]) != jb + b'\x00' or len(eb) > len(jb):
            st['addressed_skipped'] += 1
            continue
        b[fo:fo + len(jb)] = eb + b'\x00' * (len(jb) - len(eb))
        st['addressed'] += 1
    for fo, jp, en in ADDRESSED:
        jb, eb = encode_keys(jp)[0], encode_en(en)
        if bytes(b[fo:fo + len(jb) + 1]) != jb + b'\x00' or len(eb) > len(jb):
            st['addressed_skipped'] += 1
            continue
        b[fo:fo + len(jb)] = eb + b'\x00' * (len(jb) - len(eb))
        st['addressed'] += 1
    for fo, jp, en in INLINE_BANNERS:
        jb, eb = encode_keys(jp)[0], encode_en(en)
        if bytes(b[fo - 2:fo - 1]) != b'\x0a' or bytes(b[fo:fo + len(jb) + 1]) != jb + b'\x00' \
                or len(eb) != len(jb):
            st['banner_skipped'] += 1
            continue
        b[fo:fo + len(jb)] = eb
        st['banner'] += 1


def patch_menu(boot, table=None):
    """boot bytes -> patched bytes; returns (bytes, stats)."""
    if table is None:
        table = load_table()
    refs = referenced_offsets(boot)
    b = bytearray(boot)
    st = collections.Counter()
    if boot[:4] == b'\x7fELF':
        patch_addressed(b, st)
    # prefixes that did not fit stay Japanese here for the pool
    protected = {fo for fo, _, _ in refine_prefixes(bytes(b))} if boot[:4] == b'\x7fELF' else set()
    # longest keys first: a whole record is patched before any shorter key
    # that also occurs inside it
    for jp, en in sorted(table, key=lambda t: -len(t[0])):
        try:
            keys = encode_keys(jp)
            eb = encode_en(en)
        except Exception:
            st['encode_error'] += 1
            continue
        jb = keys[0]
        if not jb or len(eb) > len(jb):
            st['overflow_skipped'] += 1
            continue
        hit = 0
        for jb in keys:
            pad = jb + b'\x00'  # the stored string is NUL-terminated
            rep = eb + b'\x00' * (len(jb) - len(eb)) + b'\x00'
            i = 0
            while True:
                idx = b.find(pad, i)
                if idx < 0:
                    break
                i = idx + 1
                if idx in protected:
                    continue
                if string_start(b, idx) or idx in refs:
                    b[idx:idx + len(pad)] = rep
                    hit += 1
        if hit:
            st['patched'] += 1
            st['occurrences'] += hit
        else:
            st['not_found'] += 1
    b, st['fullwidth_to_ascii'] = fullwidth_to_ascii(bytes(b))
    return b, st


FULLWIDTH = ('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'
             '０１２３４５６７８９－．／：！？（）＆＋％＝，')


def _fullwidth_codes():
    """{2-byte code: ASCII byte} for the full-width Latin characters, plus
    the menu full-width space 0x9940."""
    out = {b'\x99\x40': b' '}
    for k, v in psp_text.TBL.items():
        if len(v) == 1 and v in FULLWIDTH:
            out[int(k).to_bytes(2, 'big')] = bytes([ord(v) - 0xFEE0])
    return out


STRING_AREAS = ((0x194840, 0x1DCCB0), (0x1DCD00, 0x29FB7C))   # .rodata, .data (file offsets)
MAX_LABEL = 16


def fullwidth_to_ascii(boot, areas=STRING_AREAS):
    """Rewrite every standalone string (NUL before and after) that consists
    only of full-width Latin letters, digits, punctuation and spaces as
    ASCII, in place (ASCII is half the bytes, so it always fits).

    Why: the variable width font gives ASCII proportional Latin glyphs, and
    full-width codes share those glyph cells but keep a full cell advance,
    so labels such as ＮＥＷ　ＧＡＭＥ, ＨＰ, ＧＲＡＤＥ would show narrow
    letters with wide gaps. As ASCII they take the proportional path.
    Returns (bytes, number of strings)."""
    codes = _fullwidth_codes()
    b = bytearray(boot)
    n = 0
    for start, end in areas:
        end = min(end, len(b))
        i = max(start, 1)
        while i < end - 2:
            if b[i - 1] != 0:
                i += 1
                continue
            j, out = i, bytearray()
            while j + 1 < end and bytes(b[j:j + 2]) in codes:
                out += codes[bytes(b[j:j + 2])]
                j += 2
            alnum = sum(1 for c in out if 48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122)
            # longer runs are data (the name entry keyboard's alphabet), not labels
            if j < end and b[j] == 0 and 2 <= alnum and len(out) <= MAX_LABEL:
                b[i:j] = bytes(out) + bytes(j - i - len(out))
                n += 1
                i = j
            else:
                i += 1
    return bytes(b), n


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    out, st = patch_menu(open(src, 'rb').read())
    open(dst, 'wb').write(out)
    print('menu patch:', dict(st))
