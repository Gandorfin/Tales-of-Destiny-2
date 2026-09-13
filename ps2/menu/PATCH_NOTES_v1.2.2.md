# Tales of Destiny 2 English Patch v1.2.2

## Summary

Version 1.2.2 incorporates player feedback from review tabs 4–6, improving
dialogue, terminology, battle banners, menu text and movie subtitle layout.

## Fixed

- Revised reported story and skit lines for accuracy, clarity and text-box
  fitting.
- Standardized terminology including Saintess, Draconis, Wildwood, Townhouse,
  Aeropolis Ruins and the affected city and cave names.
- Replaced visible `NOTICE`/`Noitce` and `Select` labels with `Info` and
  `Option`; corrected `KO` and `ESCAPE GAUGE`.
- Translated additional battle banners, including Judas's and Kyle's Mystic
  Artes and Might Oratorio, and centered Mystic Arte and enemy arte banners.
- Added safe migration of older English menu, title and relocated Quiz Book
  strings, allowing existing patched resources to receive the new wording.
- Adjusted movie subtitles to use one fitted line in the lower black bar while
  retaining every subtitle cue and its original timing.

## Verification

- Translation audit reports zero code mismatches, untranslated text,
  misplaced Japanese, source drift or over-width lines.
- All 12 battle-text and Quiz Book migration tests pass.
- All 159 battle-text records and 218 enemy names fit their fixed fields.
- All eight movie sources, 120 subtitle cues and 765 end-credit events pass
  validation.
- Menu and executable dry-runs accept all new terminology migrations against
  the current build resources.

A complete gameplay playthrough and final release ISO have not yet been
claimed for this version.
