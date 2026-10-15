# PSP tools (ULJS-00097)

Scripts for the PSP version. The build tools use Python 3's standard library;
the standalone PNG font tool additionally requires Pillow. Supply your own
clean UMD image; no game binaries are part of the source release.

This directory is the collaborator build, including the confirmed Elrane
scene-freeze repair. See [CHANGELOG.md](CHANGELOG.md) for the changes and
[GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) for source-only upload instructions.

## Standalone PNG font customization

Use [patch_font_iso.py](patch_font_iso.py) to export, prepare, validate and
reinsert the PSP dialogue font from a single 256x4400 PNG. It supports the
clean Japanese and collaborator translation ISOs, preserves glyph mappings,
and writes a verified ISO copy. Only that script and Pillow are needed.
See [FONT_CUSTOMIZATION.md](FONT_CUSTOMIZATION.md) for commands, compression
limits, the separate bold-menu-font limitation and retail startup handling.

## Repository layout and prerequisites

Keep this folder at `psp/tools` inside the Tales-of-Destiny-2 repository.
Commands below run from that repository's root.

### Where the PSP text lives: psp/text

The PSP build reads its text only from `psp/text`, the PSP's own copy of
the PS2 translation:

| `psp/text/...` | copy of | what |
|---|---|---|
| `scenario/` | `Third pass Quality-Safe Output/` | scenario English (459 files) |
| `skits/` | `third pass skits safe output/` | skit English (609 files) |
| `subtitles/` | `ps2/movies/subtitles/` | movie subtitles (`--movies`) |
| `TBL.json` | `ps2/PyTOD2/TBL.json` | text encoding table |
| `skit_speeds.json` | `ps2/PyTOD2/skit_speeds.json` | time window of every skit line |
| `overrides.tsv` | (PSP only) | PSP only fixes, they win over everything else |

The copies change only when the sync runs, so an edit of the PS2 text never
changes a PSP build by surprise, and the PSP build does not depend on what
the PS2 folders look like on the build machine. Rules:

* Edit the text in the PS2 folders (as before, both PS2 copies), then copy
  it over and commit `psp/text` in the same pull request. On Windows 11
  (PowerShell or Command Prompt, inside the cloned `Tales-of-Destiny-2`
  folder):

  ```
  python psp\tools\sync_text_from_ps2.py --check
  python psp\tools\sync_text_from_ps2.py
  ```

  `--check` only lists what differs (files and records changed, new,
  removed) and exits with 1 when `psp/text` lags behind; without it the
  tool copies those files. It writes nothing outside `psp/text`. The audit
  (`scripts/audit_translation.py`) shows the lag as the INFO line
  `psp-text-lag`, and the build prints it too.
* Never edit the copies in `psp/text` by hand: the next sync overwrites
  them. A line that must read differently on the PSP goes into
  `psp/text/overrides.tsv` (kind, PSP script number or `*`, the Japanese as
  the build extracts it, the English, a note; the format is described at
  the top of the file). The sync never touches that file.
* `psp_supplement.tsv` (this folder) stays what it was: English for PSP
  Japanese that has no PS2 twin, used only when nothing else matches.

Priority for each record: `overrides.tsv`, then the same line of the PS2
twin skit, then any PS2 record with the same Japanese, then
`psp_supplement.tsv`; otherwise the record stays Japanese.

Still read from `ps2/` (code and one binary that change only with the
tools, so a copy would just be a second place to keep in step):
`ps2/PyTOD2/skit_speed.py` (the skit speed rules),
`ps2/menu/title_credit.py` and `ps2/menu/title_glyphs.py` (the title
screen patch name) and `ps2/movies/fonts/Ubuntu-Bold.ttf` (the subtitle
font, with its licence there, only with `--movies`). So build from a full,
up to date clone, not from a copy of `psp` alone:

```
git pull
python psp\tools\build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_en.iso
```

The build first prints the repository folder, its commit and a fingerprint
of every source it reads (line endings do not change the fingerprint, so a
Windows and a Linux clone of the same commit print the same values). Two
builds with the same fingerprints carry the same text and skit timing. When
a source is missing, or `skit_speeds.json` predates the full length skit
retranslation, the build stops before it touches the ISO and names the
path. It also says whether `psp/text` is up to date with the PS2 folders
(information only: the build always uses `psp/text` as it is).

The source release is an overlay for that repository, not a standalone ISO
patcher. Tests need the shared encoding table but do not need a game image.

## psp_iso.py: files in the ISO

```
python "psp/tools/psp_iso.py" list game.iso
python "psp/tools/psp_iso.py" replace game.iso out.iso /PSP_GAME/USRDIR/file.fpb=new.fpb /PSP_GAME/SYSDIR/EBOOT.BIN=BOOT.BIN
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
python "psp/tools/psp_fpb.py" extract BOOT.BIN file.fpb FPB
python "psp/tools/psp_fpb.py" pack BOOT.BIN file.fpb FPB new_file.fpb new_BOOT.BIN
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
python "psp/tools/ascii_test.py" "Tales of Destiny 2 (Japan).iso" test_ascii.iso
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
python "psp/tools/build_psp.py" "Tales of Destiny 2 (Japan).iso" tod2_psp_en.iso
python "psp/tools/build_psp.py" "Tales of Destiny 2 (Japan).iso" tod2_psp_test.iso --probe
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

### Movie subtitles (`--movies`)

The English movie subtitles are only burned in when you pass `--movies`.
The commands above leave the Japanese movies untouched. Release build:

```
python -m pip install imageio-ffmpeg
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_en.iso --version 0.2.1 --movies
```

`--movies` needs an FFmpeg with libass and libx264. `python -m pip install
imageio-ffmpeg` provides one; `--ffmpeg C:\path\to\ffmpeg.exe` uses your own
(the build stops with "no FFmpeg with libass and libx264 found" if neither
works). It burns `ps2/movies/subtitles/*.en.srt` (PSP movie N = PS2 movie
N - 1, PSP 012 repeats 008) plus the PSP staff roll (`psp_credits.ass`) into
movie 006, re-encodes with the original H.264 settings and swaps the nine
`/PSP_GAME/USRDIR/movie/0NN.pmf` files in the output ISO. The log shows one
`movie 0NN (PS2 000NN):` block per movie; no such lines means the switch was
missing. To redo only the movies into a work folder:
`python psp/tools/psp_movies.py "Tales of Destiny 2 (Japan) PSP.iso" WORK`.

### Choosing the lowercase font hack

`--lowercase-font on` applies the collaborator's lowercase hack and is the
default, preserving existing build commands. `--lowercase-font off` builds
the same English translation with the original uppercase ASCII rendering:

```
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_lowercase_hack_v0.2.5.iso --version 0.2.5 --movies  --lowercase-font on
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_uppercase_v0.2.5.iso --version 0.2.5 --movies  --lowercase-font off
```

The `off` choice skips the lowercase glyph artwork, a..z slot remapping,
ASCII font-selection patches and private bold-menu table. The original font
member is copied unchanged. English text still contains its original case,
but the retail engine displays lowercase ASCII letters as capitals. Menu/name
and monster translations, the title credit (`--version`), text verification
and scene-freeze fix run in both modes. Character widths are unchanged.

Start from a clean Japanese PSP ISO; this switch is not a font-hack removal
tool for an already patched image. Use different output filenames for the
two variants. `--probe` and `--keep WORKDIR` work with either choice.

Font-choice regression tests (synthetic assets, no ISO required):

```
python -B -m unittest discover -s psp/tools -p test_build_psp.py -v
```

Use a new output filename and, if using `--keep`, a new work directory. Do not
point the build at your only copy of an earlier image or edited extraction.

## psp_text.py: scenario and skit text

```
python "psp/tools/psp_text.py" extract BOOT.BIN file.fpb WORK
python "psp/tools/psp_text.py" match WORK
python "psp/tools/psp_text.py" build BOOT.BIN file.fpb WORK new.fpb new_BOOT.BIN
python "psp/tools/psp_text.py" verify new_BOOT.BIN new.fpb WORK
```

The steps `build_psp.py` runs, for working on the text by hand. `extract`
writes one text file per script in the same format as the PS2 files (one
record per block, dashed separators, tags as `<Kyle>`, `<color:...>`,
`{XX}`), plus `pointers.json` with the position of every text pointer.
`match` looks each Japanese record up in the PSP text (`psp/text/scenario`,
`psp/text/skits`, `psp/text/overrides.tsv`) and writes the
English versions into `WORK/scenario_en` and `WORK/skit_en`, Japanese kept
as `#` lines; whatever it could not match is listed in `WORK/unmatched.tsv`
(mostly developer comments and debug menus). A skit line first takes the
English of the same line in its PS2 twin (PSP skit n = PS2 skit n - 159)
when the Japanese is the same, so a short line such as うん。 keeps the
wording of its own skit; the `skit` rows of `psp_supplement.tsv` cover the
few lines whose Japanese differs on the PSP. Edit those files, then
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
python -B -m unittest discover -s "psp/tools" -p test_psp_sced.py -v
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
