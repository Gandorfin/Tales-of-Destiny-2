!!!!!!!!!!
new order


Then run the GUI PyTOD2.py steps in this order:

1 Unpack FPB
2 Organize FPB
3 Unpack SCPK
4 Unpack SCED
5 Unpack PAK1
6 Move Skits OUT
7 Extract SKIT

fill TXT_EN folder with scenario translated files and one  at "file/pak1/TXT_EN" with translated skits

8 Pack SCED
9 Pack SCPK
10 Insert SKIT (also sets each skit line's text speed from skit_speeds.json, see skit_speed.py; the console prints how many lines got which speed)
11 Move Skits IN
12 Pack PAK1
13 Pack FPB you will get files  "FILE_NEW.FPB" and "new_SLPS_251.72", remove previous "FILE.FPB" and "SLPS_251.72" ,  "FILE_NEW.FPB" needs to be renamed to "FILE.FPB" and "new_SLPS_251.72" to "SLPS_251.72"
note:  " " are not parts of file names