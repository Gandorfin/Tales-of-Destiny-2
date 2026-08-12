## Dialogue and Script Layout Restrictions

The English translation must follow the PS2 game's dialogue and script-rendering limitations. These rules are based on the current safe-layout audit and runtime testing of the translated game.

### General Dialogue Limits

For ordinary dialogue:

- Maximum visible width: **36 characters per rendered line/segment**.
- Maximum ordinary English dialogue length: **5 lines per text record**.
- The game displays **4 dialogue rows per page** before advancing.
- A four-row page may contain at most **126 visible characters in total**.
- A fifth dialogue line is therefore treated as part of the following page rather than the first four-row page.
- English line count does **not** normally have to match the number of Japanese source lines.
- Dialogue may be reflowed or rewritten as long as its meaning, speaker voice, terminology, and script structure are preserved.

A valid five-line example could therefore have:

```text
Line 1: <= 36 visible characters
Line 2: <= 36 visible characters
Line 3: <= 36 visible characters
Line 4: <= 36 visible characters
        ---------------------------
        Lines 1-4 <= 126 characters

Line 5: <= 36 visible characters
```

The 36-character limit alone is not sufficient. Four lines of 36 characters would total 144 characters and exceed the 126-character first-page budget.

### Visible Width

Layout limits apply to **visible rendered text**, not necessarily the raw number of characters stored in the script.

Runtime/control codes such as:

```text
<Kyle>
<Reala>
<Judas>
<button:00000028>
<num:00000014>
<03:00000000>
{16}{25}{D2}{C0}
```

are control data and are not counted as ordinary visible dialogue characters.

Control codes that divide rendered segments or pages must also be respected when calculating layout.


### Event-Sensitive / Unprofiled Records

Not every text-bearing SCED record may be treated as ordinary dialogue.

Records whose SCED call profile is unknown, missing, ambiguous, or associated
with scene transitions, event narration, triggers, map-state changes, or other
scripted sequences must preserve their physical text-line structure by default.

For these records:

- Do not add physical English lines solely to satisfy the 36-column limit.
- Preserve the Japanese/source physical line count unless clean SCED profiling
  or direct in-game testing proves that line expansion is safe.
- A newline inside a `.sced.txt` record is compiled as an actual `0x01`
  control byte; it is not merely editor formatting.
- Width-safe reflow is therefore not automatically runtime-safe.
- Unprofiled records must not be included in automatic line-expansion or
  lossless-reflow passes.
- Scene-transition and event-state records require a dedicated PCSX2 test
  after any change to their physical line structure.

The 36-column / 126-character page rules describe renderer limits.
They do not override stricter script-specific runtime requirements.

### Exact-Structure Text

Some records are structurally different from normal dialogue. Examples include:

- `NOTICE`
- `SELECT`
- choices
- menu prompts
- tutorial prompts
- certain system messages

When a record is marked as **exact structure**, its required English line count must be preserved.

For these records:

- Do not freely add or remove lines.
- Preserve the required line count.
- Preserve choice ordering.
- Preserve menu/selection structure.
- Keep every visible segment within 36 characters.
- Keep every applicable four-row page within the 126-character budget.
- Do not convert an exact-structure record into ordinary dialogue simply because a different layout reads better.

The Japanese source structure is the authoritative reference when determining the required structure.

### Runtime and Control Codes

Runtime-sensitive records require additional protection.

The English version must preserve the runtime/control-code sequence required by the Japanese source.

Do not accidentally:

- delete a control code;
- duplicate a control code;
- reorder control codes;
- introduce additional control codes;
- split byte-code groups that are contiguous in the source;
- convert a control marker into ordinary visible text;
- introduce literal newline/control strings that were not present in the source.

Examples include:

```text
<03:00000000>
<button:00000025>
<num:00000014>
<item:00000031>
{18}{44}{70}{C0}
```

When editing text around these codes, the Japanese/source runtime sequence is authoritative.

The previous English translation must not be assumed to have the correct control-code sequence.

### Japanese Source Preservation

Japanese source lines beginning with `#` are structural reference data and must not be changed during English editing.

For every `.sced.txt` file:

- preserve the Japanese source-line sequence;
- preserve the number and ordering of SCED records;
- preserve divider boundaries;
- do not insert additional SCED records;
- do not remove existing SCED records.

Additional English line breaks inside an existing divider-delimited record do **not** create additional SCED records.

Therefore, raw text-file line count is not a valid structural-integrity check.

### Known-Good / Runtime-Tested Records

Some records are marked as **known-good** because they have already been repaired and/or tested in PCSX2.

These records are intentionally locked during automated translation and layout passes.

A known-good record may intentionally differ from generic audit heuristics. An audit warning by itself is therefore not sufficient reason to rewrite it.

Known-good records should only be changed deliberately when:

1. the current English has a genuine translation, grammar, style, or presentation problem;
2. the revised version satisfies the current layout and structural rules; and
3. the affected scene can be tested again in PCSX2.

Crash-sensitive or previously problematic scenes should receive particular care.

### Preferred Editing Order

When revising a record, use the following priorities:

1. **Preserve script/runtime correctness.**
2. **Preserve the meaning of the Japanese source.**
3. **Preserve gameplay mechanics and factual information.**
4. **Preserve established names and terminology.**
5. **Preserve character voice and tone.**
6. **Make the English natural and readable.**
7. **Fit the text within the layout limits.**

Do not shorten text simply to satisfy an obsolete line-count restriction when the current renderer limits allow a fuller and more natural translation.

### Current Safe-Layout Summary

```text
Visible width per rendered segment:   <= 36 characters
Rows displayed per dialogue page:     4
Visible characters per 4-row page:    <= 126
Ordinary dialogue lines per record:   <= 5

Ordinary dialogue:
    English line count may differ from Japanese.

Exact-structure records:
    Required line count and structure must be preserved.

Runtime-sensitive records:
    Runtime/control-code sequence must match the Japanese/source sequence.

Known-good records:
    Locked by default and changed only through deliberate review and retesting.
```

These limits should be treated as the default translation policy unless direct in-game testing demonstrates that a particular script type has different requirements.