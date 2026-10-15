#!/usr/bin/env python3
"""One-shot PSP build: Japanese UMD image in, English image out.

    python psp/tools/build_psp.py "Tales of Destiny 2 (Japan).iso" tod2_psp_en.iso --version 0.1.1 [--lowercase-font on|off] [--movies [--ffmpeg PATH]] [--probe] [--keep WORKDIR]

--version X.Y.Z draws "Green Gel Patch vX.Y.Z" on the title screen in place
of the Japanese designer credit (psp_title.py). Without it the title screen
keeps the original two lines, so pass it for every release build.

Steps (all from this repository, no other tools):
1. pull BOOT.BIN and file.fpb out of the image (psp_iso.py)
2. extract every scenario and skit script using instruction-validated pointers
3. match each Japanese record against the translated PS2 script and write
   the English versions (psp_text.py match)
4. insert with bytecode-preservation checks, rebuild packages and the archive
5. decode the new archive and compare with what was inserted (verify)
6. write the new archive and the executable (as BOOT.BIN and EBOOT.BIN)
   into a copy of the image (psp_iso.py replace)

--probe additionally replaces two lines of the opening scene with width
test patterns (a line of i's over a line of M's, and a long pangram), for
checking how the engine draws Latin text. --keep leaves the work folder.
--lowercase-font on (the default) applies SkyBladeCloud's lowercase font hack.
--lowercase-font off keeps the retail fonts and uppercase ASCII rendering.
--movies also burns the English subtitles into the nine movies with dialogue
(psp_movies.py; needs an FFmpeg with libass and libx264, or the
imageio-ffmpeg package; --ffmpeg names the executable).
"""
import sys, os, re, json, hashlib, subprocess, tempfile, shutil, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))

# What the build reads from the rest of the repository (outside psp/tools):
# (what it is, path relative to the repository root, file pattern for a
# folder or None for a file, minimum file count, when it is needed)
SOURCES = [
    ('scenario English', 'Third pass Quality-Safe Output', r'.*\.txt$', 400, 'always'),
    ('skit English', 'third pass skits safe output', r'.*\.txt$', 600, 'always'),
    ('text encoding table', 'ps2/PyTOD2/TBL.json', None, 1, 'always'),
    ('skit speed rules', 'ps2/PyTOD2/skit_speed.py', None, 1, 'always'),
    ('skit time windows', 'ps2/PyTOD2/skit_speeds.json', None, 1, 'always'),
    ('title credit drawing', 'ps2/menu/title_credit.py', None, 1, 'always'),
    ('title credit glyphs', 'ps2/menu/title_glyphs.py', None, 1, 'always'),
    ('movie subtitles', 'ps2/movies/subtitles', r'\d{5}\.en\.srt$', 8, 'movies'),
    ('movie subtitle font', 'ps2/movies/fonts/Ubuntu-Bold.ttf', None, 1, 'movies'),
]


def source_files(path, pattern):
    if pattern is None:
        return [path] if os.path.isfile(path) else []
    if not os.path.isdir(path):
        return []
    return sorted(os.path.join(path, n) for n in os.listdir(path) if re.match(pattern, n))


def fingerprint(files):
    """Short hash of the file names and contents, line endings normalised,
    so a Windows checkout (CRLF) and a Linux one give the same value."""
    h = hashlib.sha256()
    for f in files:
        h.update(os.path.basename(f).encode('utf-8') + b'\0')
        with open(f, 'rb') as o:
            h.update(o.read().replace(b'\r\n', b'\n'))
        h.update(b'\0')
    return h.hexdigest()[:12]


def check_sources(movies=False, report=True):
    """Stop with the missing path when the rest of the repository is not
    there; otherwise print what the build reads, so two builds can be
    compared (same fingerprints = same text and timing)."""
    missing, lines = [], []
    for what, rel, pattern, least, when in SOURCES:
        if when == 'movies' and not movies:
            continue
        path = os.path.join(ROOT, *rel.split('/'))
        files = source_files(path, pattern)
        if len(files) < least:
            missing.append('%s: %s (%d file(s) found, %d needed)' % (what, path, len(files), least))
            continue
        lines.append('  %-21s %s  [%d file(s), fingerprint %s]' % (what, path, len(files), fingerprint(files)))
    if not missing:
        table = json.load(open(os.path.join(ROOT, 'ps2', 'PyTOD2', 'skit_speeds.json'), encoding='utf-8'))
        # every timed line has [pointer, speed, Japanese glyphs, window]; the
        # untimed opening diary 00054_02 has no window
        if not all(len(row) > 3 for name, rows in table.items() if name != '00054_02.sced' for row in rows):
            missing.append('skit time windows: ps2/PyTOD2/skit_speeds.json has no window column '
                           '(older than the full length skit retranslation)')
    if missing:
        raise SystemExit('The PSP build reads these from the rest of the repository and they are missing or outdated:\n  '
                         + '\n  '.join(missing)
                         + '\nBuild from a full, up to date clone of Tales-of-Destiny-2 (git pull), '
                           'not from a copy of psp/tools alone.')
    if report:
        try:
            commit = subprocess.run(['git', '-C', ROOT, 'log', '-1', '--format=%h %cd', '--date=short'],
                                    capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            commit = ''
        print('repository:', ROOT, '(commit %s)' % commit if commit else '(no git commit found)')
        print('sources:')
        print('\n'.join(lines))


check_sources(report=False)
sys.path.insert(0, HERE)
import psp_iso, psp_text, psp_names, psp_menu, psp_lowercase, psp_fpb, psp_pool, psp_monsters, psp_title

def add_probes(work):
    p = os.path.join(work, 'scenario_en', '06470.txt')
    s = open(p, encoding='utf-8').read()
    for jp, new in (('だいじょぶかっ!?', 'iiiiiiiiiiiiiiiiiiii\nMMMMMMMMMMMMMMMMMMMM'),
                    ('わかってる！', 'The quick brown fox jumps over the lazy dog 0123456789 abc')):
        m = re.search(r'#' + re.escape(jp) + r'\n(.*?)\n-{5,}', s, re.S)
        if not m:
            raise SystemExit('probe anchor not found: ' + jp)
        s = s[:m.start(1)] + new + s[m.end(1):]
    open(p, 'w', encoding='utf-8').write(s)
    print('probes placed in 06470')

def main(iso, out_iso, probe=False, keep=None, version=None, lowercase_font=True, movies=False, ffmpeg=None):
    check_sources(movies)
    work = keep or tempfile.mkdtemp(prefix='tod2psp_')
    os.makedirs(work, exist_ok=True)
    boot = os.path.join(work, 'BOOT.BIN')
    fpb = os.path.join(work, 'file.fpb')
    new_fpb = os.path.join(work, 'new.fpb')
    new_boot = os.path.join(work, 'new_BOOT.BIN')
    text = os.path.join(work, 'text')
    psp_iso.extract(iso, '/PSP_GAME/SYSDIR/BOOT.BIN', boot)
    psp_iso.extract(iso, '/PSP_GAME/USRDIR/file.fpb', fpb)
    _named = psp_names.patch_names(open(boot, 'rb').read())[0]
    open(boot, 'wb').write(_named)
    _menu, _mst = psp_menu.patch_menu(open(boot, 'rb').read())
    open(boot, 'wb').write(_menu)
    print('menu patch:', dict(_mst))
    if lowercase_font:
        _lc, _lcinfo = psp_lowercase.patch_boot(open(boot, 'rb').read())
        open(boot, 'wb').write(_lc)
        print('lowercase:', _lcinfo)
    else:
        print('lowercase font hack: off (retail uppercase rendering)')
    _pool, _pst = psp_pool.relocate_menu(open(boot, 'rb').read())
    open(boot, 'wb').write(_pool)
    print('menu pool:', dict(_pst))
    # after the pool: the bold menu text routine gets a retail copy of the
    # slot table (it can only draw the icon font, so it keeps capitals)
    if lowercase_font:
        _bold, _binfo = psp_lowercase.patch_bold_table(open(boot, 'rb').read())
        open(boot, 'wb').write(_bold)
        print('bold table:', _binfo)
    psp_text.extract(boot, fpb, text)
    psp_text.match(text)
    if probe:
        add_probes(text)
    _extra = {}
    if lowercase_font:
        _extra[0] = psp_lowercase.build_font(psp_fpb.read_member(fpb, open(boot, 'rb').read(), 0)[0])
    _mons, _monst = psp_monsters.build_changed_members(boot, fpb)
    print('monster book:', dict(_monst))
    _extra.update(_mons)
    if version:
        _extra[psp_title.PAK_INDEX] = psp_title.build_member(boot, fpb, psp_title.label_for(version))[0]
    else:
        print('title credit: unchanged (pass --version X.Y.Z to draw the patch name on the title screen)')
    psp_text.build(boot, fpb, text, new_fpb, new_boot, extra=_extra)
    if not psp_text.verify(new_boot, new_fpb, text):
        raise SystemExit('verification failed, image not written')
    replaced = [
        ('/PSP_GAME/USRDIR/file.fpb', new_fpb),
        ('/PSP_GAME/SYSDIR/BOOT.BIN', new_boot),
        ('/PSP_GAME/SYSDIR/EBOOT.BIN', new_boot),
    ]
    if movies:
        import psp_movies
        replaced += psp_movies.build(iso, os.path.join(work, 'movies'), ffmpeg)
    psp_iso.replace(iso, out_iso, replaced)
    if keep is None:
        shutil.rmtree(work)
    print('wrote', out_iso)

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('iso', help='clean Japanese ULJS-00097 ISO')
    parser.add_argument('out_iso', help='English output ISO')
    parser.add_argument('--probe', action='store_true', help='insert opening-scene width probes')
    parser.add_argument('--keep', metavar='WORKDIR', help='keep extracted build files here')
    parser.add_argument('--version', help='patch version to draw on the title screen')
    parser.add_argument('--lowercase-font', choices=('on', 'off'), default='on',
                        help="apply the collaborator's lowercase font hack (default: on); off uses retail uppercase rendering")
    parser.add_argument('--movies', action='store_true', help='burn the English subtitles into the movies')
    parser.add_argument('--ffmpeg', help='FFmpeg executable for --movies (needs libass and libx264)')
    return parser.parse_args(argv)


if __name__ == '__main__':
    args = parse_args()
    main(args.iso, args.out_iso, args.probe, args.keep, args.version,
         lowercase_font=args.lowercase_font == 'on', movies=args.movies, ffmpeg=args.ffmpeg)
