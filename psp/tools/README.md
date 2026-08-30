# PSP tools (ULJS-00097)

Scripts for the PSP version. Python 3, standard library only. Supply your own
clean UMD image; no game binaries are part of the source release.

This directory is the collaborator build, including the confirmed Elrane
scene-freeze repair. See [CHANGELOG.md](CHANGELOG.md) for the changes and
[GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) for source-only upload instructions.

## Repository layout and prerequisites

Keep this folder at `psp/jazz tools` inside the Tales-of-Destiny-2 repository.
Commands below run from that repository's root. The tools also use:

- `ps2/PyTOD2/TBL.json` for the shared text encoding table;
- `Third pass Quality-Safe Output` for the scenario translation corpus;
- `third pass skits safe output` for the skit translation corpus;
- the `.tsv` and `TBL_PSP.json` files included alongside these scripts.

The source release is an overlay for that repository, not a standalone ISO
patcher. Tests need the shared encoding table but do not need a game image.

## psp_iso.py: files in the ISO

```
python "psp/jazz tools/psp_iso.py" list game.iso
python "psp/jazz tools/psp_iso.py" replace game.iso out.iso /PSP_GAME/USRDIR/file.fpb=new.fpb /PSP_GAME/SYSDIR/EBOOT.BIN=BOOT.BIN
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
python "psp/jazz tools/psp_fpb.py" extract BOOT.BIN file.fpb FPB
python "psp/jazz tools/psp_fpb.py" pack BOOT.BIN file.fpb FPB new_file.fpb new_BOOT.BIN
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
python "psp/jazz tools/ascii_test.py" "Tales of Destiny 2 (Japan).iso" test_ascii.iso
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

## build_psp.py: the English build in one command

```
python "psp/jazz tools/build_psp.py" "Tales of Destiny 2 (Japan).iso" tod2_psp_en.iso
python "psp/jazz tools/build_psp.py" "Tales of Destiny 2 (Japan).iso" tod2_psp_test.iso --probe
```

Takes a clean ULJS-00097 UMD dump and writes a new image with every
scenario and skit script carrying the English from the PS2 translation.
About two minutes and 3 GB of temporary space. The output image is larger
than the original (the archive grows and is appended at the end of the
image). `--probe` also puts two width test lines into the opening scene
(a row of `i` over a row of `M`, and a long pangram) so we can see how the
engine spaces Latin letters. This build also applies menu/name translations,
monster-name replacements, lowercase glyphs, the apostrophe-preserving glyph
allocation, and the isolated bold-font table. No separate freeze-repair helper
or post-build memory patch is required: the normal build uses the fixed scanner.

Use a new output filename and, if using `--keep`, a new work directory. Do not
point the build at your only copy of an earlier image or edited extraction.

## psp_text.py: scenario and skit text

```
python "psp/jazz tools/psp_text.py" extract BOOT.BIN file.fpb WORK
python "psp/jazz tools/psp_text.py" match WORK
python "psp/jazz tools/psp_text.py" build BOOT.BIN file.fpb WORK new.fpb new_BOOT.BIN
python "psp/jazz tools/psp_text.py" verify new_BOOT.BIN new.fpb WORK
```

The steps `build_psp.py` runs, for working on the text by hand. `extract`
writes one text file per script in the same format as the PS2 files (one
record per block, dashed separators, tags as `<Kyle>`, `<color:...>`,
`{XX}`), plus `pointers.json` with the position of every text pointer.
`match` looks each Japanese record up in the translated PS2 files ("Third
pass Quality-Safe Output", "third pass skits safe output") and writes the
English versions into `WORK/scenario_en` and `WORK/skit_en`, Japanese kept
as `#` lines; whatever it could not match is listed in `WORK/unmatched.tsv`
(mostly developer comments and debug menus). Edit those files, then
`build`. `verify` decodes the built archive and compares every record.

How insertion works: the original text block stays in place, changed records
are appended, and only their validated text pointers are redirected. Scripts
whose text would exceed the 64 KB pointer range rebuild the text block.

### Scene-freeze safety fix (2026-08-30)

`psp_sced.py` decodes instruction widths before accepting `F8 xx xx` text
references. An `F8` byte inside a branch, constant, variable, or argument-list
operand is not a text opcode. The previous raw-byte scan accepted 12 false
entries on this disc and missed 26 genuine references. One false entry
corrupted the transition routine after Kyle's first meeting with Elrane.

Both append and rebuild paths now validate saved pointer metadata and assert
that all non-text code bytes and instruction boundaries remain unchanged.
Unknown/truncated instructions fail closed. Old metadata containing false
entries raises an error asking for re-extraction; do not reuse it or adjust
translation blocks by index after the pointer list changes. Carry translations
forward using the script ID and genuine pointer-operand address instead.

The older empty/out-of-order-string heuristic remains only as a translation
selection policy for compatibility. It is no longer the bytecode safeguard.

Regression tests, from the repository root:

```
python -B -m unittest discover -s "psp/jazz tools" -p test_psp_sced.py -v
```

Test a corrected ISO with a fresh boot and an ordinary in-game save from before
the scene. A frozen save state can retain the old corrupt script in RAM even
after selecting a new ISO. Existing saves and older ISOs need not be deleted.

The reporter confirmed that the corrected build progresses past the Elrane
freeze. This confirms that reproduction, not a complete playthrough of every
scene in the game.

`TBL_PSP.json` lists 522 text codes that `ps2/PyTOD2/TBL.json` never had.
They were derived from the PSP font's glyph list (archive member 00001,
Shift-JIS code per glyph) and the game's own decoder, and agree with all
1,782 existing entries; they apply to the PS2 as well.
