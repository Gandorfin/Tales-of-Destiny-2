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
  menu text (party names, Artes tabs, arte grid, Battle Rank) with the icon
  font's geometry hard-coded; it gets its own copy of the retail table and
  stays in capitals.
* `--lowercase-font off` builds without all of this (the v0.2.1 build).
* `psp/tools/patch_font_iso.py` exports, prepares, checks and patches PNG
  font sheets for both fonts (`psp/tools/FONT_CUSTOMIZATION.md`).

## PSP: menus and the string pool

* Menus are compiled into BOOT.BIN. `psp/tools/psp_menu.py` writes English
  that fits the Japanese slot in place (`psp_menu.tsv`). The full-width space
  must be encoded as `0x9940` (`{99}{40}`), the code retail menus use.
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
* Item and arte descriptions are two-line records `line1 0x01 line2` stored
  as one string; key them with `{01}` in the tables.
* The arte grid draws single-byte ASCII at a fixed full-cell width and
  mangles any multi-byte trick, so long arte names are shortened.

## PSP: enemy names, movies, title

* Enemy and Monster Book names live in the battle-resource members around
  `08378..09565`, one PAK level deep and then inside a raw deflate blob, in
  the game encoding (`psp/tools/psp_monsters.py`, `psp_monsters.tsv`). The
  Monster Book screen itself still shows Japanese names from a source not
  yet located.
* Movies: `/PSP_GAME/USRDIR/movie/0NN.pmf` (PSMF, H.264 + ATRAC3plus). PSP
  movie N is PS2 movie N - 1 frame for frame; PSP 012 repeats 008.
  `psp/tools/psp_movies.py` burns the PS2 subtitle tracks, `psp_pmf.py`
  rebuilds each navigation unit keeping audio and timing. The PSP staff roll
  differs from the PS2 one and has its own table (`psp_credits.tsv`).
* Title credit: 4-bit TIM2 in member `00002` entry 1 (128 x 32),
  `psp/tools/psp_title.py`.

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
