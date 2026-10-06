#!/usr/bin/env python3
"""Apply and verify the PSP ASCII half-width renderer patch with armips."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
ARMIPS = os.path.join(ROOT, 'Project tools', 'armips-v0.11.0', 'armips.exe')
ASM = os.path.join(HERE, 'psp_halfwidth.asm')

# vaddr, original instruction, patched instruction (little endian)
PATCHES = (
    (0x13ECA8, bytes.fromhex('21 98 C0 03'), bytes.fromhex('42 98 1E 00')),
    (0x13ECD4, bytes.fromhex('06 00 1E A6'), bytes.fromhex('06 00 13 A6')),
)


def _check(data, expected_index):
    for vaddr, original, patched in PATCHES:
        off = vaddr + 0xC0
        expected = (original, patched)[expected_index]
        actual = data[off:off + 4]
        if actual != expected:
            raise ValueError('renderer instruction %08X: expected %s, found %s' %
                             (vaddr, expected.hex(), actual.hex()))


def patch_file(path, armips=ARMIPS):
    """Patch BOOT.BIN in place through a verified temporary armips output."""
    if not os.path.exists(armips):
        raise FileNotFoundError('armips not found: ' + armips)
    _check(open(path, 'rb').read(), 0)
    out = path + '.halfwidth.tmp'
    if os.path.exists(out):
        os.remove(out)
    try:
        subprocess.run([
            armips, ASM, '-erroronwarning',
            '-strequ', 'input_file', os.path.abspath(path),
            '-strequ', 'output_file', os.path.abspath(out),
        ], cwd=ROOT, check=True)
        data = open(out, 'rb').read()
        _check(data, 1)
        if len(data) != os.path.getsize(path):
            raise ValueError('armips unexpectedly changed BOOT.BIN size')
        os.replace(out, path)
    finally:
        if os.path.exists(out):
            os.remove(out)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: psp_halfwidth.py INPUT_BOOT OUTPUT_BOOT')
    shutil.copyfile(sys.argv[1], sys.argv[2])
    patch_file(sys.argv[2])
    print('half-width ASCII renderer patched:', sys.argv[2])
