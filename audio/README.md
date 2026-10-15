# Audio index (PS2 and PSP)

Every audio file on both discs, as text tables, plus a tool that rebuilds the
tables and exports the voices as WAV for transcription. The tables hold
positions, sizes and durations only, no game audio.

| File | What it is |
|---|---|
| `ps2_audio.csv` | 6,376 audio members of the PS2 FILE.FPB |
| `psp_audio.csv` | 6,766 audio members of the PSP file.fpb |
| `voice_pairs.csv` | which PS2 voice is which PSP voice (6,216 pairs) |
| `audio_index.py` | the tool that wrote them |

Columns of the two disc tables: platform, member (FPB member index, the
same number PyTOD2 and psp_fpb.py use), offset and size inside the archive,
format, sample rate, channels, seconds, kind (voice, battle voice, music,
sound effects) and name (the PSP battle voices carry one in their header).

## What is where

| | PS2 | PSP |
|---|---|---|
| Story and skit voices | 5,350 members 57..6041, SPU ADPCM, mono, 48000 Hz, 8.9 hours | 5,361 members 216..6194 and 8122..8138, ATRAC3plus, mono, 44100 Hz |
| Battle voices | 870 members 7185..8054, SPU ADPCM, mono, 22050 Hz | 996 members 7311..8323, VAG, 22050 Hz, named |
| Music | 4 stereo streams (50..53) | 3 stereo ATRAC3plus, 375 MIDI sequences |
| Sound effects | IECS banks and their sample bodies | .phd/.pbd banks |

* Story voices come one file per voiced line or short scene, in the order
  of the game's scenario data. A few long files near the start hold whole
  scenes.
* Battle voices sit at the end of the list, one line per file. On the PSP
  every one has a name: the 870 `044_003` style names are the battle lines
  the PS2 also has (in the same order; the first number groups related
  files), the 126 `BTL_03_11_07` style names are PSP extras.
* The PSP voices are the PS2 voices re-encoded, in the same order, so a
  transcript of one disc maps to the other through `voice_pairs.csv`
  (durations agree within 0.2 seconds for every story pair). Unpaired rows
  are files only one disc has, or a line that was re-cut (PS2 7576 against
  PSP 7702 `044_008`).

## Exporting WAV files for Whisper

```
python3 audio/audio_index.py index "Tales of Destiny 2 (Japan, Asia).iso" ps2_audio.csv --wav wav_ps2
python3 audio/audio_index.py index "Tales of Destiny 2 (Japan).iso" psp_audio.csv --wav wav_psp
```

`--wav DIR` writes one 16-bit WAV per voice (`ps2_07300.wav`,
`psp_07426_008_000_a.wav`, ...). By default only voices and battle voices are
written; `--kind "battle voice"` limits it to the battle lines, which is the
quickest start for battle subtitles (870 files, about 20 minutes of audio).
The PS2 audio is decoded by the tool itself. The PSP ATRAC3plus files need
FFmpeg: `pip install imageio-ffmpeg` (used automatically) or `--ffmpeg PATH`.

Then run the Lifebottle transcriber over the folder, for example
[wav2txt_jp.py](https://github.com/lifebottle/PythonLib/blob/main/wav2txt_jp.py)
with the Whisper medium model. Its JSON (file name to text) joins back to
these tables through the member number in the file name.

`audio_index.py pair ps2_audio.csv psp_audio.csv voice_pairs.csv` rebuilds
the pair table.
