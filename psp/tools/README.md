# PSP tools (ULJS-00097)

Scripts for the PSP version. Python 3, standard library only. Nothing here
contains game data; everything reads the files you extract from your own
UMD image.

## psp_iso.py: files in the ISO

```
python psp/tools/psp_iso.py list game.iso
python psp/tools/psp_iso.py replace game.iso out.iso /PSP_GAME/USRDIR/file.fpb=new.fpb /PSP_GAME/SYSDIR/EBOOT.BIN=BOOT.BIN
```

Plain ISO9660 reader/writer: a replacement that fits in the original sector
span goes in place, a larger one is appended at the end of the image and the
directory record and volume size are updated (what UMDReplace does, in
Python). To pull a file out, use `list` for the LBA and size, or any ISO
tool.

`PSP_GAME/SYSDIR/BOOT.BIN` on this UMD is already the decrypted executable
(plain PRX), so no `deceboot` step is needed. Builds write the modified
BOOT.BIN to both `BOOT.BIN` and `EBOOT.BIN`.

## psp_fpb.py: the archive

```
python psp/tools/psp_fpb.py extract BOOT.BIN file.fpb FPB
python psp/tools/psp_fpb.py pack BOOT.BIN file.fpb FPB new_file.fpb new_BOOT.BIN
```

The member table (9,636 u32 entries) sits in BOOT.BIN at
`0x29531C..0x29E9AC`: high bits = start offset (sector aligned), low 11
bits = bytes between the member's end and the next sector boundary.
`extract` writes every member decompressed as `FPB/00000.bin` and so on plus
`FPB/manifest.json`. `pack` copies untouched members byte for byte from the
original archive (the game's deflate streams cannot be reproduced with
zlib), recompresses edited ones with zlib, pads to sectors, and writes the
new table into a copy of BOOT.BIN. Packing an untouched extraction gives
back the original archive and executable bit for bit.

Compressed members: byte `04`, u32 packed length, u32 unpacked length, raw
deflate. A raw container with four entries also starts with `04 00 00 00`;
the tools tell them apart by the packed length matching the stored size.

## ascii_test.py: how does the PSP draw Latin text?

```
python psp/tools/ascii_test.py "Tales of Destiny 2 (Japan).iso" test_ascii.iso
```

Builds a test image from your own dump (ULJS-00097, UMD, CRC-32 9DE4F587).
Four lines of the opening scene in Cresta Forest are replaced, in place,
by `Hurry, hurry!`, `abcdefghijklmnop`, `ABCDEFGHIJKL` and a line of
half-width katakana (ｱｲｳｴｵ ｶｷｸｹｺ ﾋﾛｦ). The plain executable is written as
BOOT.BIN and EBOOT.BIN, nothing else changes.

Run it in PPSSPP (or on a PSP with custom firmware), start a new game and
screenshot Cinnamon's first lines. What we want to know:

1. Does the image boot with the unencrypted EBOOT.BIN?
2. Do the letters show as full-width capitals (expected, the retail font
   has no lowercase and maps `a..z` onto `A..Z`) or something else?
3. How many characters fit on one line before it wraps?
4. Does the katakana line display?

The answers decide how the English text will be rendered (half-width
glyphs need a small change in the executable, since the engine advances
one full cell per character today).
