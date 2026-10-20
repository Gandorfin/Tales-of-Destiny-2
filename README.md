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
| PSP (ULJS-00097) | **v0.3.2** (one download, variable width font; v0.3.1 also came without the lowercase font hack) | **Playable in emulators and on a PS Vita.** Story, skits, movies, world map and almost every menu are English; a few areas are still Japanese (listed below). A real PSP does not run it yet. |

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
* PS3 playback: the v1.3.0 download was built without the disc layout fix
  (last build step), so a PS3 shows it as a blue disc (pnvnd; it works after
  burning with ImgBurn). Run the fix on your patched ISO yourself, see
  [Playing it](#ps2-1). Releases have to run it as step 8 of the build.

In the source for the next PS2 release: every skit line now finishes
before the next speaker starts (dreck's report on v1.3.0: the next voice
began while the text was still scrolling), and the 30 lines that needed
more than 20 characters per second were shortened.

### PSP

v0.3.2 (16 October 2026) has the full story script, all 608 timed skits at
full length with per line text speed (as PS2 v1.3.0), menus, items, artes,
titles, descriptions, the Quiz Book, English subtitles in the nine movies
with dialogue and the PSP's own ending staff roll in English. New in
v0.3.2:

* a new English font: all Latin text (dialogue, skits, menus, labels) is
  drawn in one typeface, Fira Sans SemiBold (SIL Open Font License), on one
  baseline with real descenders, and every letter has its own width (no
  more typewriter look); text boxes fit the text, and full-width labels
  such as NEW GAME or HP use the same font
* lowercase in the bold menu text: party names, menu tabs, Battle Rank and
  the Custom menu values read "Kyle", "Normal" instead of KYLE, NORMAL
* the world map in English in all five eras: the location name over a town
  or dungeon, signposts and mine labels, the box puzzle, vehicle controls,
  the Draconis anchor scene and Kyle's ending monologue
* about 100 menu strings that had English in the table but were never
  applied: all shop names, scene titles and some labels; Frostheim (not
  Snowfria) in the PSP only menus
* the enemy name banner at the start of a battle ("Owlbear 1"), the first
  time menu tip about the key help, and short "Hira" / "Kata" labels on the
  name entry screen

Where it runs (reports from the forum, October 2026): PPSSPP on PC, on
Android (a development build, v1.20.4 or newer, ran best) and on the
Switch, and the PSP emulator of a PS3 run v0.3.2. A PS Vita with
Adrenaline plays it with infrequent crashes (for example when selecting
some items). **A real PSP does not run it yet:** a PSP-3000 stops on a
white screen after the logos with v0.3.2, a PSP-2000 crashed often with
v0.3.1. This is being investigated; see
[Help wanted](#help-wanted-open-psp-problems).

Still Japanese on PSP (full scan of the current source, October 2026):

* menu messages the patch does not apply yet: the button legends of most
  menus, some shop and cooking confirmations and cooking results, the field
  exit prompt ("Leave Cresta"), the airship landing message, the "obtained
  the title" message
* the single-kanji element and status labels (地 水 火 風 光 闇 毒)
* the save screen (the game title and the Gald / Lens / Clear line), the
  texts of the PSP only Illustration Book, and the PSP_GAME picture
  PIC1.PNG shown in the system menu
* the Mystic Arte banners of some enemies, and about 50 enemy arte names
  and boss lines that have no table yet

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
4. PS3: if the console shows the disc as a blue disc instead of an orange
   PS2 disc (v1.3.0 was released without the disc layout fix), install
   Python, download this repository and run
   `python ps2\menu\fix_disc_layout.py fix "your patched.iso"` from its
   folder before burning. It changes only file system descriptors.

### PSP

1. Download the PSP patch from the
   [releases page](https://github.com/Gandorfin/Tales-of-Destiny-2/releases)
   (tags `PSP_X.Y.Z`). Since v0.3.2 there is one file (`VWF`, the variable
   width font). v0.3.1 and older came as `Font_Hack` (mixed case) and
   `No_Font_Hack` (capitals only, for devices where the first one crashed).
2. You need your own dump of the Japanese UMD (ULJS-00097). Apply the patch
   with Delta Patcher or `xdelta3 -d -s original.iso patch.xdelta patched.iso`.
3. Play on PPSSPP (on Android a development build, v1.20.4 or newer) or a
   PS Vita with Adrenaline. A real PSP with custom firmware does not run
   v0.3.2 yet (see Status).

The title screen shows the patch version ("Green Gel vX.Y.Z" on PS2,
"Green Gel vX.Y.Z" on PSP since 0.3.3). Please include it in bug reports.

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
* **Monster Book display names.** The next release writes English into the
  TEKI list (member 08331), which the encounter banner reads; the Monster
  Book most likely reads it too. Someone with a save that has the Library
  should check the book screen.
* **Real hardware.** Up to v0.3.0 the PSP kernel never loaded the patch's
  string pool (it loads only consecutive program headers), which explained
  the missing labels, random characters and freezes on a PSP or a Vita.
  Since v0.3.1 the kernel loads it, and the PS Vita (Adrenaline) plays the
  game with infrequent crashes. A real PSP still fails: a PSP-3000 stops on
  a white screen after the logos with v0.3.2, a PSP-2000 crashed often
  with v0.3.1. Not the cause, checked in an emulator with the release and
  a build of the same source:
  the kernel load and relocation rules, misaligned memory access (none in
  boot, title, story, battle, town and menus), the larger executable (the
  game still runs with 2 MB less memory) and the code hooks' instructions.
  Wanted: a crash report from a real PSP (an exception handler plugin that
  shows the crash address) and which builds boot there.
  Android PPSSPP showed flickering menu items with v0.3.0; with v0.3.2 and a
  development build only some text in the cooking menu flickers.

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

One command runs every step below in order, with no GUI, on Windows,
Linux or macOS:

```
python ps2/build_ps2.py --japanese-iso "Tales of Destiny 2 (Japan).iso" --cless-iso "Tales of Destiny 2 (Eng-cless patch).iso" --movie-fpb MOVIE.FPB --version 1.3.1 --out tod2_ps2_en.iso
```

* `--cless-iso` is the build base: the ISO with the old (2008) Cless
  English menu patch. Its FILE.FPB and SLPS_251.72 hold the menus the
  menu tools patch. It differs from the Japanese ISO in those two files
  only. `--base-fpb` and `--base-slps` take the two files instead.
* `--movie-fpb` is the MOVIE.FPB with the subtitled movies (take it from
  the latest release; step 5 explains how to rebuild it).
* `--japanese-iso` is the clean Japanese ISO. The three rebuilt files
  (FILE.FPB, SLPS_251.72, MOVIE.FPB) are written into a copy of it in
  place (`ps2/menu/replace_iso_files.py`), so every other file stays
  byte for byte retail and the image has the retail disc layout.
* `--font` is the Latin font PNG (default: dreck's
  `ps2/menu/font-ready_final.png`, the one the releases carry).
* The build runs the PyTOD2 steps through the same functions as its
  buttons, then the menu tools, Pack FPB, the ISO, the font,
  `verify_menu_patch.py` and the disc layout check, and stops at the
  first failure. `--work FOLDER` keeps all intermediate files there.
  Outside Windows, `ps2/menu/lzss.py` does the compressing that
  comptoe.exe does on Windows.

The manual steps (details in `ps2/menu/README.md`, "Applying it", and
`ps2/movies/README.md`):

1. Extract `FILE.FPB` and `SLPS_251.72` from the Cless ISO (old English
   menu patch, not the Japanese ISO) into
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
4. Pack FPB. It writes `FILE_NEW.FPB` and `new_SLPS_251.72`; those two
   (renamed to `FILE.FPB` and `SLPS_251.72`) go into the ISO. Do
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
python psp/tools/build_psp.py "Tales of Destiny 2 (Japan) PSP.iso" tod2_psp_en.iso --version 0.3.2 --movies
```

* `--version` is the number drawn on the title screen as
  "Green Gel vX.Y.Z"; pass the one you are releasing.
* `--movies` burns the English subtitles into the movies. **Without it the
  movies stay Japanese.** It needs an FFmpeg with libass and libx264:
  `imageio-ffmpeg` brings one, or pass `--ffmpeg C:\path\to\ffmpeg.exe`.
  The log shows a `movie 0NN (PS2 000NN):` block for each of the nine movies.
* `--vwf off` keeps the retail fixed letter width (the font hack builds up
  to v0.3.1); `--lowercase-font off` also leaves out the lowercase font hack
  (the `No_Font_Hack` download up to v0.3.1).
* `--keep WORKDIR` keeps the extracted and rebuilt files.

The build extracts BOOT.BIN and file.fpb, applies the party names, menus
(in place or through the string pool), lowercase font, scenario and skit
text with skit speeds, enemy names, the Quiz Book, the world map scripts,
the title credit and the movies, then
repacks, verifies every rebuilt file and writes the ISO. Each step is
explained in `psp/tools/README.md`. A custom font goes in on the finished
ISO with `psp/tools/patch_font_iso.py` (`psp/tools/FONT_CUSTOMIZATION.md`).

### Making a release

One command per platform builds, checks and packs a release:

```
python -m pip install py7zr
python scripts/make_release.py ps2 --version 1.3.1
python scripts/make_release.py psp --version 0.3.3
```

It checks out upstream/main (or `--commit`) into a clean folder, runs the
translation audit and the unit tests, builds with `ps2/build_ps2.py` or
`psp/tools/build_psp.py --movies`, makes the xdelta (`xdelta3 -e -9 -S none`,
no secondary compression, which some patchers cannot read), applies it to
the clean Japanese ISO again and checks the result is the built ISO byte for
byte, runs the release checks (PS2: menus and disc layout; PSP: BOOT.BIN load
order), packs the 7z with the usual names (`ToD2_Eng_patch_QS_vX.7z`,
`PSP_Patch_VWF_vX.7z`) and drafts the notes from the merged PRs. For the
PS2 it takes MOVIE.FPB from the latest PS2 release unless `--movie-fpb` is
given. With `--upload` it creates a draft GitHub release and uploads the
7z; the draft goes public when someone clicks Publish on its page.

Local paths go in `release.local.json` in the repository root (not
committed): `japanese_iso_ps2`, `cless_iso`, `japanese_iso_psp`, `xdelta3`
(path of the xdelta3 program) and `token_file` (a file with a classic
GitHub token, scope public_repo, only needed for `--upload`).

The PS2 xdelta is around 465 MB (about 415 MB as a 7z) because the movies
with dialogue are re-encoded; the PSP one around 795 MB.

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
