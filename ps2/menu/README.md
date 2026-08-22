# Menu and UI translation (PS2)

English text for the in-game menus, battle memos, world map and character
titles, plus the tools to apply it. No game files are included here: the
tables reference offsets inside files you extract yourself.

## What is covered

| Where | Strings | What |
|---|---|---|
| `*.md1` overlay modules in `FILE.FPB` | 510 (+122 inside `00017.pak3`) | items, equipment, shop, refine, enchant, save, status, customize, cooking UI, grade shop, monster book, titles, artes and tactics menus, name entry, battle system and the Battle Memos, world map region labels |
| `*.pak0` world map scripts in `FILE.FPB` | 256 | signposts, mine entrance labels, map location labels, ferry and minigame text, the flying dragon anchor scene, the ending monologue |
| `06306.scpk` | 1 | the opening caption "And so... eighteen years passed...", a scenario package that predates the proofread range (06307 onward) and has no text file of its own; patched in place inside the package |
| `SLPS_251.72` | 597 + 277 ops | character titles, plus the earlier Arte / Status / Enchant / Cooking-help menu patch (`slps_menu_patch.json`), so the executable is complete from a clean English-menu base |

The table has 766 FPB records. Eleven of them (the Battle Memo category
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

Extract `FILE.FPB` with PyTOD2 first (Extract Files). That creates an `FPB`
folder full of `06799.md1`, `09028.pak0` and so on. The first argument is
**that folder**, not `FILE.FPB` itself.

The paths below are written from the **repository root**, so `cd` there first,
not into this folder:

```
cd Tales-of-Destiny-2
python ps2/menu/patch_menu_text.py ps2/PyTOD2/FPB
python ps2/menu/sfm_text.py build ps2/PyTOD2/FPB
python ps2/menu/patch_slps_titles.py ps2/PyTOD2/SLPS_251.72
```

Windows and PowerShell work the same way; backslashes are fine:

```
cd C:\Users\you\Tales-of-Destiny-2
python ps2\menu\patch_menu_text.py ps2\PyTOD2\FPB
python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB
python ps2\menu\patch_slps_titles.py ps2\PyTOD2\SLPS_251.72
```

`patch_menu_text.py` covers the menus, `sfm_text.py build` covers the Quiz
Book (different files, see below), and both must run before Pack FPB.
Skipping the second leaves the whole Quiz Book in Japanese.

You can also run them from anywhere by giving the script an absolute path:

```
python C:\Users\you\Tales-of-Destiny-2\ps2\menu\patch_menu_text.py C:\Users\you\Tales-of-Destiny-2\ps2\PyTOD2\FPB
```

All three accept `--dry-run` to preview without writing. If you point them at the
wrong thing (at `FILE.FPB`, or one folder too high) they say so and change
nothing. The title patcher also accepts the folder containing `SLPS_251.72`.

Then run Pack FPB in PyTOD2 as usual and rebuild the ISO.

### Getting the patched files into the ISO (this is where it goes wrong)

Patching the `FPB` folder changes nothing in the game until the archive is
rebuilt. The full sequence, with the PyTOD2 button names:

1. **Unpack FPB** (creates the `FPB` folder).
2. `python ps2\menu\patch_menu_text.py ps2\PyTOD2\FPB`
   and `python ps2\menu\sfm_text.py build ps2\PyTOD2\FPB` (the Quiz Book).
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
5. Put `new_FILE.FPB` (as `FILE.FPB`) and `new_SLPS_251.72` (as
   `SLPS_251.72`) into the ISO.

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

* Every record is checked before anything is written: it must hold either
  the original Japanese or the final English. If any record in a file is
  something else, that whole file is left untouched rather than half-patched.
* Re-running is safe. Records that are already English are counted as
  current and skipped, so running again after a new version of the table
  only fills the gaps. The title patcher likewise reports an already patched
  executable instead of failing, and repairs one known problem from an
  earlier version of itself (a pooled title written over the previous
  string's terminator) if it finds it.
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

## Not translated

* Six added-arte names in `08055.md1`. They sit in dense records with what
  looks like a length prefix and no padding, unlike ordinary text which is
  zero-padded, so editing them risked breaking the record format. The arte
  names are already translated in `SLPS_251.72`.
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
