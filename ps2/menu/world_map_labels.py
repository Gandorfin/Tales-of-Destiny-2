"""Relocate two world-map labels into verified spare SCED string padding.

The containing PAK0 and SCED retain their sizes. Only the label's F8/u16
reference and unused padding after an existing choice string are changed.
"""
import struct
import md1text as M
import md1patch as P

# file: (old string, F8 instruction, containing SCED, spare string storage)
LABELS = {
    '09028.pak0': (0xFFE57, 0xFF005, 0xFD76B, 0x10055F),
    '09032.pak0': (0xFFF33, 0xFF267, 0xFDBDD, 0x10055E),
}
DONOR = ' Retry\n Quit\n Cancel\n'
TEXT = 'Laguna Ruins'


def apply(data, name):
    """Return (changed, current); reject unexpected references or occupied space."""
    old, instruction, member, target = LABELS[name]
    if data[member:member + 4] != b'SCED':
        raise ValueError('world-map SCED signature changed')
    text_start = member + struct.unpack_from('<I', data, member + 8)[0]
    old_rel, target_rel = old - text_start, target - text_start
    if data[instruction] != 0xF8:
        raise ValueError('world-map label instruction changed')
    reference = struct.unpack_from('<H', data, instruction + 1)[0]
    if reference not in (old_rel, target_rel):
        raise ValueError('world-map label reference changed')
    original = M.decode_at(data, old)
    if not original or original[0] not in ('ラグナ遺跡', 'Laguna', TEXT):
        raise ValueError('world-map original label changed')
    donor_start = target - len(P.encode(DONOR)) - 1
    donor = M.decode_at(data, donor_start)
    if not donor or donor[0] != DONOR or donor[1] != target - 1:
        raise ValueError('world-map spare-space donor changed')
    encoded = P.encode(TEXT) + b'\0'
    occupied = bytes(data[target:target + len(encoded)])
    if occupied not in (bytes(len(encoded)), encoded):
        raise ValueError('world-map spare space is occupied')
    # No other script may address this previously unused storage.
    for at in range(member + 12, text_start - 2):
        if data[at] == 0xF8:
            rel = struct.unpack_from('<H', data, at + 1)[0]
            if target_rel <= rel < target_rel + len(encoded) and at != instruction:
                raise ValueError('world-map spare space has another reference')
    if reference == target_rel:
        if occupied != encoded:
            raise ValueError('world-map relocated label is damaged')
        return 0, 1
    data[target:target + len(encoded)] = encoded
    struct.pack_into('<H', data, instruction + 1, target_rel)
    return 1, 0
