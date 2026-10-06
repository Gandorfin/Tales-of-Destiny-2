; Condense single-byte menu glyphs horizontally without using the unsafe
; in-band <size> command.  The original PSP parser uses the full X scale for
; ASCII at 0x13ECA8/0x13ECD4, while its two-byte glyph path already halves X.
; Match that proven path for ASCII but leave Y scale untouched.

.psp
.erroronwarning on
.open input_file, output_file, 0

.orga 0x0013ED68       ; vaddr 0x13ECA8 + ELF segment file bias 0xC0
.area 4
    srl s3, fp, 1       ; horizontal advance = 50%, vertical state unchanged
.endarea

.orga 0x0013ED94       ; vaddr 0x13ECD4 + ELF segment file bias 0xC0
.area 4
    sh s3, 6(s0)        ; draw width uses the same condensed X value
.endarea

.close
