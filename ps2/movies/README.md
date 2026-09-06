# Ending staff roll (PS2)

The ending credits are not game text. They are baked into the ending
movie: the fifth stream in `MOVIE.FPB` (7 min 17 s, 640x448 MPEG-2), where
white Japanese text scrolls up the left side over the illustrations at about
48 pixels per second. Nothing in `FILE.FPB` or the executable holds those
names, so the only way to translate them is the same way the dialogue videos
were done: re-encode the video with the English burned in.

This folder holds everything needed for that, except the video itself.

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

## Burning it

The timing in the table is measured against the movie's own timestamps, so
burn without seeking:

```
python3 ps2/movies/credits_ass.py
ffmpeg -i ending.pss -vf "ass=ps2/movies/ending_credits.ass" -c:v mpeg2video -b:v 7400k -an ending_en.m2v
```

then remux `ending_en.m2v` with the original audio stream into a PSS the way
the dialogue movies were rebuilt. The overlay uses the Ubuntu font (free,
rounded, close to the original); put the TTF next to the .ass and add
`:fontsdir=ps2/movies` to the filter if it is not installed system wide.
Any bold sans serif works if it is missing.

Extracting the movie: `MOVIE.FPB` is a plain concatenation of eleven PSS
streams. Each starts right after the previous MPEG end code
(`00 00 01 B9`), not on a sector boundary. The ending is the fifth one,
offset 0x2C888140 to 0x44B08144 inside `MOVIE.FPB` (405,272,580 bytes).

## Cost

Re-encoding the ending adds roughly the size of the movie to the release
patch (the xdelta cannot express a re-encode as a small diff), the same
trade-off already made for the dialogue videos. That is the reason this is
delivered as an overlay for Gandorff to burn rather than as a rebuilt
`MOVIE.FPB`.
