# Menu and UI translation (PS2)

English text for the in-game menus, battle memos, world map and character
titles, plus the tools to apply it. No game files are included here: the
tables reference offsets inside files you extract yourself.

## What is covered

| Where | Strings | What |
|---|---|---|
| `*.md1` overlay modules in `FILE.FPB` | 525 (+122 inside `00017.pak3`) | items, equipment, shop, refine, enchant, save, status, customize, cooking UI, grade shop, monster book, titles, artes and tactics menus, name entry, battle system and the Battle Memos, world map region labels |
| `*.pak0` world map scripts in `FILE.FPB` | 261 | signposts, mine entrance labels, map location labels, ferry and minigame text, the flying dragon anchor scene, the ending monologue |
| `*.pak1` enemy packs in `FILE.FPB` | 159 table entries, alternate/cut-in literals + 218 enemy names | enemy arte and Mystic Arte names shown in battle, the lines bosses shout (Barbatos, Elrane and others) and the enemy-name banner at the start of an encounter (the name field in every enemy pack, plus the `TEKI` list in 08063.pak1), via `enemy_text.py` |
| `00017.pak3` member 4 (new) | 356 battle subtitles | spoken battle lines, drawn while the voice plays, via `battle_subs.py` (861 voice files listed in `battle_subtitles.csv`) |
| `06306.scpk` | 1 | the opening caption "And so... eighteen years passed...", a scenario package that predates the proofread range (06307 onward) and has no text file of its own; patched in place inside the package |
| `SLPS_251.72` | 597 + 277 ops + 27 cut-ins | character titles, plus the earlier Arte / Status / Enchant / Cooking-help menu patch (`slps_menu_patch.json`) and the battle cut-in names of the 27 party artes that still flashed up in kanji, so the executable is complete from a clean English-menu base |

The table has 787 FPB records. Eleven of them (the Battle Memo category
headings such as ＜特技習得＞, and four cooking menu labels) use three
character codes that `TBL.json` does not list; the decoder fills those in
(`0x9A7D` ＜, `0x9A7E` ＞, `0x9DD5` 熟).

Most menu text lives in the `md1` overlay modules inside `FILE.FPB`, not in
the executable, which is why it was easy to miss. All `pak0` files in this
build are stored uncompressed.

**Three modules exist twice.** The battle module (`08055`), the world map
module (`08996`) and `06304` are also stored LZSS-compressed inside
`00017.pak3`, and that is the copy the game loads. Patching only the loose
`08055.md1` changes nothing on screen. `patch_menu_text.py` therefore also
opens `00017.pak3`, patches the modules inside, recompresses them and
rebuilds the container (members 4-byte aligned, as in the original). The
codec is a pure Python port of the game's compressor (`lzss.py`), so no
`comptoe.exe` is needed; its output is byte-identical to comptoe's.
`verify_menu_patch.py` reports those compressed copies separately, marked
as the ones the game loads.

## Applying it

`python ps2/build_ps2.py` runs this whole sequence (the PyTOD2 steps, these
five tools, Pack FPB, the ISO, the font, the checks) in one command; see
"Building the patch from source" in the main README. Releases are made with
`scripts/make_release.py`. The manual steps:

Extract `FILE.FPB` (and `SLPS_251.72`) from the ISO with the old Cless
English menu patch, not the Japanese ISO, with PyTOD2 first (Extract Files). That creates an `FPB`
folder full of `06799.md1`, `09028.pak0` and so on. The first argument is
**that folder**, not `FILE.FPB` itself.

The paths below are written from the **repository root**, so `cd` there first,
not into this folder:

```
cd Tales-of-Destiny-2
python ps2/menu/patch_menu_text.py ps2/PyTOD2/FPB
python ps2/menu/sfm_text.py build ps2/PyTOD2/FPB
python ps2/menu/enemy_text.py build ps2/PyTOD2/FPB
python ps2/menu/battle_subs.py build ps2/PyTOD2/FPB
python ps2/menu/title_credit.py ps2/PyTOD2/FPB --version 1.3.1
python ps2/menu/patch_slps_titles.py ps2/PyTOD2/SLPS_251.72
```

Windows and PowerShell work the same way; backslashes are fine:

```
cd C:\Users\you\Tales-of-Destiny-2
python ps2\menu\patch_menu_text.py ps2\PyTOD2\FPB
python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB
python ps2\menu\enemy_text.py build ps2\PyTOD2\FPB
python ps2\menu\battle_subs.py build ps2\PyTOD2\FPB
python ps2\menu\title_credit.py ps2\PyTOD2\FPB --version 1.3.1
python ps2\menu\patch_slps_titles.py ps2\PyTOD2\SLPS_251.72
```

`patch_menu_text.py` covers the menus, `sfm_text.py build` covers the Quiz
Book and `enemy_text.py build` covers enemy arte names, Mystic Arte banners
and boss lines in battle (different files, see below); all three must run before Pack
FPB. Skipping one leaves that part of the game in Japanese. `battle_subs.py
build` adds English subtitles for the spoken battle lines (victory quotes
and the like, "Battle subtitles" below); it must run after
`patch_menu_text.py`, which rebuilds the same container.

Do not run PyTOD2's optional "Insert FONT" afterwards: it replaces the
game's Latin font with the 2008 alternative font (`font.bin`), which no
Green Gel release has used, and it would undo the `&`, `~` and `*` glyphs
that `patch_slps_titles.py` draws into the retail font (see "The Latin
font" below).

### Arte extension banners (`08055.md1`)

The green banner of a Base Arte Extension (the follow-up arte an Arte
Extension enchant adds, 飛連双閃 for Dreadfall and so on) is an inline
literal in the battle module's effect script: opcode `0A`, one argument
byte, then the name as a NUL-terminated string. The script is position
dependent, so the English must keep the eight bytes of the four kanji: the
fourteen entries in `menu_translations.csv` (offsets `0x4A7BE`..`0x4B187`)
are padded with spaces to exactly eight characters, and that limit is
hard. The Japanese column needs the battle font's own kanji codes, which
`md1text.py` adds on top of `TBL.json` (翔 閃 龍 燐 鼓, and the battle
font's copies of 闘 and 槍). Nanaly's, Reala's and Harold's extensions have
no banner literal anywhere in `FILE.FPB`, so there is nothing to translate
for them.

### The shop's sell prompt ("iH☆")

Selling an item showed `iH☆` instead of the confirmation. The cause is a
mistake in the 2008 menu patch, which appended an English string table to
the shop module `06803.md1` and pointed the module's string pointers at it.
For the sell confirmation it wrote the new address (`0x2A4869`, the appended
`Sell?` prompt) to the wrong place: over the first four bytes of the Japanese
prompt at `0x8A18` instead of into the pointer at `0x87A8`. That pointer
still leads to `0x8A18`, and the bytes `69 48 2A 00` of the stray address
read as the text `iH*` plus a terminator. `shop_prompt.py`, which
`patch_menu_text.py` runs on the shop module, writes the address into the
pointer, so selling asks `Sell?` the way buying asks `Buy?`. The records at
`0x89E8`, `0x89F0`, `0x8A1C` and `0x8A48` of the table are not reached by
the game in this module (their pointers lead to the appended table); an
earlier note here blamed the byte length of `  Buy` for the prompt, which
was wrong. `test_shop_prompt.py` guards the pointer repair.

### World map labels that do not fit their slot

A map label is one string in the map script's string storage, referenced by
an `F8` instruction with a 16-bit offset. Two English names are longer than
the Japanese slot: `Laguna Ruins` (both map files) and `Atamoni Ovum`
(`09032.pak0`, a ten-byte slot). `world_map_labels.py` writes each into zero
padding that follows another string of the same script and points the
instruction at it; the file size does not change. The padding only exists
once the string in front of it is English, which `patch_menu_text.py` sees
to before it relocates anything.

`title_credit.py` is the title screen: the two copyright lines under the
menu are a 384x32 texture in `00021.pak3`, not text. The tool redraws the
first line (the Japanese designer credit) as "Green Gel v1.3.1" and keeps
the Namco line; give it the version you are releasing. The title screen
draws that first line as a sprite about 96 pixels wide (the width of the
Japanese credit), which is why the label is short and condensed and why the
tool refuses a wider one. It only touches
pixels (same texture size and palette), recompresses the member, rebuilds the
pack and checks its own work, so it can be run again with a new version any
time before Pack FPB. `--label "text"` draws an exact string instead,
`--preview strip.png` writes the result as an image for a quick look. No extra
Python packages are needed (the letters are baked into `title_glyphs.py`).

You can also run them from anywhere by giving the script an absolute path:

```
python C:\Users\you\Tales-of-Destiny-2\ps2\menu\patch_menu_text.py C:\Users\you\Tales-of-Destiny-2\ps2\PyTOD2\FPB
```

All four accept `--dry-run` to preview without writing. If you point them at the
wrong thing (at `FILE.FPB`, or one folder too high) they say so and change
nothing. The title patcher also accepts the folder containing `SLPS_251.72`.

Then run Pack FPB in PyTOD2 as usual and rebuild the ISO.

### Getting the patched files into the ISO (this is where it goes wrong)

Patching the `FPB` folder changes nothing in the game until the archive is
rebuilt. The full sequence, with the PyTOD2 button names:

1. **Unpack FPB** (creates the `FPB` folder).
2. `python ps2\menu\patch_menu_text.py ps2\PyTOD2\FPB`
   and `python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB` (the Quiz Book)
   and `python ps2\menu\enemy_text.py build ps2\PyTOD2\FPB` (enemy artes)
   and `python ps2\menu\battle_subs.py build ps2\PyTOD2\FPB` (battle subtitles)
   and `python ps2\menu\title_credit.py ps2\PyTOD2\FPB --version 1.3.1`
   (the patch name on the title screen, with the version being released).
3. Make sure `new_SLPS_251.72` exists next to `SLPS_251.72` (Pack FPB
   writes the new pointer table into it), then
   `python ps2\menu\patch_slps_titles.py ps2\PyTOD2` which patches **both**
   copies it finds, so whichever one you ship is right. This applies the
   earlier Arte / Status / Enchant / Cooking-help menu patch first (all 277
   operations, verified byte for byte against its original installer's
   output) and the titles second, so a clean English-menu `SLPS_251.72`
   comes out complete. An executable that already has the menu patch is
   detected and only gets the titles.
4. **Pack FPB**. This writes `new_FILE.FPB` and updates `new_SLPS_251.72`.
   Pack FPB reapplies `enemy_text.py` after copying `PAK1_PACKED` into
   `FPB`, so staged enemy packs cannot restore the Japanese encounter-name
   table immediately before the archive is assembled.
5. Put `new_FILE.FPB` (as `FILE.FPB`) and `new_SLPS_251.72` (as
   `SLPS_251.72`) into the ISO.
6. After any font step, finish the ISO with
   `python ps2\menu\fix_disc_layout.py fix path\to\your.iso`: it gives the
   rebuilt image the retail UDF layout (file types, read only partition,
   closing anchor, whole 16-sector blocks) that a PS3 reads first. It
   changes descriptors only; `check` reports without writing.

If a screenshot still shows Japanese, check the build you are actually
running before changing anything:

```
python ps2\menu\verify_menu_patch.py path\to\your.iso
python ps2\menu\verify_menu_patch.py ps2\PyTOD2\new_FILE.FPB ps2\PyTOD2\new_SLPS_251.72
python ps2\menu\verify_menu_patch.py ps2\PyTOD2\FPB
```

It reads only what it needs (an ISO is fine) and prints, per file, how
many of the translated strings are English, Japanese or something else,
so you can see exactly which step was skipped. `PATCHED` everywhere means
the build is right and the remaining Japanese is text this patch does not
cover yet.

### If you also apply the earlier Arte, Status and Enchant menu patch

Apply that one **first**, then the titles. Both use the same spare string
area inside the executable. `patch_slps_titles.py` appends after whatever is
already there, so running it second is safe, while running it first and that
patch second would overwrite the titles. The script prints how much of that
area is already in use, and says so when it looks untouched, so you can tell
which state your executable is in.

Order does not matter relative to the SLPS menu patch: every `md1` and `pak0`
edit is made **in place at identical file size**, so the FPB pointer table is
never touched and Pack FPB is unaffected.

## Safety

* Every record is checked before anything is written: it must hold the
  original Japanese, the final English, or an English wording an earlier
  release wrote there. If any record in a file is something else, that whole
  file is left untouched rather than half-patched, and the run ends with a
  `NOT PATCHED` block that names it. **A file in that block keeps its old
  text in the game**, so do not build an ISO until the block is gone.
* The earlier wordings are in `menu_former_translations.csv`. They matter
  for a working `FPB` folder that is kept from one release to the next: its
  files hold the English of the older release, and without that table a
  single reworded record froze the whole file (the shop, the battle module
  and both world maps stayed at their 1.1.9 text that way). **After changing
  the English column of `menu_translations.csv`, run
  `python ps2/menu/update_former_translations.py` and commit the result**; it
  rebuilds the table from the history of the file.
* Re-running is safe. Records that are already English are counted as
  current and skipped, so running again after a new version of the table
  only fills the gaps. The title patcher likewise reports an already patched
  executable instead of failing, and repairs one known problem from an
  earlier version of itself (a pooled title written over the previous
  string's terminator) if it finds it.
* Known terminology from earlier English builds is migrated in place. This
  includes menu strings, titles reached through their current pointers, and
  Quiz Book strings that an earlier build relocated to the end of an SFM
  module. Ambiguous matches are refused rather than guessed.
* A `.bak` is written on first run.
* File sizes never change.
* For the titles, the patcher also verifies that each pointer really points at
  the record it claims before rewriting it.

## The text format

Strings are NUL-terminated arrays of font indices:

* `0x99`-`0x9F` and `0xE0`-`0xE4` begin a 2-byte character, looked up in
  `ps2/PyTOD2/TBL.json`
* `0x01` is a line break
* `0x03`-`0x09` and `0x0B` are a tag byte plus a 4-byte little-endian
  parameter (`color`, `size`, `num`, `char`, `item`, `button`)
* printable ASCII is literal, `0xA1`-`0xDF` is half-width katakana
* `0x12` and `0x14`-`0x18` start a formatting run that ends at `0xBC` or `0xC0`

`md1text.py` decodes this, `md1patch.py` encodes it back and checks that a
translation fits its slot.

### Battle Memo lines: 33 units, no more

The Battle Memo renderer draws at most 33 glyph slots per line, where every
character and every tag counts as one slot (the longest Japanese line is
exactly 33). Anything past that is simply not drawn. English is written
half-width, so a full memo line only reaches mid-screen; that is the
engine's limit, not a bug. Keep each memo line at 33 units or fewer.

The battle command labels (Artes / Plan / Equip / Items) sit in fixed slots
about five characters wide; "Tactics" overflowed into the next slot, hence
"Plan" there while the main menu keeps "Tactics".

### Two things worth knowing if you extend this

**Find string starts by parsing a text region linearly, not by scanning back to
the previous NUL.** Tag parameters contain zero bytes, so scanning backwards
stops in the middle of a control code and writing there corrupts it.

**A string's budget is its own bytes plus any trailing NUL padding, minus one
for the terminator.** Japanese costs 2 bytes per character and English 1, so
most translations fit in place. Titles are the exception: they are packed into
contiguous arenas, so `patch_slps_titles.py` repacks a whole arena and rewrites
the pointers, spilling into the spare string pool only when an arena fills up.

## The executable's spare string pool is not spare

Text that does not fit where the Japanese was goes into a run of zeros in
`SLPS_251.72`, `0xFAB10..0xFC530`. Those zeros are the work area of the
game's CD/DVD library (the bytes between the `PsIIlibcdvd` and
`PsIIlibkernl` markers). The game calls two functions of that library,
`sceCdInit` and `sceCdMmode`, both while it boots, and they write here:

| File offset | Bytes | Written by |
|---|---|---|
| `0xFAB10` | 4 | init counter, incremented by every `sceCdInit` |
| `0xFBCC0` | 16 | reply buffer of the init and media mode commands |
| `0xFC100` | 4 | parameter buffer of the media mode command |
| `0xFC508` | 40 | RPC client record of the command channel |

A string on one of these ranges is fine in the file and damaged in memory.
That is why Kyle's arte Kyoueisou could read "Lyoueisou", why the Battle
Rank after Normal and the item Pickaxe drew as nothing, and why the title
Ferry to Cherik and one cooking message were cut short. The rest of the
area is only touched by library functions the game never calls, which is
why pooled text works at all.

`patch_slps_titles.py` keeps the list (`LIVE`), places nothing at or above
`0xFC508`, and as its fourth step moves any pooled string that touches a
range, with its pointers, and zeroes the bytes it leaves. The manifest
strings that sat on a range have a `former_pool_offset` and now live in a
second pool: the zero run `0x115E54..0x115F60` after the destination list
in `.rodata`, which the game cannot write to. The only references into that
run come from a debug list of battle backgrounds that the 2008 patch already
broke. `test_slps_pool.py` checks that no manifest string is on a live
range. Before adding text to the executable, check the table above.

The manifest also restores the game's own file name. The 2008 patch wiped
`SLPS_251.72` out of the string `cdrom0:\SLPS_251.72` at `0xFE698` (its arte
text starts eight bytes too early). The game hands that string to
`VENUS.ELF`, the Venus & Braves preview on the title menu, as the program to
start when the preview ends; with only `cdrom0:\` left the console fell
back to its browser screen.

## Not translated

* A handful of fragments whose first character is absent from `TBL.json`.
* Cooking recipe names. They are not text: two independent scans found them in
  no encoding anywhere in the executable or `FILE.FPB`, so they appear to be
  baked into TM2 graphics and need an image edit instead.

## Quiz Book (`sfm_text.py`)

The Quiz Book minigame keeps its text in FPB members 06171 to 06301 (type
`sfm`, LZSS-compressed script modules). `sfm_text.py` extracts and rebuilds
that text; `quiz_translations.csv` holds the records (file, section-relative
offset, in-place byte budget, pinned flag, Japanese, English).

```
python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB            # patch the sfm files in place (backups as .bak)
python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB --dry-run  # report only
python ps2\menu\sfm_text.py extract ps2\PyTOD2\FPB          # regenerate the CSV (keeps existing English)
```

English that fits the Japanese slot is written in place; longer English is
appended to the module's data section and every pointer to the old string is
redirected. Strings marked `pinned` have references the tool cannot prove to
be pointers, so their English must fit the budget (the build reports any
overflow and leaves that string Japanese). Run `build` before `Pack FPB`, in
the same folder as `patch_menu_text.py`.

When terminology changes in a later release, `build` can also find a known
former English value at its relocated offset and replace it without requiring
a clean Japanese module. It still validates live source strings and refuses
multiple matches, so this migration path does not weaken clean-build checks.

## Enemy artes and boss lines (`enemy_text.py`)

Every enemy has a `pak1` pack (08063 onward): a `u32 count` plus
(offset, size) pairs, members 16-byte aligned. Member 1 is a comptoe v3
LZSS stream holding an `ENd` script, and the names that flash up when an
enemy uses an arte, plus the lines bosses shout, are string literals
inside that script: opcode `0A`, one argument byte, then the NUL-terminated
text in the usual TBL encoding. Nothing points at them, so the English
is written in place, padded with spaces to the Japanese byte count, and
no offset in the script moves. `enemy_translations.csv` holds the 159
canonical strings (89 distinct) with their byte budgets. The same scripts
also occur 61 times in alternate ENd members (usually member 4 or 5) across
48 packs. `build` patches those reused copies by matching their Japanese
text, including Rune Uruz and Rune Algiz variants that do not load member 1.
Additional strings exist only in alternate members: Sand Shoot, Luminous
Field, Genius, Wisdom Rondo, Regeneration, Spider Net and Might Oratorio.
They are listed in `EXTRA_TRANSLATIONS` in `enemy_text.py` and receive the
same in-place, fixed-budget treatment.

Mystic Arte cut-ins are literals in `efD` effect scripts. Most decode through
the normal table, but Judas's kanji banner uses a cut-in-specific glyph page;
`enemy_text.py` identifies its exact raw byte sequence before decoding so it
cannot fall back to Japanese. Compact English names are used where the full
localized name cannot fit the fixed byte slot. Mystic Arte and hyphen-wrapped
enemy banners are padded on both sides so they render centered instead of
left-aligned; ordinary battle lines keep their original alignment.

```
python ps2\menu\enemy_text.py build ps2\PyTOD2\FPB            # patch the pak1 files in place (backups as .bak)
python ps2\menu\enemy_text.py build ps2\PyTOD2\FPB --dry-run  # report only
python ps2\menu\enemy_text.py extract ps2\PyTOD2\FPB          # regenerate the CSV (keeps existing English)
python ps2\menu\enemy_text.py check                          # every English line fits its budget
```

`build` also translates the enemy names from `enemy_names.csv` (columns
slot, japanese, english, 218 names). The name banner at the start of an
encounter reads the enemy's own pack, not a central list: every `ENd`
member of a `.pak1` (members 1, 4, 5 or 7) carries a parameter block
with a 24-byte name field, the TBL name padded with NULs and one data byte
last. The retail disc has 951 such fields in 550 packs (215 distinct
names); English is written into the field, the data byte and the stats
after it untouched, longest Japanese name first so デス is never matched
inside デスナイト. The `TEKI` list in 08063.pak1 (one LZSS member starting
with `TEKI`, 256 slots of 0x1C bytes: a 24-byte space-padded name plus
four data bytes) is patched as well so both lists agree. Gandorff's
2026-09-03 test showed the banner still Japanese with only the `TEKI`
list translated, which is how the pack copies were found. The name list
in 06813.md1 and the category and immunity tables at 06813 0x7731 still
look dead (the 2008 patch relocated the English versions the Monster
Book shows).

## Battle subtitles (`battle_subs.py`)

The voices in battle (victory quotes, spell incantations, the lines a
character shouts with a special arte, the banter and hints in scripted
fights, boss lines) had no text at all. `battle_subs.py build` adds English
subtitles for them. They appear centred just above the HP bars while the
line plays, in the battle font, white; when two characters talk at once
the second line goes above the first.

```
python ps2\menu\battle_subs.py build ps2\PyTOD2\FPB            # patch 00017.pak3 in place
python ps2\menu\battle_subs.py build ps2\PyTOD2\FPB --dry-run  # report only
python ps2\menu\battle_subs.py check                          # check the table
```

Run it after `patch_menu_text.py` (both rebuild `00017.pak3`) and before
Pack FPB. Running it again on the same folder replaces the earlier
subtitles, so the table can be edited and the step repeated.

The text is `battle_subtitles.csv`: voice_id, member, owner, speaker,
seconds, japanese, english. One row per battle voice file, 861 rows (the
member column is the FILE.FPB member, `audio/ps2_audio.csv` lists them;
party voice N is member 7253 + N); 356 of them have English: victory
quotes, incantations, the phrases of special artes, the leader's orders,
the hints and banter of scripted fights and the boss lines. Speaker `*` means the game supplies the name: the hook writes
the name of the character who plays the voice, so scripted lines whose
speaker is not known from the file name still get the right one. Speaker
empty means no name (lines with several speakers carry the names in the
text, boss lines whose boss is not certain). Rows without English draw
nothing: grunts, and arte shouts that only say the arte name (the arte
banner shows it already).

Limits: one line holds 54 characters (46 when the game adds the name),
longer text wraps at spaces into up to three lines. The battle font has no
glyphs for `[ ] _ @ ^`, and its comma sits a little high.

How it works (details in TECHNICAL.md, "PS2: battle voices and battle
subtitles"): a 472 byte hook appended to the battle module (member 0 of
`00017.pak3`, in the 4 KB the overlay buffer has left) replaces the call of
the battle frame function; after the frame it looks at every actor, and
the halfword at actor + 0x13E is the id of the voice that actor is
speaking. The table is a fourth, uncompressed member of `00017.pak3`; the
game loads the whole container at boot and never reads that member, the
hook finds it through the container's offset table.

The Japanese column comes from Whisper (large-v3-turbo) on the PS2 voice
files and was corrected by hand where the wording was clear from context
(incantations, arte names); it has not been checked by ear line by line.

The PSP build reads a copy of this table (`psp/text/battle_subtitles.csv`,
`psp/tools/psp_battle_subs.py`; the voice ids are the same): after an
edit run `python psp/tools/sync_text_from_ps2.py` and commit both files.

## The Latin font (`slps_font.py`)

For custom font artwork, [FONT_CUSTOMIZATION.md](FONT_CUSTOMIZATION.md)
explains how to use the standalone `patch_font_iso.py` tool. It exports an
editable PNG from an ISO, validates a single edited PNG, converts it back to
the game's TM2@ format and writes a verified ISO copy.

The Latin glyphs the game draws come from one compressed TM2 texture inside
`SLPS_251.72` (file offset `0xCA238`, 128x512 pixels, 4 bits per pixel,
cells of 12x16 in rows of ten). Single-byte text goes through a 96-entry
table at `0xC9D00` (glyph cell per ASCII code `0x20`..`0x7F`). The retail
table sends `&` and `~` to empty cells, so both showed as gaps, and `*`
to a star. `patch_slps_titles.py` runs `slps_font.py` as its fourth step:
it draws an ampersand and a tilde over the two curly-quote cells that only
`#` and `$` reach (no text of the patch uses those), redraws the star cell
as an asterisk, packs the texture back into the room it came from and
points `&` and `~` at the new cells. The script text can therefore use the
plain ASCII `&`; `~` will follow once the glyph has been seen in a build
(the scripts still carry the full-width `～` from the kanji font).

```
python ps2/menu/slps_font.py ps2/PyTOD2/SLPS_251.72 --export font.png --grid
```

writes the texture as a PNG with cell indices (Pillow needed) for checking
or redrawing glyphs; the glyph art itself is ASCII art in `slps_font.py`.

## Battle cut-in names of the party artes (`slps_artes.py`)

The green banner that flashes up when a party member uses an arte does
not use the arte's menu name pointer: it shows the string that follows
the arte's *reading* in the executable (records of 28 bytes at 0xB7000,
pointers to menu name, reading and description). The 2008 patch wrote
English after the reading for 14 artes and left the kanji for 27 (Loni's
and Judas's, mostly), which is why "Soudashou" in the menu was 双打鐘 in
battle. `patch_slps_titles.py` now fixes that as its third step: each of
the 27 gets a new "reading + menu name" slot in the spare pool or in the
room another record freed, and its reading pointer is redirected. The
cut-in text is always the menu name, so the two agree.

**There is no new command and nothing to point at the FPB folder.**
`slps_artes.py` is a module, not a script; it runs inside the existing
executable step:

```
python ps2\menu\patch_slps_titles.py ps2\PyTOD2\SLPS_251.72
```

whose output gains a line `arte cut-in names: 27 redirected (...)`, or
`all English` when the step was already done.
