# Changelog

## 2026-08-30 — SCED instruction-boundary / Elrane freeze fix

### Fixed

- Decode script instructions before recognizing `F8` text references. A byte
  inside a branch, constant, variable, or argument-list operand is no longer
  mistaken for a text instruction.
- Reject invalid legacy `pointers.json` entries before extraction/insertion.
- Check that append and rebuild insertion preserve all non-text code bytes and
  instruction boundaries. Unknown/truncated instructions fail closed.
- The standard `build_psp.py` entry point applies the fix automatically.

### Evidence and regression coverage

- The original-disc audit found 12 false entries in 11 scripts and recovered
  26 genuine text references missed by the previous scanner.
- Seven scripts had non-text bytecode corruption in the preceding image:
  06480, 06481, 06524, 06581, 06598, 06607, and 06673.
- In 06524, false pointer operand `0x345F` overlapped a conditional branch and
  the next variable descriptor. The repaired bytes are
  `F3 F8 33 24 1E C1 C0`, preserving the transition progress update.
- All 1,062 scripts passed structural/text checks; 161,465 branch/call targets
  aligned with instruction boundaries. Eleven synthetic regression tests cover
  operand false positives, missed genuine references, stale metadata, append,
  rebuild, and the specific Elrane sequence. Tests contain no extracted assets.
- The reporter confirmed the repaired build passes the first Elrane encounter
  that previously froze. A complete game playthrough has not been claimed.

### Preserved

Lowercase letters, the apostrophe glyph at slot `DB`, dotted `i`/`j`, menu-font
selection and the private bold-font table remain unchanged by this fix.
The tested repair retained existing genuine translated strings and every
non-script archive member from the previous build.

### Upgrading an existing text workspace

Back up edited translations. Extract into a fresh directory; do not reuse old
pointer metadata. If carrying manual edits forward, match script ID and genuine
pointer-operand address, not record index: removing false entries and recovering
real entries changes record numbering. Do not suppress the validation error.
Boot the new ISO normally and use an ordinary in-game save when testing;
old save states may restore corrupt script bytes from the earlier image.
