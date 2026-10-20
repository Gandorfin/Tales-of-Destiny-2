# Technical reference

Formats, offsets and rules of Tales of Destiny 2 (PS2 SLPS-25172, PSP
ULJS-00097) as far as this project has worked them out. It is written so a
person or an AI model with no history in the project can pick up any part of
the work. Every statement here is what the current tools rely on; where
something is unproven, it says so.

The player and build instructions are in [README.md](README.md). Deeper notes
per area live next to the tools: `ps2/menu/README.md` (PS2 menus, executable,
Quiz Book, enemy text, font), `ps2/movies/README.md` (PS2 movies),
`psp/tools/README.md` (PSP tools), `audio/README.md` (audio),
`Dialogue and Script Layout Restrictions.md` (text box limits).

## Contents

* [Text encoding (both versions)](#text-encoding-both-versions)
* [Scripts: SCPK and SCED](#scripts-scpk-and-sced)
* [Skits and the skit text speed](#skits-and-the-skit-text-speed)
* [PS2: FILE.FPB](#ps2-filefpb)
* [PS2: the executable SLPS_251.72](#ps2-the-executable-slps_25172)
* [PS2: menus, Quiz Book, enemy text](#ps2-menus-quiz-book-enemy-text)
* [PS2: movies](#ps2-movies)
* [PS2: building the image, releases](#ps2-building-the-image-releases)
* [PSP: the executable BOOT.BIN](#psp-the-executable-bootbin)
* [PSP: file.fpb](#psp-filefpb)
* [PSP: fonts and lowercase](#psp-fonts-and-lowercase)
* [PSP: menus and the string pool](#psp-menus-and-the-string-pool)
* [PSP: enemy names, movies, title](#psp-enemy-names-movies-title)
* [Rules learned the hard way](#rules-learned-the-hard-way)

## Text encoding (both versions)

* Two-byte glyph codes with lead bytes `0x99..0x9F` and `0xE0..0xE4`. The
  table is `ps2/PyTOD2/TBL.json` (code as decimal string to character);
  `psp/tools/TBL_PSP.json` adds codes the PS2 table never listed (decode
  only). The game's text is **not** Shift JIS.
* Single bytes `0x20..0x7E` are ASCII; `0xA1..0xDF` are half-width kana.
* `0x01` is a newline. A NUL ends the string.
* `0x03..0x0B` start a tag followed by a u32 argument: `0x04` colour,
  `0x05` size, `0x06` number, `0x07` party member name (1 Kyle, 2 Reala,
  3 Loni, 4 Judas, 5 Nanaly, 6 Harold), `0x08` item, `0x09` button. `0x03`
  marks a choice record, `0x0B` switches number mode: between `<0B:1>` and
  `<0B:0>` the game draws full-width capitals, so only digits and
  punctuation belong inside.
* `0x12`, `0x14..0x18` start a variable sequence that runs to the next
  `0xBC` or `0xC0` byte.
* The text tools write tags as `<color:00000002>`, `<Kyle>`, `<button:00000035>`
  and unknown bytes as `{XX}`; `scripts/HexToJpn.py`, `scripts/JpnToHex.py`
  and the website's converter pages do the same by hand.
* `TBL.json` is still missing codes. A string with an unknown code is
  invisible to every extractor, and a fragment of it can be written back
  over the real string. Codes added so far: `0x9FF3`, `0x9FC8`, `0xE27A`,
  `0xE28E`. After any table addition, rerun the extractors and diff their
  CSV output.

## Scripts: SCPK and SCED

* A scenario package (`SCPK`) holds a background, sprites, animations and,
  last, the `SCED` script. Header: magic, then at 8 a u32 member count, at
  16 one u32 size per member, then the members back to back.
* `SCED`: magic, u32 start of the code section, u32 start of the text
  section. The code is a bytecode whose instruction widths are known
  (`psp/tools/psp_sced.py`, taken from the retail interpreter). Opcode
  `0xF8` references text: its u16 operand is the string's offset inside the
  text section. Only real `0xF8` instructions count; an `0xF8` byte inside
  another instruction's operand is not one (scanning raw bytes once
  damaged a branch and froze a scene).
* Text is inserted by appending the changed records to the text section
  and redirecting only the validated `0xF8` operands. The operand is 16 bits,
  so a file whose text would pass 64 KB rebuilds its text section instead.
* Record format in the project's text files: one record per block, blocks
  separated by `-----------------------`, Japanese lines prefixed with `#`,
  English below. Control codes in the English must match the Japanese
  exactly (count, order, values).

## Skits and the skit text speed

* Skits are PAK files (see below) containing a `SCED`. PS2 skit files are
  in `FILE/pak1`; PSP skit member n is PS2 skit n - 159. The Skit Hut
  number is (file - 54) / 2 ("No 001" is 00056).
* Every skit line has a speed byte (frames per glyph) right before its
  `0xF8` text instruction (found by SkyBladeCloud). A skit line renders as
  one ticker line; two rows show, a line leaves when the line after next
  starts, and about 60 glyphs fit before the start scrolls away.
* A line starts at a fixed time, not when the previous text is done. Each
  skit plays one voice track (the FILE.FPB member right after the skit,
  `00066` plays `00067`), and before each line the script waits twice,
  `FE <push T> CE C0 F3 ..` and `FE <push T+3> CF C0 F3 ..`, T in frames
  (59.94 per second) since the skit started. T+3 is the line's cue. All
  2412 timed lines have one, in rising order. Measured on dreck's 1.3.0
  and Japanese recordings (2026-10-16): line changes in both languages land
  on the cues within 3 frames; the next line's box starts moving at its
  first wait (cue - 3), a line's first glyph appears about 13 frames after
  its cue, and the skit closes 4 frames after its voice track ends. Text
  still revealing when the next line starts keeps revealing in the upper
  row while the next speaker talks (seen in the 1.3.0 recording); the last
  line has until the skit closes.
* `ps2/PyTOD2/skit_speed.py` sets each line's speed from its window, the
  frames from its first glyph to the next line's box:
  `window = max(next cue - 3 - (cue + 13), original speed * Japanese glyphs)`
  (last line: `voice track frames + 4 - (cue + 13)`), then
  `speed = window // English glyphs`, at most the original, at least 1.
  So the English ends revealing before the next line starts, or no later
  than the Japanese where the Japanese itself runs past the cue. Budget
  (audit `skit-budget`): a line that fits one 60 glyph row may need a
  speed of 2 (30 glyphs per second, the fastest the Japanese game uses,
  in `00856_02`), a longer line scrolls and needs at least 3 (20 per
  second), never more than 384 characters. Original speeds and windows are
  stored in `ps2/PyTOD2/skit_speeds.json` (`skit_speed.py table <ISO>`
  rebuilds it from the retail ISO) so repeated builds do not keep speeding
  up. `00054_02` (the opening diary) is untimed and exempt. Until
  2026-10-16 the window was `max(original speed * Japanese glyphs, PR 18
  English glyphs * 7.5 frames)`; with it 1073 of 2412 lines were still
  revealing when the next line started (802 by more than half a second).
* Glyph counting for budgets: spaces count, a name tag counts as the name's
  letters, `<button:..>` is 1, `<char:..>` is 5, other codes 0.

## PS2: FILE.FPB

* The member table is in `SLPS_251.72` from `0xDD320`, one u32 per member:
  high bits are the start offset, the low 6 bits a remainder.
* Members use the game's LZSS/RLE compressor (`comptoe`); a pure Python
  port is `ps2/menu/lzss.py`. `PyTOD2` unpacks and repacks the archive.
* PAK containers (`pak0`, `pak1`, `pak3`): a u32 count, then count pairs of
  (u32 offset, u32 size), ascending.
* Menu text lives in the `md1` overlay modules inside the archive, not in
  the executable. Three modules (`08055`, `06304`, `08996`) are also stored
  compressed inside `00017.pak3`, and that copy is the one the game loads.
* Enemy packs (`ENd` scripts, pak1 member 1, LZSS v3): text is opcode
  `0x0A`, one argument byte, then an inline NUL string, with no pointers,
  so English is pinned to the Japanese byte count. The battle banner reads a
  24-byte name field in each enemy pack.

## PS2: the executable SLPS_251.72

| Offset | What |
|---|---|
| `0x000000` | ELF start |
| `0x0C9D00` | Latin font map: one byte per ASCII code, `0xC9D00 - 0x20 + ascii` is the glyph index |
| `0x0CA328` | Latin font texture (TM2) |
| `0x0DD320` | FILE.FPB member table |
| `0x0B7000` | party arte records, 28 bytes each (pointers to menu name, reading, description) |
| `0x0FE698` | `cdrom0:\SLPS_251.72`, the return path for the Venus & Braves preview |

* The shipped Latin font is the retail texture in the executable, redrawn
  by `ps2/menu/slps_font.py` (adds `&`, `~`, `*` in cells `4B`, `4C`, `4E`
  and remaps `0x26`, `0x7E`) and, since v1.2.3, replaced by dreck's font via
  `ps2/menu/patch_font_iso.py`. Never run PyTOD2's "Insert FONT": it inserts
  the unused 2008 font and drops those glyphs.
* The font TM2 has ten 4-bit palettes of `0x40` bytes with `0x10` byte
  subheaders, then a 128 x 512 4-bit pixel matrix, low nibble first.
* The arte cut-in banner shows the string after the arte's reading
  (`ps2/menu/slps_artes.py` writes "reading + menu name" and redirects the
  reading pointer).
* **The "spare" string area `0xFAB10..0xFC530` is libcdvd's work memory**,
  written at boot at `0xFAB10` (4 bytes), `0xFBCC0` (16), `0xFC100` (4) and
  `0xFC508` (40). `ps2/menu/patch_slps_titles.py` knows these ranges (`LIVE`)
  and stops at `0xFC508`. A second free area is the zero run
  `0x115E54..0x115F60`.

## PS2: menus, Quiz Book, enemy text

* Menu tables: `ps2/menu/menu_translations.csv` (file, offset, Japanese,
  English). After any change to its English column run
  `python ps2/menu/update_former_translations.py` and commit
  `menu_former_translations.csv`, otherwise a kept FPB folder freezes whole
  files at their old wording.
* The 2008 patch relocated many tables to English copies at the end of the
  modules, leaving the old Japanese bytes in place. Before translating a
  Japanese string in an md1, look for its English twin and check pointers,
  not bytes.
* The shop sell prompt bug ("iH*") was a 2008 pointer written over the
  string at `06803` `0x8A18` instead of into the pointer at `0x87A8`
  (`ps2/menu/shop_prompt.py` fixes it; `06803.md1` loads at `0x29BB00`).
* Quiz Book: `sfm` members, `ps2/menu/sfm_text.py` with
  `quiz_translations.csv`.
* Enemy artes and boss lines: `ps2/menu/enemy_text.py` with
  `enemy_translations.csv`; banner names `enemy_names.csv`.
* Title screen credit: a 4-bit TM2 texture (PS2 `00021.pak3` member 1,
  384 x 32); `ps2/menu/title_credit.py` draws "Green Gel vX.Y.Z" (the game
  shows only the first 96 pixels).
* Cooking recipe names and a few posters are drawn into textures, not text.

## PS2: movies

* The movies are in `MOVIE.FPB`, a separate archive. The ending staff roll
  is part of movie 5 (no text anywhere else).
* `ps2/movies/build_hardsubbed_movies.py` burns `ps2/movies/subtitles/*.en.srt`
  and the credits overlay (`ending_credits.ass`), `remux_ps2_movie.py` puts
  the video back into the original packs (audio byte for byte, original
  timing), `ps2/PyTOD2/Install-HardsubbedMovies.ps1` writes them into
  `MOVIE.FPB`. Details and limits: `ps2/movies/README.md`.
* Releases take `MOVIE.FPB` from the previous release, not from a rebuild:
  movies were edited after the subtitle files were last written, so a
  rebuild from `ps2/movies/subtitles` can lose changes. Compare with the
  released movies before replacing them.

## PS2: building the image, releases

* Build base: FILE.FPB and SLPS_251.72 of the ISO with the old (2008) Cless
  English menu patch (SLPS SHA-256 prefix 4833A2A0), not the Japanese ISO.
  Its FILE.FPB differs from retail in 38 md1 menu modules (06798..06835)
  and 551 battle pak1 packs; the menu tools expect those modules. Every
  other file of the Cless ISO is identical to the Japanese one, at the same
  sectors.
* `ps2/build_ps2.py` runs the whole build headless. It loads the part of
  `ps2/PyTOD2/PyTOD2.py` above the line `Graphical Interface Start` (the
  button functions) without a window; outside Windows the comptoe.exe calls
  go to `ps2/menu/lzss.py` (same stream format, not always byte identical,
  the game reads both).
* `ps2/menu/replace_iso_files.py` writes FILE.FPB, SLPS_251.72 and MOVIE.FPB
  into a copy of the Japanese ISO in place. Retail order on the disc:
  SLPS_251.72 at sector 289, MOVIE.FPB at 87440, FILE.FPB at 838649 and
  last, so only FILE.FPB may grow (into the area after it; the closing UDF
  anchor moves). Each file has one UDF short allocation descriptor whose
  length field holds the plain byte count even above 1 GB (retail does the
  same for file.FPB); the UDF names are lowercase on retail (file.FPB,
  movie.FPB). fix_disc_layout.fix then rounds the image to whole 16-sector
  blocks.
* Reproduction check (2026-10-20): the 1.3.0 commit built this way matches
  the released v1.3.0 image in 9,091 of 9,095 FILE.FPB members; the other
  four are merged fixes the release lacked.
* `verify_menu_patch.py` counts "Enemy extras" (Japanese literals in battle
  scripts with no table row): 34 in v1.3.0, 26 in v1.3.1. The release gate
  allows up to 26 and is strict on everything else.
* Release font: `ps2/menu/font-ready_final.png` (dreck), applied with
  `patch_font_iso.py` on the finished image.

## PSP: the executable BOOT.BIN

* `PSP_GAME/SYSDIR/BOOT.BIN` on the UMD is already the decrypted executable
  (a plain PRX). The build writes the patched one over both `BOOT.BIN` and
  `EBOOT.BIN`.
* Segments: text and rodata at vaddr `0x0`, file offset = vaddr + `0xC0`;
  data at vaddr `0x1DCC00`, file offset = vaddr + `0x100`. Runtime module
  base is `0x08804000` (runtime = vaddr + base), which maps debugger
  addresses back to the file.
* Relocations (section type `0x700000A0`, from file `0x29FB80`, 8 bytes
  each: u32 offset, u32 info). Info = type | ofsbase << 8 | addrbase << 16;
  the patched word's address is `ph[ofsbase].vaddr + offset`, the target
  is the stored value plus `ph[addrbase].vaddr`. Types: 2 = 32-bit data
  pointer, 5/6 = HI16/LO16 address pair built in code (`lui`/`addiu`),
  4 = jump target.
* A string can be reached through a data pointer, through a code address
  pair, or both. Rewriting only the data pointer leaves the screens that
  use the code path in Japanese (example: 防御回数 at file `0x1AB0D4`,
  data pointer redirected to "Block Count", `lui`/`addiu` at `0xFAE9C`
  still builds the old address).

## PSP: file.fpb

* The member table is in BOOT.BIN at `0x29531C..0x29E9AC`: high bits are
  the start (sector * `0x800`), the low 11 bits a remainder; a member ends
  `remainder` bytes before the next member's start. 9,636 members.
* Compressed members: byte `0x04`, u32 packed length, u32 unpacked length,
  raw deflate. Nested deflate entries inside containers use the same header
  and may carry 4 to 16 bytes of alignment padding. A raw container with
  four entries also starts with `04 00 00 00`; tell them apart by the
  packed length. The game's compressor is not stock zlib, so unchanged
  members are copied byte for byte (`psp/tools/psp_fpb.py`).
* Containers: `SCPK` (scenario), PAK as on PS2 (entries padded to 16
  bytes), deflate entries inside PAKs. Other leaf types seen: `MCD`, `MFH`,
  `MDL@`, `anp2`, `ENd` (enemy scripts), `SFM_` (Quiz Book), `TM2#`/`TM2@`
  (TIM2), `MIG.` (GIM), `RIFF`/`VAGp`/`MThd` (audio).
* Member 0 is the dialogue font, member 1 lists the Shift JIS code of every
  glyph in order. Story and skit voices, battle voices and music are mapped
  in `audio/`.

## PSP: fonts and lowercase

* Two fonts. **Font 0x01** = member 0: a swizzled 4-bit texture, 256 x 4400,
  23 pixel cells, 11 per row (`slot = row * 11 + col`, `A` = slot `0x17`).
  **Font 0x02** = a 128 x 512 icon/ASCII font in the executable (12 x 16
  cells, 10 per row) that most of the UI uses; it has no free cells. Its
  button glyphs use palette indices 7 to 14, coloured only in some of its
  ten palettes.
* Two-byte codes map to glyphs as `(lead - 0x99) * 187 + (second - 0x40)`
  with two skipped second-byte values (u16 code map at file `0x27DB40`).
  Single ASCII bytes go through an 8-bit slot table at file `0x27DD40`
  where `a..z` point at the same slots as `A..Z` (the uppercasing).
* Lowercase (SkyBladeCloud's method, `psp/tools/psp_lowercase.py`): draw
  `a..z` into font 0x01's free slots `0xD9`, `0xDA`, `0xDC..0xF3` (slot `0xDB`
  is the retail apostrophe), remap them in the slot table, and force the
  three ASCII text walkers to font 0x01: dialogue `0x13EEC4`, speaker names
  `0x143444`, menu/battle `0x14A084` (an `ori` whose low nibble is the
  font). A fourth routine, `0x144248` (wrapper `0x1464BC`), draws "bold"
  menu text (party names, menu tabs, Custom menu values, arte grid, Battle
  Rank, HP/TP/LV) with the icon font's geometry hard-coded; it gets its own
  copy of the retail table. Its two-byte path (the kana of the name entry
  keyboard) maps codes to font 0x02 cells through `0x144604` (low 8 bits).
  Since October 2026 the variable width font step gives it lowercase: a copy
  of font 0x02 with `a..z` drawn over hiragana cells 49..74 lives in the
  string pool (32 KB, pre-swizzled), `a..z` in the private table point at
  those cells, and a hook at the routine's start binds the copy
  (`sceGuTexImage` at `0x59E4`) unless the string has a two-byte code that
  `0x144604` maps to cells 49..74, so the keyboard keeps its kana. Font
  0x02 itself stays retail: it has no free cells (the bottom left block is
  the stone texture of the round "next" indicator).
* `--lowercase-font off` builds without all of this (the v0.2.1 build).

## PSP: text renderers and the variable width font

Verified in PPSSPP (debugger breakpoints and memory checks), October 2026.
Runtime address = vaddr + `0x08804000`.

* **Text boxes.** `0x13EADC` lays out one line into 10-byte glyph records at
  window + `0x2CC`: `[0]` font type, `[1]` reveal alpha, `[2]` colour, `[3]`
  unused in retail, `[4]` glyph slot, `[6]` width, `[8]` height (1/16 px).
  Single-byte path `0x13EE00..0x13EE44`, two-byte path `0x13EC94..0x13ECD8`,
  tags `0x13EFD8`. The glyph loop `0x140C7C` (font-1 sprite `0x140CE4`)
  draws each sprite from x to x + width and moves x by the same width.
  Before a box opens, `0x13E340` sizes it with the measuring walker
  `0x1426B4` (single-byte width `0x14283C..0x142868`).
* **Text printer.** Walker `0x142F0C` calls put-char `0x1432C0` (labels such
  as "notice", choices, item names, side panels). Single-byte path
  `0x143380..0x1433BC`; the font select at `0x143384` is the one the notes
  used to call the speaker name walker.
* **Ticker walker** `0x149E74` (skit lines, some battle and menu text): 8-byte
  records at object + `0x1BC`, `[0]` colour index << 4 | font, `[1]` reveal
  alpha, `[2]` glyph, `[4]` width = advance, `[6]` height. Draw loop
  `0x14A238`, font-1 sprite `0x14A380..0x14A4C8`.
* **Bold routine** `0x144248` (called only by the wrapper `0x1464BC` and
  by itself for inserted names): font 0x02 sprites, cell = slot (10 per
  row, 12 x 16), fixed advance `ctx[4]` at `0x144438..0x144448`. The
  wrapper binds font 0x02 with `sceGuTexImage(0, 128, 512, 128, ptr)`; the
  texture lives in bss at vaddr `0x54C7D0` (swizzled at startup).
* The menu tabs and other widgets (`0xF16C0`, `0xF5940`, `0xF5C8C`) draw
  through the bold routine or the text printer.
* Font 1 cells are 23 px but single-byte text draws them half a cell wide
  (about 9 x 11 px on screen, 22 % narrower than tall).

The Latin letters themselves (`psp/tools/psp_latin_font.py`, since PR 126):
every printable ASCII character is drawn from one font, Fira Sans SemiBold
(SIL Open Font License, `psp/fonts/`, subset to ASCII), into font 1 and into
the bold menu font copy, on one baseline with one cap height and x-height,
in the retail style (white fill, soft dark outline). Before that the PSP
mixed retail full-width capitals with two different sets of lowercase
letters, so lines bounced up and down. `python psp/tools/psp_latin_font.py
render` (Pillow) writes `psp/fonts/latin_glyphs.json`; the build reads only
that table. Sizes (cell pixels): font 1 cap height 13, baseline row 18;
font 2 cap height 10.6, baseline 12.6; descenders are squeezed just enough
to fit the cell. On screen a font 1 cell is about 16.5 px (0.72 of the
cell) in both directions when drawn a full cell wide, so the hooks draw
single-byte sprites a full cell wide (square, like kanji; SX = 512).
* Characters that share a slot (`-~_`, `(<{`, `)>}`, `:;`, `` "` ``) get the
  first one. Slots are shared with the full-width (two-byte) Latin codes, so
  full-width Latin text would show the narrow letters in wide full cells:
  `psp_menu.fullwidth_to_ascii` turns every standalone string of only
  full-width Latin, digits and punctuation in `.rodata`/`.data` (30 labels:
  ＮＥＷ　ＧＡＭＥ, ＨＰ, ＧＲＡＤＥ　ＳＨＯＰ...) into ASCII; runs longer than 16
  characters are data (the name entry alphabet) and stay.
* Font 1 has no room for separate Latin cells: it is 256 x 4400 = 191 rows
  of 11 cells (2101 glyphs), all used except a handful.

The variable width font (`psp/tools/psp_vwf.py`) hooks all of these:

* The width tables come from `latin_glyphs.json`: (pen position in the
  cell, advance) per slot, the font's own advances plus a little tracking;
  digits share one advance. The hooks also support a y offset and a
  horizontal squeeze per slot (all 0 now; the first version used them for
  descenders and the hyphen before the glyphs were redrawn).
* Layout hooks store the glyph's advance (line width, box size and ticker
  scrolling follow it); draw hooks draw the full sprite shifted left by the
  bearing and move the pen by the advance. Single-byte sprites are drawn a
  full cell wide (twice the retail half cell, square proportions).
* Records are told apart without new fields: the text box layout marks
  single-byte records with `[3] = 1` (the two-byte and tag paths now clear
  it), the ticker compares width and height (half-width cells are 0.8 times
  the height, kanji 1.6 times), the bold routine derives the cell from the
  texture coordinates it wrote.
* **Rules for code patches** (learned here): never overwrite a word the
  loader relocates (`lui`/LO16 users, `j`, `jal`: check
  `psp_pool._relocs`); keep them in place and patch around them. Reach new
  code without new relocation entries: build its address from a register
  that already holds a relocated address (the slot table in `v1`/`t7`/`a0`,
  data + `0xA0DE0` in `s2`) or from `ra` after a `bal`. New code lives in
  the string pool segment (the kernel ignores segment flags; Allegrex has no
  execute protection; loadcore flushes the caches after loading).
* Memory reads of code in PPSSPP show JIT markers (`0x68......`) instead of
  the real word; compare files, not RAM, when checking a patch.
* `psp/tools/patch_font_iso.py` exports, prepares, checks and patches PNG
  font sheets for both fonts (`psp/tools/FONT_CUSTOMIZATION.md`).

## PSP: menus and the string pool

* Menus are compiled into BOOT.BIN. `psp/tools/psp_menu.py` writes English
  that fits the Japanese slot in place (`psp_menu.tsv`). The full-width space
  must be encoded as `0x9940` (`{99}{40}`), the code retail menus use, on
  BOTH sides: the TBL encodes U+3000 as the filler `0xE499`, so until
  October 2026 every table key with a space (all shop names, scene titles)
  silently never matched (`psp_menu.encode_keys`).
* Longer strings go to a new load segment appended at the end of the file
  (`psp/tools/psp_pool.py`, vaddr `0x881000`, the program header fits the
  zero gap before `.text`); every standalone copy of the string has its
  32-bit data pointers and code address pairs rewritten.
* **The pool's program header must sit between text and data.** The PSP
  kernel (loadcore `sceKernelLoadExecutableObject`; a PS Vita in Adrenaline
  runs the same kernel) loads PT_LOAD headers only while they are
  consecutive from the first one, stops at the first other header (which
  must be the relocation header), counts at most 3 loaded segments, and
  zero-fills the bss of the last loaded segment only. PPSSPP loads every
  PT_LOAD header wherever it is. With the pool as header 3 after the
  relocation header (builds up to PSP 0.3.0) the pool was never loaded on
  hardware: blank or random pooled labels, a blank bold menu font table,
  and freezes when the game's own data reached that memory. The build's
  last step (`psp_pool.make_hardware_loadable`) reorders the headers to
  text, pool, data, relocation and renumbers the segment indices in every
  relocation entry (data 1 to 2, pool 3 to 1); `check_hardware_layout`
  refuses an image the kernel would load differently. Tools that parse
  relocations with fixed header indices must run before that step.
* Where a string starts (`psp_menu.string_start`, October 2026): after a NUL,
  unless that NUL is the end of a control code's 4-byte argument
  (`<button:00000036>` = `09 36 00 00 00`), or at any address the executable
  points at (`referenced_offsets`: data pointers and `lui`/`addiu` pairs),
  because some strings follow binary data with no NUL in front (リファイン
  after a float at `0x1C3A8C`). The menu table is applied longest key first.
  Before this, fragments inside button legends and confirmation dialogs were
  patched in place (決定 / Back), after which the whole record never matched.
* Code-built addresses (`psp_pool._code_pair_groups`): a run of HI16
  relocations and the LO16 entries after it. LO16 entries of another
  segment can sit between them (a data address finished with its own
  `lui` elsewhere); until October 2026 such an entry marked the whole run
  as mixed and dropped it, so 302 code-built string addresses (the Artes
  legend at `0x1C910C`, built at `0x128C24`/`0x128C28`, among them) were
  neither seen as string starts nor redirected to the pool. They are now
  skipped instead.
* `psp_menu.ADDRESSED` patches a few strings at one address only, where the
  same text needs other English elsewhere: the battle result fragments at
  `0x1F2390` (の, エンチャント, スキル, スペル, を習得), emptied like on the PS2
  so the enchant line reads "Loni: Increase Accuracy".
* BOOT.BIN contains one SCED script of its own at file `0x282F40`: the
  shared event for treasure chests and pickups (item obtained, inventory
  full, empty chest, Gald and Lens found, the Lens "take / put back" choice,
  game over epilogue, title earned). Its strings are reached only through
  its F8 operands, so menu tools never saw them.
  `psp/tools/psp_boot_script.py` and `psp_boot_script.tsv` rebuild its text
  area in place (588 bytes of room).
* Item and arte descriptions are two-line records `line1 0x01 line2` stored
  as one string; key them with `{01}` in the tables.
* The arte grid is drawn by the bold routine; it mangles any multi-byte
  trick, so long arte names were shortened. With the variable width font
  (October 2026) the names are narrower; whether the shortened names can get
  their full form back still needs a look at the grid in game.

## PSP: enemy names, movies, title

* Enemy and Monster Book names live in the battle-resource members around
  `08378..09565`, one PAK level deep and then inside a raw deflate blob, in
  the game encoding (`psp/tools/psp_monsters.py`, `psp_monsters.tsv`). The
  encounter banner at the start of a battle ("Owlbear  1") reads the TEKI
  list in member `08331` (PAK child 2, comptoe LZSS, codec
  `ps2/menu/lzss.py`): "TEKI" then 256 records of 28 bytes, a 24 byte name
  (game encoding, space padded) and 4 bytes of data; slot n = row n of
  `ps2/menu/enemy_names.csv`. `psp_monsters.patch_teki` writes English
  there (October 2026). The Monster Book screen most likely reads the same
  list; not yet seen in game.
* Movies: `/PSP_GAME/USRDIR/movie/0NN.pmf` (PSMF, H.264 + ATRAC3plus). PSP
  movie N is PS2 movie N - 1 frame for frame; PSP 012 repeats 008.
  `psp/tools/psp_movies.py` burns the PS2 subtitle tracks, `psp_pmf.py`
  rebuilds each navigation unit keeping audio and timing. The PSP staff roll
  differs from the PS2 one and has its own table (`psp_credits.tsv`).
  Retail video: H.264 Main profile, level 2.1, CABAC, one reference frame,
  no B frames and no weighted prediction (PPS weighted_pred_flag 0). x264
  enables weighted P frames by default; PSP 0.3.2 (checked) shipped movies
  with it (flag 1 in every PPS of 002 to 006, 008, 009, 011, 012). The
  encoder now passes `weightp=0` and refuses a unit whose PPS has the flag
  (October 2026), because the PSP decodes video in hardware and software
  decoders (PPSSPP) accept both.
* Title credit: 4-bit TIM2 in member `00002` entry 1 (128 x 32),
  `psp/tools/psp_title.py`.
  The game draws only the first 96 pixels of line one (as on the PS2), so
  the label is "Green Gel vX.Y.Z" and `psp_title.py` refuses wider ones;
  "Green Gel Patch v0.3.2" (117 px) showed as "Green Gel Patch v0".
* XMB background `PSP_GAME/PIC1.PNG` (480 x 272): Japanese taglines on the
  band at the bottom right and the designer credit at the bottom left.
  `psp/tools/psp_pic1.py` (Pillow) fills them from the background and draws
  English plus "Green Gel Group English Patch vX.Y.Z"; build_psp runs it
  with `--version`.
* World map text: members `09272..09276` are sizes packs (u32 count, u32
  sizes, children back to back, every size a multiple of 4), one per era
  (present, future, altered present, Great War, final present). Child 19 is
  the world map field script, an uncompressed `SCED`; the location name
  that appears over a town or dungeon, signposts, mine labels, the inn on
  the map, the box puzzle, the Draconis anchor scene and the ending
  monologue are its F8 strings. PSP twin of the PS2 `09028..09032.pak0`.
  The `クレスタの街` / `ラグナ遺跡` list in BOOT.BIN is a different list
  these labels never read. `psp/tools/psp_worldmap.py`, `psp_worldmap.tsv`.

## Rules learned the hard way

* Control codes in a translated record must match the Japanese record
  exactly. Choice records (`<03>`) must also keep the Japanese line
  structure; an extra line once made the Skit Hut replay menu stick.
* Scenario edits go into both `Third pass Quality-Safe Output` and
  `ps2/PyTOD2/TXT_EN` (skits: `third pass skits safe output` and
  `ps2/PyTOD2/FILE/pak1/TXT_EN`); the audit fails on any difference. The PSP
  build reads the Third pass folders.
* Text box limits: 36 visible characters per line, 126 per four-row page,
  `{02}` starts a new page. About 766 records have a fifth line that shows
  alone on a second page (an open decision).
* A Japanese string found in a binary is not necessarily shown: relocated
  tables leave the old bytes behind. Check what points at it.
* Before calling something a bug, compare with the retail game: for
  example the Refine format "A1,B0/ 99" is original, and the PS2 and PSP
  staff rolls really spell 理恵子 and 恵理子 differently.
* Never commit game files, disc images or extracted game data; the
  repository holds tables, text and scripts only.
