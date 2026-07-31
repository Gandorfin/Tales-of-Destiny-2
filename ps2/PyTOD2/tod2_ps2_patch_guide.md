!!!!!!!!!!
new order


Then run the GUI PyTOD2.py steps in this order:

Unpack FPB
Organize FPB
Unpack SCPK
Unpack SCED
Unpack PAK1
Move Skits OUT
Extract SKIT

fill text en folder with scenario translated files and one  at "file/pak1/txten" with translated skits

Pack SCED
Pack SCPK
Insert SKIT
Move Skits IN
Pack PAK1
Pack FPB
Insert FONT



## 6. Turning this into a distributable patch (not covered by the repo)

This part is standard PS2 romhacking territory rather than anything in the `Tales-of-Destiny-2` repo itself:

1. **Get your two modified files into an ISO.** PS2 discs use ISO9660/UDF; because `FILE.FPB` will very likely change size, a naive "open in an archiver and overwrite" approach (7-Zip/PowerISO/UltraISO) can corrupt the volume descriptors and directory table. Purpose-built tools handle relocation and directory-record updates for you:
   - **UMDReplaceK** (romhacking.net) — command-line, open-source, cross-platform (.NET 6), built specifically for replacing files (including resized ones) in single-layer PS2 and PSP ISOs, and supports batch file-replacement lists.
   - **Ps2IsoTools** (`github.com/Finzenku/Ps2IsoTools`) — a C# library/tool for reading and rebuilding UDF-based PS2 ISOs (add/replace/copy files, rebuild).
2. **Don't distribute the rebuilt ISO itself** — that would mean distributing copyrighted game data. The normal fan-translation convention is to distribute an **`xdelta3` diff** between the original (unmodified) ISO and your patched ISO, plus instructions for the end user to dump their own legally-owned disc and apply the patch themselves (tools like `xdelta3` CLI or `XDeltaUI` on the user's side). Some projects instead ship a small patcher .exe that performs the same file-replacement step at install time (rather than shipping a raw ISO diff) — either is standard practice.
3. Version-control your `new_SLPS_251.72` / `FILE_NEW.FPB` outputs (or at least keep the originals) so you can regenerate diffs cleanly after each translation pass, rather than hand-patching the same ISO repeatedly.

