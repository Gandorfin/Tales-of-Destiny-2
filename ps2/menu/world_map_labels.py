"""Relocate world-map labels into verified spare SCED string padding.

A label that does not fit the slot of its Japanese name is written into
unused bytes of the same script's string storage and the script's F8/u16
reference is pointed at the new copy. The containing PAK0 and SCED keep
their sizes; only the reference and the spare bytes change.

Each spare area is the zero padding that follows an existing string (the
"donor"): that string must be in place, in English, and must end directly
in front of the spare bytes, which proves the padding is where this table
says it is. patch_menu_text.py writes the donor before it calls apply().
"""
import struct
from collections import namedtuple
import md1text as M
import md1patch as P

# old: the label's own slot; instruction: the F8 that references it;
# member: the containing SCED; target: the spare storage; japanese and
# former: what the old slot may hold; donor: the string that ends at target-1
Label = namedtuple('Label', 'old instruction member target text japanese former donor')

CHOICES = ' Retry\n Quit\n Cancel\n'
RETRY = 'Try again?<03:00000000>\n Yes\n No\n'
LABELS = {
    '09028.pak0': [
        Label(0xFFE57, 0xFF005, 0xFD76B, 0x10055F, 'Laguna Ruins', 'ラグナ遺跡', ('Laguna',), CHOICES),
    ],
    '09032.pak0': [
        Label(0xFFF33, 0xFF267, 0xFDBDD, 0x10055E, 'Laguna Ruins', 'ラグナ遺跡', ('Laguna',), CHOICES),
        # the gate of the final dungeon: ten bytes of slot, twelve of name
        Label(0x1001BD, 0xFF63C, 0xFDBDD, 0x10032E, 'Atamoni Ovum', '神のたまご', ('Egg of God',), RETRY),
    ],
}


def find(name, offset):
    """The relocated label whose own slot is at this offset, or None."""
    for label in LABELS.get(name, ()):
        if label.old == offset:
            return label
    return None


def _apply_one(data, label):
    if data[label.member:label.member + 4] != b'SCED':
        raise ValueError('world-map SCED signature changed')
    text_start = label.member + struct.unpack_from('<I', data, label.member + 8)[0]
    old_rel, target_rel = label.old - text_start, label.target - text_start
    if data[label.instruction] != 0xF8:
        raise ValueError('world-map label instruction changed')
    reference = struct.unpack_from('<H', data, label.instruction + 1)[0]
    if reference not in (old_rel, target_rel):
        raise ValueError('world-map label reference changed')
    original = M.decode_at(data, label.old)
    if not original or original[0] not in (label.japanese, label.text) + label.former:
        raise ValueError('world-map original label changed')
    donor_start = label.target - len(P.encode(label.donor)) - 1
    donor = M.decode_at(data, donor_start)
    if not donor or donor[0] != label.donor or donor[1] != label.target - 1:
        raise ValueError('world-map spare-space donor changed')
    encoded = P.encode(label.text) + b'\0'
    occupied = bytes(data[label.target:label.target + len(encoded)])
    if occupied not in (bytes(len(encoded)), encoded):
        raise ValueError('world-map spare space is occupied')
    # No other script may address this previously unused storage.
    for at in range(label.member + 12, text_start - 2):
        if data[at] == 0xF8:
            rel = struct.unpack_from('<H', data, at + 1)[0]
            if target_rel <= rel < target_rel + len(encoded) and at != label.instruction:
                raise ValueError('world-map spare space has another reference')
    if reference == target_rel and occupied == encoded:
        return 0, 1
    # also reached when a later rewrite of the donor cleared the padding
    data[label.target:label.target + len(encoded)] = encoded
    struct.pack_into('<H', data, label.instruction + 1, target_rel)
    return 1, 0


def apply(data, name):
    """Return (changed, current) over the file's labels. Every label is
    checked on a copy first, so a rejected one leaves data untouched."""
    trial = bytearray(data)
    changed = current = 0
    for label in LABELS[name]:
        c, k = _apply_one(trial, label)
        changed += c
        current += k
    data[:] = trial
    return changed, current
