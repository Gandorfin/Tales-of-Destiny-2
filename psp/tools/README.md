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
| `quiz_translations.csv` | `ps2/menu/quiz_translations.csv` | Quiz Book English (`psp_quiz.py`) |
| `battle_subtitles.csv` | `ps2/menu/battle_subtitles.csv` | battle subtitles (`psp_battle_subs.py`) |
| `overrides.tsv` | (PSP only) | PSP only fixes, they win over everything else |

Skit text speed: PSP skit member n is PS2 skit n - 159, with the same line
cue times (checked for all 608 timed skits). Each line gets the PS2 window
from `skit_speeds.json` (the frames from its first glyph until the next line
starts, never less than the Japanese took) and the speed window // English
glyphs, so the English finishes revealing before the next speaker; rules
in `ps2/PyTOD2/skit_speed.py` and `TECHNICAL.md`. The build prints how many
lines got which speed.

The copies change only when the sync runs, so an edit of the PS2 text never
changes a PSP build by surprise, and the PSP build does not depend on what
the PS2 folders look like on the build machine. Never edit the copies in
`psp/text` by hand: the next sync overwrites them.

All commands below are for Windows 11 (PowerShell or Command Prompt),
run inside the cloned `Tales-of-Destiny-2` folder.

**A text fix that both versions need** (the usual case): edit the PS2 text
as before, in `Third pass Quality-Safe Output` or `third pass skits safe
output` and in its PS2 build copy (`ps2/PyTOD2/...`, the audit's
`source-drift` check makes sure both agree). Then, in the same branch:

```
python psp\tools\sync_text_from_ps2.py --check
python psp\tools\sync_text_from_ps2.py
python scripts\audit_translation.py
```

`--check` lists what differs (files, records changed, new and removed
files) without copying and exits with 1 when `psp/text` lags behind; the
second command copies exactly those files. The sync writes nothing outside
`psp/text`. Commit `psp/text` together with the PS2 change, so one pull
request carries both. When a changed record holds a choice code (`<03:...>`,
a menu such as the Skit Hut selector) the sync prints a `CHECK:` line: a
choice record must keep the Japanese line and code structure, or its menu
can stick (PR 107), so look at that record before you commit.

**A fix only the PSP needs** (the PSP Japanese differs, a PSP screen is
narrower, a PSP only line): add a row to `psp/text/overrides.tsv`: kind
(`scenario` or `skit`), the PSP script number as in the build's text
folder (`--keep WORKDIR`, then `WORKDIR/text/scenario/06944.txt`) or `*`,
the Japanese exactly as extracted (line breaks as `\n`), the English, and
a note why. The format is at the top of the file. A row there wins over
everything else and the sync never touches the file, so a later sync can
never undo it. The PSP's own Skit Hut "unavailable" record (06944) is
pinned there for that reason.

**Before a PSP build or release**: `git pull`, then
`python psp\tools\sync_text_from_ps2.py --check`. If it lists files,
somebody changed the PS2 text without syncing: run the sync, check the
`CHECK:` lines, commit `psp/text` in a small pull request, then build.

**What the audit shows**: `python scripts\audit_translation.py` prints the
INFO line `psp-text-lag` with the number of `psp/text` files that differ
from their PS2 source (0 when in step). It never fails the audit; the PSP
build simply does not have those PS2 changes yet. The build log says the
same in its first lines.

**Two branches that both synced**: `psp/text` conflicts exactly where the
PS2 files conflict. Resolve the PS2 files, then run the sync again instead
of resolving `psp/text` by hand.

`psp_supplement.tsv` (this folder) keeps its old job: English for PSP
Japanese that has no PS2 twin, used only when nothing else matches (it is
partly written by `psp_recover.py`, so it is not the place for hand fixes).

Priority for each record: `psp/text/overrides.tsv`, then the same line of
the PS2 twin skit, then any PS2 record with the same Japanese, then
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

## psp_pool.py: menu strings longer than their slot

`build_psp.py` runs it after the in place menu patch. English that is
longer than its Japanese slot in BOOT.BIN goes into a new string pool (a
fourth program segment appended at the end of the file), and every
relocated reference to the Japanese string is pointed at the pool:

* 32 bit data pointers (R_MIPS_32);
* code that builds the address in a register (`lui` + `addiu`, relocated
  as an HI16/LO16 pair). The pair is rewritten only when every `addiu`
  sharing that `lui` builds the address of a pooled string; otherwise it
  stays on the Japanese and the build log names it (`menu pool: lui at
  ... left on the Japanese`).

A string that directly follows other bytes instead of a NUL (for example
名前入力 after a binary record at file 0x1C79F8) is taken only when a
relocation points exactly at it.

The pool header is first appended after the relocation header (header 3).
As the very last BOOT.BIN step, `build_psp.py` calls
`psp_pool.make_hardware_loadable`, which moves it between text and data
(text, pool, data, relocation) and renumbers the segment indices of every
relocation entry. Without that the PSP kernel (real PSP, PS Vita
Adrenaline) never loads the pool, because it only loads PT_LOAD headers that
follow each other and stops at the relocation header; PPSSPP loads it
either way. The build prints `hardware load layout: {...}` and stops if
`check_hardware_layout` finds a layout the kernel would load differently.

Tests (synthetic images, no ISO needed; they model both loaders):

```
python -B -m unittest discover -s psp/tools -p test_psp_pool.py -v
```

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
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_en.iso --version 0.3.6 --movies
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
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_lowercase_hack_v0.3.6.iso --version 0.3.6 --movies --lowercase-font on
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_uppercase_v0.3.6.iso --version 0.3.6 --movies --lowercase-font off
```

The `off` choice skips the lowercase glyph artwork, a..z slot remapping,
ASCII font-selection patches and private bold-menu table. The original font
member is copied unchanged. English text still contains its original case,
but the retail engine displays lowercase ASCII letters as capitals. Menu/name
and monster translations, the title credit (`--version`), text verification
and scene-freeze fix run in both modes. With `off` character widths are
the retail fixed widths (the variable width font needs the lowercase font).

Start from a clean Japanese PSP ISO; this switch is not a font-hack removal
tool for an already patched image. Use different output filenames for the
two variants. `--probe` and `--keep WORKDIR` work with either choice.

Font-choice regression tests (synthetic assets, no ISO required):

```
python -B -m unittest discover -s psp/tools -p test_build_psp.py -v
```

Use a new output filename and, if using `--keep`, a new work directory. Do not
point the build at your only copy of an earlier image or edited extraction.

## psp_latin_font.py: one typeface for all English text

Draws every printable ASCII character from Fira Sans SemiBold
(`psp/fonts/FiraSans-SemiBold-ASCII.ttf`, SIL Open Font License, see
`psp/fonts/OFL.txt`) into font 1 and the bold menu font copy: one baseline,
one cap height and x-height, retail glyph style. The build reads the
committed table `psp/fonts/latin_glyphs.json` and needs no Pillow. To change
the look (another font, sizes, spacing), edit `FONT`, `FONT1`, `FONT2` in
the script and run

```
python psp\tools\psp_latin_font.py render
```

then rebuild and look at a text box, a skit and the menus.
`test_psp_latin_font.py` checks the table (one baseline, real descenders,
tabular digits).

## psp_vwf.py, psp_bold_lowercase.py: letter widths and bold lowercase

Both run inside `build_psp.py` with the lowercase font and `--vwf on`
(the defaults):

* `psp_bold_lowercase.py` builds a copy of font 2 (the small menu font in
  BOOT.BIN) with 26 lowercase letters drawn over hiragana cells 49..74 and
  maps `a..z` in the bold routine's private slot table to them. The letters
  are made from the dialogue font's lowercase, so both fonts match.
  `psp_vwf.py` stores the copy in the string pool and binds it for bold
  text that has no kana from those cells (the name entry keyboard keeps
  its kana). Result: "Kyle", "Normal", "Message Speed" instead of KYLE,
  NORMAL, MESSAGE SPEED.
* `psp_vwf.py` gives every single-byte character its own width (variable
  width font). It patches the
  six places that lay out or draw single-byte text: the text box layout,
  the text box glyph loop, the text printer (labels, choices, menus), the
  box measurer, the bold menu routine and the skit/battle ticker. The
  widths come from `psp/fonts/latin_glyphs.json`; digits share one width
  so number columns stay aligned.
  The code goes into the string pool segment; no new relocation entries.
* `mips_asm.py` is the small assembler the hooks are written in, so the
  build needs no armips. `test_psp_vwf.py` checks its output against
  armips v0.11.0 and that no patched word is one the loader relocates.

`--vwf off` builds without the width hooks and without the bold lowercase
(fixed width and bold capitals as before). Text boxes keep the line breaks
of the translation; they are just narrower now.

Testing a renderer change: build, start a NEW game (save states bring back
the old executable), check a text box, a skit, the main menu, Status and a
battle. Stock PPSSPP loads every program header, a real PSP does not
(TECHNICAL.md, "The pool's program header must sit between text and
data"); a code change still needs a test on hardware.

## psp_battle_subs.py: subtitles for the spoken battle lines

```
python psp/tools/psp_battle_subs.py check
```

`build_psp.py` runs this step on BOOT.BIN after the variable width font.
The PSP runs the PS2 battle engine, so it works like
`ps2/menu/battle_subs.py`: while a battle actor speaks, its record holds
the voice id (actor `+0x14A`); a hook called once per frame looks every
party actor and every enemy up in the table and draws the English, white,
centred, above the HP bars, with the speaking character's name in front
for rows whose speaker is `*`. A second speaker stacks above the first.
The hook and the table go to the end of the string pool; the frame call
at `0x1B27C` (a `jal`) gets the hook as its target. Addresses, record
layout and the reason this needs no new relocation: TECHNICAL.md, "PSP:
battle voices and battle subtitles".

The table is `psp/text/battle_subtitles.csv`, the PSP snapshot of
`ps2/menu/battle_subtitles.csv`: edit the PS2 table, run
`python psp/tools/sync_text_from_ps2.py`, commit both. The voice ids are
the same on both consoles. Lines are wrapped again by pixel width with the
letter widths of `psp/fonts/latin_glyphs.json` (at most three lines);
`check` reports a row that does not fit.

```
python -B -m unittest discover -s psp/tools -p test_psp_battle_subs.py -v
```

## psp_jpscan.py: which Japanese is still in a build

```
python psp/tools/psp_jpscan.py "Tales of Destiny 2 (Japan).iso" tod2_psp_en.iso OUTDIR
python psp/tools/psp_jpscan.py "Tales of Destiny 2 (Japan).iso" WORK OUTDIR --members 6335-6466
```

Read only: it writes nothing into either image. The second argument is the
English ISO or a `build_psp.py --keep WORK` folder (it reads `new_BOOT.BIN`
and `new.fpb` there); a `BOOT.BIN,file.fpb` pair also works for either side.
Both images are unpacked in lockstep (BOOT.BIN, every FILE.FPB member, down
through deflate, SCPK, PAK, offsets pack, sizes pack and comptoe LZSS
levels, each validated so plain data is not taken for a container) and
every Japanese string of the Japanese image is followed into the English
one; data embedded at an offset inside a leaf is covered because every
offset of every leaf is searched. Strings are tied to what points at them
(BOOT.BIN relocations, both data pointers and lui/addiu code pairs, the
SCED text operands and the SFM string references of the Quiz Book), so it
can tell "the game still draws this Japanese" from "the old bytes are
still there but nothing reads them". `--members A-B` limits the FPB part to a member range (BOOT.BIN is
always scanned), `--jobs N` sets the worker count. A full disc takes about
10 minutes with one worker per CPU.

Output files in OUTDIR:

* `summary.md`: overview, start here. Duplicates first, then the counts per
  category and area, then the top high confidence groups.
* `groups.tsv`: one row per distinct Japanese text, with its category,
  confidence, number of copies, the English found in the build or in a
  project table (and which table), and where it is still Japanese.
* `occurrences.tsv`: one row per location (leaf path such as
  `06470/z/s2/z`, offset, status, reference sites). Paths: `z` = deflate
  wrapper, `l` = LZSS stream, `sN` = SCPK entry, `pN` = PAK entry, `oN` =
  offsets pack entry (u32 count, then offsets; the title pack 00002),
  `nN` = sizes pack entry (u32 count, then sizes; the Quiz Book packs
  06333, 06334, 06366, 06467, 07310, 09272..09276 and most of
  09347..09565).
* `duplicates.tsv`: every text stored at two or more locations, with the
  state of every copy (translated, live, unreferenced, no reference model).
* `leaf_duplicates.tsv`: byte identical leaves or members stored more than
  once, partially patched clusters first.
* `table_duplicates.tsv`: the same run of 3+ strings in two places, the
  usual sign of a second table the game reads.
* `boot_partial.tsv`: BOOT.BIN strings where some pointers were redirected
  to the English and others still reach the Japanese.
* `graphics.tsv`: picture, sound and movie leaves (Japanese drawn into
  pixels is not text; check those by eye).

Categories in `groups.tsv`:

* `missed_copy`: translated in one place, still Japanese in another. The
  English exists; only that copy was never patched.
* `known_unapplied`: never translated in the build, but a project table
  (the PSP tsv files, the PS2 menu, enemy, title and quiz tables, or the
  scenario and skit text in `psp/text`) has a translation.
* `untranslated`: Japanese with no translation anywhere.
* `residue`: every copy translated, redirected or no longer referenced.

Confidence: `high` = a reference site provably points at the text,
`medium` = real looking text (4+ Japanese characters, or 2+ stored twice)
in a leaf without a reference model, `low` = short fragments. Reference
kinds in `ref_sites`: `f8` = SCED text operand, `sfm` = SFM string
reference, `ptr0`/`ptr1` = 32 bit pointer relative to segment 0/1,
`code0`/`code1` = lui/addiu pair.

How to read a scan (lessons from October 2026, when two scans already
listed the world map labels and about 100 shop names and both were missed):

* Run it again after every change to the scanner and before every PSP
  release. An old scan does not see what the scanner learned later (the
  15 October scan predates sizes pack support, so the world map scripts
  in 09272..09276 had no reference sites).
* Check every `known_unapplied` and `missed_copy` row on its own. Look at
  `ref_sites` in `occurrences.tsv`: `ptr` means a plain data pointer, so
  the menu tools should reach it, and a miss is a tooling bug (that is how
  the full-width space key bug showed up); only `code` rows are the known
  "address built in code" problem.
* The area column says where a member sits, not whether the player sees
  it. World map scripts are `map:sced` (live text).

Tests (synthetic data, no ISO needed):

```
python -B -m unittest discover -s psp/tools -p test_psp_jpscan.py -v
```

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

## psp_quiz.py: the Quiz Book

```
python psp/tools/psp_quiz.py report BOOT.BIN file.fpb quiz.tsv
python psp/tools/psp_quiz.py verify BOOT.BIN file.fpb new_BOOT.BIN new.fpb
python psp/tools/psp_quiz.py check
```

`build_psp.py` runs this pass and its check on its own; the commands are
for looking at it by hand. Every quiz is one `SFM_` script module, the same
format as the PS2 members 06171..06301 that `ps2/menu/sfm_text.py`
translates (see the PS2 menu README, "Quiz Book"); the PSP modules are
deflate wrapped instead of LZSS packed. The disc holds every module five
times, and which copy the game loads is not known, so all are translated:

* the loose members 06335..06466 (06366 is not a module);
* 06333: a sizes pack (u32 count, u32 sizes, children back to back) with
  the three quiz pictures and all 131 modules, identical to the loose ones;
* 06334: the same pack built from the debug variant of the modules (longer
  bytecode, and developer sample quizzes in the slots that are empty stubs
  elsewhere; those 165 sample strings have no English and stay Japanese);
* 06366 (modules 06335..06365) and 06467 (modules 06367..06466).

PSP module N holds PS2 member N - 164 up to 06365 and N - 165 from 06367
on. Where the English comes from, per string, matched by the exact
Japanese:

* `psp_quiz.tsv` (this folder) first: the 201 Japanese strings the PSP
  release rewrote or added (no PS2 row has them), plus the one PS2 line
  that does not fit its PSP slot (shortened there);
* otherwise `psp/text/quiz_translations.csv` (the PSP copy of
  `ps2/menu/quiz_translations.csv`, refreshed by `sync_text_from_ps2.py`
  like the rest of `psp/text`), rows of the matching PS2 member.

Writing is `sfm_text.SFM.apply`, the PS2 tool's own logic: English that
fits the Japanese slot goes in place, longer English is appended to the
module's data section and every reference to the old string redirected.
A string whose references cannot be proven to be pointers ("pinned") must
fit its slot or stays Japanese and is reported as overflow (none at the
moment). The module code is the PS2 tool's, but the glyph table is the
PSP one (`psp/text/TBL.json` plus `TBL_PSP.json`, with the blank `○` of
the fill in puzzles, `α`, `β`), so no string is hidden from the pass by
an unknown code. ASCII `~` is written as the full width
`～`, because the PSP's ASCII table draws `~` as a dash.

`report` prints the counts for a Japanese archive and writes every string
of every copy with its source (`ps2`, `psp` or `none`) to the tsv.
`verify` compares a built archive with the Japanese one: every reference
to a translated string must lead to its English, the bytecode must be
unchanged apart from those references and the pack pictures untouched.
`check` encodes every English line of both tables and flags lines of the
PSP table over 40 characters or over four rows.

Tests (synthetic modules, no ISO needed):

```
python -B -m unittest discover -s psp/tools -p test_psp_quiz.py -v
```

## psp_worldmap.py: world map labels and scripts

```
python psp/tools/psp_worldmap.py report BOOT.BIN file.fpb
python psp/tools/psp_worldmap.py verify BOOT.BIN file.fpb new_BOOT.BIN new.fpb
python psp/tools/psp_worldmap.py check
```

`build_psp.py` runs this pass and its check on its own. Members
09272..09276 are sizes packs, one per era of the world map; child 19 of
each is the world map field script, an uncompressed SCED. Its strings are
the big location name shown when the party walks up to a town or dungeon
("Laguna Ruins", "Cresta"), signposts and mine entrance labels, the inn on
the map, treasure messages, the box puzzle, the Draconis anchor scene, the
Ixifoslar controls and the ending monologue. These are the PSP twins of
the PS2 world map scripts `09028..09032.pak0`.

English comes from `psp_worldmap.tsv` (this folder; Japanese, English,
source), matched by the exact decoded record with its control codes. Most
rows reuse the PS2 world map English (`ps2/menu/menu_translations.csv`),
with the PS2 slot cuts undone because the PSP script can grow ("Laguna
Ruins", "Lienea", "Crimson City Speranza"); 14 PSP only strings are
translated there (the box puzzle help names the SELECT menu, the
Ixifoslar controls, a Shrine of Light sign, debug lines). Writing is the
scenario writer `psp_text.insert_sced` in append mode: the English goes
after the text block and each F8 operand is redirected, the bytecode keeps
its length, every other child of the pack is copied byte for byte. The
scripts grow by about 2 to 3.5 KB each.

`verify` decodes every F8 reference of a built archive and compares it
with the table. Tests (synthetic scripts plus the real table):

```
python -B -m unittest discover -s psp/tools -p test_psp_worldmap.py -v
```
