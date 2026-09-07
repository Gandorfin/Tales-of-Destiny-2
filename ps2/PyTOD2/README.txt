Tales of Destiny 2 — English hard-subbed in-game movies
========================================================

Freshly rebuilt translated replacements:
  00001.mpeg  (23 dialogue cues)
  00002.mpeg  ( 6 dialogue cues)
  00003.mpeg  (11 dialogue cues)
  00004.mpeg  (45 dialogue cues)
  00005.mpeg  ( 5 dialogue cues + 765 translated credit events)
  00007.mpeg  (23 dialogue cues)
  00008.mpeg  ( 4 dialogue cues)
  00010.mpeg  ( 3 dialogue cues)

00006.mpeg and 00009.mpeg contain no spoken dialogue and remain untouched.
00000 was not part of the requested 00001–00010 set.

Installation
------------

1. Close PyTOD2 and anything else using MOVIE.FPB.
2. Open PowerShell in this PyTOD2 folder.
3. Run:

   powershell -ExecutionPolicy Bypass -File .\Install-HardsubbedMovies.ps1

The installer reads this folder automatically. It validates every replacement
against the exact slot size, keeps MOVIE.FPB.before-hardsubs.bak, writes the
eight replacements to MOVIE.FPB, and verifies every installed byte.

Compatibility and verification
------------------------------

All eight outputs were rebuilt from extracts that match their exact untouched
MOVIE.FPB.before-hardsubs.bak slots byte-for-byte. Each English SRT was burned
again with the pinned Ubuntu Bold font. The ending keeps its dialogue hardsubs
and adds the translated staff roll.

The replacements retain the original 640x448 MPEG-2 layout, 29.97 fps, exact
slot sizes, pack timing, and PlayStation 2 private-stream audio packets. Every
replacement frame uses the corresponding source PTS, with monotonic DTS. All
source I-frame positions are retained; only a terminal encoder I-frame is
allowed. Spare capacity is carried in legal MPEG padding-stream packets.

Final build results:

  Movie  Peak buffer  Minimum decode lead  SHA-256
  00001      100,179              50.002 ms  7EE464447F613E5B29940D9FDCEF7382E48C08826A1F030F3DD827960E52B9A1
  00002       63,625              50.131 ms  AEBC553FAB2E1BD936468053FF9FC63BA2979A75811A7045FD42498D43CD3034
  00003       53,497              50.184 ms  2154E1FD1DDD7D6F84F476CC8FB5AF5465B2DFF2B0BB9F538EE39AC859E1B42B
  00004       96,824              50.049 ms  94825B4C062AD498633DF26681790538ACD631B1076F388A02C7565145997AF7
  00005      401,621              50.087 ms  63FE1173133F5BC70E4CF175F59DB46C21D76CEAB6C275EA3275ADB940E85E55
  00007       59,096               0.001 ms  315DD1B245E8C0251A58EA5A6024D1FA0311CFB8B01A1EB8BDCF903F3BAED50F
  00008       60,232              10.222 ms  0449EBA437C7969571C4086A90B6D4828BA25DA619EAF52B81C687EAF71160FC
  00010      349,018              44.167 ms  A269A78EDB362BC16947C8987E65FB910FEA76D5177E38758468F7D200ED19DC

The P-STD video buffer bound is 1,841,152 bytes; every measured peak is safely
below it and no underflow was detected. Movies 00007 and 00008 retain their
sources' unusually early startup timing.

MPC-BE may lose sound after seeking because it does not reinitialize the PS2
audio header when playback starts midstream. Play from 0:00 when checking
sound on PC; the PS2 stream contains the original audio unchanged.

Editable English SRT files are in MOVIE and subtitles. The complete build
method and release checks are documented in ..\movies\README.md.
