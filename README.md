# Green Gel ToD2 patch

![logo](TOD2_logo.png)

The **Green Gel ToD2 patch** is an open-source English fan translation of **Tales of Destiny 2** (テイルズ オブ
デスティニー 2, Namco, PlayStation 2, 2002) and its PSP port
(2007). This is *not* Tales of Eternia (released as "Tales of Destiny II" in
North America) and not the PS1 Tales of Destiny.

Website: https://gandorfin.github.io/Tales-of-Destiny-2/

## Status

| Version | State |
|---|---|
| PS2 (SLPS-25172) | **Complete.** Latest release: **QS v1.1.6F** ([releases](https://github.com/Gandorfin/Tales-of-Destiny-2/releases/latest)) |
| PSP (ULJS-00097) | **First release: PSP patch v0.1.0.** Full script, skits, menus, items, artes, titles, descriptions and the Monster Book are English; story dialogue now renders in mixed case. A few menu/UI corners are still Japanese (see PSP port below) |

The PS2 patch covers the whole game:

* every story scene (459 scenario files) and all skits, proofread line by
  line against the Japanese, with the layout limits of the game's text
  boxes and skit timers respected
* menus and UI: items, equipment, shops, refine, enchant, cooking,
  customize, status, tactics, save, name entry, grade shop, Monster Book,
  Battle Memos, battle command labels, memory card messages
* character titles, party arte names and their battle cut-in banners,
  enemy arte names and the lines bosses shout in battle
* world map labels, signposts, ferry and minigame text, the ending
  monologue, the Quiz Book
* the in-game videos with dialogue, hard-subtitled

What is still Japanese in the PS2 build is the handful of strings the tools
cannot reach yet (see the open items in `ps2/menu/README.md`).

## Getting the PS2 patch

1. Go to the [releases page](https://github.com/Gandorfin/Tales-of-Destiny-2/releases)
   and download the latest release (a `.7z` holding the `.xdelta` patch).
2. You need your own dump of the Japanese game (SLPS-25172). Apply the
   patch to it with [Delta Patcher](https://github.com/marco-calautti/DeltaPatcher/releases)
   (Windows, Linux, macOS): original ISO in, xdelta file in, click Apply.
   Command line users: `xdelta3 -d -s original.iso patch.xdelta patched.iso`.
3. Play the patched ISO on PCSX2 or real hardware.

Bug reports and screenshots of anything wrong or still Japanese are
welcome as GitHub issues.

## Getting the PSP patch

1. Download the latest **PSP patch** from the [releases page](https://github.com/Gandorfin/Tales-of-Destiny-2/releases)
   (a `.7z` holding an `.xdelta` patch).
2. You need your own dump of the Japanese UMD (ULJS-00097). Apply the patch to
   the ISO with [Delta Patcher](https://github.com/marco-calautti/DeltaPatcher/releases)
   or `xdelta3 -d -s "Tales of Destiny 2 (Japan).iso" patch.xdelta patched.iso`.
3. Play the patched ISO on PPSSPP or a real PSP (CFW).

The one-command build from source is `python3 psp/tools/build_psp.py <JP.iso>
<out.iso> --version 0.1.1` (extracts, patches BOOT.BIN and the archive,
verifies, writes the English ISO). `--version` is the number that appears as
"Green Gel Patch v0.1.1" on the title screen, so pass the one you are
releasing.

### Making a release (maintainers)

After building the patched ISO as described below:

```
xdelta3 -e -9 -S none -s "Tales of Destiny 2 (Japan).iso" patched.iso "[Green Gel] ToD2 patch v1.1.6F (PS2).xdelta"
```

`-S none` turns off the secondary compression that some patchers cannot
read. The patch only stays small if the patched ISO keeps the original
file layout (files replaced in place, not a re-authored image), so that
only the changed sectors end up in the diff.

## Repository map

| Path | What |
|---|---|
| `ps2/scenarios/`, `ps2/skits/` | the translated script, one text file per scene or skit; Japanese lines are marked with `#`, English follows |
| `ps2/menu/` | menu, title, Quiz Book, enemy arte and cut-in translation tables and the scripts that apply them (`README.md` there explains the full apply sequence) |
| `ps2/PyTOD2/` | archive tool for `FILE.FPB`: unpack, insert text, repack (GUI and command line) |
| `scripts/audit_translation.py` | checks the script for crash-class problems and layout issues; runs on every pull request |
| `glossary.txt`, `character_voice_guide.txt` | terminology (locked terms) and how each character speaks |
| `Dialogue and Script Layout Restrictions.md` | the text box limits every line must respect |
| `psp/tools/` | PSP archive and ISO tools and the rendering test build (`README.md` there) |
| `psp/` (rest) | older PSP extractors and Japanese scenario dumps |
| `docs/` | the website (GitHub Pages) and the hex/Japanese converter tools |
| `dictionary/`, `tm2_converter/`, `pakcomposer/` | helper data and tools |

The `*_output` folders in the root are earlier passes of the translation
pipeline, kept for reference; `ps2/scenarios` and `ps2/skits` are the
current text.

## Building the PS2 patch from source

Short version; the details are in `ps2/menu/README.md` ("Applying it") and
`tod2_ps2_patch_guide.md`.

1. Extract `FILE.FPB` and `SLPS_251.72` from the Japanese ISO into
   `ps2/PyTOD2/` and run PyTOD2: Unpack FPB, Organize FPB, Unpack SCPK,
   Unpack SCED, Unpack PAK1, Move Skits OUT, Extract SKIT.
2. Put the translated scenario files into `TXT_EN` and the skits into
   `file/pak1/TXT_EN`, then Pack SCED, Pack SCPK, Insert SKIT, Move Skits IN,
   Pack PAK1.
3. Apply the menu tables (all five, in this order, from the repository root;
   put the version you are about to release in the last FPB step):
   ```
   python ps2/menu/patch_menu_text.py ps2/PyTOD2/FPB
   python ps2/menu/sfm_text.py build ps2/PyTOD2/FPB
   python ps2/menu/enemy_text.py build ps2/PyTOD2/FPB
   python ps2/menu/title_credit.py ps2/PyTOD2/FPB --version 1.1.8
   python ps2/menu/patch_slps_titles.py ps2/PyTOD2/SLPS_251.72
   ```
   `title_credit.py` redraws the Japanese designer credit under the title
   menu as "Green Gel Patch v1.1.8" (the Namco line below it is kept).
4. Pack FPB, Insert FONT, and put `new_FILE.FPB` and `new_SLPS_251.72` into
   the ISO.
5. `python ps2/menu/verify_menu_patch.py your.iso` tells you which parts of
   the build are English, so a Japanese screen can be traced to the step
   that was skipped.

## PSP port

The PSP version (ULJS-00097) shares the `file.fpb` structure and the text
encoding with the PS2 game, so most of the translated text carries over.
Differences: archive members are zlib-compressed, the member table lives in
the executable, the menus are compiled into the executable (no overlay
modules), the font is a swizzled 4-bit texture, and the UI renderer draws
ASCII full width and in capitals.

The whole pipeline is one command, `python3 psp/tools/build_psp.py`, which:

* pulls `BOOT.BIN` and `file.fpb` out of the ISO (`psp_iso.py`, `psp_fpb.py`)
* patches the party names in `BOOT.BIN` (`psp_names.py`)
* applies the ~3,900 menu/UI strings, overwriting the ones that fit in place
  and relocating the longer ones into a new load segment with a
  pointer-rewrite pool (`psp_menu.py`, `psp_pool.py`)
* matches every scenario and skit record against the PS2 English script and a
  hand-translated supplement for the PSP-exclusive scenes, then inserts them
  (`psp_text.py`, `psp_supplement.tsv`)
* translates the Monster Book / bestiary enemy names, which live one PAK level
  deep and then inside a raw-deflate blob in the battle-resource archive
  members (`psp_monsters.py`)
* redraws the title-screen copyright texture so the Japanese designer credit
  reads "Green Gel Patch vX.Y.Z" (`psp_title.py`, with `--version`)
* rebuilds the font member with lowercase glyphs and applies SkyBladeCloud's
  font-selection patch to every ASCII text walker so dialogue, names and menus
  render in mixed case; the bold icon-font menu text (party names in the menu,
  tabs, arte grid, Battle Rank) keeps retail capitals (`psp_lowercase.py`)
* repacks the archive, verifies every rebuilt file, and writes the English ISO

### Help wanted (open PSP problems)

These are the remaining engineering problems, not translation. If you know PSP
reverse engineering, `armips`, or this engine, help is very welcome (open an
issue or a PR). What we have worked out so far:

* **The engine has two fonts.** 8-bit ASCII resolves through an 8-bit slot
  table (file `0x27DD40`), where `a` (`0x61`) and `A` both point to slot `0x17`
  (that is the uppercasing). The slot is then drawn from whichever font the
  code selected. **Font 0x01** is archive member 0 (the big editable font, has
  everything); **font 0x02** is a smaller icon/ASCII font with no free space
  that most of the UI uses.
* **Lowercase is done** by (1) drawing `a..z` into font 0x01's 26 free slots
  below `0x100` (`0xD9`, `0xDA`, `0xDC..0xF3`; slot `0xDB` is the retail
  apostrophe and must stay), (2) remapping `a..z` in the slot table to those
  slots, and (3) forcing the single-byte text paths to font 0x01 with one-byte
  `0x02` -> `0x01` code patches. Exactly three text walkers resolve ASCII
  through the slot table (found by taking every `lui 0xa / addiu ..,0x1040`
  reference to it in the disassembly): the dialogue text walker (file
  `0x13EEC4`), the speaker-name walker (`0x143444`) and the menu/battle walker
  (`0x14A084`, an `ori` whose low nibble is the font). Module load base is
  `0x08804000`, so runtime `0x08942E04` / `0x08947384` / `0x08949FC4`. Each
  walker's two-byte (kanji) path already hard-codes font 0x01, and the retail
  table maps every single-byte code to the same slot in both fonts, so font
  0x01 has every glyph these paths can address. Thanks to SkyBladeCloud, who
  reverse engineered the font system and shared his edited font.
* **The "bold" menu text stays in capitals.** A fourth routine reads the slot
  table but is not a walker: `0x144248` (wrapper `0x1464BC`, runtime
  `0x08948248`, called from nine menu subsystems) draws an ASCII string straight
  to a vertex list with the icon font's cell geometry hard-coded (10 cells per
  row, 12 x 16 pixels) on texture slot 0, which the wrapper binds to font 0x02.
  It has no font byte and no font 0x01 branch, so it can only ever draw the
  icon font: party names in the menu, the Artes tabs, the arte shortcut grid,
  the Battle Rank value, the HP/TP/LV labels. With `a..z` remapped it drew icon
  fragments, so the build gives this one routine its own untouched copy of the
  retail table (appended to the menu pool segment; the `lui`/`addiu` pair at
  `0x1443D8`/`0x1443DC` is re-pointed, its HI16/LO16 relocations stay valid)
  and those contexts render capitals exactly like retail. Lowercase there needs
  either lowercase glyphs drawn into the icon font (it has no free cells) or a
  rewrite of that routine's geometry to draw from font 0x01.
* **The arte grid uses a fixed-width renderer** that only handles single-byte
  ASCII: it mangles any multi-byte sequence, so neither a dual-tile encoding
  (two half-width letters in one glyph code) nor the game's own `<size>` scale
  control fixes the overflow there. For v0.1.0 the overflowing arte names are
  shortened to fit; the proper fix is an `armips` patch to that renderer's
  glyph advance (halve the ASCII step, keep two-byte and control codes).
* **Monster Book display names** still show Japanese even though the battle
  enemy names are translated, so the book UI reads names from a second, not-yet
  located source.

A format-aware Japanese-string scanner for the PSP ISO (walks every FPB member,
nested SCPK/PAK/deflate containers, and the game's glyph encoding) is described
in the help thread linked under Resources.

## Contributing

* Work on a branch and open a pull request. The audit runs automatically
  and fails only if a change adds a crash-class finding.
* Text rules: 36 visible characters per line, 126 per four-row page, page
  breaks with `{02}`, control codes must match the Japanese source exactly.
  Skit lines reveal at 8 characters per second and have a fixed time window;
  keep them short.
* Use the terms marked `[LOCK]` in `glossary.txt` and the voices in
  `character_voice_guide.txt`.
* Never commit game files or images of the disc; the repository holds text
  tables and scripts only.

Reference spreadsheet with older research:
https://docs.google.com/spreadsheets/d/1UVaEjK0o-V1-3atPHfRRw2q9QQcCzPCpr4GXJ2MLvvg

## Technical notes

### FILE.FPB (PS2)

* The member table is in `SLPS_251.72` starting at `0xDD320`, one u32 per
  member: high bits = start offset, low 6 bits = remainder.
* Members use the game's own LZSS/RLE compressor (`comptoe`); a pure Python
  port lives in `ps2/menu/lzss.py`.
* Menu text lives in the `md1` overlay modules inside the archive, not in
  the executable. Three modules (`08055`, `06304`, `08996`) are also stored
  compressed inside `00017.pak3`, and that is the copy the game loads.

### SLPS_251.72

| Offset | Description |
|---|---|
| `0x000000` | ELF start |
| `0x0CA328` | font (TM2) |
| `0x0C9D00` | font map: byte per ASCII code, `0xC9D00 - 0x20 + ascii` gives the glyph index |
| `0x0DD320` | FILE.FPB member table |

The 2008 English menu base mapped lowercase letters onto redrawn hiragana
glyphs through that map; the current patch builds on that executable.

### FILE.FPB and the executable (PSP)

* `PSP_GAME/SYSDIR/BOOT.BIN` on the UMD is already the decrypted
  executable (a plain PRX), so no `deceboot` step is needed.
* The member table is at `0x29531C..0x29E9AC` in it: high bits = start
  (sector * 0x800), low 11 bits = remainder; a member ends `remainder`
  bytes before the next member's start.
* Compressed members start with byte `04`, u32 packed length, u32 unpacked
  length, then a raw deflate stream. A raw container with four entries also
  starts with `04 00 00 00`; tell them apart by the packed length.
* The font is member 0 (font 0x01): a PSP-swizzled 4-bit texture, 256 x 4400
  pixels, 23-pixel cells, 11 per row (`slot = row * 11 + col`, `A` = slot
  `0x17`). Member 1 lists the Shift-JIS code of every glyph in order. There is
  also a second, smaller icon/ASCII font (font 0x02) that most of the UI draws
  from; the code selects between them per context with `li reg, fontindex`.
* Two-byte text codes map to glyphs as `(lead - 0x99) * 187 + (second - 0x40)`
  with two skipped second-byte values (the u16 code map is at file `0x27DB40`).
  Single ASCII bytes instead go through an 8-bit slot table at file `0x27DD40`
  that points `a..z` at the same slots as `A..Z` (the uppercasing).
* The executable's module load base at runtime is `0x08804000` (runtime address
  = segment vaddr + base), which is how in-game debugger addresses map back to
  file offsets (data file = vaddr + 0x100, text/rodata file = vaddr + 0xC0).

### Text encoding (both versions)

Two-byte codes with lead bytes `0x99..0x9F` and `0xE0..0xE4`, listed in
`ps2/PyTOD2/TBL.json`; `0x01` is a newline; `0x03..0x0B` introduce a tag
with a u32 argument (colour, size, number, party member name, item,
button); a NUL ends the string.

### Older notes

The scenario packages (`SCPK`) hold a background, sprites and animations,
and last the `SCED` script with a code section and a text section. The
PS2 font TM2 has ten 4-bit palettes of `0x40` bytes with `0x10`-byte
subheaders, then a 128 x 512 4-bit pixel matrix, low nibble first.

## Resources

* https://gamefaqs.gamespot.com/ps2/561922-tales-of-destiny-2/faqs/58741
* https://gbatemp.net/threads/romhacking-in-tales-of-destiny-2.373960/
* https://pastebin.com/fCVPLUP4 (text decoder routine)
* https://github.com/talestra/talestra/tree/master/compto (comptoe)

## Credits

* `Gandorff` for leading and maintaining the project, the translation, and the
  tooling
* `casino3346` for the PS2 and PSP ports and translation work
* `pnvnd` for terminology, the Lifebottle style reference, and the
  format-aware PSP Japanese-string scanner
* `SkyBladeCloud` (GBAtemp) for the original file-format research and for
  reverse engineering the PSP font system and lowercase font-selection hack
* `Amarant01` for the font graphics: https://www.behance.net/deco-7105af
* `Lanyn` for permission to use the Tales of Destiny 2 English translation
  script: https://www.youtube.com/user/lanyn/videos
* The `Temple of Tales Translations` team (http://temple-tales.ru/translations.html)
  for the skit and scenario extraction tools
* `alizor` for the Python scripts to extract and repack the PS2 and PSP archives
* `flamethrower` / `flame1234` (GBAtemp) for the PSP string extractor
