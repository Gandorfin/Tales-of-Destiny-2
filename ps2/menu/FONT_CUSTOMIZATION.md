# Custom PS2 font from one PNG

`patch_font_iso.py` is a standalone script for Tales of Destiny 2 PS2
(SLPS-25172). Give it an edited font PNG and your ISO; it builds the game's
TM2@ font texture, compresses it and writes a verified ISO copy.

Only this Python file is needed from the repository. Install Python 3.10+
and its two dependencies once:

```powershell
python -m pip install Pillow pycdlib
```

## Export, edit and patch

Put the script beside your ISO, or use full paths.

1. Export a compatible template from the ISO you intend to patch:

   ```powershell
   python patch_font_iso.py export "game.iso" "font.png"
   ```

2. Edit `font.png` in a pixel editor. Keep it exactly **128 x 512 pixels**.
   Preserve the indexed palette and transparency; draw using the existing
   16 colours. Keep the glyphs in their original cells (12 x 16 pixels,
   ten cells per row). Avoid resizing, smoothing, palette optimization and
   changes to opacity. Keep the exported palette even if its preview looks
   blue or partly transparent: the game uses several palettes for the same
   pixels. The export preserves the raw PS2 alpha values (usually 128 for
   opaque entries), rather than scaling them to PNG alpha 255.

3. Optionally validate the PNG and compression fit:

   ```powershell
   python patch_font_iso.py check "game.iso" "font.png"
   ```

4. Write a new ISO:

   ```powershell
   python patch_font_iso.py patch "game.iso" "font.png" -o "game-custom-font.iso"
   ```

   Without `-o`, the output is named `game-custom-font.iso` next to the input.
   Existing outputs are refused. The output directory needs space for another
   full ISO. The tool prints the output SHA-256 after verification.

You can use an existing PNG directly if it passes `check`. Indexed PNGs must
use only indices 0–15 and retain the corresponding template colours. RGBA
PNGs are accepted when every pixel exactly matches one of the template's
16 RGBA colours. RGB images without alpha, animated PNGs and incompatible
dimensions/palettes are rejected.

## What the script preserves

The template comes from your own ISO; the script contains no game font assets.
It preserves all ten palette blocks, the TM2@ metadata, glyph mapping and
everything outside the font's reserved executable region. The TM2@ conversion
takes place in memory, so no separate TM2 file or converter is required.

For Green Gel/English-menu images, the font must compress to **10,242 bytes
or less**. Original Japanese images have a larger stream; the tool uses its
current length as the limit (21,785 bytes on the tested retail disc).
An overly detailed font can exceed that limit even when its PNG dimensions
and palette are correct. The tool refuses the edit before creating an ISO;
simplify the glyph detail or restore unused cells and retry.

The output retains the original ISO size, file positions and directory data.
The tool checks that ISO9660 and UDF, when present, refer to the same contiguous
executable data, then verifies every output byte against the input with only
the font slot allowed to differ. Existing movie archives, hardsubs, scripts,
menu translations and saves are not edited. Use the completed translation ISO
as input and apply this customization last: running other font patchers later
can replace customized glyphs.

## Verification performed

- Fourteen automated tests cover codec round trips, palette/dimension
  rejection, compression overflow, UDF disagreement, output overwrite
  protection and cleanup after failed verification.
- Export and unchanged-PNG validation passed on the original Japanese ISO
  and the Green Gel v1.2.2 ISO.
- The script ran from an isolated folder with no repository imports, patched
  one pixel in a temporary v1.2.2 ISO and verified that every byte outside the
  font slot remained identical. The temporary ISO was removed after testing.

Boot and visual checks in PCSX2 or on hardware are still needed for each
user-designed font; byte verification cannot judge glyph legibility.

