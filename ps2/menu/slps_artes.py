"""Battle cut-in names of the party's artes (the green banner in battle).

The arte table in SLPS_251.72 is a run of 28-byte records at 0xB7000..;
the last three words of a record are pointers (file offset + 0xFF000) to
the menu name, the reading, and the description.  The banner that flashes
up when a character uses an arte does not use either name pointer: it
shows the string that follows the reading (the next string after the
reading's terminator).  In the Japanese game that is the kanji name; the
2008 patch replaced it with English for 14 artes and left the kanji for
the other 27 because the slot is too small for the English names.

This step gives each of those records a new slot "reading NUL cut-in NUL"
with the cut-in text taken from the record's own menu name, so battle and
menu agree, and redirects the reading pointer to it.  Slots go into the
spare pool or into the room freed by another redirected record.  A record
whose following string is already plain ASCII is left alone, so the step
is safe to run again.
"""
import struct

BIAS = 0xFF000
TABLE = (0xB7000, 0xBA000)
STRIDE = 0x1C


def _lead(b):
    return 0x99 <= b <= 0x9F or 0xE0 <= b <= 0xE4


def _ascii_at(d, p):
    e = d.index(b'\0', p)
    s = d[p:e]
    if s and all(0x20 <= c < 0x7F for c in s):
        return s.decode('ascii')
    return None


def records(d):
    out = []
    o = TABLE[0]
    while o + STRIDE <= TABLE[1]:
        w = struct.unpack_from('<7L', d, o)
        if all(0x1F0000 <= v < 0x200000 for v in w[4:7]):
            out.append(o)
            o += STRIDE
        else:
            o += 4
    return out


def pending(d):
    """Records whose cut-in string is still Japanese:
    list of (record, reading, cutin, slot_start, slot_end)."""
    out = []
    for o in records(d):
        w = struct.unpack_from('<7L', d, o)
        p1, p2 = w[4] - BIAS, w[5] - BIAS
        reading = _ascii_at(d, p2)
        if reading is None:
            continue
        q = p2 + len(reading) + 1
        while d[q] == 0:
            q += 1
        if not _lead(d[q]):
            continue
        while d[q] != 0:
            q += 1
        while d[q] == 0:
            q += 1
        cutin = _ascii_at(d, p1) or reading
        out.append((o, reading, cutin, p2, q))
    return out


def apply(d, pool_start, pool_end):
    """-> (bytes, into_slots, into_pool, pool_left)."""
    pend = pending(d)
    data = bytearray(d)
    # every pending slot is dead once its pointer moves; any entry may use any slot
    slots = sorted(((s, e) for _, _, _, s, e in pend), key=lambda t: t[1] - t[0])
    for s, e in slots:
        data[s:e] = b'\0' * (e - s)
    entries = sorted(pend, key=lambda t: -(len(t[1]) + len(t[2])))
    pool = pool_start
    into_slots = into_pool = 0
    for o, reading, cutin, _, _ in entries:
        blob = reading.encode('ascii') + b'\0' + cutin.encode('ascii') + b'\0'
        home = None
        for i, (s, e) in enumerate(slots):
            if e - s >= len(blob):
                home = s
                del slots[i]
                into_slots += 1
                break
        if home is None:
            if pool + len(blob) > pool_end:
                raise RuntimeError('spare pool full while placing %r' % cutin)
            home = pool
            pool += len(blob)
            into_pool += 1
        data[home:home + len(blob)] = blob
        struct.pack_into('<L', data, o + 0x14, home + BIAS)
    return bytes(data), into_slots, into_pool, pool_end - pool


if __name__ == '__main__':
    print('slps_artes.py is not a command. It runs as step 3 of patch_slps_titles.py:\n'
          '    python ps2\\menu\\patch_slps_titles.py ps2\\PyTOD2\\SLPS_251.72')
