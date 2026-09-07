#!/usr/bin/env python3
"""Replace the MPEG-2 video elementary stream in a TOD2 PS2 movie.

The original program-stream pack headers and private-stream (0xBD) audio
packets are kept byte-for-byte. Video data is distributed over the original
video packet capacity, while every replacement frame receives the matching
original frame's presentation time and a decode-order-correct timestamp.
Unused bytes become standard MPEG padding packets, preserving the fixed size.
"""

from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
from pathlib import Path


PACK_SIZE = 0x4000
START = b"\x00\x00\x01"


def pack_header_size(pack: bytes) -> int:
    if pack[:4] != START + b"\xBA":
        raise ValueError("pack does not begin with an MPEG-2 pack header")
    return 14 + (pack[13] & 7)


def packet_spans(pack: bytes):
    pos = pack_header_size(pack)
    while pos < len(pack):
        if pos + 6 > len(pack) or pack[pos : pos + 3] != START:
            raise ValueError(f"invalid PES packet at pack offset 0x{pos:X}")
        sid = pack[pos + 3]
        length = int.from_bytes(pack[pos + 4 : pos + 6], "big")
        end = pos + 6 + length
        if end > len(pack):
            raise ValueError(f"PES packet overruns pack at offset 0x{pos:X}")
        yield pos, end, sid
        pos = end


def pack_scr_27mhz(pack: bytes) -> int:
    """Decode an MPEG-2 pack SCR without losing its 27 MHz extension."""
    if pack[:4] != START + b"\xBA":
        raise ValueError("pack does not begin with an MPEG-2 pack header")
    base = (
        ((pack[4] >> 3) & 7) << 30
        | (pack[4] & 3) << 28
        | pack[5] << 20
        | (pack[6] >> 3) << 15
        | (pack[6] & 3) << 13
        | pack[7] << 5
        | pack[8] >> 3
    )
    extension = ((pack[8] & 3) << 7) | (pack[9] >> 1)
    return base * 300 + extension


def video_payload_start(packet: bytes) -> int:
    if packet[:4] != START + b"\xE0" or len(packet) < 9:
        raise ValueError("not an MPEG-2 video PES packet")
    start = 9 + packet[8]
    if start > len(packet):
        raise ValueError("invalid video PES header length")
    return start


def padding_packet(total_size: int) -> bytes:
    if total_size < 6:
        raise ValueError("padding packet needs at least 6 bytes")
    return START + b"\xBE" + (total_size - 6).to_bytes(2, "big") + b"\xFF" * (total_size - 6)


def encode_timestamp(prefix: int, value: int) -> bytes:
    value &= (1 << 33) - 1
    return bytes(
        [
            (prefix << 4) | (((value >> 30) & 7) << 1) | 1,
            (value >> 22) & 0xFF,
            (((value >> 15) & 0x7F) << 1) | 1,
            (value >> 7) & 0xFF,
            ((value & 0x7F) << 1) | 1,
        ]
    )


def decode_timestamp(encoded: bytes) -> int:
    if len(encoded) != 5:
        raise ValueError("MPEG timestamp must be five bytes")
    return (
        ((encoded[0] >> 1) & 7) << 30
        | encoded[1] << 22
        | ((encoded[2] >> 1) & 0x7F) << 15
        | encoded[3] << 7
        | ((encoded[4] >> 1) & 0x7F)
    )


def picture_timestamps(video: bytes):
    """Return picture-start offsets and PS2-friendly 90 kHz PTS/DTS values."""
    pictures = []
    search_at = 0
    gop_base = 0
    previous_max_tr = -1
    previous_picture = -1
    coding_index = 0
    clock_start = 12_000
    frame_ticks = 3_003  # 90 kHz / 29.970029...
    while True:
        pos = video.find(START + b"\x00", search_at)
        if pos < 0:
            break
        if pos + 6 > len(video):
            break
        if previous_picture >= 0 and video.find(START + b"\xB8", previous_picture + 4, pos) >= 0:
            gop_base += previous_max_tr + 1
            previous_max_tr = -1
        temporal_reference = ((video[pos + 4] << 8) | video[pos + 5]) >> 6
        previous_max_tr = max(previous_max_tr, temporal_reference)
        pts = clock_start + (gop_base + temporal_reference) * frame_ticks
        dts = clock_start + (coding_index - 1) * frame_ticks
        pictures.append((pos, pts, max(0, dts)))
        coding_index += 1
        previous_picture = pos
        search_at = pos + 4
    if not pictures:
        raise ValueError("replacement video has no MPEG-2 picture start codes")
    return pictures


def rebuild_video_packet(
    template: bytes,
    payload: bytes,
    timestamps=None,
    picture_coding_type: int | None = None,
    preserve_header: bool = False,
    stuff_pes_header: bool = False,
) -> bytes:
    # A constant-rate MPEG program stream represents an idle video slot with a
    # padding-stream packet.  Do not emit a header-only (zero-payload) video
    # PES: Sony's PS2 libmpeg rejects that construction even though tolerant PC
    # demuxers accept it.  This is also how an SVCD-style mux keeps its rate
    # without claiming that empty data belongs to the video stream.
    if not payload and timestamps is None and not preserve_header:
        return padding_packet(len(template))

    payload_at = video_payload_start(template)
    header = bytearray(template[:payload_at])
    # Old PTS values belong to the old frames.  Add replacement timestamps only
    # to a PES packet containing the start of a replacement picture; otherwise
    # retain the ten-byte optional-header area as stuffing.
    if preserve_header:
        pass
    elif timestamps is None:
        header[7] = 0
        header[9:payload_at] = b"\xFF" * (payload_at - 9)
    else:
        pts, dts = timestamps
        if picture_coding_type == 3:
            # The original PS2 mux gives B pictures a PTS only.  Supplying an
            # explicit DTS here changes the decoder's original timing model.
            header[7] = 0x80
            header[9:14] = encode_timestamp(2, pts)
            header[14:payload_at] = b"\xFF" * (payload_at - 14)
        elif picture_coding_type in (1, 2):
            # I/P reference pictures carry both PTS and DTS.  Keep any
            # template PES extension after them, notably the first packet's
            # P-STD buffer descriptor (flags 0xC1, bytes 1E 67 06).
            header[7] = 0xC0 | (template[7] & 0x01)
            header[9:19] = encode_timestamp(3, pts) + encode_timestamp(1, dts)
            if template[7] & 0x01:
                header[19:payload_at] = template[19:payload_at]
            else:
                header[19:payload_at] = b"\xFF" * (payload_at - 19)
        else:
            raise ValueError(
                f"unsupported MPEG-2 picture coding type {picture_coding_type}"
            )
    remaining = len(template) - len(header) - len(payload)
    if stuff_pes_header and remaining > 0:
        stuffing = min(remaining, 255 - header[8])
        header[8] += stuffing
        header.extend(b"\xFF" * stuffing)

    new_pes_length = len(header) - 6 + len(payload)
    if new_pes_length > 0xFFFF:
        raise ValueError("rebuilt video PES packet is too large")
    header[4:6] = new_pes_length.to_bytes(2, "big")
    used = bytes(header) + payload
    remaining = len(template) - len(used)
    if remaining == 0:
        return used
    if remaining >= 6:
        return used + padding_packet(remaining)
    raise ValueError(
        f"cannot represent a {remaining}-byte PES remainder as legal padding"
    )


def inspect_original(data: bytes):
    if len(data) < 4 or (len(data) - 4) % PACK_SIZE:
        raise ValueError("movie size is not N * 0x4000 + 4 bytes")
    if data[-4:] != START + b"\xB9":
        raise ValueError("movie does not end with an MPEG program end code")

    video_packets = []
    audio_packets = 0
    audio_bytes = 0
    pack_count = (len(data) - 4) // PACK_SIZE
    for pack_index in range(pack_count):
        base = pack_index * PACK_SIZE
        pack = data[base : base + PACK_SIZE]
        for start, end, sid in packet_spans(pack):
            packet = pack[start:end]
            if sid == 0xE0:
                payload_at = video_payload_start(packet)
                video_packets.append((pack_index, start, end, payload_at, end - start - payload_at))
            elif sid == 0xBD:
                audio_packets += 1
                audio_bytes += end - start
    return pack_count, video_packets, audio_packets, audio_bytes


def original_picture_timestamps(
    original: bytes, video_packets: list[tuple], original_video: bytes
) -> list[tuple[int, int]]:
    """Associate every original picture with its exact PES PTS and DTS."""
    picture_offsets = [item[0] for item in picture_timestamps(original_video)]
    timestamps: list[tuple[int, int | None] | None] = [None] * len(picture_offsets)
    video_at = 0
    for pack_index, start, end, payload_at, payload_size in video_packets:
        base = pack_index * PACK_SIZE
        packet = original[base + start : base + end]
        packet_video_end = video_at + payload_size
        flags = packet[7]
        if flags & 0x80:
            pts = decode_timestamp(packet[9:14])
            dts = decode_timestamp(packet[14:19]) if flags & 0x40 else None
            picture_index = bisect.bisect_left(picture_offsets, video_at)
            if (
                picture_index < len(picture_offsets)
                and picture_offsets[picture_index] < packet_video_end
            ):
                timestamps[picture_index] = (pts, dts)
        video_at = packet_video_end

    nominal = picture_timestamps(original_video)
    frame_ticks = 3_003
    origins = Counter(
        timestamp[0] - ((nominal[index][1] - 12_000) // frame_ticks) * frame_ticks
        for index, timestamp in enumerate(timestamps)
        if timestamp is not None
    )
    if not origins:
        raise ValueError("original video contains no usable PES timestamps")
    pts_origin = origins.most_common(1)[0][0]
    first_known_dts_index = next(
        (
            index
            for index, timestamp in enumerate(timestamps)
            if timestamp is not None and timestamp[1] is not None
        ),
        None,
    )
    if first_known_dts_index is None:
        raise ValueError("original video contains no usable DTS")
    first_known_dts = timestamps[first_known_dts_index][1]
    assert first_known_dts is not None
    dts_origin = first_known_dts - first_known_dts_index * frame_ticks

    missing = 0
    normalized: list[tuple[int, int]] = []
    for index, timestamp in enumerate(timestamps):
        if timestamp is None:
            display_frame = (nominal[index][1] - 12_000) // frame_ticks
            pts = pts_origin + display_frame * frame_ticks
            missing += 1
        else:
            pts = timestamp[0]
        dts = (
            timestamp[1]
            if timestamp is not None and timestamp[1] is not None
            else dts_origin + index * frame_ticks
        )
        normalized.append((pts, dts))
    if missing:
        print(f"original_timestamps_inferred={missing:,}")
    return normalized


def replacement_picture_timestamps(
    original_video: bytes,
    replacement_video: bytes,
    original_timestamps: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Use original presentation times with replacement decode ordering."""
    nominal_clock = 12_000
    frame_ticks = 3_003
    original_nominal = picture_timestamps(original_video)
    replacement_nominal = picture_timestamps(replacement_video)
    if len(original_nominal) != len(original_timestamps):
        raise AssertionError("original timestamp count does not match its pictures")

    pts_by_display_frame = {}
    for nominal, exact in zip(original_nominal, original_timestamps):
        display_frame = (nominal[1] - nominal_clock) // frame_ticks
        pts_by_display_frame[display_frame] = exact[0]

    first_dts = original_timestamps[0][1]
    result = []
    for coding_index, nominal in enumerate(replacement_nominal):
        display_frame = (nominal[1] - nominal_clock) // frame_ticks
        if display_frame not in pts_by_display_frame:
            raise ValueError(f"replacement display frame {display_frame} is not in the original")
        pts = pts_by_display_frame[display_frame]
        dts = first_dts + coding_index * frame_ticks
        result.append((pts, dts))
    return result


def replacement_padding_targets(
    original_video: bytes,
    replacement_video: bytes,
    capacity: int,
) -> list[int]:
    """Return cumulative legal padding wanted before each replacement picture.

    A replacement encode can have a very different cumulative byte curve even
    when its final size nearly matches the original.  Padding cannot later be
    removed, so use the suffix minimum of the original/replacement picture
    offsets.  This delays each picture as much as the fixed total capacity
    permits without pushing a later picture past its original byte position.
    """
    original_offsets = [item[0] for item in picture_timestamps(original_video)]
    replacement_offsets = [item[0] for item in picture_timestamps(replacement_video)]
    if len(original_offsets) != len(replacement_offsets):
        raise ValueError("original and replacement picture counts differ")

    total_padding = capacity - len(replacement_video)
    suffix_minimum = total_padding
    targets = [0] * len(replacement_offsets)
    for index in range(len(replacement_offsets) - 1, -1, -1):
        difference = original_offsets[index] - replacement_offsets[index]
        suffix_minimum = min(suffix_minimum, difference)
        targets[index] = max(0, min(total_padding, suffix_minimum))
    # The first picture must remain in the initial video PES with its P-STD
    # descriptor; any padding needed for later pictures starts after it.
    targets[0] = 0
    return targets


def video_pstd_buffer_bound(
    original: bytes, video_packets: list[tuple]
) -> int:
    """Read the video P-STD bound from the first original video PES."""
    pack_index, start, end, payload_at, _ = video_packets[0]
    base = pack_index * PACK_SIZE
    packet = original[base + start : base + end]
    if not (packet[7] & 0x01) or payload_at < 22:
        raise ValueError("first video PES has no P-STD buffer descriptor")
    extension_flags = packet[19]
    if not (extension_flags & 0x10):
        raise ValueError("first video PES extension has no P-STD buffer field")
    field_hi, field_lo = packet[20:22]
    if field_hi & 0xC0 != 0x40:
        raise ValueError("invalid P-STD buffer field marker")
    scale = 1024 if field_hi & 0x20 else 128
    size_bound = ((field_hi & 0x1F) << 8) | field_lo
    return scale * size_bound


def buffer_aware_payload_plan(
    original: bytes,
    video_packets: list[tuple],
    video: bytes,
    replacement_timestamps: list[tuple[int, int]],
    minimum_decode_lead_ticks: int,
) -> tuple[list[int], dict[str, int]]:
    """Schedule ES bytes as late as possible without overflowing P-STD.

    The pack/SCR/audio layout is fixed.  A smaller replacement elementary
    stream therefore has to be paced with program-stream padding rather than
    poured continuously into every video slot.  Work backwards from each
    picture's decode deadline, while retaining the first picture in the first
    video PES so its original P-STD descriptor remains in force.
    """
    picture_offsets = [item[0] for item in picture_timestamps(video)]
    if len(picture_offsets) != len(replacement_timestamps):
        raise ValueError("replacement picture/timestamp counts differ")
    picture_ends = picture_offsets[1:] + [len(video)]
    picture_starts = [0] + picture_offsets[1:]
    picture_sizes = [
        end - start for start, end in zip(picture_starts, picture_ends)
    ]

    capacities = [item[4] for item in video_packets]
    slot_clocks: list[int] = []
    latest_clock = 0
    for pack_index, _start, _end, _payload_at, _capacity in video_packets:
        base = pack_index * PACK_SIZE
        pack = original[base : base + PACK_SIZE]
        # A TOD2 file contains two tiny backward SCR steps.  Physical packet
        # arrival cannot go backwards, so use its monotonic envelope.
        latest_clock = max(latest_clock, pack_scr_27mhz(pack))
        slot_clocks.append(latest_clock)

    allocations = [0] * len(video_packets)

    # Keep picture zero (including the sequence preamble) at the beginning.
    # Otherwise the only PES carrying the original P-STD descriptor would be
    # empty and a later ordinary PES would initialize the first picture.
    first_deadline = (
        replacement_timestamps[0][1] - minimum_decode_lead_ticks
    ) * 300
    need = picture_sizes[0]
    slot_index = 0
    while need:
        if slot_index >= len(allocations) or slot_clocks[slot_index] > first_deadline:
            raise ValueError("first replacement picture misses its decode deadline")
        take = min(need, capacities[slot_index])
        remainder = capacities[slot_index] - take
        if 0 < remainder < 6:
            # Leave a legal six-byte minimum padding PES and carry the handful
            # of ES bytes into the following slot.
            take -= 6 - remainder
        allocations[slot_index] = take
        need -= take
        slot_index += 1
    first_picture_last_slot = slot_index - 1
    if picture_offsets[0] >= allocations[0]:
        raise ValueError("first picture start is not in the first video PES")

    # Assign every later picture into the latest slots that precede its decode
    # deadline.  Reuse a partial slot only for the tail of a picture that began
    # earlier; fitting a whole picture there would put two starts in one PES.
    slot_index = len(allocations) - 1
    for picture_index in range(len(picture_sizes) - 1, 0, -1):
        deadline = (
            replacement_timestamps[picture_index][1]
            - minimum_decode_lead_ticks
        ) * 300
        while (
            slot_index > first_picture_last_slot
            and slot_clocks[slot_index] > deadline
        ):
            slot_index -= 1
        need = picture_sizes[picture_index]
        while need:
            if slot_index <= first_picture_last_slot:
                raise ValueError(
                    f"insufficient pre-decode capacity for picture {picture_index}"
                )
            if slot_clocks[slot_index] > deadline:
                slot_index -= 1
                continue
            free = capacities[slot_index] - allocations[slot_index]
            if free == 0:
                slot_index -= 1
                continue
            if allocations[slot_index] and need <= free:
                # This entire picture would add a second start to the PES.
                slot_index -= 1
                continue
            take = min(need, free)
            allocations[slot_index] += take
            need -= take
            if not need:
                remainder = capacities[slot_index] - allocations[slot_index]
                if 0 < remainder < 6:
                    # Move at most five leading bytes of this picture segment
                    # into the preceding slot so this one can end in a legal
                    # minimum-size padding PES.
                    move = 6 - remainder
                    if take < move:
                        raise AssertionError(
                            "cannot legalize a tiny buffer-aware remainder"
                        )
                    allocations[slot_index] -= move
                    need = move
            if need:
                slot_index -= 1

    if sum(allocations) != len(video):
        raise AssertionError("buffer-aware plan does not consume the whole ES")
    for index, (take, capacity) in enumerate(zip(allocations, capacities)):
        remainder = capacity - take
        if 0 < remainder < 6:
            raise ValueError(
                f"video slot {index} leaves an illegal {remainder}-byte remainder"
            )

    # Verify the one-picture-start-per-PES property and locate completion time
    # for every picture in the scheduled elementary stream.
    cumulative_ends: list[int] = []
    source_at = 0
    for packet_index, take in enumerate(allocations):
        packet_end = source_at + take
        first = bisect.bisect_left(picture_offsets, source_at)
        after = bisect.bisect_left(picture_offsets, packet_end)
        if after - first > 1:
            raise AssertionError(
                f"video slot {packet_index} contains more than one picture start"
            )
        source_at = packet_end
        cumulative_ends.append(source_at)

    minimum_lead = None
    for picture_index, picture_end in enumerate(picture_ends):
        packet_index = bisect.bisect_left(cumulative_ends, picture_end)
        decode_clock = replacement_timestamps[picture_index][1] * 300
        lead = decode_clock - slot_clocks[packet_index]
        minimum_lead = lead if minimum_lead is None else min(minimum_lead, lead)
    assert minimum_lead is not None
    if minimum_lead < minimum_decode_lead_ticks * 300:
        raise AssertionError("buffer-aware plan violates its decode lead")

    arrivals: dict[int, int] = defaultdict(int)
    removals: dict[int, int] = defaultdict(int)
    for clock, take in zip(slot_clocks, allocations):
        arrivals[clock] += take
    for timestamps, size in zip(replacement_timestamps, picture_sizes):
        removals[timestamps[1] * 300] += size

    occupancy = 0
    maximum_occupancy = 0
    for clock in sorted(set(arrivals) | set(removals)):
        occupancy -= removals[clock]
        if occupancy < 0:
            raise ValueError(
                f"video P-STD underflow of {-occupancy:,} bytes at {clock / 27_000_000:.6f}s"
            )
        occupancy += arrivals[clock]
        maximum_occupancy = max(maximum_occupancy, occupancy)
    if occupancy:
        raise AssertionError(f"video P-STD finishes with {occupancy:,} bytes")

    buffer_bound = video_pstd_buffer_bound(original, video_packets)
    if maximum_occupancy > buffer_bound:
        raise ValueError(
            "replacement cannot fit the original P-STD buffer: "
            f"maximum={maximum_occupancy:,}, bound={buffer_bound:,}"
        )
    metrics = {
        "maximum_occupancy": maximum_occupancy,
        "buffer_bound": buffer_bound,
        "minimum_lead_27mhz": minimum_lead,
        "padding_slots": sum(
            take != capacity
            for take, capacity in zip(allocations, capacities)
        ),
    }
    return allocations, metrics


def fill_video_capacity_with_user_data(
    video: bytes,
    capacity: int,
    target_picture_offsets: list[int],
    packet_ends: list[int],
) -> bytes:
    """Expand an elementary stream without creating extra program-stream packets.

    TOD2's movie demuxer is sensitive to the thousands of 0xBE padding PES
    packets produced when a replacement encode is smaller than the original.
    MPEG user-data start codes are ignored by the picture decoder, so distribute
    the spare bytes between pictures and keep the original video PES layout full.
    """
    if len(video) > capacity:
        raise ValueError("video is larger than its packet capacity")
    if len(video) == capacity:
        return video

    picture_offsets = [item[0] for item in picture_timestamps(video)]
    if len(picture_offsets) != len(target_picture_offsets):
        raise ValueError("replacement and target picture counts differ")

    def add_user_data(result: bytearray, size: int) -> None:
        if size < 4:
            raise ValueError("MPEG user-data filler must be at least four bytes")
        result.extend(START + b"\xB2")
        result.extend(b"\xFF" * (size - 4))

    result = bytearray()
    source_at = 0
    previous_slot = -1
    source_size = len(video)
    for picture_offset in picture_offsets:
        result.extend(video[source_at:picture_offset])
        source_at = picture_offset
        desired = (picture_offset * capacity) // source_size
        picture_position = max(len(result), desired)
        slot_index = bisect.bisect_right(packet_ends, picture_position)
        if slot_index == previous_slot:
            picture_position = packet_ends[slot_index]
            slot_index += 1
        filler_size = picture_position - len(result)
        if 0 < filler_size < 4:
            filler_size = 4
        if filler_size:
            add_user_data(result, filler_size)
        slot_index = bisect.bisect_right(packet_ends, len(result))
        if slot_index == previous_slot:
            raise AssertionError("two replacement pictures still share a video PES packet")
        previous_slot = slot_index

    tail = video[source_at:]
    sequence_end = tail.rfind(START + b"\xB7")
    if sequence_end >= 0:
        result.extend(tail[:sequence_end])
        remaining = capacity - len(result) - len(tail[sequence_end:])
        if remaining >= 4:
            add_user_data(result, remaining)
        result.extend(tail[sequence_end:])
    else:
        result.extend(tail)

    remaining = capacity - len(result)
    if remaining:
        if remaining < 4:
            # Extend the final user-data payload; 0xFF cannot form a start code.
            result[-4:-4] = b"\xFF" * remaining
        else:
            add_user_data(result, remaining)
    if len(result) != capacity:
        raise AssertionError("user-data filling did not reach video capacity")
    if len(picture_timestamps(bytes(result))) != len(picture_offsets):
        raise AssertionError("user-data filling changed the picture count")
    return bytes(result)


def remux(
    original_path: Path,
    video_path: Path,
    output_path: Path,
    fill_video_capacity: bool = False,
    stuff_pes_headers: bool = False,
    buffer_aware: bool = False,
    minimum_decode_lead_ms: float = 50.0,
) -> dict[str, int]:
    original = original_path.read_bytes()
    video = video_path.read_bytes()
    pack_count, video_packets, audio_packets, audio_bytes = inspect_original(original)
    capacity = sum(item[4] for item in video_packets)
    if len(video) > capacity:
        raise ValueError(
            f"new video is {len(video):,} bytes but original capacity is only {capacity:,} bytes"
        )
    original_video = bytearray()
    packet_ends = []
    cumulative_packet_capacity = 0
    for pack_index, start, end, payload_at, _slot_capacity in video_packets:
        base = pack_index * PACK_SIZE
        packet = original[base + start : base + end]
        original_video.extend(packet[payload_at:])
        cumulative_packet_capacity += _slot_capacity
        packet_ends.append(cumulative_packet_capacity)

    if fill_video_capacity:
        unfilled_video_size = len(video)
        target_picture_offsets = [item[0] for item in picture_timestamps(bytes(original_video))]
        video = fill_video_capacity_with_user_data(
            video, capacity, target_picture_offsets, packet_ends
        )
        print(f"video_user_data_filler={len(video) - unfilled_video_size:,}")

    original_timestamps = original_picture_timestamps(
        original, video_packets, bytes(original_video)
    )
    replacement_picture_offsets = [item[0] for item in picture_timestamps(video)]
    replacement_picture_types = [
        (video[offset + 5] >> 3) & 7 for offset in replacement_picture_offsets
    ]
    padding_targets = replacement_padding_targets(
        bytes(original_video), video, capacity
    )
    if len(replacement_picture_offsets) != len(original_timestamps):
        raise ValueError(
            "replacement has a different frame count: "
            f"original={len(original_timestamps):,}, "
            f"replacement={len(replacement_picture_offsets):,}"
        )
    replacement_timestamps = replacement_picture_timestamps(
        bytes(original_video), video, original_timestamps
    )
    payload_plan = None
    buffer_metrics = None
    if buffer_aware:
        if fill_video_capacity or stuff_pes_headers:
            raise ValueError(
                "--buffer-aware cannot be combined with ES filling or PES stuffing"
            )
        minimum_decode_lead_ticks = round(minimum_decode_lead_ms * 90)
        payload_plan, buffer_metrics = buffer_aware_payload_plan(
            original,
            video_packets,
            video,
            replacement_timestamps,
            minimum_decode_lead_ticks,
        )

    result = bytearray(original)
    source_at = 0
    cumulative_capacity = 0
    stamped_pictures = 0
    multi_picture_packets_avoided = 0
    for video_packet_index, (
        pack_index,
        start,
        end,
        payload_at,
        slot_capacity,
    ) in enumerate(video_packets):
        capacity_before = cumulative_capacity
        cumulative_capacity += slot_capacity
        picture_index = bisect.bisect_left(replacement_picture_offsets, source_at)
        if payload_plan is not None:
            target = source_at + payload_plan[video_packet_index]
        elif stuff_pes_headers:
            target = (len(video) * cumulative_capacity) // capacity
        else:
            # Keep the original optional-header lengths and spend the available
            # size difference only as legal padding in continuation packets.
            target = min(len(video), source_at + slot_capacity)
            if picture_index < len(replacement_picture_offsets):
                distance_to_picture = (
                    replacement_picture_offsets[picture_index] - source_at
                )
                padding_emitted = capacity_before - source_at
                padding_needed = max(
                    0, padding_targets[picture_index] - padding_emitted
                )
                if distance_to_picture >= slot_capacity and padding_needed >= 6:
                    # This PES contains only continuation data, so shortening
                    # its payload cannot separate a picture from its timestamp.
                    legal_padding = min(padding_needed, slot_capacity)
                    target = source_at + slot_capacity - legal_padding
        if payload_plan is None and (
            picture_index + 1 < len(replacement_picture_offsets)
            and replacement_picture_offsets[picture_index + 1] < target
        ):
            # Keep one picture start per PES packet so every frame can carry
            # its own original timestamp. The encode has ample global slack,
            # and the following video packets absorb the deferred bytes.
            target = replacement_picture_offsets[picture_index + 1]
            multi_picture_packets_avoided += 1
        if payload_plan is None:
            minimum_to_finish = len(video) - (capacity - cumulative_capacity)
            target = max(target, minimum_to_finish)
        target = min(target, source_at + slot_capacity)
        take = target - source_at
        if take > slot_capacity:
            raise AssertionError("distribution exceeded a video packet's capacity")
        base = pack_index * PACK_SIZE
        template = original[base + start : base + end]
        stamp = None
        if (
            picture_index < len(replacement_picture_offsets)
            and replacement_picture_offsets[picture_index] < source_at + take
        ):
            stamp = replacement_timestamps[picture_index]
            stamped_pictures += 1
        rebuilt = rebuild_video_packet(
            template,
            video[source_at : source_at + take],
            stamp,
            (
                replacement_picture_types[picture_index]
                if stamp is not None
                else None
            ),
            stuff_pes_header=stuff_pes_headers,
        )
        if len(rebuilt) != len(template):
            raise AssertionError("rebuilt packet changed its slot size")
        result[base + start : base + end] = rebuilt
        source_at += take

    if source_at != len(video):
        raise AssertionError(f"only consumed {source_at:,} of {len(video):,} video bytes")
    if len(result) != len(original):
        raise AssertionError("output size changed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result)
    print(f"packs={pack_count:,}")
    print(f"video_packets={len(video_packets):,}")
    print(f"video_capacity={capacity:,}")
    print(f"new_video={len(video):,} ({len(video) / capacity:.2%} of capacity)")
    print(f"original_picture_timestamps={len(original_timestamps):,}")
    print(f"replacement_pictures_stamped={stamped_pictures:,}")
    print(f"multi_picture_packets_avoided={multi_picture_packets_avoided:,}")
    print(f"audio_packets_preserved={audio_packets:,}")
    print(f"audio_packet_bytes_preserved={audio_bytes:,}")
    if buffer_metrics is not None:
        print(
            "video_pstd_maximum="
            f"{buffer_metrics['maximum_occupancy']:,}/"
            f"{buffer_metrics['buffer_bound']:,}"
        )
        print(
            "minimum_decode_lead_ms="
            f"{buffer_metrics['minimum_lead_27mhz'] / 27_000:.3f}"
        )
        print(f"video_padding_slots={buffer_metrics['padding_slots']:,}")
    print(f"output_size={len(result):,}")
    metrics = {
        "packs": pack_count,
        "video_packets": len(video_packets),
        "video_capacity": capacity,
        "new_video": len(video),
        "frames": len(original_timestamps),
        "audio_packets": audio_packets,
        "audio_packet_bytes": audio_bytes,
        "output_size": len(result),
    }
    if buffer_metrics is not None:
        metrics.update(buffer_metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("video", type=Path, help="raw MPEG-2 elementary stream (.m2v)")
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--fill-video-capacity",
        action="store_true",
        help="fill spare video bytes with MPEG user data instead of padding PES packets",
    )
    parser.add_argument(
        "--stuff-pes-headers",
        action="store_true",
        help="place spare bytes in standard PES header stuffing when possible",
    )
    parser.add_argument(
        "--buffer-aware",
        action="store_true",
        help="pace video bytes against original SCR and the declared P-STD bound",
    )
    parser.add_argument(
        "--minimum-decode-lead-ms",
        type=float,
        default=50.0,
        help="require every complete picture this many milliseconds before DTS",
    )
    args = parser.parse_args()
    remux(
        args.original,
        args.video,
        args.output,
        args.fill_video_capacity,
        args.stuff_pes_headers,
        args.buffer_aware,
        args.minimum_decode_lead_ms,
    )


if __name__ == "__main__":
    main()
