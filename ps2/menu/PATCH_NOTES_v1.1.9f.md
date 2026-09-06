# Tales of Destiny 2 English Patch v1.1.9f

## Summary

Version 1.1.9f translates five player Mystic Arte banners that were still
stored in Japanese inside battle-effect scripts. It includes and supersedes
all enemy-name, enemy-arte and battle-message fixes from v1.1.9e.

## Fixed

- Added translation coverage for compressed `efD` battle-effect scripts.
- Translated the five remaining Mystic Arte banner strings:
  - `裂衝蒼破塵` -> `Azure Dust`
  - `絶破滅焼撃` -> `Annihilate`
  - `魔人千裂衝` -> `Demon Rend`
  - `震天裂空` -> `Sky Rend`
  - `震天裂空斬光` -> `Sky Rend Ray`
- Extended the final ISO verifier to scan both enemy `ENd` scripts and Mystic
  Arte `efD` scripts for Japanese battle literals.

The compact banner names are intentional. These strings sit inline in battle
bytecode and have fixed 8-12 byte fields; longer names such as `Azure
Devastation` would shift the following instructions and risk corrupting the
effect script.

## Translation coverage

- 900 menu and UI records
- 597 character-title records
- 218 enemy names
- 159 canonical enemy arte and taunt records
- 92 alternate-member enemy arte and taunt occurrences
- 5 player Mystic Arte banner occurrences
- 256 total battle-text occurrences representing 100 distinct strings

## Verification

- The final ISO is scanned for Japanese literals in every compressed `ENd`
  and `efD` member of all enemy/battle packs.
- Menu, titles, enemy names, enemy battle text and Mystic Arte banners are
  verified independently.
- Structural archive and ISO checks are performed after rebuilding.
- All 16 automated menu and enemy-resource tests pass.
- All 9,203 `FILE.FPB` entries and 9,204 executable pointers were verified
  during packing.
- All 16 files in the rebuilt ISO were verified through both UDF and ISO9660.

A complete gameplay playthrough has not been claimed.

## Release image

`Tales of Destiny 2 (Eng-v1.1.9f) (Patched).iso`

- Size: 3,234,158,592 bytes
- SHA-256: `804BD86D12F620B079C52E601AD4CC05AE8CC6EA42CBAC0795AF8D1B62388765`
