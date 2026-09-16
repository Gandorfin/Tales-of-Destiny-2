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

   If an editor or palette converter changes the PNG to RGB/RGBA, moves the
   transparent colour, alters alpha values, or produces a font that is too
   detailed for the English executable, normalize it with:

   ```powershell
   python patch_font_iso.py prepare "game.iso" "edited.png" "font-ready.png"
   ```

   Use `font-ready.png` for the remaining commands. `prepare` maps pixels to
   the exact palette and transparency stored in that ISO, saves a real indexed
   4bpp PNG, and reduces colour use only as far as required by the available
   compressed-font slot. It accepts indexed, RGB and RGBA input. Pixels with
   alpha below 16 are transparent by default; unusually faint artwork can use
   `--alpha-threshold 1`.

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
dimensions/palettes are rejected by `check`/`patch`; RGB can be converted by
the explicit `prepare` command. A transparent background is strongly
recommended because an RGB image has no way to identify transparent pixels.

## What the script preserves

The template comes from your own ISO; the script contains no game font assets.
It preserves all ten palette blocks, the TM2@ metadata, glyph mapping and
everything outside the font's reserved executable region. The TM2@ conversion
takes place in memory, so no separate TM2 file or converter is required.

For Green Gel/English-menu images, the font must compress to **10,242 bytes
or less**. Original Japanese images have a larger stream; the tool uses its
current length as the limit (21,785 bytes on the tested retail disc).
An overly detailed font can exceed that limit even when its PNG dimensions,
indexed palette and PNG bit depth are correct. PNG storage as 4bpp does not
reduce the game's compressed texture: the patcher always converts accepted
input to 4bpp internally. Use `prepare` to make the smallest automatic colour
reduction, or manually simplify glyph detail/restore unused cells.

### Common errors

- `compresses to 21761 bytes; the limit is 10242` does **not** mean the PNG
  needs a generic 4bpp conversion. The patcher already produces the game's
  packed 4bpp pixels. The original Japanese sheet simply contains far more
  detail than the translated executable's remaining font slot. Run `prepare`
  against the translated ISO to produce a fitted copy.
- `Palette index ... differs from the ISO template` means an image tool
  changed RGB values, raw PS2 alpha, palette ordering or the transparent
  index. Do not bypass this check: incorrect indices cause the colours seen
  in game to be wrong. Run `prepare` on the RGBA or indexed source instead.
- Prefer the pre-conversion RGBA source when both it and a generic “4bpp” copy
  are available. `prepare` performs the correct indexed conversion itself.

The output retains the original ISO size, file positions and directory data.
The tool checks that ISO9660 and UDF, when present, refer to the same contiguous
executable data, then verifies every output byte against the input with only
the font slot allowed to differ. Existing movie archives, hardsubs, scripts,
menu translations and saves are not edited. Use the completed translation ISO
as input and apply this customization last: running other font patchers later
can replace customized glyphs.

## Verification performed

- Sixteen automated tests cover codec round trips, palette/dimension
  rejection, ISO-aware preparation, transparency repair, automatic colour
  fitting, compression overflow, UDF disagreement, output overwrite protection
  and cleanup after failed verification.
- Export and unchanged-PNG validation passed on the original Japanese ISO
  and the Green Gel v1.2.2 ISO.
- The script ran from an isolated folder with no repository imports, patched
  one pixel in a temporary v1.2.2 ISO and verified that every byte outside the
  font slot remained identical. The temporary ISO was removed after testing.

Boot and visual checks in PCSX2 or on hardware are still needed for each
user-designed font; byte verification cannot judge glyph legibility.

