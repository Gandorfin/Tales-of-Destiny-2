# Changelog

## 2026-10-16: one English typeface (Fira Sans) for all PSP text

* Problem (seen by the user on PR 124's build): the letters bounced up and
  down and some were hard to read ("orphanage" looked like "or hanage").
  The Latin glyphs came from three sources: retail full-width capitals and
  digits, eleven retail lowercase letters and fifteen hand-made ones, with
  different x-heights, baselines and weights; PR 124 then pushed g p q y j
  down by hand, which made it worse.
* New `psp_latin_font.py`: draws all printable ASCII from Fira Sans
  SemiBold (SIL Open Font License; `psp/fonts/FiraSans-SemiBold-ASCII.ttf`,
  subset to ASCII, license in `psp/fonts/OFL.txt`) into font 1 and the bold
  menu font copy: one baseline, cap height and x-height, real descenders,
  the font's own advances plus tracking, retail white-with-outline style.
  `render` (needs Pillow) writes `psp/fonts/latin_glyphs.json`; the build
  only reads that table.
* `psp_vwf.py`: widths from that table (no glyph measuring, no descender or
  hyphen hacks), sprites a full cell wide so letters keep their real
  proportions. `psp_bold_lowercase.py`: the bold font copy gets all Latin
  cells from the table.
* `psp_menu.fullwidth_to_ascii`: 30 labels written in full-width Latin
  (title menu, HP, TP, LV, GRADE SHOP, BGM names) become ASCII, so they use
  the new font with normal spacing instead of narrow letters in wide cells.
* `psp_menu.tsv`: "On" becomes "On " so the third option of Battle Auto
  Camera (Active) no longer touches it.
* Checked in PPSSPP (strict loader) with a fresh new game: title, opening,
  first battle, Cresta dialogue, skit, main menu, Items, Custom, Status,
  name entry. Known: long skit lines still scroll (as in the original), the
  name being edited on the name entry screen shows full-width letters.

## 2026-10-16: encounter banner, menu tip, name entry labels

Three leftovers seen while testing the variable width font (PR 124):

* The enemy name banner at the start of a battle showed オウルベア. It reads
  the TEKI list in member 08331 (PAK child 2, comptoe LZSS): "TEKI", 256
  records of 28 bytes (24 byte name, 4 bytes data). No step touched it.
  `psp_monsters.patch_teki` decodes it, writes the English from
  `psp_monsters.tsv` (space padded), packs it again and rebuilds the PAK;
  the other two children stay byte identical. 229 names, 27 empty slots.
  Nine names were missing from the table and are added (Rimul, Death,
  Thanatos Knight, Leon, Rutee, Woodrow, Philia, Lilith, ???), spelled as in
  `ps2/menu/enemy_names.csv` and `glossary.txt`.
* The first time menu tip (しばらくキー操作がないと...) had no table row.
  BOOT.BIN file 0x1C3144, 126 bytes; the English (98 bytes) fits in place
  and keeps the two colour codes.
* The name entry mode labels "Hiragana" and "Katakana" ran into each other
  (the labels sit in fixed slots); now "Hira" and "Kata".
* Seen in PPSSPP (strict loader): "Owlbear  1" banner, the tip in English,
  "Hira  Kata  ABC" without overlap. The Monster Book screen was not
  reachable with the test save (Library not yet open).

## 2026-10-16: variable width font, lowercase bold menu text

* English on the PSP looked like a typewriter: every single-byte letter
  took half a font cell ("L o n i  a c q u i r e d"), boxes were wide, and
  the bold menu text (party names, tabs, Battle Rank, Custom menu values)
  could only show capitals.
* New `psp_vwf.py`: per letter widths measured from the built fonts, hooked
  into the text box layout (`0x13EE24`), the text box glyph loop
  (`0x140E78`), the text printer put-char (`0x143380`), the box measurer
  (`0x14283C`), the bold routine (`0x144438`) and the skit/battle ticker
  (`0x149FD0`, `0x14A4A0`). Digits keep one width; `g p q y j` get
  descenders; single-byte `-` is drawn as a hyphen; letters are drawn 1.25
  times wider than retail. The hooks and tables (about 3 KB, plus the 32 KB
  font copy) are appended to the string pool; no relocated word is touched and no relocation entry
  is added (`test_psp_vwf.py` checks both).
* New `psp_bold_lowercase.py`: a copy of font 2 with `a..z` drawn over
  hiragana cells 49..74 (from the dialogue font's lowercase), stored in the
  pool (32 KB) and bound by a hook at the start of the bold routine
  (`0x144250`) for every string without kana from those cells; `a..z` in
  the bold routine's private table point at them. The name entry keyboard
  draws its kana through the same routine, so it keeps the retail font 2
  (a first version that painted font 2 itself broke the keyboard; caught in
  PPSSPP before any push).
* New `mips_asm.py`: the small assembler the hooks are written in (output
  identical to armips v0.11.0).
* `build_psp.py --vwf on|off` (default on, needs the lowercase font).
* Tested in PPSSPP 1.20.4 with the real kernel load rule: fresh boot,
  opening, first battle, Cresta, a skit, main menu, Items, Custom, Status,
  name entry. Still owed: a real PSP / PS Vita, the arte grid with a save
  that has artes.

## 2026-10-16: about 100 more menu strings, Frostheim, scan lessons

* Menu table keys with a full-width space never matched BOOT.BIN: the
  game stores U+3000 as 0x9940, the key encoder wrote the TBL's 0xE499.
  The English was in `psp_menu.tsv` all along but never applied: every
  shop name ("Weapon Shop SOUL & SWORD", "Food Shop CRESTA'S KITCHEN"),
  the scene titles of the debug scene list and some labels.
  `psp_menu.encode_keys` and `psp_pool.relocate_menu` now try the retail
  form first (the TBL form stays as a second key). Full build: 31 more
  strings in place, 50 more pooled; `known_unapplied` in the scan 151 to 74.
* スノーフリア is Frostheim everywhere (it was Snowfria in `psp_menu.tsv`
  and in the ferry and debug rows of `psp_supplement.tsv`).
* Three debug guide lines stored in about 1,800 places in the town
  scripts now come from `psp_supplement.tsv`.
* `psp_jpscan.py` labels SCED scripts inside sizes packs `map` instead of
  `battle`; the tools README says how to read a scan.

## 2026-10-16: world map location names and scripts in English

* Gandorff (PSP 0.3.0): the location name over a town or dungeon on the
  world map was Japanese ("ラグナ遺跡", "クレスタの街"). The labels live in
  the world map field scripts (child 19, an SCED, of the sizes packs
  09272..09276), which no build step touched; the English "Cresta" in
  BOOT.BIN is a different list. The same scripts also held the signposts,
  mine labels, the inn on the map, the box puzzle, the Draconis anchor
  scene and the ending monologue, all Japanese until now.
* New `psp_worldmap.py` + `psp_worldmap.tsv` (373 strings in 5 scripts, 134
  distinct; 120 reuse the PS2 world map English, 14 PSP only strings newly
  translated), wired into `build_psp.py` with its own verify step.

## 2026-10-16: the string pool now loads on a real PSP and on a PS Vita

* Cause of the random characters and freezes on a PS Vita (Adrenaline) and
  of the old "lowercase build crashes on some PSPs" reports: the PSP kernel
  loads only the PT_LOAD program headers that come right after each other,
  and our pool header came after the relocation header, so the pool (about
  1,800 pooled menu, item and arte strings plus the bold menu text's slot
  table) was never loaded. PPSSPP loads it anyway, so the bug never showed
  there.
* `psp_pool.make_hardware_loadable` (last BOOT.BIN step of `build_psp.py`)
  orders the headers text, pool, data, relocation and renumbers the segment
  indices of all relocation entries. Same memory image as before; no file
  data moves. `check_hardware_layout` stops the build if the kernel would
  load the image differently. Tests model both loaders.

## 2026-10-16: skit lines finish before the next speaker

* `psp/text/skit_speeds.json` (synced from the PS2 table) now holds each
  line's window from the skit script's cue times: the frames from the
  line's first glyph until the next line starts (or the skit closes),
  never less than the Japanese took. The old window let 1,073 of 2,412
  lines keep revealing after the next line had started (dreck's report on
  PS2 1.3.0; the PSP uses the same table).
* The PSP skits have the same cue times as their PS2 twins (all 608 timed
  skits checked), so no PSP code change was needed; `retime_skit` is the
  same rule as before with the new windows.

## 2026-10-15: the PSP's own text in psp/text

* The PSP build reads its text only from `psp/text` (scenario, skits,
  subtitles, TBL.json, skit_speeds.json), a copy of the PS2 sources that
  `sync_text_from_ps2.py` refreshes on request (`--check` only reports).
* `psp/text/overrides.tsv` holds PSP only fixes; they win over the synced
  text and the sync never touches them. The PSP Skit Hut "unavailable"
  choice record (06944) moved there from `psp_supplement.tsv`.
* The sync prints a `CHECK:` line for every changed choice record (`<03:`).
* `build_psp.py` lists `psp/text` and the four files still read from `ps2/`
  (skit_speed.py, title_credit.py, title_glyphs.py, Ubuntu-Bold.ttf) and
  says when `psp/text` lags behind; the audit reports it as `psp-text-lag`.
* Same build output as before the move (byte identical ISO).

## 2026-10-15: skit lines from the PS2 twin, source check

* A skit line takes the English of the same line in its PS2 twin skit when
  the Japanese is the same (5 short lines had the wording of another skit).
* The 9 `skit` rows of `psp_supplement.tsv` (PSP Japanese differs slightly)
  now carry the full length retranslation, one line each (they had the old
  condensed text, 01433 even had three lines of which a skit shows one).
* `build_psp.py` prints the repository, commit and a fingerprint of every
  source it reads outside `psp/tools`, and stops with the path when one is
  missing or `skit_speeds.json` is older than the skit retranslation.

## 2026-10-06 — Optional lowercase font hack

- Add `--lowercase-font on|off` to the PSP ISO builder. Default `on` preserves
  existing builds; `off` retains the retail font member, ASCII slot mapping,
  font selection and bold-menu table for uppercase rendering.
- Both modes keep the English translation, menu/name and Monster Book patches,
  optional version credit, SCED freeze fix and pre-write text verification.
- Cover both modes and the default in synthetic regression tests, including
  CLI validation and refusal to write an ISO when verification fails.

## 2026-08-30 — SCED instruction-boundary / Elrane freeze fix

### Fixed

- Decode script instructions before recognizing `F8` text references. A byte
  inside a branch, constant, variable, or argument-list operand is no longer
  mistaken for a text instruction.
- Reject invalid legacy `pointers.json` entries before extraction/insertion.
- Check that append and rebuild insertion preserve all non-text code bytes and
  instruction boundaries. Unknown/truncated instructions fail closed.
- The standard `build_psp.py` entry point applies the fix automatically.

### Evidence and regression coverage

- The original-disc audit found 12 false entries in 11 scripts and recovered
  26 genuine text references missed by the previous scanner.
- Seven scripts had non-text bytecode corruption in the preceding image:
  06480, 06481, 06524, 06581, 06598, 06607, and 06673.
- In 06524, false pointer operand `0x345F` overlapped a conditional branch and
  the next variable descriptor. The repaired bytes are
  `F3 F8 33 24 1E C1 C0`, preserving the transition progress update.
- All 1,062 scripts passed structural/text checks; 161,465 branch/call targets
  aligned with instruction boundaries. Eleven synthetic regression tests cover
  operand false positives, missed genuine references, stale metadata, append,
  rebuild, and the specific Elrane sequence. Tests contain no extracted assets.
- The reporter confirmed the repaired build passes the first Elrane encounter
  that previously froze. A complete game playthrough has not been claimed.

### Preserved

Lowercase letters, the apostrophe glyph at slot `DB`, dotted `i`/`j`, menu-font
selection and the private bold-font table remain unchanged by this fix.
The tested repair retained existing genuine translated strings and every
non-script archive member from the previous build.

### Upgrading an existing text workspace

Back up edited translations. Extract into a fresh directory; do not reuse old
pointer metadata. If carrying manual edits forward, match script ID and genuine
pointer-operand address, not record index: removing false entries and recovering
real entries changes record numbering. Do not suppress the validation error.
Boot the new ISO normally and use an ordinary in-game save when testing;
old save states may restore corrupt script bytes from the earlier image.
