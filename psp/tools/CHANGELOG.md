# Changelog

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
