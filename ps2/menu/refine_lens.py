"""Give the refine screen its labelled lens line ("A:0 B:0/100").

The refine module 06802.md1 (and its LZSS copy 06821.md1, the one the game
loads for the Refine screen) formats the lens line with

    lui   v1, 0x2A
    addiu a1, v1, 0x219E        # 0xE1C: 0x2A219E = module + 0x669E
    jal   sprintf

0x669E is the English string table the 2008 patch appended to the module
("Result A", "Result B", "Lens", "-", "A%d,B%d/%3d", "%d/%3d", ...), which
leaves no room for a longer format. The Japanese table it replaced is dead;
its lens slot at 0x63A0 holds "A:%d B:%d/%3d" since menu_translations.csv
row 06802 0x63A0 (PR 106), but nothing read it, so every release showed
"A0,B0/100". The fix points the addiu at 0x63A0 (0x2A1EA0).
"""
import struct

BASE = 0x29BB00                 # load address of the module
ADDIU = 0xE1C                   # addiu a1, v1, <format>
OLD = 0x669E                    # the 2008 format "A%d,B%d/%3d"
NEW = 0x63A0                    # the translated format "A:%d B:%d/%3d"
TEXT = b'A:%d B:%d/%3d\x00'


def _word(target):
    return 0x24650000 | ((BASE + target) & 0xFFFF)


def apply(data):
    """Return (changed, current); raise ValueError on an unknown layout."""
    if len(data) < OLD + 12 or bytes(data[OLD:OLD + 12]) != b'A%d,B%d/%3d\x00':
        raise ValueError('refine lens: the 2008 format string is missing')
    if bytes(data[NEW:NEW + len(TEXT)]) != TEXT:
        raise ValueError('refine lens: 0x%X does not hold %r yet' % (NEW, TEXT))
    word = struct.unpack_from('<L', data, ADDIU)[0]
    if word == _word(NEW):
        return 0, 1
    if word != _word(OLD):
        raise ValueError('refine lens: unexpected instruction 0x%08X at 0x%X' % (word, ADDIU))
    struct.pack_into('<L', data, ADDIU, _word(NEW))
    return 1, 0
