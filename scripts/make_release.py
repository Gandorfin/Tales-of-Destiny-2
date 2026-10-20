#!/usr/bin/env python3
"""Build, check and (optionally) upload a release in one command.

    python scripts/make_release.py ps2 --version 1.3.1
    python scripts/make_release.py psp --version 0.3.3
    python scripts/make_release.py ps2 --version 1.3.1 --upload

What it does, in order; any failure stops it:

1. Takes the commit to release (default: upstream/main after a fetch) and
   checks it out into a fresh, clean git worktree in the work folder, so no
   local change or stale file can end up in the patch.
2. Runs the translation audit (only the four known chest number-mode
   mismatches are accepted) and the unit tests of ps2/menu, ps2/PyTOD2,
   psp/tools and audio.
3. Builds the English ISO from the clean Japanese ISO with the one-command
   builder of that checkout: ps2/build_ps2.py (base = the Cless ISO,
   MOVIE.FPB = the one of the latest PS2 release unless --movie-fpb) or
   psp/tools/build_psp.py --movies.
4. Makes the xdelta (xdelta3 -e -9 -S none), applies it to the clean
   Japanese ISO again and checks the result is byte for byte the built ISO,
   then runs the release checks on that image (PS2: retail disc layout and
   menu patch; PSP: kernel load order of BOOT.BIN and the title version).
5. Packs the xdelta into a 7z with the names the releases use
   (ToD2_Eng_patch_QS_vX.7z, PSP_Patch_VWF_vX.7z).
6. Writes release_notes.md: the PRs merged since the previous release of
   that platform, to edit before publishing (or the file given with
   --notes).
7. With --upload: creates a DRAFT GitHub release (tag created on publish,
   pointing at the exact commit built) and uploads the 7z. Nobody but the
   maintainers sees a draft; publishing it is a click on its page.

Local paths live in release.local.json in the repository root (not
committed):

    {"japanese_iso_ps2": "...", "cless_iso": "...", "japanese_iso_psp": "...",
     "xdelta3": "xdelta3", "token_file": ".release_token"}

The token is a classic GitHub token with the public_repo scope.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, 'release.local.json')
GITHUB = 'Gandorfin/Tales-of-Destiny-2'
API = 'https://api.github.com/repos/' + GITHUB
UPLOADS = 'https://uploads.github.com/repos/' + GITHUB
ACCEPTED_CRITICAL = {'code-mismatch': 4}
MAX_ENEMY_EXTRAS = 26      # battle script lines with no table row yet (build_ps2.py --max-enemy-extras)
TEST_DIRS = ('ps2/menu', 'ps2/PyTOD2', 'psp/tools', 'audio')

PLATFORMS = {
    'ps2': {'tag': lambda v: v, 'name': lambda v: 'Patch: QS v' + v,
            'asset': lambda v: 'ToD2_Eng_patch_QS_v%s' % v,
            'is_tag': re.compile(r'^\d+\.\d+\.\d+[a-z]?$')},
    'psp': {'tag': lambda v: 'PSP_' + v, 'name': lambda v: 'PSP_Patch_v' + v,
            'asset': lambda v: 'PSP_Patch_VWF_v%s' % v,
            'is_tag': re.compile(r'^PSP_\d+\.\d+\.\d+$')},
}


class ReleaseError(RuntimeError):
    pass


def say(text):
    print('== ' + text, flush=True)


def run(argv, cwd=REPO, capture=False):
    result = subprocess.run(argv, cwd=cwd, text=True,
                            stdout=subprocess.PIPE if capture else None)
    if result.returncode:
        raise ReleaseError('%s failed (exit %d)' % (' '.join(map(str, argv[:3])), result.returncode))
    return result.stdout if capture else None


def git(*args, cwd=REPO):
    return run(['git'] + list(args), cwd=cwd, capture=True).strip()


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fp:
        for chunk in iter(lambda: fp.read(1 << 24), b''):
            h.update(chunk)
    return h.hexdigest()


def api(url, token=None, data=None, method=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'tod2-make-release')
    if token:
        req.add_header('Authorization', 'token ' + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def releases():
    return api(API + '/releases?per_page=100')


def previous_release(platform):
    pattern = PLATFORMS[platform]['is_tag']
    for rel in releases():                       # newest first
        if not rel['draft'] and pattern.match(rel['tag_name']):
            return rel
    return None


def download(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': 'tod2-make-release'})
    with urllib.request.urlopen(req) as resp, open(dest + '.part', 'wb') as out:
        shutil.copyfileobj(resp, out, 1 << 24)
    os.replace(dest + '.part', dest)


def movie_from_release(rel, cfg, cache):
    """MOVIE.FPB of a published PS2 release: download, unpack, apply, extract."""
    import py7zr
    sys.path.insert(0, os.path.join(REPO, 'ps2'))
    import build_ps2
    folder = os.path.join(cache, rel['tag_name'])
    movie = os.path.join(folder, 'MOVIE.FPB')
    if os.path.exists(movie):
        return movie
    os.makedirs(folder, exist_ok=True)
    asset = next(a for a in rel['assets'] if a['name'].endswith('.7z'))
    archive = os.path.join(folder, asset['name'])
    if not os.path.exists(archive):
        say('Downloading %s (%d MB) for its movies' % (asset['name'], asset['size'] >> 20))
        download(asset['browser_download_url'], archive)
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(folder)
    patch = next(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith('.xdelta'))
    image = os.path.join(folder, 'release.iso')
    run([cfg['xdelta3'], '-d', '-f', '-s', cfg['japanese_iso_ps2'], patch, image])
    build_ps2.extract_from_iso(image, ['MOVIE.FPB'], folder)
    os.remove(image)
    return movie


def audit_and_tests(src):
    say('Translation audit')
    report = os.path.join(src, 'audit.json')
    run([sys.executable, 'scripts/audit_translation.py', '--json', report], cwd=src, capture=True)
    critical = {k: v for k, v in json.load(open(report, encoding='utf-8'))['critical'].items() if v}
    if critical != ACCEPTED_CRITICAL:
        raise ReleaseError('audit critical findings %s, expected only %s' % (critical, ACCEPTED_CRITICAL))
    for folder in TEST_DIRS:
        if os.path.isdir(os.path.join(src, folder)):
            say('Unit tests ' + folder)
            run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', folder, '-p', 'test_*.py'], cwd=src)


def build(platform, version, src, work, cfg, args):
    out = os.path.join(work, 'english.iso')
    if platform == 'ps2':
        movie = args.movie_fpb
        if not movie:
            rel = previous_release('ps2')
            if rel is None:
                raise ReleaseError('no PS2 release to take MOVIE.FPB from; pass --movie-fpb')
            movie = movie_from_release(rel, cfg, os.path.join(REPO, 'release-cache'))
        argv = [sys.executable, 'ps2/build_ps2.py', '--japanese-iso', cfg['japanese_iso_ps2'],
                '--movie-fpb', movie, '--version', version, '--out', out,
                '--work', os.path.join(work, 'build')]
        argv += ['--cless-iso', cfg['cless_iso']] if cfg.get('cless_iso') else \
                ['--base-fpb', cfg['base_fpb'], '--base-slps', cfg['base_slps']]
        if cfg.get('ps2_font'):
            argv += ['--font', cfg['ps2_font']]
        say('Building the PS2 ISO')
        run(argv, cwd=src)
        base = cfg['japanese_iso_ps2']
    else:
        say('Building the PSP ISO')
        run([sys.executable, 'psp/tools/build_psp.py', cfg['japanese_iso_psp'], out,
             '--version', version, '--movies', '--keep', os.path.join(work, 'build')], cwd=src)
        base = cfg['japanese_iso_psp']
    return out, base


def check_image(platform, version, image, src):
    if platform == 'ps2':
        say('Release checks: disc layout, menu patch')
        run([sys.executable, 'ps2/menu/fix_disc_layout.py', 'check', image], cwd=src)
        # the same gate as the build: strict except the known enemy extras
        run([sys.executable, '-c', 'import sys; sys.path.insert(0, "ps2"); import build_ps2; '
             'build_ps2.verify(sys.argv[1], int(sys.argv[2]))', image, str(MAX_ENEMY_EXTRAS)], cwd=src)
        return
    say('Release checks: BOOT.BIN load order')
    code = ('import sys; sys.path.insert(0, "psp/tools"); import psp_iso, psp_pool, tempfile, os\n'
            'd = tempfile.mkdtemp(); p = os.path.join(d, "BOOT.BIN")\n'
            'psp_iso.extract(sys.argv[1], "/PSP_GAME/SYSDIR/BOOT.BIN", p)\n'
            'print(psp_pool.check_hardware_layout(open(p, "rb").read()))')
    run([sys.executable, '-c', code, image], cwd=src)


# paths whose changes go into each platform's patch (docs and other tools do not)
BUILD_INPUTS = {'ps2': ('ps2/', 'Third pass Quality-Safe Output/', 'third pass skits safe output/'),
                'psp': ('psp/',)}


def notes(platform, version, sha, prev):
    lines = ['# Tales of Destiny 2 %s English Patch v%s' % ('PS2' if platform == 'ps2' else 'PSP', version), '']
    if prev:
        log = git('log', '--merges', '--format=%H%x1f%s%x1f%b%x1e', '%s..%s' % (prev['tag_name'], sha))
        for entry in log.split('\x1e'):               # (\x1f and \x1e count as whitespace for strip)
            if not entry.strip('\n'):
                continue
            merge, subject, body = (entry.lstrip('\n').split('\x1f', 2) + ['', ''])[:3]
            m = re.match(r'Merge pull request #(\d+) from \S+', subject)
            changed = git('diff', '--name-only', merge + '^1', merge).splitlines()
            if m and any(p.startswith(BUILD_INPUTS[platform]) and not p.endswith('.md') for p in changed):
                title = body.strip().splitlines()[0] if body.strip() else subject
                try:                                     # merge commits cut long titles with "…"
                    title = api('%s/pulls/%s' % (API, m.group(1)))['title']
                except OSError:
                    pass
                lines.append('* %s (#%s)' % (title, m.group(1)))
        lines += ['', 'Changes since %s (%s..%s).' % (prev['tag_name'], prev['tag_name'], sha[:8])]
    lines += ['', 'Apply the xdelta to the clean Japanese ISO (Delta Patcher, or',
              '`xdelta3 -d -s original.iso patch.xdelta patched.iso`).']
    return '\n'.join(lines) + '\n'


def upload(platform, version, sha, archive, notes_path, cfg):
    token = open(os.path.join(REPO, cfg.get('token_file', '.release_token'))).read().strip()
    spec = PLATFORMS[platform]
    tag = spec['tag'](version)
    if any(r['tag_name'] == tag for r in api(API + '/releases?per_page=100', token)):
        raise ReleaseError('a release with tag %s exists already (draft or published)' % tag)
    say('Creating the draft release %s' % tag)
    body = json.dumps({'tag_name': tag, 'target_commitish': sha, 'name': spec['name'](version),
                       'body': open(notes_path, encoding='utf-8').read(), 'draft': True,
                       'prerelease': False}).encode()
    rel = api(API + '/releases', token, body, 'POST', {'Content-Type': 'application/json'})
    say('Uploading %s (%d MB)' % (os.path.basename(archive), os.path.getsize(archive) >> 20))
    with open(archive, 'rb') as fp:
        api('%s/releases/%d/assets?name=%s' % (UPLOADS, rel['id'], os.path.basename(archive)), token, fp, 'POST',
            {'Content-Type': 'application/x-7z-compressed', 'Content-Length': str(os.path.getsize(archive))})
    return rel['html_url']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('platform', choices=sorted(PLATFORMS))
    ap.add_argument('--version', required=True, help='X.Y.Z, without "v"')
    ap.add_argument('--commit', help='commit to release (default: upstream/main)')
    ap.add_argument('--movie-fpb', help='PS2: MOVIE.FPB to use instead of the latest release one')
    ap.add_argument('--work', help='work folder (default: release-work/<platform>-<version>)')
    ap.add_argument('--notes', help='release notes file to use instead of the generated draft')
    ap.add_argument('--upload', action='store_true', help='create a draft GitHub release and upload')
    ap.add_argument('--skip-tests', action='store_true', help='only for trying the script itself')
    args = ap.parse_args(argv)
    if not re.match(r'^\d+\.\d+\.\d+[a-z]?$', args.version):
        ap.error('version must look like 1.3.1')
    if args.notes and not os.path.isfile(args.notes):
        ap.error('notes file %s not found' % args.notes)
    if args.notes:
        args.notes = os.path.abspath(args.notes)
    cfg = json.load(open(CONFIG, encoding='utf-8'))
    cfg.setdefault('xdelta3', 'xdelta3')
    spec = PLATFORMS[args.platform]
    work = os.path.abspath(args.work or os.path.join(REPO, 'release-work', '%s-%s' % (args.platform, args.version)))
    if os.path.exists(work):
        raise SystemExit('work folder %s exists; remove it or pass --work' % work)
    try:
        if args.commit:
            sha = git('rev-parse', args.commit + '^{commit}')
        else:
            say('Fetching upstream')
            git('fetch', 'upstream', '--tags')
            sha = git('rev-parse', 'upstream/main')
        say('Releasing %s v%s from %s' % (args.platform.upper(), args.version, sha[:8]))
        os.makedirs(work)
        src = os.path.join(work, 'src')
        git('worktree', 'add', '--detach', src, sha)
        try:
            if not args.skip_tests:
                audit_and_tests(src)
            image, base = build(args.platform, args.version, src, work, cfg, args)
            name = spec['asset'](args.version)
            patch = os.path.join(work, name + '.xdelta')
            say('Making %s' % os.path.basename(patch))
            run([cfg['xdelta3'], '-e', '-9', '-S', 'none', '-f', '-s', base, image, patch])
            say('Applying it to the clean Japanese ISO again')
            check = os.path.join(work, 'from_patch.iso')
            run([cfg['xdelta3'], '-d', '-f', '-s', base, patch, check])
            if sha1(check) != sha1(image):
                raise ReleaseError('the xdelta does not reproduce the built ISO')
            check_image(args.platform, args.version, check, src)
            os.remove(check)
            say('Packing the 7z')
            import py7zr
            archive = os.path.join(work, name + '.7z')
            with py7zr.SevenZipFile(archive, 'w') as z:
                z.write(patch, os.path.basename(patch))
            notes_path = os.path.join(work, 'release_notes.md')
            open(notes_path, 'w', encoding='utf-8').write(
                open(args.notes, encoding='utf-8').read() if args.notes else
                notes(args.platform, args.version, sha, previous_release(args.platform)))
            stamp = {'platform': args.platform, 'version': args.version, 'commit': sha,
                     'built': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
                     'iso_sha1': sha1(image), 'xdelta_sha1': sha1(patch), 'archive': archive}
            json.dump(stamp, open(os.path.join(work, 'release.json'), 'w'), indent=1)
            url = upload(args.platform, args.version, sha, archive, notes_path, cfg) if args.upload else None
        finally:
            git('worktree', 'remove', '--force', src)
    except ReleaseError as exc:
        print('RELEASE STOPPED: %s' % exc, file=sys.stderr)
        return 1
    print('\nDone: %s' % archive)
    print('Notes to review: %s' % notes_path)
    if url:
        print('Draft release (check the notes, then click Publish): %s' % url)
    return 0


if __name__ == '__main__':
    sys.exit(main())
