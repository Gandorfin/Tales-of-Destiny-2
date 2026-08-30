"""Instruction boundaries for ULJS00097 SCED bytecode.

Widths are from the retail interpreter (PSP runtime addresses): constants
089520E4, text references 08952204, variables 08952260, native calls 08952374,
branches/calls 0895562C..08955720, argument binding 08955724. Unknown or
truncated instructions fail closed; never fall back to a raw F8-byte scan.
"""
import struct


def regions(data):
    if len(data) < 12 or data[:4] != b'SCED':
        raise ValueError('not a SCED file')
    code, text = struct.unpack_from('<II', data, 4)
    if not 12 <= code <= text <= len(data):
        raise ValueError('invalid SCED code/text boundaries')
    return code, text


def instructions(data):
    """Yield (offset, opcode, size), excluding operands and text bytes."""
    p, end = regions(data)

    def require(at, size):
        if at + size > end:
            raise ValueError(f'truncated SCED instruction at 0x{at:X}')

    def variable_size(at):
        require(at, 1)
        op = data[at]
        if op == 0xFE:
            return 1
        if op >= 0x80:
            raise ValueError(f'invalid argument variable at 0x{at:X}')
        return 3 if op & 8 else 2

    while p < end:
        op = data[p]
        if op < 0x80 or op == 0xFE:
            size = variable_size(p)
        elif op < 0xC0:
            size = (1, 2, 3, 5)[(op >> 4) & 3]
        elif op < 0xE0 or op in (0xF0, 0xF1):
            size = 1
        elif op < 0xF0:
            size = 2
        elif op in (0xF2, 0xF3, 0xF4, 0xF5) or 0xF8 <= op <= 0xFB:
            size = 3
        elif op == 0xF6:
            require(p, 2)
            size = 2
            for _ in range(data[p + 1]):
                size += variable_size(p + size)
        else:
            raise ValueError(f'unsupported SCED opcode 0x{op:02X} at 0x{p:X}')
        require(p, size)
        yield p, op, size
        p += size


def text_operands(data):
    """Addresses of genuine 16-bit F8 operands, even if their target is zero."""
    return {p + 1 for p, op, _ in instructions(data) if op == 0xF8}


def validate_code_changes(original, rebuilt):
    """Only real text-reference operands may change in the code region."""
    code, text = regions(original)
    if regions(rebuilt) != (code, text) or original[:code] != rebuilt[:code]:
        raise ValueError('SCED header/code boundaries changed')
    allowed = {p + k for p in text_operands(original) for k in (0, 1)}
    changed = [p for p in range(code, text)
               if original[p] != rebuilt[p] and p not in allowed]
    if changed:
        raise ValueError('non-text bytecode changed: ' + ', '.join(hex(p) for p in changed[:12]))
    if list(instructions(original)) != list(instructions(rebuilt)):
        raise ValueError('SCED instruction boundaries changed')
