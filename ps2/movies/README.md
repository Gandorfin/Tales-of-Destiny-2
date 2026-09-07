# PS2 hard-subbed movie rebuild

This directory contains the release pipeline for the eight translated in-game
movies: `00001`, `00002`, `00003`, `00004`, `00005`, `00007`, `00008`, and
`00010`. It rebuilds every movie from the fresh extracted stream in
`ps2/PyTOD2/MOVIE`, burns its English SRT, and recreates the original
fixed-size PlayStation 2 program stream. Movie `00005` also receives the
translated ending-credit overlay without losing its five dialogue subtitles.

## Translation inputs

* `ps2/PyTOD2/MOVIE/NNNNN.en.srt` is the authoritative subtitle track used by
  the builder. All 120 cues are syntax-, ordering-, duration-, and width-checked.
* `ending_credits.tsv` contains 323 measured credit rows. `KEEP` rows are
  already Latin text or logos. Two-column translations use `left / right`.
  A trailing `?` marks an unverified name reading and is not rendered.
* `credits_ass.py` validates the table and pinned font, fits every translated
  line to the measured credit region, and generates `ending_credits.ass`.
  The generated file contains 765 events.
* `fonts/Ubuntu-Bold.ttf` is the pinned render font. Its required SHA-256 is
  `679b5c1e09cab3156bb8ef529735f9382bf31ca7ac737382ab959297f8d82ad4`.
  Its licence is `LICENSES/Ubuntu-UFL.txt`.

## Building all movies

Use Python 3 and an FFmpeg build with libass. The font need not be installed
system-wide. First regenerate and check the ending overlay:

```powershell
python ps2/movies/credits_ass.py
python ps2/movies/credits_ass.py --check
```

Validate every input without encoding:

```powershell
python ps2/movies/build_hardsubbed_movies.py --validate-only
```

Build the complete staged set:

```powershell
python ps2/movies/build_hardsubbed_movies.py --ffmpeg C:\path\to\ffmpeg.exe
```

The builder refuses non-empty stage/work directories. By default it writes
verified results to `ps2/PyTOD2/hardsubbed_movies.rebuilt`, intermediates and
FFmpeg logs to `ps2/PyTOD2/.movie-rebuild-work`, and a machine-readable
`build_manifest.json` beside the staged movies. It never modifies
`hardsubbed_movies` or `MOVIE.FPB`.

`build_ending_movie.py` remains available for an isolated `00005` rebuild. It
requires `00005.en.srt` beside the fresh source movie and burns both the SRT
and translated credits.

## Fresh-source and subtitle guarantees

Before encoding, the builder reads the executable movie-pointer table and
hashes each exact slot of `MOVIE.FPB.before-hardsubs.bak`. A build stops unless
every extracted source MPEG matches its untouched archive slot byte-for-byte.
It also stops unless FFmpeg confirms that libass loaded every subtitle layer
and selected the bundled Ubuntu Bold font, with no reported filter or encode
errors. Movie `00005` must confirm two independent libass layers.

The standard dialogue style is Ubuntu Bold 20 px, white with a two-pixel black
outline, centered 24 px above the lower and side edges of the 640x448 frame.
Each SRT line is measured against the bundled TrueType metrics and must fit the
592 px safe width.

## Encoding limits

Every replacement is MPEG-2 Main Profile/Main Level, 640x448, 30000/1001 fps,
progressive 4:2:0, with an 18-frame maximum GOP and two B frames. The original
display aspect is retained (`00003` is the one square-pixel stream; the others
declare 4:3). Every source I-frame presentation position is forced and
verified; only an encoder-added terminal I-frame is permitted.

Most streams use FFmpeg average-bitrate control with `qmin=1` and the original
declared peak. `00010` needs constant-rate control and automatically steps from
7.75 to 7.50 Mbps to meet its tight startup schedule. The target setting is
not treated as a promise to fill the slot: the resulting elementary stream
must fit the actual video PES capacity and the original decoder timing. The
declared sequence bitrate is patched to 9 Mbps, except `00010` at 7.75 Mbps.
The MPEG VBV value is 1,835,008 bits and the PS2 P-STD video bound is
1,841,152 bytes.

## PS2 remux and verification

`remux_ps2_movie.py` reuses every original 0x4000-byte pack and SCR value. It
preserves every private-stream (`0xBD`) audio packet byte-for-byte and fills
unused video capacity with legal MPEG padding-stream (`0xBE`) packets. It does
not use FFmpeg's generic program-stream muxer, emit raw sector padding, or emit
header-only video PES packets.

The scheduler assigns each replacement picture its corresponding original
PTS, emits monotonic decode-order DTS, and enforces the stream-specific safe
startup lead: 50 ms for `00001`-`00005`, the original near-zero lead for
`00007`, 10 ms for `00008`, and 40 ms for `00010`. It rejects decoder underflow
or occupancy above the original P-STD bound.

Before staging an output, the build verifies:

* exact slot byte size, pack construction, and legal padding;
* exact frame count, source I-frame positions, and MPEG-2 sequence fields;
* exact audio packet bytes and positions;
* picture-for-picture PTS equality and monotonic DTS; and
* decoder-buffer occupancy and minimum decode lead.

## Release procedure

Keep the old `hardsubbed_movies` directory until all eight staged files pass.
After replacing that directory, run `ps2/PyTOD2/Install-HardsubbedMovies.ps1`.
The installer validates every slot size, retains
`MOVIE.FPB.before-hardsubs.bak`, writes only the eight requested slots, and
hashes the installed bytes back for confirmation.

Automated checks prove that the text layers were loaded, fit their bounds, and
survived the PS2 remux. A release candidate should still be watched in PCSX2
or on hardware. Check at least one cue in every movie and, in `00005`, the
first entering credit near 2:18, long two-column names, the Production I.G
logo transition, the final names, and the Green Gel card through MPEG end.
