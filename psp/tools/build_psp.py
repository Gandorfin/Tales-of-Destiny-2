#!/usr/bin/env python3
"""One-shot PSP build: Japanese UMD image in, English image out.

    python psp/tools/build_psp.py "Tales of Destiny 2 (Japan).iso" tod2_psp_en.iso [--probe] [--keep WORKDIR]

Steps (all from this repository, no other tools):
1. pull BOOT.BIN and file.fpb out of the image (psp_iso.py)
2. extract every scenario and skit script (psp_text.py extract)
3. match each Japanese record against the translated PS2 script and write
   the English versions (psp_text.py match)
4. insert, rebuild the packages, repack the archive (psp_text.py build)
5. decode the new archive and compare with what was inserted (verify)
6. write the new archive and the executable (as BOOT.BIN and EBOOT.BIN)
   into a copy of the image (psp_iso.py replace)

--probe additionally replaces two lines of the opening scene with width
test patterns (a line of i's over a line of M's, and a long pangram), for
checking how the engine draws Latin text. --keep leaves the work folder.
"""
import sys, os, re, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_iso, psp_text, psp_names, psp_menu, psp_lowercase, psp_fpb, psp_pool, psp_monsters

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

def main(iso, out_iso, probe=False, keep=None):
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
    _lc, _lcinfo = psp_lowercase.patch_boot(open(boot, 'rb').read())
    open(boot, 'wb').write(_lc)
    print('lowercase:', _lcinfo)
    _pool, _pst = psp_pool.relocate_menu(open(boot, 'rb').read())
    open(boot, 'wb').write(_pool)
    print('menu pool:', dict(_pst))
    # after the pool: the bold menu text routine gets a retail copy of the
    # slot table (it can only draw the icon font, so it keeps capitals)
    _bold, _binfo = psp_lowercase.patch_bold_table(open(boot, 'rb').read())
    open(boot, 'wb').write(_bold)
    print('bold table:', _binfo)
    psp_text.extract(boot, fpb, text)
    psp_text.match(text)
    if probe:
        add_probes(text)
    _font = psp_lowercase.build_font(psp_fpb.read_member(fpb, open(boot, 'rb').read(), 0)[0])
    _mons, _monst = psp_monsters.build_changed_members(boot, fpb)
    print('monster book:', dict(_monst))
    _extra = {0: _font}
    _extra.update(_mons)
    psp_text.build(boot, fpb, text, new_fpb, new_boot, extra=_extra)
    if not psp_text.verify(new_boot, new_fpb, text):
        raise SystemExit('verification failed, image not written')
    psp_iso.replace(iso, out_iso, [
        ('/PSP_GAME/USRDIR/file.fpb', new_fpb),
        ('/PSP_GAME/SYSDIR/BOOT.BIN', new_boot),
        ('/PSP_GAME/SYSDIR/EBOOT.BIN', new_boot),
    ])
    if keep is None:
        shutil.rmtree(work)
    print('wrote', out_iso)

if __name__ == '__main__':
    a = sys.argv[1:]
    probe = '--probe' in a
    keep = None
    if '--keep' in a:
        keep = a[a.index('--keep') + 1]
        a.remove('--keep'); a.remove(keep)
    a = [x for x in a if x != '--probe']
    if len(a) != 2:
        print(__doc__)
        sys.exit(1)
    main(a[0], a[1], probe, keep)
