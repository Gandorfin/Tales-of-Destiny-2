# Custom PSP dialogue font from one PNG

Send the font designer **this folder's `patch_font_iso.py`**. It is standalone:
no other repository files or game assets are bundled or required. It is the
PSP tool; the identically named script under `ps2/menu` is for PS2.

Requires Python 3.10+ and Pillow:

```powershell
python -m pip install Pillow
```

Supply an uncompressed Tales of Destiny 2 PSP ISO, disc ID **ULJS-00097**.
Use the translated ISO when designing a font for the English patch, so the
export includes its custom lowercase glyphs and existing character layout.

## Export, edit, prepare, check, patch

Place the script beside the ISO, or use full paths:

```powershell
python patch_font_iso.py export "tod2_psp_collaborator_20260830_freeze_fix.iso" "psp-font.png"
```

Edit `psp-font.png` at its original **256 x 4400** size. This is a sheet of
**23 x 23 pixel cells, 11 cells per row**. Keep every glyph in its existing
cell; preserve unused regions and the patched lowercase cells. The export is
indexed 4bpp grayscale: 16 levels from black (0) to white (255), in steps of 17.
The PSP assigns text colours when drawing, so this is not the PS2 blue palette
or a TM2 texture. Black is zero coverage; white is full coverage.

If the editor changed the palette, added intermediate grays, or saved RGB/RGBA,
prepare a new PNG:

```powershell
python patch_font_iso.py prepare "tod2_psp_collaborator_20260830_freeze_fix.iso" "edited.png" "psp-font-ready.png"
```

`prepare` converts to 16 grayscale levels and writes an indexed 4bpp PNG.
RGBA transparency is composited onto black before quantization: transparent
white becomes zero coverage, while opaque white remains full coverage.
It preserves dimensions and cell positions and checks compression before
publishing the new PNG. It does not silently reduce the image below 16 levels.
Palette ordering is handled through actual pixel colours, so reordered
grayscale palette indices are accepted.

Then validate and produce a new ISO:

```powershell
python patch_font_iso.py check "tod2_psp_collaborator_20260830_freeze_fix.iso" "psp-font-ready.png"
python patch_font_iso.py patch "tod2_psp_collaborator_20260830_freeze_fix.iso" "psp-font-ready.png" -o "tod2-psp-custom-font.iso"
```

An edited PNG that retains the exact 16 grayscale levels can go straight to
`check`/`patch`. All commands accept full paths. Without `-o`, `patch` appends
`-custom-font.iso` to the input stem. Existing output files are refused. Keep
enough free space for a full ISO copy. An unchanged export/reimport preserves
every ISO byte, including the original compressed stream.

## Compression and supported images

The tool reads the font allocation from the selected ISO. Both supplied images
reserve **299,008 bytes** for archive member 00000:

- `Tales of Destiny 2 (Japan) PSP.iso`
- `tod2_psp_collaborator_20260830_freeze_fix.iso`

The translated sheet is close to that limit. More detailed glyphs can overflow
even with correct PNG dimensions and colours. If needed, simplify the edited
cells, or explicitly request fewer intensity levels:

```powershell
python patch_font_iso.py prepare "game.iso" "edited.png" "font-8-levels.png" --levels 8
```

Allowed values are 2, 4, 8 and 16; fewer levels lose shading and may improve
compression, but fitting is always checked. Saving a PNG as 4bpp by itself
does not bypass the compressed-font limit.

The physical texture is PSP-swizzled 4bpp, 563,200 bytes before raw-deflate
compression. The tool handles swizzling, nibble order and compression.
Some old helper comments mention a 512 x 2200 preview; this tool exports the
actual 256 x 4400 cell layout. PS2 128 x 512 fonts and resized sheets are rejected.

## What changes

For the translated image, the output changes only:

- archive member 00000 and its existing sector padding;
- its four-byte size/remainder entry in each of `BOOT.BIN` and `EBOOT.BIN`.

All other archive members stay byte-identical at their original positions.
Character mappings, lowercase routing, code, text, movies and other fonts
are preserved. The bold menu/icon font uses a separate resource and is not
edited by this tool. Replacing glyph artwork does not add new characters,
change advance widths, or redirect characters to different cells.

For the supported clean Japanese image, an edited font additionally requires
replacing the encrypted `EBOOT.BIN` with the decrypted `BOOT.BIN` already
present on that disc, with the new font-size entry applied. The executable
stays in its existing ISO extent; its directory size is updated in both
ISO9660 byte orders. This follows the existing PSP build tools and requires
PPSSPP or a PSP able to run unsigned images. The tool identifies the known
retail encrypted executable by SHA-256 and rejects unknown encrypted builds.
An unchanged font does not trigger this conversion.

When a replacement compresses much smaller, the tool inserts valid empty
DEFLATE blocks before the end of the stream so the archive's 11-bit remainder
still describes the original sector span. These are part of a complete,
validated deflate stream, not junk appended after its terminator.

## Verification

The output is written to a temporary file, read back, and compared against
every input ISO byte with only the explicitly planned edits allowed.
The tool checks disc ID, file bounds, archive boundaries, both executable
tables, decompressed size, palette values and texture round-trip. It refuses
overlapping extents, unsupported ISO layouts, CSO/PBP input and overwrites.
Only after verification does it publish the new ISO and print its SHA-256.

Thirteen synthetic tests cover swizzle coordinates, exact reimport, legal
deflate padding, overflow, palette reordering, alpha conversion, malformed
input, retail startup conversion, output preservation and failure cleanup.
Tests use Pillow and pycdlib; the standalone tool itself only needs Pillow:

```powershell
python -m pip install Pillow pycdlib
python -m unittest discover -s psp/tools -p test_patch_font_iso.py
```

Export/check and one-pixel-edit patching passed on both named real ISOs.
The entire outputs passed byte verification and independent ISO-directory
readback with pycdlib. Temporary test outputs were removed.

PPSSPP/hardware boot and visual font checks have not been performed for this
tool. Test the resulting ISO with a fresh boot; a save state may retain the
previous font in memory.
