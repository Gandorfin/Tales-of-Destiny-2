"""Field messages in SLPS_251.72 that no other step translates.

Step 6 of patch_slps_titles.py. The strings below are built by code (lui /
addiu pairs, no pointer in the data), so they can only change in place,
within the Japanese byte length; the control codes are kept byte for byte.

* 0xCFCCE: the Info box after a skit that gives a title, for example
  "Kyleは / 称号「Swordian Master」を得ました" (reported on 1.3.5 after
  the skit "Disposing of Dymlos 1"). 0x15 30 1C C0 prints the character
  name, 0x16 A0 00 08 30 18 CA C0 the title name; 0x01 is the line break.
* 0xCFCF0: the same box when the whole party gets titles
  ("<name>たちは称号を得ました").

apply() accepts the Japanese or the English bytes at each offset (re-running
is safe) and refuses anything else.
"""

NAME = bytes.fromhex('15301cc0')
TITLE = bytes.fromhex('16a0000830 18cac0'.replace(' ', ''))

ENTRIES = [
    # (offset, Japanese bytes with the terminator, English without it)
    (0xCFCCE,
     bytes.fromhex('15301cc099a1019dc59bc499c216a000083018cac099c399c49d5499b09989999100'),
     NAME + b' got\x01the title "' + TITLE + b'"'),
    (0xCFCF0,
     bytes.fromhex('15301cc09991999399a19dc59bc499c49d5499b09989999100'),
     NAME + b"'s party got titles"),
]


class MessageError(Exception):
    pass


def english(old, new):
    """New text padded with zeros to the old length (terminator included)."""
    if len(new) + 1 > len(old):
        raise MessageError('English longer than the Japanese slot')
    return new + bytes(len(old) - len(new))


def apply(src):
    """-> (bytes, number of messages changed)."""
    d = bytearray(src)
    changed = 0
    for off, old, new in ENTRIES:
        want = english(old, new)
        got = bytes(d[off:off + len(old)])
        if got == want:
            continue
        if got != old:
            raise MessageError('unexpected bytes at file 0x%X: %s' % (off, got.hex()))
        d[off:off + len(old)] = want
        changed += 1
    return bytes(d), changed
