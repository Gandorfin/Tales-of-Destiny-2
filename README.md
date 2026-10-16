# Green Gel ToD2 patch

![logo](TOD2_logo.png)

The **Green Gel ToD2 patch** is an open-source English fan translation of
**Tales of Destiny 2** (テイルズ オブ デスティニー 2, Namco, PlayStation 2, 2002)
and its PSP port (2007). This is *not* Tales of Eternia (released as "Tales of
Destiny II" in North America) and not the PS1 Tales of Destiny.

* Website: https://gandorfin.github.io/Tales-of-Destiny-2/
* Downloads: https://github.com/Gandorfin/Tales-of-Destiny-2/releases
* English manual: https://gandorfin.github.io/Tales-of-Destiny-2/manual.html
  (the original PS2 manual translated with the patch's terms, also as a
  [PDF](https://gandorfin.github.io/Tales-of-Destiny-2/manual/Tales-of-Destiny-2-Manual-EN.pdf))
* Forum thread: https://retrogametalk.com/threads/release-tales-of-destiny-2-ps2-psp-english-ai-translation.26456/

## Status

| Version | Latest release | State |
|---|---|---|
| PS2 (SLPS-25172) | **QS v1.3.0** | **Complete.** The whole game is English. |
| PSP (ULJS-00097) | **v0.3.1** (two downloads: with and without the lowercase font hack) | **Playable.** Story, skits, movies and almost every menu are English; a few areas are still Japanese (listed below). |

### PS2

Everything a player reads is English:

* every story scene (459 scenario files), proofread line by line against the
  Japanese within the limits of the game's text boxes
* all 608 timed skits, retranslated at full length in v1.3.0: the build sets
  each skit line's text speed so the whole line fits its voice
* menus and UI: items, equipment, shops, Refine (with the required Lens),
  enchant, cooking, customize, status, tactics, save, name entry, grade shop,
  Monster Book, Battle Memos, battle commands, memory card messages, the Skit Hut
* character titles, party arte names and their battle cut-in banners, arte
  extension and mystic arte banners, enemy encounter names, enemy arte names
  and the lines bosses shout in battle
* world map labels, signposts, ferry and minigame text, the Quiz Book, the
  ending monologue
* the movies with dialogue, hard-subtitled, and an English ending staff roll
* a redrawn Latin font (by dreck, since v1.2.3)

Known limits:

* Text drawn into pictures stays Japanese: cooking recipe names, a poster in
  the Katz Village and similar textures.
* The enchant level up message is cut off by the game at about 32
  characters, so it is shortened.
* About 766 dialogue records have a fifth line that the game shows alone on
  a second page. Fixing that means shortening text; not decided yet.
* PS3 playback: the disc layout fix (last build step) is in place, a test on
  a PS3 is still owed.

### PSP

v0.3.1 (October 2026) has the full story script, all 608 timed skits at
full length with per line text speed (as PS2 v1.3.0), menus, items, artes,
titles, descriptions, the Quiz Book, battle enemy names, English subtitles
in the nine movies with dialogue and the PSP's own ending staff roll in
English. Each release comes in two builds: with SkyBladeCloud's font
selection hack (mixed case dialogue, names and menus) and without it
(capitals only). v0.3.1 also fixes how the PSP and the PS Vita load the
patch's extra strings (the cause of missing menu labels, random characters
and freezes on real hardware with v0.3.0 and older); a confirmation on a
real PSP and a Vita is still owed.

Already in the source and coming with the next PSP release:

* the world map in English: the location name over a town or dungeon,
  signposts and mine labels, the box puzzle, the Draconis anchor scene and
  the ending monologue
* about 100 menu strings whose Japanese contains a full-width space and
  that had English in the table but were never applied: all shop names,
  scene titles and some labels
* Frostheim (not Snowfria) in the PSP only menus and debug lines
* a variable width font: every Latin letter has its own width in text
  boxes, skits, menus, labels and the bold menu text (no more
  typewriter look), boxes fit the text, `g p q y` hang below the line and
  `-` is a real hyphen
* lowercase in the bold menu text: party names, menu tabs, Battle Rank and
  the Custom menu values read "Kyle", "Normal" instead of KYLE, NORMAL

Still Japanese on PSP (full scan of the current source, October 2026):

* menu messages that the game reaches through an address built in code,
  which the patch does not redirect yet: the button legends at the bottom
  of several menus, the airship landing message, two cooking recipe
  messages, the "obtained the title" message
* the single-kanji element and status labels (地 水 火 風 光 闇 毒)
* the Monster Book's own name list, the Mystic Arte banners of some
  enemies, and about 50 enemy arte names and boss lines that have no table
  yet

See [Help wanted](#help-wanted-open-psp-problems) for the engineering side.

## Playing it

### PS2

1. Download the latest PS2 patch from the
   [releases page](https://github.com/Gandorfin/Tales-of-Destiny-2/releases)
   (a `.7z` holding `[Green Gel] ToD2 patch vX.Y.Z (PS2).xdelta`).
2. You need your own dump of the Japanese game (SLPS-25172). Apply the patch
   with [Delta Patcher](https://github.com/marco-calautti/DeltaPatcher/releases)
   (Windows, Linux, macOS): original ISO in, xdelta file in, Apply. Command
   line: `xdelta3 -d -s original.iso patch.xdelta patched.iso`.
3. Play on PCSX2 or a real PS2.

### PSP

1. Download the PSP patch from the
   [releases page](https://github.com/Gandorfin/Tales-of-Destiny-2/releases)
   (tags `PSP_X.Y.Z`). Each release has two files: `Font_Hack` for mixed
   case text, `No_Font_Hack` (capitals only) if the first one crashes or
   shows broken letters on your device.
2. You need your own dump of the Japanese UMD (ULJS-00097). Apply the patch
   with Delta Patcher or `xdelta3 -d -s original.iso patch.xdelta patched.iso`.
3. Play on PPSSPP or a PSP with custom firmware.

The title screen shows the patch version ("Green Gel vX.Y.Z" on PS2,
"Green Gel Patch vX.Y.Z" on PSP). Please include it in bug reports.

## How to help

Help of every kind is welcome, coding or not.

* **Report what is wrong.** Open a
  [GitHub issue](https://github.com/Gandorfin/Tales-of-Destiny-2/issues) or
  post in the forum thread with: PS2 or PSP, the patch version from the title
  screen, emulator or hardware, a screenshot, and where it happens (place,
  story point, menu). Japanese text, cut-off lines, wrong names, freezes and
  typos all count. A save state near the spot helps a lot.
* **Playtest.** A full playthrough with a sheet of screenshots and suggested
  fixes (as pnvnd did for PS2) finds what scans cannot. The PSP version needs
  this most right now.
* **Improve the text.** Corrections go into the scenario and skit sources
  (see [Contributing](#contributing)): mistranslations, wrong speaker,
  character voice (`character_voice_guide.txt`), terminology
  (`glossary.txt`).
* **Draw.** Latin fonts for both versions (PS2:
  `ps2/menu/FONT_CUSTOMIZATION.md`, PSP: `psp/tools/FONT_CUSTOMIZATION.md`;
  both tools take a PNG sheet), and English versions of the textures that
  still show Japanese.
* **Reverse engineering.** The open PSP problems are below; the formats are
  in [TECHNICAL.md](TECHNICAL.md).

### Help wanted: open PSP problems

These are engineering problems, not translation. If you know PSP reverse
engineering, `armips` or this engine, open an issue or a pull request.

* **Code-built string addresses.** Long menu strings are moved to a new
  segment and their 32-bit data pointers rewritten (`psp/tools/psp_pool.py`).
  Some screens build the same address in code with a `lui`/`addiu` pair
  (HI16/LO16 relocations) and still show the Japanese. Rewriting those pairs
  is only safe when every LO16 that shares the HI16 points at a moved
  string; otherwise the English has to fit in place.
* **Arte grid names.** 29 arte names were shortened to fit the grid when
  every letter was a full cell wide. The grid now uses the variable width
  font (next release); someone with a save that has many artes should check
  which full names fit again (`psp/tools/psp_menu.tsv`).
* **Monster Book display names.** Battle enemy names are English, but the
  book screen reads its names from a second source that is not located yet.
* **Real hardware.** Up to v0.3.0 the PSP kernel never loaded the patch's
  string pool (it loads only consecutive program headers), which explains
  the missing labels, random characters and freezes on a PSP or a Vita.
  v0.3.1 orders the headers so the kernel loads it; reports from real
  hardware are still needed. Android PPSSPP shows flickering menu items
  with v0.3.0; not yet known whether v0.3.1 fixes that.

## Contributing

* Work on a branch and open a pull request. An automated audit
  (`scripts/audit_translation.py`) runs on every pull request and fails on
  crash-class problems.
* Scenario text lives in `Third pass Quality-Safe Output/` and skits in
  `third pass skits safe output/` (Japanese lines start with `#`, English
  follows). Each folder has a build copy (`ps2/PyTOD2/TXT_EN`,
  `ps2/PyTOD2/FILE/pak1/TXT_EN`) that must stay identical; edit both. The
  PSP build reads its own copy in `psp/text/`: after a PS2 text change run
  `python psp/tools/sync_text_from_ps2.py` and commit `psp/text/` with it.
  Never edit the copies in `psp/text/` by hand; a fix that only the PSP
  needs goes into `psp/text/overrides.tsv`, which wins over the synced text.
* Text rules (`Dialogue and Script Layout Restrictions.md`): 36 visible
  characters per line, 126 per four-row page, `{02}` starts a page, control
  codes must match the Japanese exactly. A skit line is one line up to its
  budget: it has to finish revealing before the next line starts, at no
  more than 30 characters per second if it fits one 60 character row and
  no more than 20 per second if it is longer, never more than 384
  characters (`python ps2/PyTOD2/skit_speed.py report <skit folder>` and
  the audit check it).
* Use the `[LOCK]` terms in `glossary.txt` and the voices in
  `character_voice_guide.txt`.
* Write pull request descriptions so someone with no context (or another AI
  model) can follow them years later: the problem as it was seen, the root
  cause with files and offsets, what changed in each file and why, how to
  use it (commands, any new build step), how it was verified and what still
  needs an in-game check.
* Never commit game files, disc images or extracted game data. The
  repository holds text, tables and scripts only.

## Building the patch from source

The commands are written for Windows 11; on Linux or macOS use `python3`.
Python 3.10 or newer.

### PS2

Details for every step are in `ps2/menu/README.md` ("Applying it") and
`ps2/movies/README.md`.

1. Extract `FILE.FPB` and `SLPS_251.72` from the Japanese ISO into
   `ps2/PyTOD2/` and run PyTOD2: Unpack FPB, Organize FPB, Unpack SCPK,
   Unpack SCED, Unpack PAK1, Move Skits OUT, Extract SKIT.
2. Build the text from the `TXT_EN` copies: Pack SCED, Pack SCPK, Insert
   SKIT, Move Skits IN, Pack PAK1. Insert SKIT also sets each skit line's
   text speed (`ps2/PyTOD2/skit_speed.py`, stored originals in
   `skit_speeds.json`).
3. Apply the menu tables, in this order, from the repository root (put the
   version you are releasing in the fourth line):
   ```
   python ps2/menu/patch_menu_text.py ps2/PyTOD2/FPB
   python ps2/menu/sfm_text.py build ps2/PyTOD2/FPB
   python ps2/menu/enemy_text.py build ps2/PyTOD2/FPB
   python ps2/menu/title_credit.py ps2/PyTOD2/FPB --version 1.3.0
   python ps2/menu/patch_slps_titles.py ps2/PyTOD2/SLPS_251.72
   ```
   `title_credit.py` draws "Green Gel v1.3.0" under the title menu; the game
   shows only 96 pixels of that line, so the tool refuses wider labels.
4. Pack FPB and put `new_FILE.FPB` and `new_SLPS_251.72` into the ISO. Do
   **not** run "Insert FONT": it replaces the game's Latin font with an
   unused 2008 font and drops the `&`, `~` and `*` glyphs.
5. Movies: they are in `MOVIE.FPB`, which none of the steps above touch.
   Build them with
   `python ps2/movies/build_hardsubbed_movies.py --ffmpeg C:\path\to\ffmpeg.exe`
   (FFmpeg with libass; output in `ps2/PyTOD2/hardsubbed_movies.rebuilt`),
   replace `ps2/PyTOD2/hardsubbed_movies` with that folder, run
   `ps2/PyTOD2/Install-HardsubbedMovies.ps1` (writes the eight movies into
   `ps2/PyTOD2/MOVIE.FPB`) and put that `MOVIE.FPB` into the ISO.
6. `python ps2/menu/verify_menu_patch.py your.iso` shows which parts of the
   build are English, so a Japanese screen can be traced to a skipped step.
7. A custom Latin font goes in on the finished ISO:
   `python ps2/menu/patch_font_iso.py patch your.iso font.png`
   (see `ps2/menu/FONT_CUSTOMIZATION.md`).
8. Last: `python ps2/menu/fix_disc_layout.py fix your.iso` gives the ISO the
   retail disc layout (the ISO writer leaves the UDF side unlike retail,
   which readers such as a PS3 look at first). `check` instead of `fix` only
   reports.

### PSP

One command builds the whole English ISO from a clean Japanese one:

```
python -m pip install imageio-ffmpeg
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_en.iso --version 0.3.1 --movies
```

* `--version` is the number drawn on the title screen as
  "Green Gel Patch vX.Y.Z"; pass the one you are releasing.
* `--movies` burns the English subtitles into the movies. **Without it the
  movies stay Japanese.** It needs an FFmpeg with libass and libx264:
  `imageio-ffmpeg` brings one, or pass `--ffmpeg C:\path\to\ffmpeg.exe`.
  The log shows a `movie 0NN (PS2 000NN):` block for each of the nine movies.
* `--lowercase-font off` leaves out the lowercase font hack (the
  `No_Font_Hack` download of a release).
* `--keep WORKDIR` keeps the extracted and rebuilt files.

The build extracts BOOT.BIN and file.fpb, applies the party names, menus
(in place or through the string pool), lowercase font, scenario and skit
text with skit speeds, enemy names, the Quiz Book, the world map scripts,
the title credit and the movies, then
repacks, verifies every rebuilt file and writes the ISO. Each step is
explained in `psp/tools/README.md`. A custom font goes in on the finished
ISO with `psp/tools/patch_font_iso.py` (`psp/tools/FONT_CUSTOMIZATION.md`).

### Making a release

PS2, after the last build step:

```
xdelta3 -e -9 -S none -s "Tales of Destiny 2 (Japan).iso" patched.iso "[Green Gel] ToD2 patch v1.3.0 (PS2).xdelta"
```

`-S none` turns off the secondary compression some patchers cannot read.
The patch stays small only if the ISO keeps the original file layout (files
replaced in place). The PS2 xdelta is still around 800 MB (about 415 MB as
a 7z) because the movies with dialogue are re-encoded. The PSP patch is made
the same way from the `build_psp.py` output.

## Repository map

| Path | What |
|---|---|
| `Third pass Quality-Safe Output/`, `third pass skits safe output/` | the maintained scenario and skit text (Japanese lines start with `#`) |
| `ps2/PyTOD2/` | PS2 archive tool (unpack, insert text, repack; GUI and command line), the build copies of the text (`TXT_EN`), skit speeds, movie installer |
| `ps2/menu/` | PS2 menus, executable, Quiz Book, enemy text, title credit, font and disc layout tools with their tables (`README.md` there) |
| `ps2/movies/` | PS2 movie subtitles, ending credits overlay, movie rebuild and remux tools (`README.md` there) |
| `psp/tools/`, `psp/text/` | the PSP build (`build_psp.py`) and every tool and table it uses (`README.md` there); `psp/text/` is the PSP's own copy of the text, refreshed from the PS2 folders by `sync_text_from_ps2.py`, plus the PSP only fixes in `overrides.tsv` |
| `psp/` (rest) | older PSP extractors and Japanese scenario dumps |
| `audio/` | index of every voice, music and sound file on both discs, PS2/PSP voice pairs, WAV export (`README.md` there) |
| `scripts/` | the translation audit, text dump and hex/Japanese converters |
| `docs/` | the website (GitHub Pages), the English manual, the converter pages |
| `glossary.txt`, `character_voice_guide.txt`, `code_glossary.txt` | terminology, character voices, control codes |
| `Dialogue and Script Layout Restrictions.md` | the text box limits |
| `TECHNICAL.md` | formats, offsets and rules of both versions |
| `dictionary/`, `tm2_converter/`, `pakcomposer/` | helper data and tools (`pakcomposer` is a submodule from Lifebottle) |
| `second_pass_quality_output/`, `second_pass_quality_skits_output/`, `translated_output/`, `ps2/scenarios/`, `ps2/skits/`, `TOD2_Kimi_two_stage_pipeline_v5_1.py`, `translate_*.py` | history: earlier machine translation passes and the pipeline that produced the first draft; not used by the build |

## Resources

* [TECHNICAL.md](TECHNICAL.md): formats and offsets of both versions
* https://gbatemp.net/threads/romhacking-in-tales-of-destiny-2.373960/ (the
  original research thread)
* https://pastebin.com/fCVPLUP4 (text decoder routine)
* https://github.com/talestra/talestra/tree/master/compto (comptoe)
* https://gamefaqs.gamespot.com/ps2/561922-tales-of-destiny-2/faqs/58741
* Older research spreadsheet:
  https://docs.google.com/spreadsheets/d/1UVaEjK0o-V1-3atPHfRRw2q9QQcCzPCpr4GXJ2MLvvg

## Credits

* `Gandorff` for leading and maintaining the project, the translation, and the
  tooling
* `casino3346` for the PS2 and PSP ports, translation work, and the English
  manual
* `pnvnd` for terminology, the Lifebottle style reference, the format-aware
  PSP Japanese-string scanner, and full PS2 playtests with the feedback sheets
* `SkyBladeCloud` for the original file-format research, for
  reverse engineering the PSP font system and lowercase font-selection hack,
  and for finding the PS2 and PSP skit text speed control
* `dreck` for the redrawn PS2 Latin font, the PSP font work, and the skit
  timing analysis
* `Amarant01` for the font graphics: https://www.behance.net/deco-7105af
* `Lanyn` for permission to use the Tales of Destiny 2 English translation
  script: https://www.youtube.com/user/lanyn/videos
* The `Temple of Tales Translations` team (http://temple-tales.ru/translations.html)
  for the skit and scenario extraction tools
* `alizor` for the Python scripts to extract and repack the PS2 and PSP archives
* `flamethrower` / `flame1234` (GBAtemp) for the PSP string extractor
* `Asvel124`, `Randomggjc` and everyone in the RetroGameTalk thread
  (https://retrogametalk.com/threads/release-tales-of-destiny-2-ps2-psp-english-ai-translation.26456/)
  for testing and bug reports

Tales of Destiny 2 is a trademark of Bandai Namco. This is a non-commercial
fan project. See `LICENSE`.
