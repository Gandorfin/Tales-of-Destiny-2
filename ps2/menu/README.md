# Menu and UI translation (PS2)

English text for the in-game menus, battle memos, world map and character
titles, plus the tools to apply it. No game files are included here: the
tables reference offsets inside files you extract yourself.

## What is covered

| Where | Strings | What |
|---|---|---|
| `*.md1` overlay modules in `FILE.FPB` | 499 | items, equipment, shop, refine, enchant, save, status, customize, cooking UI, grade shop, monster book, titles, artes and tactics menus, name entry, battle system and the Battle Memos, world map region labels |
| `*.pak0` world map scripts in `FILE.FPB` | 256 | signposts, mine entrance labels, map location labels, ferry and minigame text, the flying dragon anchor scene, the ending monologue |
| `SLPS_251.72` | 597 | character titles |

Most menu text lives in the `md1` overlay modules inside `FILE.FPB`, not in
the executable, which is why it was easy to miss. All `pak0` files in this
build are stored uncompressed.

## Applying it

Extract `FILE.FPB` with PyTOD2 first, then:

```
python3 ps2/menu/patch_menu_text.py <folder PyTOD2 extracted FILE.FPB into>
python3 ps2/menu/patch_slps_titles.py <path to SLPS_251.72>
```

Both accept `--dry-run` to preview without writing. Then run Pack FPB in
PyTOD2 as usual and rebuild the ISO.

Order does not matter relative to the SLPS menu patch: every `md1` and `pak0`
edit is made **in place at identical file size**, so the FPB pointer table is
never touched and Pack FPB is unaffected.

## Safety

* Every record is checked against the original Japanese before anything is
  written. If any record in a file fails, that whole file is left untouched
  rather than half-patched.
* A `.bak` is written on first run.
* Re-running on an already-patched file is refused, because the Japanese no
  longer matches, so it cannot corrupt a patched file.
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
