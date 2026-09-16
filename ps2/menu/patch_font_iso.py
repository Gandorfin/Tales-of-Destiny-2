#!/usr/bin/env python3
"""Replace the Tales of Destiny 2 PS2 Latin font from one PNG.

Requires Python 3.10+ and Pillow + pycdlib:
    python -m pip install Pillow pycdlib

    python patch_font_iso.py export game.iso font.png
    python patch_font_iso.py prepare game.iso edited.png font-ready.png
    python patch_font_iso.py check game.iso font.png
    python patch_font_iso.py patch game.iso font.png -o game-font.iso

This file is standalone: no repository modules or copyrighted font assets
are bundled. The user's ISO supplies the TM2@ headers and all ten palettes.
"""
import argparse
from collections import Counter, defaultdict, deque
import hashlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile

SECTOR = 2048
FONT_OFF = 0xCA238
FONT_ROOM = 10242
RETAIL_FONT_ROOM = 21785
SLPS_SIZE = 1275360
WIDTH, HEIGHT = 128, 512
TEXTURE_SIZE = 33600
RING_SIZE = 4096


class FontError(ValueError):
    """Input cannot safely be used for this game."""


def require(ok, message):
    if not ok:
        raise FontError(message)


def dependencies():
    try:
        from PIL import Image
        import pycdlib
    except ImportError as exc:
        raise FontError(
            "Install the required packages first: python -m pip install Pillow pycdlib"
        ) from exc
    return Image, pycdlib


def initial_ring():
    # The comptoe format seeds its 4 KiB dictionary with byte/zero and
    # byte/FF patterns; this must also be present when reading retail streams.
    seed = bytearray()
    for value in range(256):
        seed.extend(bytes((value, 0)) * 4)
    for value in range(256):
        seed.extend(bytes((value, 255)) * 3 + bytes((value,)))
    seed.extend(bytes(RING_SIZE - len(seed)))
    return seed


def decompress(blob):
    require(len(blob) >= 9, "Truncated font compression header.")
    version, packed_size, unpacked_size = struct.unpack_from("<BII", blob)
    require(version in (1, 3), "Unsupported font compression version.")
    require(packed_size == len(blob) - 9, "Font compressed length is inconsistent.")
    require(unpacked_size == TEXTURE_SIZE, "Unexpected decompressed font size.")
    ring = initial_ring()
    cursor = RING_SIZE - (18 if version == 1 else 17)
    payload = memoryview(blob)[9:]
    pos = 0
    out = bytearray()

    def emit(value):
        nonlocal cursor
        require(len(out) < unpacked_size, "Font stream exceeds its declared size.")
        out.append(value)
        ring[cursor] = value
        cursor = (cursor + 1) & 4095

    while len(out) < unpacked_size:
        require(pos < len(payload), "Truncated font flags.")
        flags = payload[pos]
        pos += 1
        for bit in range(8):
            if len(out) == unpacked_size:
                break
            if flags & (1 << bit):
                require(pos < len(payload), "Truncated font literal.")
                emit(payload[pos])
                pos += 1
            else:
                require(pos + 2 <= len(payload), "Truncated font back-reference.")
                low, high = payload[pos:pos + 2]
                pos += 2
                offset = low | ((high & 0xF0) << 4)
                length = (high & 15) + 3
                if version == 3 and (high & 15) == 15:
                    if offset < 256:
                        require(pos < len(payload), "Truncated font run.")
                        value, length = payload[pos], offset + 19
                        pos += 1
                    else:
                        value, length = offset & 255, (offset >> 8) + 3
                    for _ in range(length):
                        emit(value)
                else:
                    for i in range(length):
                        emit(ring[(offset + i) & 4095])
    require(pos == len(payload), "Unexpected data after the compressed font.")
    return bytes(out)


def compress(data):
    """Greedy comptoe v3 LZSS/RLE encoder, with the retail initial dictionary."""
    require(len(data) == TEXTURE_SIZE, "Unexpected texture length for compression.")
    ring = initial_ring()
    start = RING_SIZE - 17
    sequence = bytes(ring[start:] + ring[:start]) + data
    candidates = defaultdict(deque)
    for i in range(RING_SIZE):
        candidates[sequence[i:i + 3]].append(i)
    pos, end = RING_SIZE, len(sequence)
    payload = bytearray()
    while pos < end:
        flag_pos = len(payload)
        payload.append(0)
        flags = 0
        for bit in range(8):
            if pos >= end:
                break
            best_len, best_pos = 0, 0
            key = sequence[pos:pos + 3]
            queue = candidates[key]
            while queue and queue[0] < pos - RING_SIZE:
                queue.popleft()
            limit = min(17, end - pos)
            if limit >= 3:
                for other in reversed(queue):
                    length = 3
                    while length < limit and sequence[other + length] == sequence[pos + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_pos = length, other
                        if length == limit:
                            break
            run = 1
            while run < min(274, end - pos) and sequence[pos + run] == sequence[pos]:
                run += 1
            if run >= 4 and run >= best_len:
                length = run
                if run <= 18:
                    payload.extend((sequence[pos], ((run - 3) << 4) | 15))
                else:
                    payload.extend((run - 19, 15, sequence[pos]))
            elif best_len >= 3:
                length = best_len
                offset = (start + best_pos) & 4095
                payload.extend((offset & 255, ((offset >> 4) & 0xF0) | (length - 3)))
            else:
                length = 1
                flags |= 1 << bit
                payload.append(sequence[pos])
            for i in range(pos, pos + length):
                q = candidates[sequence[i:i + 3]]
                while q and q[0] < i - RING_SIZE:
                    q.popleft()
                q.append(i)
            pos += length
        payload[flag_pos] = flags
    return struct.pack("<BII", 3, len(payload), len(data)) + payload


def texture_parts(texture):
    require(len(texture) == TEXTURE_SIZE, "Unexpected TM2@ texture length.")
    require(texture[:16] == b"TM2@" + bytes((1, 10, 1, 0)) + bytes(8),
            "Unsupported font texture header (expected the ten-palette TM2@ font).")
    palette = None
    positions = (0, 8, 0x80000, 0x80008, 0x10, 0x18, 0x80010, 0x80018, 0x100000, 0x100008)
    for number, expected_pos in enumerate(positions):
        at = 16 + number * 80
        require(struct.unpack_from("<IIIHH", texture, at) == (80, 0, expected_pos, 8, 2),
                "Unsupported font palette block %d." % number)
        if number == 0:
            palette = tuple(tuple(texture[at + 16 + i * 4:at + 20 + i * 4]) for i in range(16))
    require(struct.unpack_from("<IIIHH", texture, 0x330) == (32784, 0x14, 0xA00, WIDTH, HEIGHT),
            "Unsupported font pixel layout (expected linear 4bpp, 128x512).")
    return 0x340, palette


def font_from_executable(executable):
    require(len(executable) == SLPS_SIZE, "Unsupported SLPS_251.72 executable size.")
    require(executable[:7] == b"\x7fELF\x01\x01\x01"
            and struct.unpack_from("<H", executable, 18)[0] == 8,
            "SLPS_251.72 is not the expected little-endian MIPS executable.")
    version, packed, unpacked = struct.unpack_from("<BII", executable, FONT_OFF)
    require(version in (1, 3) and unpacked == TEXTURE_SIZE,
            "Expected compressed Latin font was not found at 0xCA238.")
    used = packed + 9
    require(9 < used <= RETAIL_FONT_ROOM, "Compressed font is outside its reserved slot.")
    # English patches reuse the space following the smaller font. Never reclaim
    # that area. On retail/other larger streams use only the current stream size.
    room = FONT_ROOM if used <= FONT_ROOM else used
    require(not any(executable[FONT_OFF + used:FONT_OFF + room]),
            "Font slot contains unexpected nonzero data after the stream.")
    blob = executable[FONT_OFF:FONT_OFF + used]
    texture = decompress(blob)
    base, palette = texture_parts(texture)
    return blob, texture, base, palette, room


def read_exact(fp, offset, size):
    fp.seek(offset)
    data = fp.read(size)
    require(len(data) == size, "ISO is truncated.")
    return data


def read_iso(path):
    """Locate SLPS in both directory trees; only a shared contiguous extent is supported."""
    _, pycdlib = dependencies()
    require(path.is_file(), "ISO file not found: %s" % path)
    require(path.stat().st_size % SECTOR == 0, "Expected a 2048-byte-sector ISO.")
    with path.open("rb") as fp:
        pvd = read_exact(fp, 16 * SECTOR, SECTOR)
        require(pvd[:7] == b"\x01CD001\x01", "Expected a PS2 ISO9660 image.")
        require(struct.unpack_from("<H", pvd, 128)[0] == SECTOR
                and struct.unpack_from(">H", pvd, 130)[0] == SECTOR,
                "Unsupported ISO sector size.")
    iso = pycdlib.PyCdlib()
    opened = False
    try:
        iso.open(str(path))
        opened = True
        rec = iso.get_record(iso_path="/SLPS_251.72;1")
        require(rec.is_file() and rec.data_length == SLPS_SIZE,
                "ISO does not contain a supported SLPS_251.72.")
        require(not (rec.file_flags & 0x80), "Multi-extent executable is unsupported.")
        require(rec.file_unit_size == 0 and rec.interleave_gap_size == 0
                and rec.xattr_len == 0, "Interleaved or extended-attribute executable is unsupported.")
        offset = rec.extent_location() * SECTOR
        require(offset >= SECTOR * 17 and offset + SLPS_SIZE <= path.stat().st_size,
                "Executable extent is outside the ISO.")
        has_udf = iso.has_udf()
        if has_udf:
            udf = iso.get_record(udf_path="/SLPS_251.72")
            require(udf.info_len == SLPS_SIZE and len(udf.alloc_descs) == 1,
                    "UDF executable must occupy one contiguous extent.")
            # Some existing Ps2IsoTools images use ICB file type 0, not 5.
            # Validate the allocation directly, rather than treating it as a directory.
            require(udf.icb_tag.file_type in (0, 5), "Unsupported UDF executable type.")
            ad = udf.alloc_descs[0]
            partitions = iso.udf_main_descs.partitions
            require(len(partitions) == 1 and hasattr(ad, "log_block_num"),
                    "Unsupported UDF partition/allocation layout.")
            if hasattr(ad, "part_ref_num"):
                require(ad.part_ref_num == 0, "Unsupported UDF partition reference.")
            udf_offset = (partitions[0].part_start_location + ad.log_block_num) * SECTOR
            require(ad.extent_type == 0 and ad.extent_length == SLPS_SIZE
                    and udf_offset == offset, "UDF and ISO9660 do not share the executable extent.")
        config = io.BytesIO()
        config_rec = iso.get_record(iso_path="/SYSTEM.CNF;1")
        require(config_rec.is_file() and 0 < config_rec.data_length <= 4096,
                "Invalid SYSTEM.CNF size.")
        iso.get_file_from_iso_fp(config, iso_path="/SYSTEM.CNF;1")
        require(b"SLPS_251.72" in config.getvalue().upper(),
                "SYSTEM.CNF does not boot SLPS_251.72.")
    finally:
        if opened:
            iso.close()
    with path.open("rb") as fp:
        executable = read_exact(fp, offset, SLPS_SIZE)
    font_from_executable(executable)
    return offset, executable, has_udf


def png_indices(path, palette):
    Image, _ = dependencies()
    require(path.is_file(), "PNG file not found: %s" % path)
    require(path.stat().st_size <= 4 * 1024 * 1024, "Font PNG exceeds 4 MiB.")
    with Image.open(path) as image:
        require(image.format == "PNG", "Input must be a PNG file.")
        require(image.size == (WIDTH, HEIGHT),
                "Font PNG must be exactly 128x512 pixels; found %dx%d." % image.size)
        require(getattr(image, "n_frames", 1) == 1, "Animated PNGs are unsupported.")
        require(image.mode in ("P", "RGBA"), "Use indexed (P) or RGBA PNG, retaining transparency.")
        image.load()
        if image.mode == "P":
            indices = image.tobytes()
            used = set(indices)
            require(max(used) < 16, "Indexed PNG uses palette indices above 15.")
            converted = image.convert("RGBA")
            actual = converted.tobytes()
            for index in used:
                point = indices.index(index)
                require(tuple(actual[point * 4:point * 4 + 4]) == palette[index],
                        "Palette index %d differs from the ISO template (RGB or transparency). "
                        "Run the prepare command to normalize this PNG." % index)
            return indices
        lookup = {rgba: index for index, rgba in enumerate(palette)}
        require(len(lookup) == 16, "Palette has duplicate RGBA entries; use an indexed template.")
        indices = bytearray()
        for point, rgba in enumerate(struct.iter_unpack("4B", image.tobytes())):
            require(rgba in lookup,
                    "Pixel (%d,%d) has unsupported RGBA %s. Preserve the exported palette; "
                    "do not resize, antialias or change opacity, or run the prepare command." %
                    (point % WIDTH, point // WIDTH, rgba))
            indices.append(lookup[rgba])
        return bytes(indices)


def png_rgba(path):
    """Read an ordinary still PNG for explicit palette preparation."""
    Image, _ = dependencies()
    require(path.is_file(), "PNG file not found: %s" % path)
    require(path.stat().st_size <= 4 * 1024 * 1024, "Font PNG exceeds 4 MiB.")
    with Image.open(path) as image:
        require(image.format == "PNG", "Input must be a PNG file.")
        require(image.size == (WIDTH, HEIGHT),
                "Font PNG must be exactly 128x512 pixels; found %dx%d." % image.size)
        require(getattr(image, "n_frames", 1) == 1, "Animated PNGs are unsupported.")
        require(image.mode in ("P", "RGB", "RGBA"),
                "Prepare accepts indexed, RGB or RGBA PNG files.")
        image.load()
        rgba = image.convert("RGBA")
        return list(struct.iter_unpack("4B", rgba.tobytes()))


def quantize_rgba(pixels, palette, allowed, alpha_threshold):
    """Map RGBA pixels onto selected ISO palette entries and return error."""
    transparent = min(range(16), key=lambda i: palette[i][3])
    require(palette[transparent][3] == 0, "ISO font palette has no transparent entry.")
    allowed = tuple(sorted(i for i in allowed if i != transparent))
    require(allowed, "At least one visible palette colour is required.")
    counts = Counter(pixels)
    mapping = {}
    error = 0
    for rgba, count in counts.items():
        red, green, blue, alpha = rgba
        if alpha < alpha_threshold:
            mapping[rgba] = transparent
            continue
        index = min(
            allowed,
            key=lambda i: ((red - palette[i][0]) ** 2
                           + (green - palette[i][1]) ** 2
                           + (blue - palette[i][2]) ** 2))
        mapping[rgba] = index
        distance = ((red - palette[index][0]) ** 2
                    + (green - palette[index][1]) ** 2
                    + (blue - palette[index][2]) ** 2)
        error += count * alpha * distance
    return bytes(mapping[pixel] for pixel in pixels), error


def texture_with_indices(texture, base, indices):
    require(len(indices) == WIDTH * HEIGHT, "Unexpected font pixel count.")
    pixels = bytes(indices[i] | (indices[i + 1] << 4)
                   for i in range(0, len(indices), 2))
    return texture[:base] + pixels


def fitted_indices(pixels, texture, base, palette, room, alpha_threshold):
    """Use the most faithful palette subset whose comptoe stream fits."""
    transparent = min(range(16), key=lambda i: palette[i][3])
    allowed = set(range(16)) - {transparent}
    indices, error = quantize_rgba(pixels, palette, allowed, alpha_threshold)
    blob = compress(texture_with_indices(texture, base, indices))
    needed_reduction = len(blob) > room
    while len(blob) > room and len(allowed) > 1:
        candidates = []
        for removed in allowed:
            subset = allowed - {removed}
            _indices, candidate_error = quantize_rgba(
                pixels, palette, subset, alpha_threshold)
            candidates.append((candidate_error, removed))
        _error, removed = min(candidates)
        allowed.remove(removed)
        indices, error = quantize_rgba(pixels, palette, allowed, alpha_threshold)
        blob = compress(texture_with_indices(texture, base, indices))
    # The game's first font palette is arranged as blue shadow, neutral
    # midtone and white highlight ramps.  Pure error-driven elimination can
    # sometimes retain only two visible colours even though this useful
    # three-colour ramp fits. Prefer it when that preserves another level.
    used_visible = set(indices) - {transparent}
    preferred = {index for index in (2, 11, 15) if index != transparent}
    if needed_reduction and len(used_visible) < len(preferred):
        preferred_indices, preferred_error = quantize_rgba(
            pixels, palette, preferred, alpha_threshold)
        preferred_blob = compress(texture_with_indices(
            texture, base, preferred_indices))
        if len(preferred_blob) <= room:
            indices, error, blob = preferred_indices, preferred_error, preferred_blob
    require(len(blob) <= room,
            "Even a two-colour conversion compresses to %d bytes; the limit is %d. "
            "Simplify the image itself." % (len(blob), room))
    return indices, len(blob), len(set(indices) - {transparent}), error


def save_indexed_png(path, indices, palette):
    Image, _ = dependencies()
    require(not path.exists(), "Output PNG already exists; choose a new filename.")
    require(path.parent.is_dir(), "Output directory does not exist.")
    image = Image.frombytes("P", (WIDTH, HEIGHT), indices)
    image.putpalette([channel for rgba in palette for channel in rgba[:3]])
    image.info["transparency"] = bytes(rgba[3] for rgba in palette)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial",
                                     dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w+b") as fp:
            image.save(fp, format="PNG", bits=4)
            fp.flush()
            os.fsync(fp.fileno())
        publish(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def prepare_png(iso_path, input_path, output_path, alpha_threshold=16):
    """Normalize a PNG to the ISO palette and reduce colours until it fits."""
    require(input_path.resolve() != output_path.resolve(),
            "Input and output PNG must be different files.")
    require(1 <= alpha_threshold <= 255, "Alpha threshold must be between 1 and 255.")
    _, executable, _ = read_iso(iso_path)
    _, texture, base, palette, room = font_from_executable(executable)
    pixels = png_rgba(input_path)
    indices, packed_size, visible_colours, _error = fitted_indices(
        pixels, texture, base, palette, room, alpha_threshold)
    save_indexed_png(output_path, indices, palette)
    require(png_indices(output_path, palette) == indices,
            "Prepared PNG failed palette verification.")
    print("Prepared exact 4bpp ISO palette: %s" % output_path)
    print("Uses %d visible palette colours; compressed %d / %d bytes."
          % (visible_colours, packed_size, room))
    if visible_colours < 15:
        print("Colour use was reduced only as far as required by the executable slot.")


def export_png(iso_path, png_path):
    Image, _ = dependencies()
    _, executable, _ = read_iso(iso_path)
    _, texture, base, palette, _room = font_from_executable(executable)
    packed_pixels = texture[base:]
    indices = bytes(value for packed in packed_pixels for value in (packed & 15, packed >> 4))
    image = Image.frombytes("P", (WIDTH, HEIGHT), indices)
    image.putpalette([channel for rgba in palette for channel in rgba[:3]])
    # Raw PS2 alpha (0..128) is intentional, matching the existing font exporter.
    image.info["transparency"] = bytes(rgba[3] for rgba in palette)
    with png_path.open("xb") as fp:
        image.save(fp, format="PNG", bits=4)
    require(png_indices(png_path, palette) == indices, "Exported PNG failed verification.")
    print("Exported 128x512 indexed PNG with the ISO font palette: %s" % png_path)


def build_font(executable, png_path):
    original_blob, texture, base, palette, room = font_from_executable(executable)
    indices = png_indices(png_path, palette)
    replacement = texture_with_indices(texture, base, indices)
    # Keep an unedited template byte-identical, including its compressor output.
    blob = original_blob if replacement == texture else compress(replacement)
    require(len(blob) <= room,
            "Edited font compresses to %d bytes; the limit is %d. PNG bit depth does not "
            "change this in-game limit: the script already builds a 4bpp texture. Run the "
            "prepare command to normalize/reduce the image, simplify glyph detail, or "
            "restore unused cells. No ISO was written." % (len(blob), room))
    require(decompress(blob) == replacement, "Compressed font failed round-trip verification.")
    result = (executable[:FONT_OFF] + blob + bytes(room - len(blob))
              + executable[FONT_OFF + room:])
    require(len(result) == len(executable), "Executable size changed.")
    changed_pixels = sum(a != b for a, b in zip(
        indices, bytes(v for b in texture[base:] for v in (b & 15, b >> 4))))
    return result, replacement, len(blob), changed_pixels, room


def verify_copy(source, output, patch_offset, patch):
    """Compare every byte against the source with exactly one allowed replacement."""
    digest = hashlib.sha256()
    total = source.stat().st_size
    with source.open("rb") as src, output.open("rb") as dst:
        pos = 0
        while pos < total:
            before = src.read(min(4 * 1024 * 1024, total - pos))
            require(before, "Source ISO became truncated during verification.")
            expected = bytearray(before)
            left = max(pos, patch_offset)
            right = min(pos + len(before), patch_offset + len(patch))
            if left < right:
                expected[left - pos:right - pos] = patch[left - patch_offset:right - patch_offset]
            actual = dst.read(len(before))
            require(actual == expected, "Output verification failed at ISO byte 0x%X." % pos)
            digest.update(actual)
            pos += len(before)
        require(not dst.read(1), "Output ISO size changed.")
    return digest.hexdigest()


def publish(temp_path, output):
    # Neither branch overwrites an output created by another process.
    if os.name == "nt":
        os.rename(temp_path, output)
    else:
        os.link(temp_path, output)
        temp_path.unlink()


def patch_iso(iso_path, png_path, output, dry_run=False):
    require(iso_path.resolve() != png_path.resolve(), "ISO and PNG must be different files.")
    if not dry_run:
        require(output.resolve() not in (iso_path.resolve(), png_path.resolve()),
                "Choose a new output filename.")
        require(not output.exists(), "Output already exists; choose a new filename.")
        require(output.parent.is_dir(), "Output directory does not exist.")
    stamp = iso_path.stat()
    offset, original, has_udf = read_iso(iso_path)
    executable, texture, packed_size, changes, room = build_font(original, png_path)
    print("PNG valid: 128x512, 16-colour palette; %d changed pixels." % changes)
    print("TM2@ valid: %d bytes; compressed %d / %d bytes." % (len(texture), packed_size, room))
    print("Executable verified through ISO9660%s." % (" and UDF" if has_udf else ""))
    if dry_run:
        print("Check passed. No output written.")
        return
    patch = executable[FONT_OFF:FONT_OFF + room]
    fd, temp_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".partial", dir=output.parent)
    temp_path = Path(temp_name)
    try:
        print("Copying ISO...", flush=True)
        with os.fdopen(fd, "w+b") as dst, iso_path.open("rb") as src:
            while True:
                block = src.read(4 * 1024 * 1024)
                if not block:
                    break
                dst.write(block)
            dst.seek(offset + FONT_OFF)
            dst.write(patch)
            dst.flush()
            os.fsync(dst.fileno())
        print("Verifying the complete output ISO...", flush=True)
        out_offset, out_executable, out_udf = read_iso(temp_path)
        require((out_offset, out_executable, out_udf) == (offset, executable, has_udf),
                "Output executable/directory verification failed.")
        digest = verify_copy(iso_path, temp_path, offset + FONT_OFF, patch)
        require((iso_path.stat().st_size, iso_path.stat().st_mtime_ns)
                == (stamp.st_size, stamp.st_mtime_ns), "Source ISO changed while patching.")
        publish(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    print("Saved: %s\nSHA-256: %s" % (output, digest))
    print("Verified: every byte outside the reserved font slot is unchanged.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                     epilog="Dependencies: python -m pip install Pillow pycdlib")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("export", "Export an editable PNG from your ISO"),
                            ("check", "Validate a PNG and compression fit without writing"),
                            ("patch", "Convert a PNG and write a verified ISO copy")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("iso", type=Path, help="Tales of Destiny 2 PS2 ISO (SLPS-25172)")
        cmd.add_argument("png", type=Path, help="128x512 font PNG")
        if name == "patch":
            cmd.add_argument("-o", "--output", type=Path, help="New ISO filename (must not exist)")
    prepare = sub.add_parser(
        "prepare", help="Normalize an ordinary PNG to the exact 4bpp ISO palette and size limit")
    prepare.add_argument("iso", type=Path, help="Tales of Destiny 2 PS2 ISO (SLPS-25172)")
    prepare.add_argument("input", type=Path, help="128x512 indexed, RGB or RGBA PNG")
    prepare.add_argument("output", type=Path, help="New normalized 4bpp PNG (must not exist)")
    prepare.add_argument(
        "--alpha-threshold", type=int, default=16, metavar="1..255",
        help="alpha values below this become transparent (default: 16)")
    args = parser.parse_args(argv)
    try:
        dependencies()
        if args.command == "export":
            export_png(args.iso, args.png)
        elif args.command == "prepare":
            prepare_png(args.iso, args.input, args.output, args.alpha_threshold)
        else:
            output = getattr(args, "output", None) or args.iso.with_name(args.iso.stem + "-custom-font.iso")
            patch_iso(args.iso, args.png, output, dry_run=args.command == "check")
    except Exception as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
