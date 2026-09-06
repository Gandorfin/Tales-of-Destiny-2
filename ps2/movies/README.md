# Ending staff roll (PS2)

The ending credits are not game text. They are baked into the ending
movie: the fifth stream in `MOVIE.FPB` (7 min 17 s, 640x448 MPEG-2), where
white Japanese text scrolls up the left side over the illustrations at about
48 pixels per second. Nothing in `FILE.FPB` or the executable holds those
names, so the only way to translate them is the same way the dialogue videos
were done: re-encode the video with the English burned in.

This folder holds the editable credit table and generated ASS overlay. It
does not contain the game movie or a release-safe PS2 MPEG remuxer.

* `ending_credits.tsv`: one row per credit line (323 lines), with the moment
  its top edge enters the screen (`t0`, seconds from the start of the movie),
  its scroll speed, its height, the x extents of its text, the Japanese and
  the English. Rows marked `KEEP` are already Latin text or a logo and are
  left as they are. Two-column rows are written `left / right`. A trailing
  `?` marks a staff name whose reading could not be verified from the kanji
  alone (19 names in 16 rows); the voice cast and the well known staff are
  certain.
* `credits_ass.py`: turns the table into `ending_credits.ass`, an overlay that
  paints a black box over each Japanese line for exactly as long as it is on
  screen (moving with the scroll) and draws the English at the same place,
  then shows an "English translation patch / Green Gel" card while the Namco
  logo is on screen at the end.
* `ending_credits.ass`: the generated overlay, committed for convenience.

## Regenerating the overlay

The timing in the table is measured against the movie's own timestamps, so
regenerate it without applying a time offset:

```
python3 ps2/movies/credits_ass.py
```

The overlay requests Ubuntu Bold. Install that font, or explicitly provide
its directory to libass, before judging final placement. A fallback font can
have different metrics and is not suitable for release verification.

## Release integration requirements

Do not use a generic FFmpeg program-stream remux or the former 7.4 Mbps
example. The fifth movie has only 292,808,866 bytes of video-payload capacity,
so that bitrate cannot fit its fixed slot. A release build must:

* encode 13,127 MPEG-2 frames at 640x448, 30000/1001 fps, 4:3, Main Profile /
  Main Level, progressive sequence, 4:2:0, with an 18-frame GOP and two B
  frames; preserve the original I-frame presentation times;
* preserve every private-stream (`0xBD`) audio packet byte-for-byte;
* reuse the original 0x4000-byte PS2 pack layout and fill spare payload with
  legal MPEG `0xBE` padding packets, never raw sector padding or zero-length
  video PES packets;
* preserve every original video PTS, emit monotonic DTS, use buffer-aware
  packet pacing with at least 50 ms decode lead, and keep the P-STD video
  buffer at or below 1,841,152 bits; and
* verify the output size, audio bytes, frame count, PTS/DTS order, buffer
  occupancy and sequence headers before inserting it into `MOVIE.FPB`.

The encoding/remux helper scripts are intentionally not present in this
folder. Until a tool implementing all checks above is added and validated,
`ending_credits.ass` is an overlay source asset rather than a release-ready
replacement movie.

Extracting the movie: `MOVIE.FPB` is a plain concatenation of eleven PSS
streams. Each starts right after the previous MPEG end code
(`00 00 01 B9`), not on a sector boundary. The ending is the fifth one,
offset 0x2C888140 to 0x44B08144 inside `MOVIE.FPB` (405,274,628 bytes).

## Cost

Re-encoding the ending adds roughly the size of the movie to the release
patch (the xdelta cannot express a re-encode as a small diff), the same
trade-off already made for the dialogue videos. That is the reason this is
delivered as an overlay for Gandorff to burn rather than as a rebuilt
`MOVIE.FPB`.
