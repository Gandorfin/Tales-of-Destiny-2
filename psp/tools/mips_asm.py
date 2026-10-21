#!/usr/bin/env python3
"""Tiny MIPS (Allegrex) assembler for the few code patches the PSP build makes.

Only the instructions our hooks use are supported, so the build needs no
external assembler (Gandorff builds on Windows with plain Python). Syntax is
close to armips: `op arg, arg`, `label:`, registers by name, immediates in
decimal or 0x hex, `hi(expr)` / `lo(expr)` for lui/addiu pairs (lo is signed,
hi is carry-adjusted), branch targets by label or absolute address.

    a = Asm(base_vaddr)
    a.op('lui', 'at', ('hi', target))
    a.label('loop')
    a.op('bnez', 't0', 'loop')
    code = a.assemble()

psp/tools/test_psp_vwf.py checks the encodings against bytes produced by
armips v0.11.0 for the same source.
"""
import struct

REGS = {n: i for i, n in enumerate(
    'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 '
    's0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split())}
REGS['s8'] = 30

# R-type: funct; I-type: opcode; regimm / special encodings below
_R3 = {'addu': 0x21, 'subu': 0x23, 'and': 0x24, 'or': 0x25, 'slt': 0x2A, 'sltu': 0x2B}
_SHIFT = {'sll': 0x00, 'srl': 0x02, 'sra': 0x03}
_IMM = {'addiu': 0x09, 'slti': 0x0A, 'sltiu': 0x0B, 'andi': 0x0C, 'ori': 0x0D}
_MEM = {'lb': 0x20, 'lh': 0x21, 'lw': 0x23, 'lbu': 0x24, 'lhu': 0x25,
        'sb': 0x28, 'sh': 0x29, 'sw': 0x2B}
_UNSIGNED_IMM = {'andi', 'ori'}


def hi(v):
    """Upper half for a lui that pairs with a sign-extended lo()."""
    return ((v + 0x8000) >> 16) & 0xFFFF


def lo(v):
    return v & 0xFFFF


def _reg(r):
    if r not in REGS:
        raise ValueError('unknown register %r' % (r,))
    return REGS[r]


class Asm:
    def __init__(self, base):
        self.base = base
        self.items = []          # (vaddr, op, args)
        self.labels = {}
        self.pc = base

    def label(self, name):
        if name in self.labels:
            raise ValueError('label %s defined twice' % name)
        self.labels[name] = self.pc

    def op(self, name, *args):
        self.items.append((self.pc, name, args))
        self.pc += 4

    def data(self, blob):
        self.items.append((self.pc, '.data', (bytes(blob),)))
        self.pc += len(blob)

    def align(self, n):
        pad = (-self.pc) % n
        if pad:
            self.data(bytes(pad))

    def addr(self, x):
        if isinstance(x, str):
            if x not in self.labels:
                raise ValueError('undefined label %s' % x)
            return self.labels[x]
        return x

    def _imm(self, x):
        """int, label, ('hi'|'lo', expr) or ('hi'|'lo', label, offset)."""
        if isinstance(x, tuple):
            kind, val = x[0], self.addr(x[1])
            if len(x) > 2:
                val -= self.addr(x[2])
            return hi(val) if kind == 'hi' else lo(val)
        return self.addr(x)

    def _branch(self, pc, target, opword):
        off = (self.addr(target) - (pc + 4)) >> 2
        if not -0x8000 <= off < 0x8000:
            raise ValueError('branch out of range at %#x' % pc)
        return opword | (off & 0xFFFF)

    def encode(self, pc, name, a):
        if name == 'nop':
            return 0
        if name == 'move':
            return (_reg(a[1]) << 21) | (_reg(a[0]) << 11) | 0x21          # addu rd, rs, zero
        if name == 'li':
            v = self._imm(a[1])
            if 0 <= v <= 0xFFFF:
                return (0x0D << 26) | (_reg(a[0]) << 16) | v                # ori rt, zero, v (as armips)
            if -0x8000 <= v < 0:
                return (0x09 << 26) | (_reg(a[0]) << 16) | (v & 0xFFFF)     # addiu rt, zero, v
            raise ValueError('li needs a 16-bit value')
        if name in _R3:
            return (_reg(a[1]) << 21) | (_reg(a[2]) << 16) | (_reg(a[0]) << 11) | _R3[name]
        if name in _SHIFT:
            sa = self._imm(a[2])
            if not 0 <= sa < 32:
                raise ValueError('shift amount')
            return (_reg(a[1]) << 16) | (_reg(a[0]) << 11) | (sa << 6) | _SHIFT[name]
        if name in _IMM:
            v = self._imm(a[2])
            if name in _UNSIGNED_IMM:
                if not 0 <= v <= 0xFFFF:
                    raise ValueError('%s immediate out of range' % name)
            elif not -0x8000 <= v <= 0xFFFF:
                raise ValueError('%s immediate out of range' % name)
            return (_IMM[name] << 26) | (_reg(a[1]) << 21) | (_reg(a[0]) << 16) | (v & 0xFFFF)
        if name == 'lui':
            return (0x0F << 26) | (_reg(a[0]) << 16) | (self._imm(a[1]) & 0xFFFF)
        if name in _MEM:
            off, base = a[1], a[2]
            v = self._imm(off)
            if not -0x8000 <= v < 0x8000:
                raise ValueError('offset out of range')
            return (_MEM[name] << 26) | (_reg(base) << 21) | (_reg(a[0]) << 16) | (v & 0xFFFF)
        if name in ('mult', 'multu'):
            return (_reg(a[0]) << 21) | (_reg(a[1]) << 16) | (0x18 if name == 'mult' else 0x19)
        if name in ('mflo', 'mfhi'):
            return (_reg(a[0]) << 11) | (0x12 if name == 'mflo' else 0x10)
        if name == 'jr':
            return (_reg(a[0]) << 21) | 0x08
        if name == 'jalr':
            return (_reg(a[0]) << 21) | (31 << 11) | 0x09
        if name == 'beq':
            return self._branch(pc, a[2], (0x04 << 26) | (_reg(a[0]) << 21) | (_reg(a[1]) << 16))
        if name == 'bne':
            return self._branch(pc, a[2], (0x05 << 26) | (_reg(a[0]) << 21) | (_reg(a[1]) << 16))
        if name == 'beqz':
            return self._branch(pc, a[1], (0x04 << 26) | (_reg(a[0]) << 21))
        if name == 'bnez':
            return self._branch(pc, a[1], (0x05 << 26) | (_reg(a[0]) << 21))
        if name == 'blez':
            return self._branch(pc, a[1], (0x06 << 26) | (_reg(a[0]) << 21))
        if name == 'b':
            return self._branch(pc, a[0], 0x04 << 26)
        if name == 'bal':
            return self._branch(pc, a[0], (0x01 << 26) | (0x11 << 16))
        raise ValueError('unsupported instruction %s' % name)

    def assemble(self):
        out = bytearray()
        for pc, name, args in self.items:
            if name == '.data':
                out += args[0]
            else:
                out += struct.pack('<I', self.encode(pc, name, args))
        return bytes(out)

    def words(self):
        """[(vaddr, word)] for instructions only (call-site patches)."""
        return [(pc, self.encode(pc, n, a)) for pc, n, a in self.items if n != '.data']
