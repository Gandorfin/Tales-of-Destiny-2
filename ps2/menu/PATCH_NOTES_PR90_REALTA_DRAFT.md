# Tales of Destiny 2 PS2 English Patch — patch notes draft

These notes combine the changes in [PR #90](https://github.com/Gandorfin/Tales-of-Destiny-2/pull/90/) (the v1.2.3 playtest-feedback update) with the subsequent Realta plaza fix. They do not designate a new release or claim a completed playthrough.

## Fixed

- Fixed the Realta plaza scene restarting after the beam sequence when Kyle regained control and moved. The affected child dialogue in `06553_27` was restored to a working length and wording: “Elrane, just like you big brothers!” Targeted PCSX2 tests from in-game saves passed; the exact script-level mechanism behind the length sensitivity has not been established.
- Reflowed the gel notepad text so its first and last characters are no longer clipped.
- Corrected the countdown and other numeric displays that showed words in the number font, including Gald, shop, crafting-timer and card-count text.

## Translation and terminology

- Revised story dialogue and skits reported in playtest tab 8, including Kyle, Harold, Judas, Karell, Reala and Elrane scenes. Karell and Harold now address each other correctly in Karell’s death scene.
- Standardized “Atamoni Ovum” across the scenario, skits, glossary, Quiz Book, character titles and destination list. Elrane’s scene now uses “deity” consistently.
- Corrected the Hope Top name and several short prompts and labels, including “Info” where “NULL” or “NOTICE” appeared.

## Menus and battles

- Changed the Quiz Book exit choice to “Go back,” Battle Rank “Second” to “Normal+,” item “Pick” to “Pickaxe,” and Kyle’s title to “Reala’s Hero.”
- Corrected Elrane’s spelling in the encounter banner and title descriptions, and translated Barbatos’s previously missed arte banner as “Blaze.”
- Updated affected item-tab and cooking labels, including “Valuable” and “Do not auto-cook”.

## Build and compatibility

- Updated the patch tools to apply the new menu and executable text to both clean and previously patched resources without duplicating changes. PR #90 also refreshed the README and website for v1.2.3.
- Added a Windows patched-ISO build launcher after PR #90. No diagnostic Realta ISO is being presented as a release build.

## Verification and remaining limits

- PR #90 reported zero critical text-audit findings, no over-budget enemy-name fields, and passing menu tests. Targeted gameplay tests confirmed the Realta scene proceeds without replaying on the working diagnostic variants.
- One earlier diagnostic Realta build had brief pauses that cleared; broader performance testing remains outstanding. A full-game playthrough and a final release ISO have not been verified here.
- The world-map label still reads “Egg of God” because of its fixed-width slot; “Er’ther HQ” is used where “Er’ther Base” would not fit.
