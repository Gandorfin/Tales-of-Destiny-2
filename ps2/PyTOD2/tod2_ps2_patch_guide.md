# Building a PS2 Patch for Tales of Destiny 2 — Guide

Based on a direct read of `lifebottle/Tales-of-Destiny-2` (code + folder structure, not just the README).

## 1. What's actually in the repo

- **`ps2/scenarios/*.sced.txt`** and **`ps2/skits/*.sced.txt`** — your translated text. Format is Japanese line prefixed with `#` (kept as a comment/reference) followed by the English line, blocks separated by `-----------------------`. This is exactly the format the insertion script expects to find in a `TXT_EN` folder.
- **`ps2/PyTOD2/`** — the actual toolchain, in two flavors:
  - `tod2_ps2.py` — CLI, driven by `python tod2_ps2.py <N>` (see table below).
  - `PyTOD2.py` — a Tkinter GUI wrapping the *same* logic plus a few extra functions (skit-specific helpers, movie extraction). It can be run directly (`python PyTOD2.py`) or frozen into an .exe with `pyinstaller --onefile --noconsole --icon favicon.ico PyTOD2.py` (instruction is in a comment at the top of the file).
  - `bat/*.bat` — one-line wrappers around the CLI numbered commands, matching the older workflow in `ps2/PyTOD2/readme.md`.
- **`pakcomposer/`** (git submodule) — a cross-platform (.NET 5) C# tool for decomposing/recomposing `pak0`/`pak1`/`pak3` archives. It's an alternative/companion to the Python script's built-in pak1 handling.
- **`dictionary/`** and **`ps2/PyTOD2/TBL.json`** — the character table mapping the game's custom text encoding to readable characters; also exportable as a `.tbl` file for hex editors (Cartographer/Atlas/WindHex/abcde).
- **`ps2/v9.7z`** — a snapshot of a fully-populated working folder (every intermediate stage populated). Useful as a reference for what your folder tree should look like at each step if you get stuck.

**Important gap:** the README's step-by-step (steps 6–15, the "SKITS" section) references `pak1.py` and `unpack_folders.py`, but **those files are not in `ps2/PyTOD2/`** — they only exist in the old `ps2/archive/PyTOR2_old/` snapshots. Their functionality has since been folded directly into `tod2_ps2.py` (commands 12/13/14: `unpack` / `extract_pak1` / `insert_pak1`) and, more completely, into `PyTOD2.py`'s GUI buttons ("Organize FPB", "Unpack PAK1", "Move Skits OUT", "Extract SKIT", "Insert SKIT", "Move Skits IN", "Pack PAK1"). **Use the GUI or the numbered CLI commands — don't go hunting for the missing scripts.**

**Also missing (not committed, and reasonably so — it's a compiled binary derived from another project):** `comptoe.exe`, the LZSS/RLE (de)compressor the scripts shell out to via `subprocess`. It's credited in the README as coming from Temple of Tales Translations (source: `https://github.com/talestra/talestra/tree/master/compto`). You'll need to build or obtain it and drop it next to `tod2_ps2.py`/`PyTOD2.py` — every compression/decompression call in the scripts assumes it's in the working directory.

## 2. How the game's data is structured (quick reference)

- `SLPS_251.72` is the main executable. It embeds a pointer table at `0xDD320`–`0xE62EF` — one 4-byte little-endian entry per file inside `FILE.FPB`, each a 26-bit offset (`& 0xFFFFFFC0`, with low 6 bits as a remainder/alignment value).
- `FILE.FPB` is a flat blob; every file's start/end offset comes from that pointer table (`FPB.json` maps each numeric index to its file extension).
- Files with extension `scpk` are `SCPK` containers: one background/data file, a size table, then a set of sprite/animation files, ending in a script file with the `SCED` signature.
- `SCED` files have a code section (scripted logic) and a text section (an array of custom font-index bytes). The extraction script walks the code section for `0xF8`-tagged pointers into the text section and decodes bytes via `TBL.json`; `<Name>` / `<tag:XXXXXXXX>` bracket notation in the `.txt` files represents control codes (speaker names, color/size/item/button tags, etc.) baked back in on insert.
- Skit dialogue lives one layer deeper: inside `pak1` archives (which themselves live inside `FILE.FPB`), one `.sced` per skit folder.
- Compression: PS2 uses a LZSS/RLE mix via `comptoe.exe`; the PSP version (not covered by this guide) uses zlib instead — the two builds are not interchangeable.

## 3. Prerequisites

1. A **legally-owned PS2 Tales of Destiny 2 disc**, dumped to files (or an ISO you can extract `SLPS_251.72` and `FILE.FPB` from — e.g., with 7-Zip, PowerISO, or a UDF-aware tool like `Ps2IsoTools`). These two files are the only inputs the toolchain needs.
2. **Python 3** (stdlib only for `tod2_ps2.py`: `json`, `struct`, `subprocess`, `shutil`, `re`, `string`; `PyTOD2.py` additionally needs `tkinter`, which ships with the standard Windows installer but may need a separate package on Linux, e.g. `python3-tk`).
3. **`comptoe.exe`** sourced/built as noted above, placed alongside the scripts.
4. Optionally, **`pakcomposer`** built via `dotnet publish -r linux-x64 -c Release /p:PublishSingleFile=true --self-contained false` (or the Windows equivalent) if you want a more robust cross-platform path for `pak0`/`pak1`/`pak3` work.
5. A way to write the modified files back into an ISO and turn that into a distributable patch — not part of this repo (see §6).

**Platform note:** several scripts create differently-cased sibling folders (e.g. reading from `pak1/` while writing outputs under `PAK1/...`). On a case-insensitive filesystem (Windows, or a case-insensitive mount) these collapse to the same folder and it just works; on Linux/macOS they're distinct directories and you can hit `FileNotFoundError`. Easiest fix: do this work on Windows (or an exFAT/NTFS mount), matching how the tools were built and tested.

## 4. Step-by-step pipeline

Work inside `ps2/PyTOD2/`. Copy your dumped `SLPS_251.72` and `FILE.FPB` there first.

### CLI command reference (`python tod2_ps2.py <N>`)

| N | Function | What it does |
|---|----------|---------------|
| 1 | `extract_files` | Full extract: FPB → SCPK → move SCED → dump TXT |
| 2 | `insert_files` | Full insert: TXT_EN → SCED_NEW → repack SCPK → copy into FPB folder |
| 3 | `pack_fpb` | Rebuild `FILE.FPB` from the `FPB/` folder + update pointer table in `new_SLPS_251.72` |
| 4 | `insert_font` | Write `font.bin` into `new_SLPS_251.72` at `0xCA238` (max `0x5518` bytes) and fix the lowercase-letter glyph map at `0xC9D41` |
| 5 | `extract_fpb` | Just unpack `FILE.FPB` → `FPB/` |
| 6 | `extract_scpk` | Just unpack `SCPK` containers found in `FPB/` |
| 7 | `extract_sced` | Just dump text from `SCED/` → `TXT/` (also writes `SCED.json`, the pointer map insertion depends on) |
| 8 | `insert_sced` | Inject `TXT_EN/*.sced.txt` into the matching files from `SCED/`, using `SCED.json` and `TBL.json` |
| 9 | `pack_scpk` | Repack `SCPK/` + `SCED_NEW/` → `SCPK_PACKED/` |
| 10 | `export_tbl` | Dump `TBL.json` as a `.tbl` file for hex editors |
| 11 | `move_sced` | Flatten last file of each `SCPK/<folder>/` into `SCED/<folder>_<n>.sced` |
| 12 | `unpack` | Sort `FPB/` contents into `FILE/<ext>/`, auto-decompressing recognized types via `comptoe.exe` |
| 13 | `extract_pak1` | Unpack `pak1` archives found under `FILE/` |
| 14 | `insert_pak1` | Repack `PAK1_PACKED/`, recompressing with `comptoe.exe` where needed |

### A. Main story scenarios

1. `python tod2_ps2.py 1` (or GUI: Unpack FPB → Unpack SCPK → Unpack SCED). This regenerates `FPB/`, `SCPK/`, `SCED/`, `TXT/`, and — critically — `SCED.json`, which records where each text block's pointer lives. **You need this generated fresh from your own dumped files**; it's not something that ships in the repo (correctly — it's derived from the copyrighted game data).
2. Create a `TXT_EN` folder and copy in your already-translated files from `ps2/scenarios/`. Filenames must match what step 1 produced (the `<folder>_<lastfile>.sced` naming from `move_sced`).
3. `python tod2_ps2.py 2` (or GUI: Pack SCED → Pack SCPK, which also copies results into `FPB/`). This writes `SCED_NEW/`, repacks into `SCPK_PACKED/`, and copies those into `FPB/`.

### B. Skits (PAK1)

Use the **GUI** here (`PyTOD2.py`) — it has dedicated buttons the CLI doesn't expose individually:

1. "Organize FPB" (`unpack`) to sort `FPB/` into `FILE/<ext>/`.
2. "Unpack PAK1" (`extract_pak1`) to unpack each `pak1` archive under `FILE/pak1/<folder>/`.
3. "Move Skits OUT" (`move_skits_out`) to collect each folder's `.sced` into `FILE/pak1/SCED/`.
4. "Extract SKIT" to dump skit text to `TXT/`.
5. Create `TXT_EN` inside that skit working folder and drop in your translated files from `ps2/skits/`.
6. "Insert SKIT" to build `SCED_NEW/`.
7. "Move Skits IN" (`move_skits_in`) to copy translated `.sced` files back into their per-folder locations.
8. "Pack PAK1" (`insert_pak1`) to rebuild `.pak1` archives (recompressing via `comptoe.exe` where `compression.json` says type `3`), written to `PAK1_PACKED/`.
9. Copy the repacked `pak1` files back over the corresponding entries in `FPB/`.

### C. Repack the FPB and executable

1. Make a copy of your original `SLPS_251.72`, name it `new_SLPS_251.72` (the pack step writes the updated pointer table into this copy, not the original).
2. `python tod2_ps2.py 3` (Pack FPB) → produces `FILE_NEW.FPB` and updates `new_SLPS_251.72`'s pointer table to match the new file layout/sizes.
3. Optional: `python tod2_ps2.py 4` (Insert FONT) to drop in a custom `font.bin` (≤ `0x5518` bytes) and remap the lowercase-letter glyph indices — this is the mechanism the README's "Mapping Lowercase Letters" section describes.
4. Optional: `python tod2_ps2.py 10` (Export TBL) if you want a `.tbl` file to sanity-check strings in a hex editor alongside Cartographer/Atlas/abcde.
5. Rename `FILE_NEW.FPB` → `FILE.FPB` and `new_SLPS_251.72` → `SLPS_251.72`. These two files are your patch payload.

## 5. Sanity-check before touching an ISO

- Compare file sizes: translated text is very likely longer than the Japanese original in places. `pack_fpb` doesn't enforce a size cap (it just recalculates offsets), so this is fine for `FILE.FPB` itself — but `insert_font` **does** enforce a hard `0x5518`-byte ceiling on `font.bin`.
- Test the two files independently if you have any way to run the game outside a full disc (e.g., a PS2 emulator that supports loading loose ELF/FPB replacements via a "fast boot"/file-override mechanism) before committing to a full ISO rebuild — this saves a lot of rebuild cycles per typo.

## 6. Turning this into a distributable patch (not covered by the repo)

This part is standard PS2 romhacking territory rather than anything in the `Tales-of-Destiny-2` repo itself:

1. **Get your two modified files into an ISO.** PS2 discs use ISO9660/UDF; because `FILE.FPB` will very likely change size, a naive "open in an archiver and overwrite" approach (7-Zip/PowerISO/UltraISO) can corrupt the volume descriptors and directory table. Purpose-built tools handle relocation and directory-record updates for you:
   - **UMDReplaceK** (romhacking.net) — command-line, open-source, cross-platform (.NET 6), built specifically for replacing files (including resized ones) in single-layer PS2 and PSP ISOs, and supports batch file-replacement lists.
   - **Ps2IsoTools** (`github.com/Finzenku/Ps2IsoTools`) — a C# library/tool for reading and rebuilding UDF-based PS2 ISOs (add/replace/copy files, rebuild).
2. **Don't distribute the rebuilt ISO itself** — that would mean distributing copyrighted game data. The normal fan-translation convention is to distribute an **`xdelta3` diff** between the original (unmodified) ISO and your patched ISO, plus instructions for the end user to dump their own legally-owned disc and apply the patch themselves (tools like `xdelta3` CLI or `XDeltaUI` on the user's side). Some projects instead ship a small patcher .exe that performs the same file-replacement step at install time (rather than shipping a raw ISO diff) — either is standard practice.
3. Version-control your `new_SLPS_251.72` / `FILE_NEW.FPB` outputs (or at least keep the originals) so you can regenerate diffs cleanly after each translation pass, rather than hand-patching the same ISO repeatedly.

## 7. Where to ask if you get stuck

The project's own Discord is the best place for tool-specific questions or to report a mismatch between the README and the current scripts: `https://discord.gg/HZ2NFjpedn`. The shared spreadsheet (`https://docs.google.com/spreadsheets/d/1UVaEjK0o-V1-3atPHfRRw2q9QQcCzPCpr4GXJ2MLvvg`) also tracks translation progress and known offsets.
