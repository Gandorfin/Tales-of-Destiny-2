# Tales of Destiny 2 English Patch v1.1.9g

## Summary

Version 1.1.9g renames Kronos to Miktran throughout the English script for
consistency with Tales of Destiny Director's Cut and the name spoken in
Tales of Destiny 2's voiced dialogue. It includes all fixes from v1.1.9f.

## Fixed

- Renamed Kronos to Miktran in 25 story-dialogue occurrences.
- Renamed Kronos to Miktran in four skit occurrences.
- Renamed both Quiz Book references to Miktran.
- Updated the project glossary so future translation work consistently uses
  Miktran.
- Added safe terminology-migration support for already-patched Quiz Book
  resources; clean Japanese resources remain supported.

## Verification

- All 25 rebuilt story occurrences and four rebuilt skit occurrences contain
  Miktran, with zero Kronos occurrences.
- Both Quiz Book fields decode as Miktran after rebuilding.
- Menu, enemy-name, battle-text, Mystic Arte, title and archive checks are
  rerun against the final ISO.
- All 17 automated menu and enemy-resource tests pass.
- All 9,203 `FILE.FPB` entries and 9,204 executable pointers were verified
  during packing.
- All 16 files in the rebuilt ISO were verified through both UDF and ISO9660.

A complete gameplay playthrough has not been claimed.

## Release image

`Tales of Destiny 2 (Eng-v1.1.9g) (Patched).iso`

- Size: 3,234,158,592 bytes
- SHA-256: `C1E9A557E4A88E8717C92CA3E5EF869FCD861E7FC494E263779BBE7ECDB23A3D`
