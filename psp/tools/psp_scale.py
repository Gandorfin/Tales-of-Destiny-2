#!/usr/bin/env python3
"""Shrink overflowing arte names with the game's own text-size control.

The arte grid lays each art's name in a fixed ~5-kanji cell. English names are
full-width and wider than the cell, so adjacent names collide ("SHADOW EDGE" +
"STONE ZAPPER" -> "SHADOW EDGETONE ZAPPER"). The engine has a native size
control: <size:000000XX> scales following text to XX/0x100 (0x100 = 100%).
The game itself ships strings that use it, e.g. <size:000000C0>Suspicious
<size:00000100> renders "Suspicious" at 0xC0/0x100 = 75%. So wrapping an arte
name in <size:000000C0>...<size:00000100> makes it render at 75% width and fit
the cell, using the engine's own opcode -- no font hack, no renderer-specific
byte tricks (unlike DTE). Because 0x05 is a control opcode, a renderer that
does not honor the scale still CONSUMES the tag (renders full size), so the
worst case is "no shrink", never garbage.

Scope is deliberately narrow: only the party arte names below, keyed by their
Japanese so the wrap can't hit an unrelated English string. Applying scale
globally is unsafe (it disturbs fixed-layout screens like the item list), so
this stays an explicit allow-list that a boot test can widen.
"""

SCALE = 0xC0            # 75%; the value the game itself uses (see docstring)

# Party arte names that overflow the arte-grid cell, keyed by JP (unique).
# Verified present as plain-English entries in psp_menu.tsv.
ARTE_NAMES_JP = {
    'クレイジーコメット', 'エクセキューション', 'リザレクション', 'ディバインセイバー',
    '雷牙衝', '影閃剣', '華連撃', '鏡影槍', 'プリズムフラッシャ', 'シャドウエッジ',
    'ストーンザッパー', 'アクアスパイク', 'ネガティブゲイト', 'グランヴァニッシュ',
    'ウィンドスラッシュ', 'フレイムドライブ', 'バーンストライク', 'スラストファング',
    'エアプレッシャー', 'デルタレイ', '神空割砕人', '爆灰鐘', '放墜鐘', '戦吼爆ッ破',
    '双打鐘', '霧氷翔', '雷神招', '割破爆走撃', '天翔弾', '風神招', '護法蓮', '流蓮弾',
    'インブレイスエンド', 'エンシェントノヴァ', 'フィアフルストーム', 'ヴォルテックヒート',
    'レイズデッド',
}


def _wrap(en):
    return '<size:%08X>%s<size:00000100>' % (SCALE, en)


def scale_english(jp, en):
    """Return en wrapped in the size control if jp is a scaled arte name and en
    is a plain string (no existing tags/newlines that a wrap would disturb)."""
    if jp in ARTE_NAMES_JP and '<' not in en and '{' not in en and '\n' not in en and en.strip():
        return _wrap(en)
    return en
