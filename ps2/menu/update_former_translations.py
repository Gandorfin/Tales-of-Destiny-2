#!/usr/bin/env python3
"""Rebuild menu_former_translations.csv from the history of menu_translations.csv.

Usage (from anywhere inside the repository, after editing the table):
    python3 ps2/menu/update_former_translations.py

patch_menu_text.py refuses a record that holds neither the original
Japanese nor the final English, and then leaves the whole file untouched.
A working FPB folder that was patched by an earlier release holds the
earlier English, so every wording that was ever committed has to be known
as a valid starting point, otherwise a reworded record freezes its file at
the old text for good. This script collects those earlier wordings: for
every record of the current table, each English text that any commit in
the history of the current branch had at the same file and offset. Run it
whenever the English column changes and commit the result with the table.
"""
import csv, io, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TABLE = "ps2/menu/menu_translations.csv"
OUT = os.path.join(HERE, "menu_former_translations.csv")


def git(*args):
    return subprocess.run(("git",) + args, cwd=ROOT, check=True, capture_output=True).stdout


def rows(text):
    # Game text uses LF. Normalize both history and working-copy fields
    # before comparing them, including newlines inside quoted CSV values.
    return list(csv.DictReader(io.StringIO(text, newline=None)))


def main():
    with open(os.path.join(HERE, "menu_translations.csv"), encoding="utf-8", newline="") as f:
        current = {(r["file"], int(r["offset"], 16)): r for r in rows(f.read())}
    former = {key: set() for key in current}
    commits = git("log", "--format=%H", "--", TABLE).decode().split()
    for commit in commits:
        try:
            text = git("show", "%s:%s" % (commit, TABLE)).decode("utf-8")
        except subprocess.CalledProcessError:
            continue                      # the commit that removed or renamed it
        for r in rows(text):
            try:
                key = (r["file"], int(r["offset"], 16))
            except (KeyError, ValueError, TypeError):
                continue
            if key in former and r.get("english") is not None:
                former[key].add(r["english"])
    out = []
    for key in sorted(former):
        now = current[key]
        for text in sorted(former[key] - {now["english"], now["japanese"]}):
            out.append((key[0], "0x%X" % key[1], text))
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(("file", "offset", "english"))
        w.writerows(out)
    print("%d earlier wording(s) of %d record(s) from %d commit(s) -> %s"
          % (len(out), len({(a, b) for a, b, _ in out}), len(commits), os.path.basename(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
