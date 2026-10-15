#!/usr/bin/env python3
"""Customize the Tales of Destiny 2 PSP fonts (ULJS-00097).

Standalone; Python 3.10+ and Pillow. Supply your own uncompressed .iso.
  python patch_font_iso.py export game.iso font.png
  python patch_font_iso.py prepare game.iso edited.png font-ready.png
  python patch_font_iso.py check game.iso font-ready.png
  python patch_font_iso.py patch game.iso font-ready.png -o game-font.iso
Add --font 2 to each command for the 128x512 ASCII/menu/icon font.
The default is --font 1, the 256x4400 dialogue/Japanese font.
"""
import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

SECTOR = 2048
WIDTH, HEIGHT = 256, 4400
FONT_SIZE = WIDTH * HEIGHT // 2
FONT2_OFFSET = 0x27E1EC
FONT2_CAPACITY = 19107
FONT2_WIDTH, FONT2_HEIGHT = 128, 512
FONT2_PIXEL_OFFSET = 0x340
FONT2_TEXTURE_SIZE = 33600
TABLE_START, TABLE_END = 0x29531C, 0x29E9AC
BOOT = "/PSP_GAME/SYSDIR/BOOT.BIN"
EBOOT = "/PSP_GAME/SYSDIR/EBOOT.BIN"
ARCHIVE = "/PSP_GAME/USRDIR/FILE.FPB"
RETAIL_EBOOT_SHA256 = "4632d8577a5862a5baaf8a4cd31669399bcacf2ff39c73a52d7877a83412c1c8"


class FontError(ValueError):
    """An input cannot be patched with the supported layout."""


def require(ok, message):
    if not ok:
        raise FontError(message)


def dimensions(font_id):
    require(font_id in (1, 2), "Choose font 1 or 2.")
    return (WIDTH, HEIGHT) if font_id == 1 else (FONT2_WIDTH, FONT2_HEIGHT)


def pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise FontError("Install Pillow: python -m pip install Pillow") from exc
    return Image


def read_exact(fp, offset, size):
    require(offset >= 0 and size >= 0, "Invalid read range.")
    fp.seek(offset)
    data = fp.read(size)
    require(len(data) == size, "Truncated ISO.")
    return data


def dual(data, at, width=4):
    lo = int.from_bytes(data[at:at + width], "little")
    hi = int.from_bytes(data[at + width:at + 2 * width], "big")
    require(lo == hi, "ISO9660 little/big-endian fields disagree.")
    return lo


@dataclass(frozen=True)
class Record:
    offset: int
    size: int
    record_offset: int


def iso_files(fp, total):
    """Read bounded ISO9660 directory records, retaining on-disc positions."""
    require(total % SECTOR == 0, "Use an uncompressed 2048-byte-sector ISO, not CSO/PBP.")
    pvd = read_exact(fp, 16 * SECTOR, SECTOR)
    require(pvd[:7] == b"\x01CD001\x01", "Expected a PSP ISO9660 image.")
    require(dual(pvd, 128, 2) == SECTOR, "Unsupported ISO sector size.")
    require(dual(pvd, 80) * SECTOR == total, "ISO volume length differs from the file size.")
    terminated = False
    for sector in range(17, min(80, total // SECTOR)):
        desc = read_exact(fp, sector * SECTOR, SECTOR)
        require(desc[1:7] == b"CD001\x01", "Invalid ISO volume descriptor.")
        if desc[0] == 255:
            terminated = True
            break
        require(desc[0] == 0, "Supplementary ISO directory trees are unsupported.")
    require(terminated, "ISO volume descriptor terminator is missing.")
    files, directories, seen = {}, [], set()

    def record(data, pos, absolute):
        length = data[pos]
        require(length >= 34 and pos + length <= len(data), "Invalid directory record.")
        require((absolute + pos) % SECTOR + length <= SECTOR,
                "Directory record crosses a sector boundary.")
        raw = data[pos:pos + length]
        require(33 + raw[32] <= length, "Invalid ISO filename length.")
        require(raw[1] == 0 and raw[26:28] == b"\0\0" and not raw[25] & 0x80,
                "Extended, interleaved or multi-extent files are unsupported.")
        require(dual(raw, 28, 2) == 1, "Unsupported ISO volume sequence.")
        offset, size = dual(raw, 2) * SECTOR, dual(raw, 10)
        require(offset >= 16 * SECTOR and offset + size <= total,
                "File extent is outside the ISO.")
        return length, raw[33:33 + raw[32]], raw[25], Record(offset, size, absolute + pos)

    def walk(rec, prefix, depth):
        require(depth < 12 and rec.offset not in seen and len(seen) < 10000,
                "Cyclic or excessive ISO directories.")
        require(rec.size <= 4 * 1024 * 1024, "ISO directory is too large.")
        seen.add(rec.offset)
        directories.append(rec)
        data = read_exact(fp, rec.offset, rec.size)
        pos = 0
        while pos < len(data):
            if data[pos] == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            length, name, flags, child = record(data, pos, rec.offset)
            pos += length
            if name in (b"\0", b"\1"):
                continue
            name = name.decode("ascii").split(";")[0].upper()
            path = prefix + "/" + name
            if flags & 2:
                walk(child, path, depth + 1)
            else:
                require(path not in files, "Duplicate ISO file path.")
                files[path] = child

    _, _, flags, root = record(pvd, 156, 16 * SECTOR)
    require(flags & 2, "Invalid root directory.")
    walk(root, "", 0)
    for name in (BOOT, EBOOT, ARCHIVE):
        require(name in files, "Missing PSP file: " + name)
        target = files[name]
        for other in list(files.values()) + directories:
            if other is target or other.size == 0:
                continue
            require(target.offset + target.size <= other.offset
                    or other.offset + other.size <= target.offset,
                    "Target file overlaps another ISO extent.")
    return files


def sfo_disc_id(data):
    require(len(data) >= 20 and data[:4] == b"\0PSF", "Invalid PARAM.SFO.")
    keys, values, count = struct.unpack_from("<III", data, 8)
    require(count <= 100 and 20 + count * 16 <= keys <= values <= len(data),
            "Invalid PARAM.SFO tables.")
    for n in range(count):
        key, _fmt, length, capacity, off = struct.unpack_from("<HHIII", data, 20 + n * 16)
        end = data.find(b"\0", keys + key, values)
        require(end >= keys + key and length <= capacity
                and values + off + capacity <= len(data), "Invalid PARAM.SFO entry.")
        if data[keys + key:end] == b"DISC_ID":
            return data[values + off:values + off + length].rstrip(b"\0")
    raise FontError("DISC_ID is missing from PARAM.SFO.")


def boot_table(data, archive_size):
    require(len(data) >= TABLE_END and data[:7] == b"\x7fELF\x01\x01\x01"
            and struct.unpack_from("<H", data, 18)[0] == 8,
            "Expected a decrypted PSP MIPS BOOT.BIN.")
    table = struct.unpack_from("<%dI" % ((TABLE_END - TABLE_START) // 4), data, TABLE_START)
    require(table[0] & ~2047 == 0 and table[-1] == archive_size,
            "Unsupported PSP archive table.")
    for here, nxt in zip(table, table[1:]):
        start, end = here & ~2047, nxt & ~2047
        require(start <= end <= archive_size and start <= end - (here & 2047),
                "Invalid archive member boundary.")
    return table


def validate_psp_deflate(stream, expected_size):
    """Check DEFLATE block compatibility with the game's own decoder.

    Its stored-block copy at vaddr 0x1AFFC executes before testing LEN.
    LEN=0 therefore copies indefinitely instead of skipping the block.
    Python/zlib accepts these legal streams, so round-trip alone is insufficient.
    """
    class Bits:
        def __init__(self):
            self.at = self.value = self.available = self.used = 0

        def read(self, count):
            while self.available < count:
                require(self.at < len(stream), "Truncated DEFLATE block.")
                self.value |= stream[self.at] << self.available
                self.at += 1
                self.available += 8
            result = self.value & ((1 << count) - 1)
            self.value >>= count
            self.available -= count
            self.used += count
            return result

    bits = Bits()

    def tree(lengths):
        counts = [lengths.count(n) for n in range(16)]
        counts[0] = 0
        codes, code = {}, 0
        for size in range(1, 16):
            code = (code + counts[size - 1]) << 1
            require(code + counts[size] <= 1 << size, "Invalid DEFLATE Huffman tree.")
            next_code = code
            for symbol, length in enumerate(lengths):
                if length == size:
                    codes[size, next_code] = symbol
                    next_code += 1
        return codes

    def symbol(codes):
        code = 0
        for size in range(1, 16):
            code = (code << 1) | bits.read(1)
            value = codes.get((size, code))
            if value is not None:
                return value
        raise FontError("Invalid DEFLATE Huffman symbol.")

    fixed_lit = tree([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8)
    fixed_dist = tree([5] * 32)
    length_base = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27,
                   31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
    length_extra = (0,) * 8 + (1,) * 4 + (2,) * 4 + (3,) * 4 + (4,) * 4 + (5,) * 4 + (0,)
    distance_extra = (0,) * 4 + tuple(n for n in range(1, 14) for _ in range(2))
    distance_base = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129,
                     193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097,
                     6145, 8193, 12289, 16385, 24577)
    order = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)
    produced = blocks = 0
    while True:
        final, kind = bits.read(1), bits.read(2)
        blocks += 1
        require(kind != 3, "Reserved DEFLATE block type.")
        if kind == 0:
            bits.read((-bits.used) % 8)
            length, complement = bits.read(16), bits.read(16)
            require(length ^ complement == 0xffff, "Invalid stored DEFLATE block length.")
            require(length > 0,
                    "PSP-incompatible empty stored DEFLATE block: the game freezes loading this font. "
                    "Repatch a known-working ISO with the updated tool.")
            produced += length
            require(produced <= expected_size, "DEFLATE output exceeds the font size.")
            for _ in range(length):
                bits.read(8)
        else:
            lit, dist = fixed_lit, fixed_dist
            if kind == 2:
                nlit, ndist, ncode = bits.read(5) + 257, bits.read(5) + 1, bits.read(4) + 4
                require(nlit <= 286, "Invalid DEFLATE literal count.")
                lengths = [0] * 19
                for index in order[:ncode]:
                    lengths[index] = bits.read(3)
                code_tree = tree(lengths)
                lengths = []
                while len(lengths) < nlit + ndist:
                    value = symbol(code_tree)
                    if value < 16:
                        lengths.append(value)
                    else:
                        require(value != 16 or lengths, "Invalid DEFLATE repeat.")
                        repeat = bits.read({16: 2, 17: 3, 18: 7}[value]) + {16: 3, 17: 3, 18: 11}[value]
                        lengths.extend([lengths[-1] if value == 16 else 0] * repeat)
                        require(len(lengths) <= nlit + ndist, "Excess DEFLATE code lengths.")
                require(lengths[256] > 0, "Missing DEFLATE end-of-block code.")
                lit, dist = tree(lengths[:nlit]), tree(lengths[nlit:])
            while True:
                value = symbol(lit)
                if value == 256:
                    break
                if value < 256:
                    produced += 1
                else:
                    require(257 <= value <= 285, "Invalid DEFLATE length code.")
                    length = length_base[value - 257] + bits.read(length_extra[value - 257])
                    distance = symbol(dist)
                    require(distance < 30, "Invalid DEFLATE distance code.")
                    distance = distance_base[distance] + bits.read(distance_extra[distance])
                    require(distance <= produced, "DEFLATE distance exceeds output history.")
                    produced += length
                require(produced <= expected_size, "DEFLATE output exceeds the font size.")
        if final:
            break
    require(produced == expected_size and (bits.used + 7) // 8 == len(stream),
            "DEFLATE output size or trailing bytes are invalid.")
    return blocks


def unpack_font(blob):
    require(len(blob) >= 9, "Truncated compressed font.")
    kind, packed, unpacked = struct.unpack_from("<BII", blob)
    require(kind == 4 and packed == len(blob) - 9 and unpacked == FONT_SIZE,
            "Expected PSP member 00000: raw-deflate 256x4400 4bpp font.")
    decoder = zlib.decompressobj(-15)
    data = decoder.decompress(blob[9:], FONT_SIZE + 1)
    require(len(data) == FONT_SIZE and decoder.eof and not decoder.unused_data
            and not decoder.unconsumed_tail, "Invalid or overlong font deflate stream.")
    validate_psp_deflate(blob[9:], FONT_SIZE)
    return data


def swizzle(linear, reverse=False):
    require(len(linear) == FONT_SIZE, "Unexpected PSP font texture length.")
    out, pos = bytearray(FONT_SIZE), 0
    for by in range(HEIGHT // 8):
        for bx in range((WIDTH // 2) // 16):
            for row in range(8):
                at = (by * 8 + row) * (WIDTH // 2) + bx * 16
                if reverse:
                    out[at:at + 16] = linear[pos:pos + 16]
                else:
                    out[pos:pos + 16] = linear[at:at + 16]
                pos += 16
    return bytes(out)


def font_indices(data, font_id=1):
    width, height = dimensions(font_id)
    require(len(data) == width * height // 2, "Unexpected PSP font pixel length.")
    linear = swizzle(data, reverse=True) if font_id == 1 else data
    return bytes(v for packed in linear
                 for v in (packed & 15, packed >> 4))


def indices_font(indices, font_id=1):
    width, height = dimensions(font_id)
    require(len(indices) == width * height and max(indices) <= 15,
            "Expected %dx%d pixels with one 4-bit intensity per pixel." % (width, height))
    linear = bytes(indices[i] | indices[i + 1] << 4 for i in range(0, len(indices), 2))
    return swizzle(linear) if font_id == 1 else linear


def font2_texture(blob):
    """Validate the executable's deflated TM2@ font, retaining all ten palettes.

    Pixel data is linear on disc; the renderer swizzles it during startup.
    Source: font initialization at vaddr 0x144730, which decompresses the
    stream at data-segment-relative 0xA14EC (file FONT2_OFFSET).
    """
    require(len(blob) >= 9, "Truncated font 2 stream.")
    kind, packed, unpacked = struct.unpack_from('<BII', blob)
    require(kind == 4 and packed == len(blob) - 9 and unpacked == FONT2_TEXTURE_SIZE,
            "Expected embedded font 2: raw-deflate 128x512 TM2@ texture.")
    decoder = zlib.decompressobj(-15)
    texture = decoder.decompress(blob[9:], FONT2_TEXTURE_SIZE + 1)
    require(len(texture) == FONT2_TEXTURE_SIZE and decoder.eof
            and not decoder.unused_data and not decoder.unconsumed_tail,
            "Invalid or overlong font 2 deflate stream.")
    validate_psp_deflate(blob[9:], FONT2_TEXTURE_SIZE)
    require(texture[:16] == b'TM2@' + bytes((1, 10, 1, 0)) + bytes(8),
            "Unsupported font 2 TM2@ header.")
    for i, pos in enumerate((0, 8, 0x80000, 0x80008, 16, 24,
                             0x80010, 0x80018, 0x100000, 0x100008)):
        require(struct.unpack_from('<IIIHH', texture, 16 + i * 80) == (80, 0, pos, 8, 2),
                "Unsupported font 2 palette layout.")
    require(struct.unpack_from('<IIIHH', texture, 0x330)
            == (32784, 0x14, 0xA00, FONT2_WIDTH, FONT2_HEIGHT),
            "Unsupported font 2 image block.")
    return texture


def embedded_font2(boot):
    require(len(boot) >= FONT2_OFFSET + FONT2_CAPACITY, "Truncated font 2 allocation.")
    stored = 9 + struct.unpack_from('<I', boot, FONT2_OFFSET + 1)[0]
    require(9 <= stored <= FONT2_CAPACITY, "Invalid font 2 compressed length.")
    blob = boot[FONT2_OFFSET:FONT2_OFFSET + stored]
    texture = font2_texture(blob)
    require(not any(boot[FONT2_OFFSET + stored:FONT2_OFFSET + FONT2_CAPACITY]),
            "Font 2 allocation padding contains unexpected data.")
    return blob, texture


@dataclass
class Context:
    files: dict
    boot: bytes
    eboot: bytes
    blob: bytes
    font: bytes
    capacity: int
    encrypted: bool
    font_id: int = 1
    texture: bytes = b''


def read_iso(path, font_id=1):
    dimensions(font_id)
    require(path.is_file(), "ISO not found: %s" % path)
    with path.open("rb") as fp:
        files = iso_files(fp, path.stat().st_size)
        sfo = files.get("/PSP_GAME/PARAM.SFO")
        require(sfo is not None and sfo.size <= 65536, "Missing or oversized PARAM.SFO.")
        require(sfo_disc_id(read_exact(fp, sfo.offset, sfo.size)) in (b"ULJS00097", b"ULJS-00097"),
                "This tool supports Tales of Destiny 2 PSP ULJS-00097 only.")
        for name in (BOOT, EBOOT):
            require(TABLE_END <= files[name].size <= 16 * 1024 * 1024,
                    "Unexpected executable size.")
        boot = read_exact(fp, files[BOOT].offset, files[BOOT].size)
        eboot = read_exact(fp, files[EBOOT].offset, files[EBOOT].size)
        table = boot_table(boot, files[ARCHIVE].size)
        encrypted = eboot[:4] == b"~PSP"
        if encrypted:
            require(hashlib.sha256(eboot).hexdigest() == RETAIL_EBOOT_SHA256,
                    "Unknown encrypted EBOOT.BIN; use a supported retail or translated ISO.")
            require(len(boot) <= len(eboot), "Decrypted executable will not fit its ISO file slot.")
        else:
            require(boot_table(eboot, files[ARCHIVE].size) == table,
                    "BOOT.BIN and EBOOT.BIN archive tables disagree.")
        if font_id == 2:
            blob, texture = embedded_font2(boot)
            if not encrypted:
                require(embedded_font2(eboot)[0] == blob,
                        "BOOT.BIN and EBOOT.BIN font 2 textures disagree.")
            return Context(files, boot, eboot, blob, texture[FONT2_PIXEL_OFFSET:],
                           FONT2_CAPACITY, encrypted, font_id, texture)
        capacity = table[1] & ~2047
        require(0 < capacity <= FONT_SIZE + SECTOR, "Unexpected font sector allocation.")
        stored = capacity - (table[0] & 2047)
        blob = read_exact(fp, files[ARCHIVE].offset, stored)
        font = unpack_font(blob)
        padding = read_exact(fp, files[ARCHIVE].offset + stored, capacity - stored)
        require(not any(padding), "Font sector padding contains unexpected data.")
        glyph_end = (table[2] & ~2047) - (table[1] & 2047)
        require(glyph_end - capacity == 5120, "Unexpected PSP glyph-code table length.")
        require(read_exact(fp, files[ARCHIVE].offset + capacity, 8)
                == bytes.fromhex("8140814381448145"), "Unexpected PSP glyph-code table.")
    return Context(files, boot, eboot, blob, font, capacity, encrypted)


def pack_font(data, capacity):
    """Deflate plus PSP-compatible fixed-Huffman blocks; keep archive positions.

    The archive table's remainder is only 11 bits. A much smaller font must
    therefore keep all but its final sector allocated. Eight nonfinal empty
    fixed-Huffman blocks occupy exactly ten bytes, keeping the original stream
    byte-aligned. Do not use empty stored blocks or Z_SYNC_FLUSH: the game's
    decoder cannot skip a stored block with LEN=0.
    """
    candidates = []
    for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED):
        encoder = zlib.compressobj(9, zlib.DEFLATED, -15, 9, strategy)
        normal = encoder.compress(data) + encoder.flush()
        candidates.append((normal, strategy))
    packed, _strategy = min(candidates, key=lambda item: len(item[0]))
    compressed_size = 9 + len(packed)
    require(compressed_size <= capacity,
            "Edited font compresses to %d bytes; this ISO has %d bytes available. "
            "Simplify glyph detail or restore untouched cells. PNG bit depth does not "
            "change this limit. No ISO was written." % (compressed_size, capacity))
    if compressed_size < capacity - 2047:
        # Each block is BFINAL=0, BTYPE=01, then fixed symbol 256 (seven zeros).
        prefix = sum(2 << (10 * i) for i in range(8)).to_bytes(10, 'little')
        count = (capacity - 2047 - compressed_size + 9) // 10
        packed = prefix * count + packed
    blob = struct.pack("<BII", 4, len(packed), FONT_SIZE) + packed
    require(0 <= capacity - len(blob) <= 2047, "Font cannot fit the archive remainder field.")
    require(unpack_font(blob) == data, "Compressed font round-trip failed.")
    return blob, compressed_size


def png_indices(path, prepare=False, levels=16, font_id=1, keep=None):
    """PNG pixels -> palette indices. With prepare, `keep` (the ISO's current
    indices) makes every pixel still showing its exported gray keep its exact
    index, so --levels only reduces the pixels that were edited. Without it,
    fewer levels would remap untouched icons too: font 2's button glyphs use
    indices 7..14, which only some palettes colour, and 8 levels folds them
    onto other entries (blue and green buttons turned gray)."""
    width, height = dimensions(font_id)
    require(levels in (2, 4, 8, 16), "Use 2, 4, 8 or 16 intensity levels.")
    Image = pillow()
    require(path.is_file() and path.stat().st_size <= 16 * 1024 * 1024,
            "PNG not found or larger than 16 MiB.")
    with Image.open(path) as image:
        require(image.format == "PNG" and image.size == (width, height),
                "PSP font %d PNG must be exactly %dx%d pixels. Export from the PSP ISO first."
                % (font_id, width, height))
        require(getattr(image, "n_frames", 1) == 1, "Animated PNGs are unsupported.")
        require(image.mode in ("P", "L", "LA", "RGB", "RGBA"), "Unsupported PNG colour mode.")
        rgba = image.convert("RGBA").tobytes()
    mapping, indices = {}, bytearray()
    for point, colour in enumerate(struct.iter_unpack("4B", rgba)):
        if colour not in mapping:
            red, green, blue, alpha = colour
            if prepare:
                # Grayscale intensity on black: alpha is coverage, not a CLUT index.
                value = ((299 * red + 587 * green + 114 * blue) * alpha + 127500) // 255000
                step = (value * (levels - 1) + 127) // 255
                mapping[colour] = (step * 15 + (levels - 1) // 2) // (levels - 1)
            else:
                require(red == green == blue and red % 17 == 0 and alpha == 255,
                        "Pixel (%d,%d) is not opaque 16-level grayscale. Run prepare first."
                        % (point % width, point // width))
                mapping[colour] = red // 17
        indices.append(mapping[colour])
    if prepare and keep is not None and levels != 16:
        require(len(keep) == len(indices), "Original font size mismatch.")
        for point, colour in enumerate(struct.iter_unpack("4B", rgba)):
            original = keep[point]
            if colour == (original * 17, original * 17, original * 17, 255):
                indices[point] = original
    return bytes(indices)


def publish(temp_path, output):
    if os.name == "nt":
        os.rename(temp_path, output)
    else:
        os.link(temp_path, output)
        temp_path.unlink()


def output_guard(output, *inputs):
    require(not output.exists(), "Output already exists; choose a new filename.")
    require(output.resolve() not in {p.resolve() for p in inputs}, "Choose a separate output filename.")
    require(output.parent.is_dir(), "Output directory does not exist.")


def write_png(path, indices, font_id=1):
    width, height = dimensions(font_id)
    Image = pillow()
    output_guard(path)
    image = Image.frombytes("P", (width, height), indices)
    image.putpalette([value * 17 for value in range(16) for _ in range(3)])
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fp:
            image.save(fp, format="PNG", bits=4)
        require(png_indices(temp, font_id=font_id) == indices, "Saved font PNG failed verification.")
        publish(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def font_plan(context, indices):
    font = indices_font(indices, context.font_id)
    require(font_indices(font, context.font_id) == indices, "PSP texture round-trip failed.")
    if font == context.font:
        return [], font, len(context.blob), len(context.blob)
    if context.font_id == 2:
        texture = context.texture[:FONT2_PIXEL_OFFSET] + font
        candidates = []
        # A smaller match-table memory setting beats zlib's default on the
        # retail icon font. Try all standard settings within its tight slot.
        for memory in range(1, 10):
            for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED):
                encoder = zlib.compressobj(9, zlib.DEFLATED, -15, memory, strategy)
                candidates.append(encoder.compress(texture) + encoder.flush())
        packed = min(candidates, key=len)
        blob = struct.pack('<BII', 4, len(packed), len(texture)) + packed
        require(len(blob) <= context.capacity,
                "Edited font 2 compresses to %d bytes; this ISO has %d bytes available. "
                "Simplify glyph detail or use prepare --levels 8. No ISO was written."
                % (len(blob), context.capacity))
        require(font2_texture(blob) == texture, "Font 2 compression round-trip failed.")
        replacement = blob + bytes(context.capacity - len(blob))
        patches = [(context.files[BOOT].offset + FONT2_OFFSET, replacement)]
        if context.encrypted:
            boot = bytearray(context.boot)
            boot[FONT2_OFFSET:FONT2_OFFSET + context.capacity] = replacement
            rec = context.files[EBOOT]
            patches += [(rec.offset, bytes(boot) + bytes(rec.size - len(boot))),
                        (rec.record_offset + 10, struct.pack('<I', len(boot)) + struct.pack('>I', len(boot)))]
        else:
            patches.append((context.files[EBOOT].offset + FONT2_OFFSET, replacement))
        return sorted(patches), font, len(blob), len(blob)
    blob, compressed_size = pack_font(font, context.capacity)
    word = struct.pack("<I", context.capacity - len(blob))
    patches = [(context.files[ARCHIVE].offset, blob + bytes(context.capacity - len(blob)))]
    patches.append((context.files[BOOT].offset + TABLE_START, word))
    if context.encrypted:
        boot = bytearray(context.boot)
        boot[TABLE_START:TABLE_START + 4] = word
        rec = context.files[EBOOT]
        patches.append((rec.offset, bytes(boot) + bytes(rec.size - len(boot))))
        patches.append((rec.record_offset + 10,
                        struct.pack("<I", len(boot)) + struct.pack(">I", len(boot))))
    else:
        patches.append((context.files[EBOOT].offset + TABLE_START, word))
    return sorted(patches), font, len(blob), compressed_size


def verify_copy(source, output, patches):
    """Verify every output byte; only explicit non-overlapping ranges may differ."""
    total = source.stat().st_size
    last = 0
    for offset, data in patches:
        require(last <= offset and offset + len(data) <= total, "Invalid patch ranges.")
        last = offset + len(data)
    digest = hashlib.sha256()
    with source.open("rb") as src, output.open("rb") as dst:
        pos = 0
        while pos < total:
            block = src.read(min(4 * 1024 * 1024, total - pos))
            require(block, "Source ISO became truncated.")
            expected = bytearray(block)
            for offset, data in patches:
                left, right = max(pos, offset), min(pos + len(block), offset + len(data))
                if left < right:
                    expected[left - pos:right - pos] = data[left - offset:right - offset]
            actual = dst.read(len(block))
            require(actual == expected, "Output byte verification failed at 0x%X." % pos)
            digest.update(actual)
            pos += len(block)
        require(not dst.read(1), "Output ISO size changed.")
    return digest.hexdigest()


def patch_iso(source, png, output=None, check=False, font_id=1):
    if not check:
        output_guard(output, source, png)
    stamp = source.stat()
    context = read_iso(source, font_id)
    indices = png_indices(png, font_id=font_id)
    patches, font, stored, compressed = font_plan(context, indices)
    width, height = dimensions(font_id)
    print("Font %d PNG valid: %dx%d, 16-level grayscale; texture round-trip verified."
          % (font_id, width, height))
    print("Compressed font: %d / %d bytes; stored stream: %d bytes."
          % (compressed, context.capacity, stored))
    if context.encrypted and patches:
        print("Retail EBOOT.BIN will be replaced by the disc's decrypted BOOT.BIN."
              " Use PPSSPP or a PSP able to run unsigned images.")
    if check:
        print("Check passed. No output written.")
        return
    fd, name = tempfile.mkstemp(prefix=output.name + ".", suffix=".partial", dir=output.parent)
    temp = Path(name)
    try:
        print("Copying ISO...", flush=True)
        with os.fdopen(fd, "wb") as dst, source.open("rb") as src:
            while True:
                data = src.read(4 * 1024 * 1024)
                if not data:
                    break
                dst.write(data)
            for offset, data in patches:
                dst.seek(offset)
                dst.write(data)
            dst.flush()
            os.fsync(dst.fileno())
        print("Verifying all output bytes...", flush=True)
        digest = verify_copy(source, temp, patches)
        result = read_iso(temp, font_id)
        require(result.font == font, "Output font does not match the input PNG.")
        require((source.stat().st_size, source.stat().st_mtime_ns)
                == (stamp.st_size, stamp.st_mtime_ns), "Source ISO changed while patching.")
        publish(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    print("Saved: %s\nSHA-256: %s" % (output, digest))
    print("Verified: archive positions, glyph mappings and all bytes outside the planned edits preserved.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "prepare", "check", "patch"):
        sub = commands.add_parser(name)
        sub.add_argument('--font', type=int, choices=(1, 2), default=1,
                         help='1: dialogue/Japanese 256x4400 (default); 2: ASCII/menu/icons 128x512')
        sub.add_argument("iso", type=Path)
        sub.add_argument("png", type=Path)
        if name == "prepare":
            sub.add_argument("output", type=Path)
            sub.add_argument("--levels", type=int, choices=(2, 4, 8, 16), default=16,
                             help="Intensity levels; fewer can help compression (default: 16)")
        if name == "patch":
            sub.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            output_guard(args.png, args.iso)
            context = read_iso(args.iso, args.font)
            write_png(args.png, font_indices(context.font, args.font), args.font)
            width, height = dimensions(args.font)
            cells = '23x23 cells, 11 per row' if args.font == 1 else '12x16 cells, 10 per row; preserve icons'
            print("Exported PSP font %d: %s (%dx%d; %s)." % (args.font, args.png, width, height, cells))
        elif args.command == "prepare":
            output_guard(args.output, args.iso, args.png)
            context = read_iso(args.iso, args.font)
            original = font_indices(context.font, args.font)
            indices = png_indices(args.png, prepare=True, levels=args.levels, font_id=args.font,
                                  keep=original)
            if args.levels != 16:
                edited = sum(a != b for a, b in zip(indices, original))
                print("--levels %d applied to edited pixels only; %d pixels differ from the ISO's font."
                      % (args.levels, edited))
            _, _, stored, compressed = font_plan(context, indices)
            write_png(args.output, indices, args.font)
            print("Prepared 4bpp grayscale PNG: %s" % args.output)
            print("Compressed %d / %d bytes; stored %d bytes."
                  % (compressed, context.capacity, stored))
        else:
            output = getattr(args, "output", None) or args.iso.with_name(args.iso.stem + "-custom-font.iso")
            patch_iso(args.iso, args.png, output, check=args.command == "check", font_id=args.font)
    except (FontError, OSError, ValueError, struct.error, zlib.error) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
