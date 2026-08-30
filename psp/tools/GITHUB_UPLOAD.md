# Uploading this source update

The source ZIP is an overlay for the Tales-of-Destiny-2 repository. Extract it
at the repository root to place the collaborator tools under `psp/jazz tools`.
It does not replace the older experimental `psp/tools` directory or PS2 tools.

Include the entire source folder from the ZIP, not just `psp_text.py`: the fixed
scanner imports the new `psp_sced.py` module. The package contains Python source,
translation/mapping tables, tests, documentation, the folder's `.gitignore`,
and the repository license. It excludes ISO/CSO images, extracted archives,
executables, memory captures, logs, saves and local build workspaces.

The shared `ps2/PyTOD2/TBL.json` and translation corpus directories must already
be present in the target repository; see the README prerequisites. This is a
source update, not a self-contained binary patch or a game download.

Before uploading, run from the repository root:

```
python -B -m unittest discover -s "psp/jazz tools" -p test_psp_sced.py -v
```

For a Git checkout, stage only the intended source folder and inspect the list:

```
git add -- "psp/jazz tools"
git diff --cached --stat
git diff --cached --name-only
```

Do not use `git add .` on a working directory containing game dumps and unrelated
changes. The scoped `.gitignore` protects this tools directory, not other paths
in the repository, and cannot remove files that are already tracked. When using
GitHub's browser upload, upload the extracted source package rather than the
mixed local folder containing your test ISOs; browser uploads do not apply Git's
ignore rules.

Suggested commit title: `Fix PSP SCED pointer detection and Elrane scene freeze`.
See `CHANGELOG.md` for the cause, validation results, and upgrade notes.
