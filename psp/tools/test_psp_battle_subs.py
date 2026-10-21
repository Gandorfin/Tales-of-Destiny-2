"""Tests for psp_battle_subs.py (no game files needed)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mips_asm  # noqa: E402
import psp_battle_subs as B  # noqa: E402

LOAD = 0x08804000       # where the PSP kernel puts BOOT.BIN


class Machine:
    """Just enough of an Allegrex to run the hook: the instructions it uses,
    delay slots, and stubs for the game functions it calls."""

    def __init__(self, stubs):
        self.mem, self.stubs = {}, stubs
        self.r = [0] * 32

    def read(self, a, n, signed=False):
        return int.from_bytes(bytes(self.mem.get(a + i, 0) for i in range(n)), 'little', signed=signed)

    def write(self, a, n, v):
        for i, x in enumerate((v & ((1 << 8 * n) - 1)).to_bytes(n, 'little')):
            self.mem[a + i] = x

    def load(self, a, blob):
        for i, x in enumerate(blob):
            self.mem[a + i] = x

    def string(self, a):
        out = bytearray()
        while self.mem.get(a, 0):
            out.append(self.mem[a])
            a += 1
        return out.decode()

    def is_branch(self, pc):
        w = self.read(pc, 4)
        return w >> 26 in (1, 3, 4, 5, 6) or (w >> 26 == 0 and w & 63 in (8, 9))

    def step(self, pc):
        """Execute one instruction; returns (branch target or None, link register or None)."""
        r, w = self.r, self.read(pc, 4)
        op, rs, rt, rd, sa, fn = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31, w & 63
        imm = (w & 0xFFFF) - 0x10000 if w & 0x8000 else w & 0xFFFF
        rel = (pc + 4 + (imm << 2)) & 0xFFFFFFFF
        out = (None, None)
        if op == 0:
            if fn == 0x21: r[rd] = (r[rs] + r[rt]) & 0xFFFFFFFF
            elif fn == 0x23: r[rd] = (r[rs] - r[rt]) & 0xFFFFFFFF
            elif fn == 0x00: r[rd] = (r[rt] << sa) & 0xFFFFFFFF
            elif fn == 0x02: r[rd] = r[rt] >> sa
            elif fn == 0x08: out = (r[rs], None)
            elif fn == 0x09: out = (r[rs], rd)
            else: raise ValueError('function %#x at %#x' % (fn, pc))
        elif op == 3: out = ((pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2), 31)
        elif op == 1 and rt == 0x11: out = (rel, 31) if r[rs] < 0x80000000 else (None, 31)
        elif op == 4: out = (rel if r[rs] == r[rt] else None, None)
        elif op == 5: out = (rel if r[rs] != r[rt] else None, None)
        elif op == 6: out = (rel if r[rs] == 0 or r[rs] >= 0x80000000 else None, None)
        elif op == 9: r[rt] = (r[rs] + imm) & 0xFFFFFFFF
        elif op == 11: r[rt] = int(r[rs] < (imm & 0xFFFFFFFF))
        elif op == 12: r[rt] = r[rs] & (w & 0xFFFF)
        elif op == 13: r[rt] = r[rs] | (w & 0xFFFF)
        elif op == 15: r[rt] = (w & 0xFFFF) << 16
        elif op in (32, 33, 35, 36, 37):
            n, signed = {32: (1, 1), 33: (2, 1), 35: (4, 0), 36: (1, 0), 37: (2, 0)}[op]
            r[rt] = self.read((r[rs] + imm) & 0xFFFFFFFF, n, bool(signed)) & 0xFFFFFFFF
        elif op in (40, 41, 43):
            self.write((r[rs] + imm) & 0xFFFFFFFF, {40: 1, 41: 2, 43: 4}[op], r[rt])
        else:
            raise ValueError('opcode %#x at %#x' % (op, pc))
        r[0] = 0
        return out

    def call(self, pc, ret, limit=50000):
        """Run from pc, entered with ra = ret, until the code returns there."""
        self.r[31] = ret
        for _ in range(limit):
            if pc == ret:
                return
            if pc in self.stubs:
                self.stubs[pc](self.r)
                pc = self.r[31]
                continue
            if not self.is_branch(pc):
                self.step(pc)
                pc += 4
                continue
            target, link = self.step(pc)
            self.step(pc + 4)                          # delay slot
            if link is not None:
                self.r[link] = pc + 8
            pc = target if target is not None else pc + 8
        raise RuntimeError('the code did not return')


def row(vid, speaker, english):
    return {'voice_id': str(vid), 'speaker': speaker, 'english': english}


def run_hook(party, enemies, voices, rows, vwf=True):
    """Run the hook the way the battle loop calls it, on a fake battle.
    party: character indexes; enemies: how many; voices: {slot: id}, the
    enemies start at slot 4. Returns ([(text, x, y)], frame calls, v0)."""
    drawn, frames = [], []
    m = Machine({})

    def frame(r):
        frames.append(r[4])
        r[2] = 0x77
    m.stubs = {LOAD + B.FRAME: frame,
               LOAD + B.TEXT: lambda r: drawn.append((m.string(r[6]), r[4], r[5], r[7], r[8], r[9]))}
    data, _ = B.build_data(rows, B.advances(vwf))
    origin = B.POOL_VADDR + 0x100
    code, _ = B.hook_code(origin, data)
    m.load(LOAD + origin, code)
    g = LOAD + B.GLOBALS
    actors = 0x08E0F840
    m.write(g + B.PARTY, 4, actors)
    m.write(g + B.ENEMIES, 4, actors + 4 * B.ACTOR_SIZE)
    m.write(g + B.PARTY_SIZE, 1, len(party))
    m.write(g + B.ENEMY_COUNT, 1, enemies)
    for slot, who in enumerate(party):
        m.write(actors + slot * B.ACTOR_SIZE + B.CHARACTER, 1, who)
    for i in range(enemies):
        m.write(actors + (4 + i) * B.ACTOR_SIZE + B.ENEMY, 1, 1)
    for slot, vid in voices.items():
        m.write(actors + slot * B.ACTOR_SIZE + B.VOICE, 2, vid)
    m.r[29] = 0x09FFF000
    m.r[4] = 0x1234                                    # the frame function's argument
    saved = list(m.r)
    m.call(LOAD + origin, LOAD + B.RET)
    for reg in (16, 17, 18, 19, 20, 21, 22, 23, 29, 30):
        assert m.r[reg] == saved[reg], 'register %d not restored' % reg
    return drawn, frames, m.r[2]


class HookTests(unittest.TestCase):
    ROWS = [row(82, '*', 'You gave us a lot of trouble.'), row(700, '', 'Boss line.'),
            row(5, '*', ''), row(256, '*', "That's the essence of victory!")]

    def test_frame_function_still_runs(self):
        drawn, frames, v0 = run_hook([0, 2], 1, {}, self.ROWS)
        self.assertEqual(frames, [0x1234])         # once, with the caller's a0
        self.assertEqual(v0, 0x77)                 # its result goes back to the loop
        self.assertEqual(drawn, [])

    def test_party_and_enemies(self):
        # party of two: the enemy is in slot 4, not slot 2
        drawn, _, _ = run_hook([0, 2], 1, {0: 82, 4: 700}, self.ROWS)
        self.assertEqual([d[0] for d in drawn], ['Kyle: ', 'You gave us a lot of trouble.', 'Boss line.'])
        name, line, boss = drawn
        self.assertEqual(line[1], name[1] + B.width('Kyle: ', B.advances()))
        self.assertEqual(line[2], B.BOTTOM)
        self.assertLess(boss[2], line[2])           # the second speaker stacks above
        for d in drawn:
            self.assertEqual(d[3:], (B.COLOUR, B.XSCALE, B.YSCALE))

    def test_name_comes_from_the_actor(self):
        drawn, _, _ = run_hook([2, 0], 0, {0: 256}, self.ROWS)
        self.assertEqual(drawn[0][0], 'Loni: ')

    def test_silent_and_untranslated(self):
        self.assertEqual(run_hook([0, 1, 2], 2, {1: 5}, self.ROWS)[0], [])

    def test_wrapped_lines_centred(self):
        rows = [row(100, '', 'word ' * 30)]
        drawn, _, _ = run_hook([1], 0, {0: 100}, rows)
        self.assertGreater(len(drawn), 1)
        adv = B.advances()
        for text, x, y, *_ in drawn:
            self.assertLessEqual(B.width(text, adv), B.LINE_W)
            self.assertLessEqual(abs(x + B.width(text, adv) / 2 - B.SCREEN_W / 2), 1)
        self.assertEqual(drawn[-1][2], B.BOTTOM)
        self.assertEqual([d[2] for d in drawn], sorted(d[2] for d in drawn))


def fake_boot():
    """A BOOT.BIN shaped image: three program headers, the frame call, a pool
    segment ending the file."""
    b = bytearray(0x200000)
    struct.pack_into('<I', b, 0x1C, 0x34)
    struct.pack_into('<H', b, 0x2C, 3)
    struct.pack_into('<8I', b, 0x34, 1, 0xC0, 0, 0, 0x194278, 0x194278, 7, 64)
    struct.pack_into('<8I', b, 0x54, 1, 0x1DCD00, 0x1DCC00, 0, 0x1000, 0x6A3C48, 6, 256)
    struct.pack_into('<8I', b, 0x74, 1, len(b) - 0x100, B.POOL_VADDR, 0, 0x100, 0x100, 6, 16)
    struct.pack_into('<I', b, B.FRAME_CALL + B.TEXT_BIAS, B.frame_call_word(B.FRAME))
    return bytes(b)


class BootTests(unittest.TestCase):
    def test_patch(self):
        boot = fake_boot()
        out, info = B.patch_boot(boot, [row(82, '*', 'We did it!')])
        hook = int(info['hook_vaddr'], 16)
        self.assertEqual(struct.unpack_from('<I', out, B.FRAME_CALL + B.TEXT_BIAS)[0], B.frame_call_word(hook))
        p = struct.unpack_from('<8I', out, 0x74)
        self.assertEqual(p[1] + p[4], len(out))
        self.assertEqual(p[4], p[5])
        # nothing else changes: only the frame call and the pool header's sizes
        changed = {i // 4 * 4 for i in range(len(boot)) if out[i] != boot[i]}
        self.assertEqual(changed, {B.FRAME_CALL + B.TEXT_BIAS, 0x74 + 16, 0x74 + 20})
        self.assertEqual(out[p[1] + hook - B.POOL_VADDR + info['code_bytes']:][:4], B.MAGIC)
        with self.assertRaises(ValueError):
            B.patch_boot(out, [row(82, '*', 'We did it!')])     # applied twice

    def test_table_problems_stop_the_build(self):
        with self.assertRaises(ValueError):
            B.patch_boot(fake_boot(), [row(82, '*', 'word ' * 80)])

    def test_shipped_table(self):
        rows = B.read_table()
        for vwf in (True, False):
            self.assertEqual(B.problems(rows, B.advances(vwf)), [])
        data, count = B.build_data(rows, B.advances())
        self.assertGreater(count, 300)

    def test_frame_call_is_a_relocated_jal(self):
        # the word the patch retargets: jal 0x1B2F4, R_MIPS_26 against the text segment
        self.assertEqual(B.frame_call_word(B.FRAME), 0x0C006CBD)
        self.assertEqual(B.RET - B.FRAME_CALL, 8)


if __name__ == '__main__':
    unittest.main()
