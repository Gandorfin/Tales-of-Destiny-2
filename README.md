# Tales of Destiny 2 English translation

![logo](TOD2_logo.png)

Open-source English fan translation of **Tales of Destiny 2** (テイルズ オブ
デスティニー 2, Namco, PlayStation 2, 2002) and, in progress, of its PSP port
(2007). This is *not* Tales of Eternia (released as "Tales of Destiny II" in
North America) and not the PS1 Tales of Destiny.

Website: https://gandorfin.github.io/Tales-of-Destiny-2/

## Status

| Version | State |
|---|---|
| PS2 (SLPS-25172) | **Complete.** Latest patch: [QS v1.1.3](https://github.com/Gandorfin/Tales-of-Destiny-2/releases/latest), 2026-08-22 |
| PSP (ULJS-00097) | **Started 2026-08-24.** Archive tools done, text and menu work ahead |

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
   and download the latest `ToD2_Eng_patch_QS_*.7z`.
2. You need your own dump of the Japanese game (SLPS-25172). Follow the
   notes in the release.
3. Play on PCSX2 or real hardware.

Bug reports and screenshots of anything wrong or still Japanese are
welcome as GitHub issues.

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
3. Apply the menu tables (all four, in this order, from the repository root):
   ```
   python ps2/menu/patch_menu_text.py ps2/PyTOD2/FPB
   python ps2/menu/sfm_text.py build ps2/PyTOD2/FPB
   python ps2/menu/enemy_text.py build ps2/PyTOD2/FPB
   python ps2/menu/patch_slps_titles.py ps2/PyTOD2/SLPS_251.72
   ```
4. Pack FPB, Insert FONT, and put `new_FILE.FPB` and `new_SLPS_251.72` into
   the ISO.
5. `python ps2/menu/verify_menu_patch.py your.iso` tells you which parts of
   the build are English, so a Japanese screen can be traced to the step
   that was skipped.

## PSP port

The PSP version has the same `file.fpb` structure and the same text
encoding, so the translated text carries over. Differences: members are
zlib-compressed, the archive table lives in the executable, the menus were
compiled into the executable (no overlay modules), and the font has no
lowercase letters and draws every character full width. Work so far:

* `psp/tools/psp_fpb.py`: extract and repack the archive, byte-identical
  when nothing changed
* `psp/tools/psp_iso.py`: replace files inside the UMD image
* `psp/tools/ascii_test.py`: builds a test image that shows how the engine
  draws Latin text (first check before the real work)

Next: scenario and skit insertion, the font and half-width rendering, then
the menus inside the executable.

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
* The font is member 0: a PSP-swizzled 4-bit texture, 512 x 2200 pixels,
  23-pixel cells, 22 per row. Member 1 lists the Shift-JIS code of every
  glyph in order.
* Text codes map to glyphs as `(lead - 0x99) * 187 + (second - 0x40)` with
  two skipped second-byte values; single ASCII bytes go through a 256-entry
  table that points `a..z` and `A..Z` at the full-width capitals.

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

* `Amarant01` for the font graphics: https://www.behance.net/deco-7105af
* `Lanyn` for permission to use the Tales of Destiny 2 English translation
  script: https://www.youtube.com/user/lanyn/videos
* The `Temple of Tales Translations` team (http://temple-tales.ru/translations.html)
  for the skit and scenario extraction tools
* `alizor` for the Python scripts to extract and repack the PS2 and PSP archives
* `SkyBladeCloud` (GBAtemp) for the file format research
* `flamethrower` / `flame1234` (GBAtemp) for the PSP string extractor
* `pnvnd` for starting the open-source project and its tooling
* `Gandorfin` for maintaining the project, building and testing every release
* `SirJazz` for the 2026 proofread, the menu, quiz, battle and title tooling, and the PSP work
