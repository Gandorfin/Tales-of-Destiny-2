#!/usr/bin/env python3
"""Build the English PS2 ISO in one command (Windows, Linux, macOS).

    python ps2/build_ps2.py --japanese-iso "Tales of Destiny 2 (Japan).iso" ^
        --cless-iso "Tales of Destiny 2 (Cless menus).iso" ^
        --movie-fpb MOVIE.FPB --version 1.3.1 --out "ToD2 English.iso"

Runs every step of the README "Building" section, in that order, with no
GUI and nothing to click:

1. FILE.FPB and SLPS_251.72 come from the ISO with the old Cless menu patch
   (--cless-iso, or --base-fpb and --base-slps); the 2008 English menus in
   it are the base the menu tools patch.
2. PyTOD2, the same functions its buttons call: Unpack FPB, Organize FPB,
   Unpack SCPK, Unpack SCED, Unpack PAK1, Move Skits OUT, Extract SKIT,
   then Pack SCED, Pack SCPK, Insert SKIT, Move Skits IN, Pack PAK1, from
   ps2/PyTOD2/TXT_EN and ps2/PyTOD2/FILE/pak1/TXT_EN of this checkout.
3. patch_menu_text.py, sfm_text.py build, enemy_text.py build,
   battle_subs.py build, title_credit.py --version, patch_slps_titles.py.
4. Pack FPB.
5. The rebuilt FILE.FPB, SLPS_251.72 and the given MOVIE.FPB go into a copy
   of the clean Japanese ISO (menu/replace_iso_files.py: files keep their
   sectors, retail disc layout).
6. The Latin font (menu/patch_font_iso.py patch; default dreck's
   menu/font-ready_final.png, the one the releases carry).
7. verify_menu_patch.py and fix_disc_layout.py check on the result.

The work folder (--work, default next to --out) keeps every intermediate
file. A step that fails stops the build; no ISO is left behind then.
On Windows comptoe.exe compresses as in the GUI; elsewhere the Python port
in menu/lzss.py does (same format, the game reads both).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PYTOD2 = os.path.join(HERE, 'PyTOD2')
MENU = os.path.join(HERE, 'menu')
sys.path.insert(0, MENU)
import lzss  # noqa: E402
import replace_iso_files  # noqa: E402

GUI_MARKER = '"""\nGraphical Interface Start'
COMPTOE = os.path.join(PYTOD2, 'comptoe.exe')


class BuildError(RuntimeError):
    pass


def comptoe_python(args):
    """comptoe.exe -d | -c1 | -c3 <in> <out>, in Python."""
    mode, src, dst = args
    data = open(src, 'rb').read()
    if mode == '-d':
        out = lzss.unpack(data)
    elif mode in ('-c1', '-c3'):
        out = lzss.pack(data, int(mode[2]))
    else:
        raise BuildError('unknown comptoe mode %s' % mode)
    open(dst, 'wb').write(out)


class _Subprocess(types.ModuleType):
    """subprocess for PyTOD2: runs comptoe.exe from ps2/PyTOD2 on Windows and
    the Python port elsewhere; anything else goes to the real module."""

    def __init__(self):
        super().__init__('subprocess')
        self.__dict__.update({k: getattr(subprocess, k) for k in dir(subprocess)
                              if not k.startswith('__') and k != 'run'})
        self.CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    def run(self, argv, *a, **kw):
        if argv and os.path.basename(argv[0]).lower() == 'comptoe.exe':
            if os.name == 'nt':
                result = subprocess.run([COMPTOE] + list(argv[1:]), *a, **kw)
                if result.returncode:
                    raise BuildError('comptoe.exe %s failed' % ' '.join(argv[1:]))
                return result
            comptoe_python(argv[1:])
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.run(argv, *a, **kw)


def load_pytod2():
    """PyTOD2.py without its window: everything above the GUI section."""
    source = open(os.path.join(PYTOD2, 'PyTOD2.py'), encoding='utf-8').read().replace('\r\n', '\n')
    cut = source.find(GUI_MARKER)
    if cut < 0:
        raise BuildError('PyTOD2.py: GUI section marker not found')
    shim = _Subprocess()
    saved = sys.modules.get('subprocess')
    sys.modules['subprocess'] = shim
    for name in ('tkinter', 'tkinter.filedialog', 'tkinter.messagebox'):
        if name not in sys.modules:
            try:
                __import__(name)
            except ImportError:
                sys.modules[name] = types.ModuleType(name)
    sys.path.insert(0, PYTOD2)
    module = types.ModuleType('PyTOD2')
    module.__file__ = os.path.join(PYTOD2, 'PyTOD2.py')
    try:
        exec(compile(source[:cut], module.__file__, 'exec'), module.__dict__)
    finally:
        if saved is not None:
            sys.modules['subprocess'] = saved
    module.subprocess = shim
    return module


def step(log, title, func, *args):
    start = time.time()
    print('== %s' % title, flush=True)
    func(*args)
    log.append((title, round(time.time() - start, 1)))


def tool(*argv):
    result = subprocess.run([sys.executable] + list(argv), cwd=REPO)
    if result.returncode:
        raise BuildError('%s failed (exit %d)' % (' '.join(os.path.basename(a) for a in argv[:2]),
                                                   result.returncode))


def verify(iso, max_extras):
    """verify_menu_patch.py on the finished ISO. It stays strict about the menu
    modules, the executable and the enemy tables; only "Enemy extras" (battle
    script lines with no table row yet, 26 on main 2026-10-20, 34 in v1.3.0)
    may be up to max_extras, since no build so far has had zero."""
    result = subprocess.run([sys.executable, os.path.join(MENU, 'verify_menu_patch.py'), iso],
                            cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout)
    rows = {}
    for line in result.stdout.splitlines():
        m = re.match(r'(FPB total|Enemy text|Mystic artes|Enemy names|SLPS titles)\s+(\d+)\s+(\d+)\s+(\d+)', line)
        if m:
            rows[m.group(1)] = (int(m.group(3)), int(m.group(4)))
        m = re.match(r'Enemy extras\s+(\d+)', line)
        if m:
            rows['Enemy extras'] = int(m.group(1))
    problems = [k for k, v in rows.items() if k != 'Enemy extras' and v != (0, 0)]
    problems += [line.split()[0] + ' ' + line.split()[1] for line in result.stdout.splitlines()
                 if line.startswith('SLPS') and not re.search(r'PATCHED|clean', line)]
    if len(rows) != 6:
        problems.append('unexpected verify_menu_patch.py output')
    elif rows['Enemy extras'] > max_extras:
        problems.append('%d Enemy extras, more than %d' % (rows['Enemy extras'], max_extras))
    if problems:
        raise BuildError('verify_menu_patch.py: ' + ', '.join(problems))


def extract_from_iso(iso, names, dest):
    """Copy files out of a PS2 ISO (ISO9660, standard library only)."""
    import fix_disc_layout as layout
    with open(iso, 'rb') as fp:
        image = layout.Image(fp)
        records = replace_iso_files.iso9660_records(image)
        for name in names:
            rec = records.get('/' + name.upper())
            if rec is None:
                raise BuildError('%s: no %s on this disc' % (iso, name))
            _, extent, size = rec
            fp.seek(extent * layout.SECTOR)
            with open(os.path.join(dest, name), 'wb') as out:
                left = size
                while left:
                    chunk = fp.read(min(left, 1 << 24))
                    out.write(chunk)
                    left -= len(chunk)


def build(args):
    log = []
    work = os.path.abspath(args.work)
    if os.path.exists(work) and os.listdir(work):
        raise BuildError('work folder %s is not empty; pass an empty or new one' % work)
    os.makedirs(work, exist_ok=True)
    out = os.path.abspath(args.out)
    if os.path.exists(out):
        raise BuildError('%s exists already' % out)

    # 1. base files
    if args.cless_iso:
        step(log, 'Base: FILE.FPB and SLPS_251.72 from the Cless ISO',
             extract_from_iso, args.cless_iso, ['FILE.FPB', 'SLPS_251.72'], work)
    else:
        shutil.copyfile(args.base_fpb, os.path.join(work, 'FILE.FPB'))
        shutil.copyfile(args.base_slps, os.path.join(work, 'SLPS_251.72'))
    for name in ('FPB.json', 'TBL.json'):
        shutil.copyfile(os.path.join(PYTOD2, name), os.path.join(work, name))

    # 2. PyTOD2
    tod = load_pytod2()
    here = os.getcwd()
    os.chdir(work)
    try:
        step(log, 'PyTOD2 Unpack FPB', tod.extract_fpb)
        step(log, 'PyTOD2 Organize FPB', tod.unpack)
        step(log, 'PyTOD2 Unpack SCPK', tod.extract_scpk)
        step(log, 'PyTOD2 Unpack SCED', tod.extract_sced)
        step(log, 'PyTOD2 Unpack PAK1', tod.extract_pak1)
        step(log, 'PyTOD2 Move Skits OUT', tod.move_skits_out)
        step(log, 'PyTOD2 Extract SKIT', tod.extract_skit)
        for src, dst in ((os.path.join(PYTOD2, 'TXT_EN'), 'TXT_EN'),
                         (os.path.join(PYTOD2, 'FILE', 'pak1', 'TXT_EN'), os.path.join('FILE', 'pak1', 'TXT_EN'))):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        step(log, 'PyTOD2 Pack SCED', tod.insert_sced)
        step(log, 'PyTOD2 Pack SCPK', tod.pack_scpk)
        step(log, 'PyTOD2 Insert SKIT', tod.insert_skit)
        step(log, 'PyTOD2 Move Skits IN', tod.move_skits_in)
        step(log, 'PyTOD2 Pack PAK1', tod.insert_pak1)
    finally:
        os.chdir(here)

    # 3. menu tables
    fpb, slps = os.path.join(work, 'FPB'), os.path.join(work, 'SLPS_251.72')
    step(log, 'patch_menu_text.py', tool, os.path.join(MENU, 'patch_menu_text.py'), fpb)
    step(log, 'sfm_text.py build', tool, os.path.join(MENU, 'sfm_text.py'), 'build', fpb)
    step(log, 'enemy_text.py build', tool, os.path.join(MENU, 'enemy_text.py'), 'build', fpb)
    step(log, 'battle_subs.py build', tool, os.path.join(MENU, 'battle_subs.py'), 'build', fpb)
    step(log, 'title_credit.py', tool, os.path.join(MENU, 'title_credit.py'), fpb, '--version', args.version)
    step(log, 'patch_slps_titles.py', tool, os.path.join(MENU, 'patch_slps_titles.py'), slps)

    # 4. Pack FPB
    os.chdir(work)
    try:
        step(log, 'PyTOD2 Pack FPB', tod.pack_fpb)
    finally:
        os.chdir(here)

    finish(args, work, out, log)
    return log


def finish(args, work, out, log):
    """Steps 5 to 7: the ISO from the packed files in work, font, checks."""
    partial = out + '.partial'
    try:
        step(log, 'ISO: write FILE.FPB, SLPS_251.72, MOVIE.FPB into the Japanese ISO',
             replace_iso_files.replace, args.japanese_iso, partial,
             {'FILE.FPB': os.path.join(work, 'FILE_NEW.FPB'),
              'SLPS_251.72': os.path.join(work, 'new_SLPS_251.72'),
              'MOVIE.FPB': args.movie_fpb})
        # 6. font
        if args.font and args.font.lower() != 'none':
            fonted = partial + '.font'
            step(log, 'patch_font_iso.py patch', tool, os.path.join(MENU, 'patch_font_iso.py'),
                 'patch', partial, os.path.abspath(args.font), '-o', fonted)
            os.replace(fonted, partial)
        # 7. checks
        step(log, 'verify_menu_patch.py', verify, partial, args.max_enemy_extras)
        step(log, 'fix_disc_layout.py check', tool, os.path.join(MENU, 'fix_disc_layout.py'), 'check', partial)
        os.replace(partial, out)
    except BaseException:
        for leftover in (partial, partial + '.font'):
            if os.path.exists(leftover):
                os.remove(leftover)
        raise


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--japanese-iso', required=True, help='clean Japanese ISO (players patch this one)')
    base = ap.add_mutually_exclusive_group(required=True)
    base.add_argument('--cless-iso', help='ISO with the old Cless menu patch (build base)')
    base.add_argument('--base-fpb', help='FILE.FPB of the Cless ISO (with --base-slps)')
    ap.add_argument('--base-slps', help='SLPS_251.72 of the Cless ISO (with --base-fpb)')
    ap.add_argument('--movie-fpb', required=True,
                    help='MOVIE.FPB with the subtitled movies (the one of the latest release)')
    ap.add_argument('--version', required=True, help='drawn under the title menu as "Green Gel vX.Y.Z"')
    ap.add_argument('--font', default=os.path.join(MENU, 'font-ready_final.png'),
                    help="Latin font PNG for patch_font_iso.py (default: dreck's font, as in the releases); "
                         "'none' keeps the font of the executable")
    ap.add_argument('--max-enemy-extras', type=int, default=26,
                    help='battle script lines without a table row allowed in the verify step (default 26)')
    ap.add_argument('--out', required=True, help='English ISO to write')
    ap.add_argument('--work', help='work folder (default: <out>.work)')
    args = ap.parse_args(argv)
    if args.base_fpb and not args.base_slps:
        ap.error('--base-fpb needs --base-slps')
    if not args.work:
        args.work = os.path.abspath(args.out) + '.work'
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        log = build(args)
    except BuildError as exc:
        print('BUILD FAILED: %s' % exc, file=sys.stderr)
        return 1
    print('\nBuilt %s' % args.out)
    for title, seconds in log:
        print('  %-70s %6.1f s' % (title, seconds))
    return 0


if __name__ == '__main__':
    sys.exit(main())
