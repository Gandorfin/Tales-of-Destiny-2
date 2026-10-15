# Tales of Destiny 2 — PS2 English Patch: Skit Update

This update combines PR96's automatic skit text-speed adjustment with PR98's fuller English skit translations.

## Skit translations

- Retranslated all **608 timed skits**, restoring fuller conversations, jokes, character interactions and details previously condensed to fit the voice timing.
- Expanded exchanges such as Loni's romantic misadventures, Kyle's excitement about ancient ruins and the party's discussions about changing history.
- Updated the glossary to reflect the established Saintess, Draconis and Atamoni Ovum terminology.
- Kept the existing full-length text of the untimed opening diary.

## Text timing and readability

- Added automatic text-speed adjustment for each skit line, helping the English finish displaying within its allotted time.
- Applied timing calculation across the full collection of **609 skit scripts**, rather than a selected test list.
- Refined the calculation to use individual line windows, drawing on the original Japanese timing and previously validated English timing budgets.
- Added line-specific length budgets to keep the fuller translations readable and within the game's display limits.
- Retained the original voice recordings; the changes affect English text and its reveal speed.

## Build and validation

- Integrated skit retiming into the normal Insert SKIT build step.
- Used stored original timing data so repeated builds do not progressively accelerate the text.
- Added audit checks for over-budget skit text and unintended multiline formatting.
- Synchronized the revised translations between the maintained skit sources and their build-ready copies.

Sources: [PR96 — per-line skit text speed](https://github.com/Gandorfin/Tales-of-Destiny-2/pull/96), merged as [ec30493](https://github.com/Gandorfin/Tales-of-Destiny-2/commit/ec30493671f17208ecb1a55b21bb0017d0a34279), and [PR98 — full skit retranslation](https://github.com/Gandorfin/Tales-of-Destiny-2/pull/98), merged as [8a5fc89](https://github.com/Gandorfin/Tales-of-Destiny-2/commit/8a5fc89cf085252e2a9a4fec6565f72cba34af9f).
