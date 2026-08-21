"""LZSS / LZSS+RLE codec used by the PS2 Tales games ("comptoe" format).

Pure Python port of soywiz's complib (LGPL, tales-tra.com), so the menu
tools can open and rebuild the compressed modules inside the .pak3
containers without needing comptoe.exe.

Stream format: 1 byte version (1 = LZSS, 3 = LZSS+RLE), 4 bytes LE packed
length, 4 bytes LE unpacked length, then the data.
"""
import struct

N = 0x1000
NIL = N
MF = 0x12
MAX_DUP = 0x100 + 0x12


def _text_buf():
    buf = bytearray(N + MF - 1)
    p = 0
    for n in range(0x100):
        buf[p] = buf[p + 2] = buf[p + 4] = buf[p + 6] = n
        buf[p + 1] = buf[p + 3] = buf[p + 5] = buf[p + 7] = 0
        p += 8
    for n in range(0x100):
        buf[p] = buf[p + 2] = buf[p + 4] = buf[p + 6] = n
        buf[p + 1] = buf[p + 3] = buf[p + 5] = 0xFF
        p += 7
    while p != N:
        buf[p] = 0
        p += 1
    return buf


def _params(version):
    if version == 1:
        return 0x12, 2
    if version == 3:
        return 0x11, 2
    raise ValueError("unknown compression version %r" % version)


def decode(data, version, outl):
    """Decode `data` (payload without the 9-byte header) to `outl` bytes."""
    F, T = _params(version)
    buf = _text_buf()
    out = bytearray()
    r = N - F
    ip = 0
    n = len(data)
    flags = 0
    while len(out) < outl:
        flags >>= 1
        if (flags & 0x100) == 0:
            if ip >= n:
                break
            flags = data[ip] | 0xFF00
            ip += 1
        if flags & 1:
            if ip >= n:
                break
            c = data[ip]
            ip += 1
            out.append(c)
            buf[r] = c
            r = (r + 1) & (N - 1)
            continue
        if ip + 1 >= n:
            break
        i = data[ip]
        j = data[ip + 1]
        ip += 2
        i |= (j & 0xF0) << 4
        j = (j & 0x0F) + T
        if version == 1 or j < F:
            for k in range(j + 1):
                c = buf[(i + k) & (N - 1)]
                out.append(c)
                buf[r] = c
                r = (r + 1) & (N - 1)
            continue
        if i < 0x100:
            if ip >= n:
                break
            j = data[ip]
            ip += 1
            i += F + 1
        else:
            j = i & 0xFF
            i = (i >> 8) + T
        for k in range(i + 1):
            out.append(j)
            buf[r] = j
            r = (r + 1) & (N - 1)
    return bytes(out[:outl])


def unpack(blob):
    """Decode a full comptoe stream (with header). Returns bytes."""
    version = blob[0]
    inl, outl = struct.unpack_from("<LL", blob, 1)
    return decode(blob[9:9 + inl], version, outl)


def is_packed(blob):
    return len(blob) > 9 and blob[0] in (1, 3) and struct.unpack_from("<L", blob, 1)[0] == len(blob) - 9


class _Encoder:
    def __init__(self, version):
        self.F, self.T = _params(version)
        self.version = version
        self.buf = _text_buf()
        self.lson = [NIL] * (N + 1)
        self.rson = [NIL] * (N + 257)
        self.dad = [NIL] * (N + 1)
        self.match_position = 0
        self.match_length = 0

    def insert(self, r):
        buf, lson, rson, dad, F = self.buf, self.lson, self.rson, self.dad, self.F
        cmp = 1
        p = N + 1 + buf[r]
        rson[r] = lson[r] = NIL
        self.match_length = 0
        while True:
            if cmp >= 0:
                if rson[p] != NIL:
                    p = rson[p]
                else:
                    rson[p] = r
                    dad[r] = p
                    return
            else:
                if lson[p] != NIL:
                    p = lson[p]
                else:
                    lson[p] = r
                    dad[r] = p
                    return
            i = 1
            while i < F:
                cmp = buf[r + i] - buf[p + i]
                if cmp != 0:
                    break
                i += 1
            if i > self.match_length:
                self.match_position = p
                self.match_length = i
                if i >= F:
                    break
        dad[r] = dad[p]
        lson[r] = lson[p]
        rson[r] = rson[p]
        dad[lson[p]] = r
        dad[rson[p]] = r
        if rson[dad[p]] == p:
            rson[dad[p]] = r
        else:
            lson[dad[p]] = r
        dad[p] = NIL

    def delete(self, p):
        lson, rson, dad = self.lson, self.rson, self.dad
        if dad[p] == NIL:
            return
        if rson[p] == NIL:
            q = lson[p]
        elif lson[p] == NIL:
            q = rson[p]
        else:
            q = lson[p]
            if rson[q] != NIL:
                while rson[q] != NIL:
                    q = rson[q]
                rson[dad[q]] = lson[q]
                dad[lson[q]] = dad[q]
                lson[q] = lson[p]
                dad[lson[p]] = q
            rson[q] = rson[p]
            dad[rson[p]] = q
        dad[q] = dad[p]
        if rson[dad[p]] == p:
            rson[dad[p]] = q
        else:
            lson[dad[p]] = q
        dad[p] = NIL


def encode(data, version=3):
    """Encode `data`; returns the payload (without header)."""
    e = _Encoder(version)
    F, T = e.F, e.T
    buf = e.buf
    out = bytearray()
    n = len(data)
    ip = 0          # insp
    ipb = 0         # inspb (position of the byte at text_buf[r])
    iplb = 0        # insplb
    code_buf = bytearray(1 + 8 * 5)
    code_buf_ptr = 1
    mask = 1
    s = 0
    r = N - F
    length = 0
    while length < F and ip < n:
        buf[r + length] = data[ip]
        ip += 1
        length += 1
    if length == 0:
        return bytes(out)
    for i in range(1, F + 1):
        e.insert(r - i)
    e.insert(r)
    dup_match_length = 0
    while length > 0:
        if version >= 3:
            if iplb - ipb <= 0:
                iplb = ipb + 1
                while iplb < n and data[iplb] == data[ipb]:
                    iplb += 1
            dup_match_length = iplb - ipb
        if e.match_length > length:
            e.match_length = length
        if version >= 3 and dup_match_length > MAX_DUP:
            dup_match_length = MAX_DUP
        if version >= 3 and dup_match_length > (T + 1) and dup_match_length >= e.match_length:
            if dup_match_length >= (n - ip):
                dup_match_length -= 1
        else:
            if e.match_length >= (n - ip):
                e.match_length -= 1
        if version >= 3 and dup_match_length > (T + 1) and dup_match_length >= e.match_length:
            e.match_length = dup_match_length
            e.match_position = r
            if e.match_length <= 0x12:
                code_buf[code_buf_ptr] = buf[r]; code_buf_ptr += 1
                code_buf[code_buf_ptr] = 0x0F | (((e.match_length - (T + 1)) & 0xF) << 4); code_buf_ptr += 1
            else:
                code_buf[code_buf_ptr] = (e.match_length - 0x13) & 0xFF; code_buf_ptr += 1
                code_buf[code_buf_ptr] = 0x0F; code_buf_ptr += 1
                code_buf[code_buf_ptr] = buf[r]; code_buf_ptr += 1
        elif e.match_length > T:
            code_buf[code_buf_ptr] = e.match_position & 0xFF; code_buf_ptr += 1
            code_buf[code_buf_ptr] = ((e.match_position >> 4) & 0xF0) | ((e.match_length - (T + 1)) & 0x0F); code_buf_ptr += 1
        else:
            code_buf[0] |= mask
            e.match_length = 1
            code_buf[code_buf_ptr] = buf[r]; code_buf_ptr += 1
        mask = (mask << 1) & 0xFF
        if mask == 0:
            out += code_buf[:code_buf_ptr]
            code_buf[0] = 0
            code_buf_ptr = 1
            mask = 1
        last = e.match_length
        i = 0
        while i < last and ip < n:
            c = data[ip]
            ip += 1
            e.delete(s)
            buf[s] = c
            if s < F - 1:
                buf[s + N] = c
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            ipb += 1
            e.insert(r)
            i += 1
        while i < last:
            e.delete(s)
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            ipb += 1
            length -= 1
            if length:
                e.insert(r)
            i += 1
    if code_buf_ptr > 1:
        out += code_buf[:code_buf_ptr]
    return bytes(out)


def pack(data, version=3):
    """Encode and prepend the 9-byte header."""
    payload = encode(data, version)
    return bytes([version]) + struct.pack("<LL", len(payload), len(data)) + payload
