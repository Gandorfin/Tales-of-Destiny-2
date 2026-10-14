"""Replace the video of a PSP movie (.pmf, PSMF 0014) without touching its
timing.

A PMF is a 2048-byte header followed by 2048-byte MPEG program stream packs.
Every pack is either an audio pack (one ATRAC3plus packet, private stream 1)
or a video pack. The video is H.264 (Main profile, level 2.1, one reference
frame, no B frames) cut into navigation units: each unit starts at a key
frame with a pack holding a system header (0xBB), a navigation packet (0xBF)
and the first video packet, and ends with a short video packet padded to the
pack end (0xBE).

Navigation packet payload (big endian):
    01 E0, four u16 (pack offset, from the unit's first pack, of the pack that
    holds the last byte of each of the first four pictures), 4 zero bytes,
    u16 4 * pictures + 2, u16 pictures, then per picture u32: bit 23 set when
    the picture is a reference picture, low 23 bits = picture size in bytes
    (from its access unit delimiter to the next one).

Video packets carry PTS and DTS (DTS = PTS - one frame) when a picture
starts in them that is the unit's first picture or 16, 32, ... pictures
after it; the unit's first packet also carries the P-STD buffer extension.

rebuild() keeps the header, every audio pack, every pack header (SCR) and
every unit's pack slots exactly where they are and only lays new pictures
into the video slots of their unit, so the PSP sees the original timing.
Within a unit it follows the rules the original muxer follows: a picture
starts in a pack at most one second before its decode time, and the video
buffer the movie declares (P-STD extension) never overflows. Each new unit
must fit the slots of the original one; UnitOverflow names the ones that do
not. The original muxer also chose the SCRs, so rebuilding the original
pictures does not give the same bytes, but it gives the same pictures with
the same or better buffer figures (roundtrip, checked for all 13 movies).
"""
import bisect
import struct

PACK = 2048
FRAME = 3003  # 90 kHz ticks per frame at 30000/1001 fps
PTS_EVERY = 16
LEAD = 90000  # a picture is muxed at most one second before its decode time
# Units that cannot fit with the 1 s window (their pictures are sized
# differently from the original's, whose pack SCRs follow its own pictures)
# may start pictures a little earlier; the decoder buffer limit still holds.
RELAXED_LEADS = (99000, 108000, 117000, 135000)
MIN_MARGIN = 18000  # every picture must have arrived 0.2 s before its decode time
# Last resort for units the original filled with near-empty pictures (black
# frames) whose new pictures carry subtitle text: such a unit's first packs
# come too late for its larger pictures. The PSP player times pictures by
# their PTS and reads ahead, so these units may arrive late against the pack
# SCRs by up to 0.6 s; rebuild.late lists them for the boot test.
LATE_MARGINS = (0, -27000, -54000)
AUD = b'\x00\x00\x00\x01\x09'


def _ts(b):
    return ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


def _ts_bytes(prefix, v):
    return bytes([prefix << 4 | ((v >> 29) & 0x0E) | 1, (v >> 22) & 0xFF,
                  ((v >> 14) & 0xFE) | 1, (v >> 7) & 0xFF, ((v << 1) & 0xFE) | 1])


def parse(d):
    """{'header', 'packs': [{'head', 'items'}], ...} of a PMF file."""
    if d[:8] != b'PSMF0014':
        raise ValueError('not a PSMF 0014 file')
    off, size = struct.unpack_from('>II', d, 8)
    if off % PACK or size % PACK or off + size > len(d):
        raise ValueError('unexpected PSMF layout')
    packs = []
    for p in range(off, off + size, PACK):
        if d[p:p + 4] != b'\x00\x00\x01\xba':
            raise ValueError('no pack header at 0x%X' % p)
        q = p + 14 + (d[p + 13] & 7)
        items = []
        while q < p + PACK:
            if d[q:q + 3] != b'\x00\x00\x01':
                raise ValueError('bad packet at 0x%X' % q)
            sid = d[q + 3]
            n = struct.unpack_from('>H', d, q + 4)[0]
            it = {'sid': sid, 'raw': d[q:q + 6 + n]}
            if sid == 0xE0:
                hl = d[q + 8]
                it['payload'] = d[q + 9 + hl:q + 6 + n]
                if d[q + 7] & 0x80:
                    it['pts'] = _ts(d[q + 9:q + 14])
            items.append(it)
            q += 6 + n
        if q != p + PACK:
            raise ValueError('pack at 0x%X overruns' % p)
        packs.append({'head': d[p:p + 14 + (d[p + 13] & 7)], 'items': items})
    return {'header': d[:off], 'packs': packs, 'tail': d[off + size:]}


def pictures(es):
    """Split an H.264 stream with access unit delimiters into pictures."""
    starts = []
    i = es.find(AUD)
    while i != -1:
        starts.append(i)
        i = es.find(AUD, i + 5)
    if not starts or starts[0] != 0:
        raise ValueError('video does not start with an access unit delimiter')
    return [es[a:b] for a, b in zip(starts, starts[1:] + [len(es)])]


def is_reference(pic):
    p = pic.find(b'\x00\x00\x01', 5)
    while p != -1:
        t = pic[p + 3] & 31
        if t in (1, 5):
            return (pic[p + 3] >> 5) & 3 != 0
        p = pic.find(b'\x00\x00\x01', p + 3)
    raise ValueError('picture without a slice')


def is_idr(pic):
    p = pic.find(b'\x00\x00\x01', 5)
    while p != -1:
        t = pic[p + 3] & 31
        if t in (1, 5):
            return t == 5
        p = pic.find(b'\x00\x00\x01', p + 3)
    raise ValueError('picture without a slice')


def layout(movie):
    """Units of the original: [(first pack, end pack, first picture,
    picture count)], the video stream, the first PTS and the system header,
    P-STD extension bytes."""
    packs = movie['packs']
    es = bytearray()
    starts = []  # (pack, es offset) of each navigation unit
    sysraw = ext = None
    first_pts = None
    for k, pk in enumerate(packs):
        for it in pk['items']:
            if it['sid'] == 0xBF:
                starts.append((k, len(es)))
            elif it['sid'] == 0xBB:
                sysraw = it['raw']
            elif it['sid'] == 0xE0:
                raw = it['raw']
                if raw[7] & 0x01 and ext is None:
                    ext = raw[19:22]
                if first_pts is None and 'pts' in it:
                    first_pts = it['pts']
                es += it['payload']
    pics = pictures(bytes(es))
    offs, o = {}, 0
    for i, p in enumerate(pics):
        offs[o] = i
        o += len(p)
    units = []
    for n, (k, e) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else None
        first = offs[e]
        last = offs[starts[n + 1][1]] if n + 1 < len(starts) else len(pics)
        units.append([k, end, first, last - first])
    # the last unit ends after its last video pack
    last_video = max(k for k, pk in enumerate(packs) if any(it['sid'] == 0xE0 for it in pk['items']))
    units[-1][1] = last_video + 1
    return units, pics, first_pts, sysraw, ext


def _pes(sid_flags_hdr, payload):
    flags, hdr = sid_flags_hdr
    body = flags + bytes([len(hdr)]) + hdr + payload
    return b'\x00\x00\x01\xe0' + struct.pack('>H', len(body)) + body


def _padding(n):
    """A padding packet of n bytes in total (n >= 6)."""
    return b'\x00\x00\x01\xbe' + struct.pack('>H', n - 6) + b'\xff' * (n - 6)


def _nav(unit_pics, slot_of_end):
    n = len(unit_pics)
    four = [slot_of_end[j] for j in range(min(4, n))] + [0] * (4 - min(4, n))
    body = b'\x01\xe0' + struct.pack('>4H', *four) + b'\x00' * 4 + struct.pack('>HH', 4 * n + 2, n)
    for p in unit_pics:
        body += struct.pack('>I', (0x800000 if is_reference(p) else 0) | len(p))
    return b'\x00\x00\x01\xbf' + struct.pack('>H', len(body)) + body


class LateKeyFrame(OverflowError):
    """The unit's first picture cannot arrive in time: it needs fewer bytes
    (only part of the unit's first pack comes before its decode time)."""


class UnitOverflow(OverflowError):
    """Some navigation units do not fit their original packs. units lists
    them as (unit index, first picture, picture count, the key frame is the
    problem)."""

    def __init__(self, units):
        OverflowError.__init__(self, '%d unit(s) do not fit their original packs' % len(units))
        self.units = units


def _scr(head):
    """System clock reference of a pack header, in 90 kHz ticks."""
    b = head[4:10]
    return (((b[0] >> 3) & 7) << 30 | (b[0] & 3) << 28 | b[1] << 20 | ((b[2] >> 3) & 31) << 15
            | (b[2] & 3) << 13 | b[3] << 5 | b[4] >> 3)


def _lay_unit(offsets, heads, unit_pics, first_index, first_pts, sysraw, ext, caps=None, lead=LEAD,
              min_margin=MIN_MARGIN):
    """Pack bodies (without pack headers) for one unit's video packs.

    offsets[i] is the position of the unit's i-th video pack among all its
    packs (audio packs included), which is what the navigation packet counts.
    A pack only carries pictures that are decoded at most LEAD after its SCR;
    when the next picture is not due yet the packet ends and the pack is
    padded, as the original muxer does. caps[i], when given, is the most
    unit bytes that may have arrived after the i-th video pack (the decoder
    buffer limit)."""
    slots = len(offsets)
    n = len(unit_pics)
    es = b''.join(unit_pics)
    pic_start = []
    o = 0
    for p in unit_pics:
        pic_start.append(o)
        o += len(p)
    dts = [first_pts + (first_index + j - 1) * FRAME for j in range(n)]
    marked = {pic_start[j]: j for j in range(0, n, PTS_EVERY)}
    nav_len = 6 + 18 + 4 * n

    def due_end(t):
        j = 0
        while j < n and dts[j] <= t + lead:
            j += 1
        return pic_start[j] if j < n else len(es)

    def timestamps(j):
        pts = first_pts + (first_index + j) * FRAME
        return _ts_bytes(3, pts) + _ts_bytes(1, pts - FRAME)

    bodies = []
    end_slot = {}
    pos = 0
    k = 0
    while pos < len(es):
        if k >= slots:
            raise OverflowError('unit needs more than its %d video packs' % slots)
        first = k == 0
        room = PACK - len(heads[k])
        pre = sysraw + b'\x00' * nav_len if first else b''
        room -= len(pre)
        limit = due_end(_scr(heads[k]))
        if caps is not None:
            limit = min(limit, caps[k])
        if limit <= pos:
            if first:
                raise OverflowError('first picture of a unit is not due in its first pack')
            bodies.append(_padding(room))
            k += 1
            continue
        ts_len = 13 if first else 10
        cap_ts = min(room - 9 - ts_len, limit - pos)
        mark = next((m for m in sorted(marked) if pos <= m < pos + cap_ts), None)
        if first or mark is not None:
            # a PES timestamp belongs to the first picture that starts in it
            lead_pic = next(j for j in range(n) if pic_start[j] >= pos)
            hdr = timestamps(lead_pic) + (ext if first else b'')
            flags = b'\x81' + (b'\xc1' if first else b'\xc0')
        else:
            hdr, flags = b'', b'\x81\x00'
        chunk = es[pos:pos + min(room - 9 - len(hdr), limit - pos)]
        left = room - 9 - len(hdr) - len(chunk)
        if 0 < left < 6:  # too small for a padding packet: stuff the header
            body = pre + _pes((flags, hdr + b'\xff' * left), chunk)
        else:
            body = pre + _pes((flags, hdr), chunk) + (_padding(left) if left else b'')
        for j in range(n):
            e = pic_start[j] + len(unit_pics[j]) - 1
            if pos <= e < pos + len(chunk):
                end_slot[j] = offsets[k]
                if dts[j] - _scr(heads[k]) < min_margin:
                    raise (LateKeyFrame if j == 0 else OverflowError)('picture %d of the unit would arrive late' % j)
        bodies.append(body)
        pos += len(chunk)
        k += 1
    nav = _nav(unit_pics, end_slot)
    assert len(nav) == nav_len
    bodies[0] = sysraw + nav + bodies[0][len(sysraw) + nav_len:]
    return bodies


def unit_capacities(movie):
    """Video bytes each navigation unit can hold in its packs (headers,
    system header, navigation packet and PTS fields subtracted)."""
    packs = movie['packs']
    units, pics, first_pts, sysraw, ext = layout(movie)
    out = []
    for start, end, first, count in units:
        video = [s for s in range(start, end) if not any(it['sid'] == 0xBD for it in packs[s]['items'])]
        room = sum(PACK - len(packs[s]['head']) - 9 for s in video)
        room -= len(sysraw) + 6 + 18 + 4 * count + 13 + 10 * ((count - 1) // PTS_EVERY)
        out.append(room)
    return out


def rebuild(original, new_pics, allow_late=False):
    """New PMF bytes: the original with its pictures replaced by new_pics."""
    movie = parse(original)
    packs = movie['packs']
    units, old_pics, first_pts, sysraw, ext = layout(movie)
    if len(new_pics) != len(old_pics):
        raise ValueError('picture count %d != original %d' % (len(new_pics), len(old_pics)))
    out = bytearray(movie['header'])
    k = 0
    failed = []
    relaxed = []
    late = []
    # decoder buffer: bytes delivered minus pictures decoded must stay <= P_STD
    decoded_at = []  # (dts, bytes of pictures decoded by then)
    total = 0
    for i, p in enumerate(new_pics):
        total += len(p)
        decoded_at.append((first_pts + (i - 1) * FRAME, total))
    dts_list = [t for t, _ in decoded_at]
    delivered = 0
    for u, (start, end, first, count) in enumerate(units):
        while k < start:  # packs before the first unit (none in practice)
            out += _raw_pack(packs[k])
            k += 1
        video = [s for s in range(start, end) if not any(it['sid'] == 0xBD for it in packs[s]['items'])]
        heads = [packs[s]['head'] for s in video]
        unit_pics = new_pics[first:first + count]
        if not is_idr(unit_pics[0]):
            raise ValueError('unit %d does not start with a key frame' % u)
        caps = []
        for s in video:
            i = bisect.bisect_right(dts_list, _scr(packs[s]['head']))
            caps.append(buffer_size(ext) + (decoded_at[i - 1][1] if i else 0) - delivered)
        bodies = None
        late_key = False
        tiers = [(lead, MIN_MARGIN) for lead in (LEAD,) + RELAXED_LEADS]
        if allow_late:
            tiers += [(RELAXED_LEADS[-1], m) for m in LATE_MARGINS]
        for lead, margin in tiers:
            try:
                bodies = _lay_unit([s - start for s in video], heads, unit_pics, first, first_pts,
                                   sysraw, ext, caps, lead, margin)
                break
            except LateKeyFrame:
                late_key = True
                if not allow_late:
                    break
            except OverflowError:
                continue
        if bodies is None:
            failed.append((u, first, count, late_key))
            delivered += sum(len(p) for p in unit_pics)
            k = end
            continue
        if margin != MIN_MARGIN:
            late.append((u, margin))
        elif lead != LEAD:
            relaxed.append((u, lead))
        delivered += sum(len(p) for p in unit_pics)
        bodies += [_padding(PACK - len(heads[i])) for i in range(len(bodies), len(video))]
        by_slot = dict(zip(video, bodies))
        for s in range(start, end):
            out += packs[s]['head'] + by_slot[s] if s in by_slot else _raw_pack(packs[s])
        k = end
    if failed:
        raise UnitOverflow(failed)
    while k < len(packs):
        out += _raw_pack(packs[k])
        k += 1
    out += movie['tail']
    if len(out) != len(original):
        raise AssertionError('size changed')
    rebuild.relaxed = relaxed  # [(unit, lead)] of units that needed a wider window
    rebuild.late = late  # [(unit, margin)] of units allowed to arrive late (allow_late)
    return bytes(out)


def _raw_pack(pk):
    return pk['head'] + b''.join(it['raw'] for it in pk['items'])


def roundtrip(original):
    """Rebuild a movie with its own pictures: (same pictures, buffer stats of
    the original, buffer stats of the rebuild)."""
    _, pics, *_ = layout(parse(original))
    data = rebuild(original, pics)
    return layout(parse(data))[1] == pics, buffer_stats(original), buffer_stats(data)


P_STD = 0x175 * 1024  # usual video buffer size (P-STD extension 1E 61 75)


def buffer_size(ext):
    """Video buffer size declared by a P-STD extension (e.g. 1E 61 75)."""
    return ((ext[1] & 0x1F) << 8 | ext[2]) * (1024 if ext[1] & 0x20 else 128)


def buffer_stats(data):
    """Decoder view of a PMF: peak video buffer fill in bytes and the
    smallest margin in 90 kHz ticks between a picture's last byte arriving
    (its pack's SCR) and the picture's decode time, plus the buffer size the
    movie declares. A rebuilt movie must keep peak <= size and a positive
    margin."""
    movie = parse(data)
    units, pics, first_pts, sysraw, ext = layout(movie)
    ends = []
    o = 0
    for p in pics:
        o += len(p)
        ends.append(o)
    arrivals = []  # (time, cumulative bytes received)
    got = 0
    for pk in movie['packs']:
        t = _scr(pk['head'])
        for it in pk['items']:
            if it['sid'] == 0xE0:
                got += len(it['payload'])
                arrivals.append((t, got))
    margin = None
    j = 0
    for i, e in enumerate(ends):
        while arrivals[j][1] < e:
            j += 1
        m = first_pts + (i - 1) * FRAME - arrivals[j][0]
        margin = m if margin is None else min(margin, m)
    # fill = bytes received minus bytes of pictures already decoded, sampled at each arrival
    peak = 0
    i = 0
    for t, total in arrivals:
        while i < len(ends) and first_pts + (i - 1) * FRAME <= t:
            i += 1
        peak = max(peak, total - (ends[i - 1] if i else 0))
    return {'peak': peak, 'margin': margin, 'size': buffer_size(ext)}
