# Tales of Destiny 2 English Patch v1.1.9e

## Summary

Version 1.1.9e fixes untranslated enemy names, artes and battle messages that
could still appear in Japanese despite the main menu translation verifying as
complete. This release supersedes v1.1.9c and v1.1.9d.

## Fixed

- Fixed enemy-name and battle-text changes being silently overwritten when
  `PAK1_PACKED` resources were staged during the final `FILE.FPB` build.
- Enemy translations are now reapplied after pak1 staging, immediately before
  the archive is assembled.
- Translated enemy encounter names in the central `TEKI` table and the
  corresponding per-enemy parameter blocks.
- Patched enemy arte names and boss taunts stored in alternate `ENd` script
  members. These copies were not covered by the original member-1 translation
  table.
- Fixed the Japanese `-Rune Uruz-` banner reported during battle, together
  with the related `-Rune Algiz-` variants.
- Added six battle-only translations that did not exist in the original table:
  `Sand Shoot`, `-Luminous Field-`, `-Genius-`, `-Wisdom Rondo-`,
  `-Regeneration-`, and `-Spider Net-`.

## Translation coverage

- 900 menu and UI records
- 597 character-title records
- 218 enemy names
- 159 canonical enemy arte and taunt records
- 92 alternate-member enemy arte and taunt occurrences
- 251 total enemy battle-text occurrences representing 95 distinct strings

## Verification

- The final ISO contains no Japanese text literals in any scanned enemy `ENd`
  battle-script member.
- The menu verifier now checks enemy names, canonical battle text and every
  alternate enemy-script member instead of reporting only ordinary menu data.
- All 15 automated menu and enemy-resource tests pass.
- All 9,203 `FILE.FPB` entries and 9,204 executable pointers were verified
  during packing.
- All 16 files in the rebuilt ISO were verified through both UDF and ISO9660.

The rebuilt resources and ISO passed structural and byte-level verification.
A complete gameplay playthrough has not been claimed.

## Release image

`Tales of Destiny 2 (Eng-v1.1.9e) (Patched).iso`

- Size: 3,234,158,592 bytes
- SHA-256: `881F11DBBD677A40C0A637077E382EEF0B94EBF83839434AF20947A694CDFF05`

Players using v1.1.9c or v1.1.9d should replace that image with v1.1.9e before
continuing battle-text testing.
