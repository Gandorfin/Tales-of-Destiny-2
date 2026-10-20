"""Burn the English subtitles into the PSP movies.

The PSP movies are the PS2 movies re-encoded for the PSP (frame for frame,
same timing), so the PS2 subtitle tracks (ps2/movies/subtitles, copied to
psp/text/subtitles by sync_text_from_ps2.py) apply unchanged: PSP movie N
plays PS2 movie N - 1, and PSP 012 is a second copy of PSP 008. For every subtitled movie this script decodes the PSP video,
burns the subtitles (libass, the pinned Ubuntu Bold), encodes H.264 with the
original's settings (Main profile, level 2.1, one reference frame, no B
frames, HRD timing, key frames at exactly the original key frames) and puts
the pictures back with psp_pmf.rebuild, which keeps the audio, the pack
timing and every navigation unit's packs. A unit that does not fit its
original packs lowers the bitrate and encodes again. Each result is checked:
same picture count, decoder buffer within the P-STD size, positive margin.

The ending movie (006) also gets the English staff roll: the PSP roll
differs from the PS2 one, so it has its own table and overlay
(psp_credits.py, psp_credits.tsv, psp_credits.ass).

    python psp_movies.py <Japanese ISO> <work dir> [--ffmpeg PATH] [--only 011 ...]

Requires an FFmpeg build with libass and libx264 (or the imageio-ffmpeg
package, whose bundled FFmpeg has both).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psp_iso
import psp_pmf

ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
# the PSP copy of ps2/movies/subtitles (sync_text_from_ps2.py); the font
# is a fixed binary with its licence in ps2/movies, read from there
SUBTITLES = os.path.join(ROOT, 'psp', 'text', 'subtitles')
FONTS = os.path.join(ROOT, 'ps2', 'movies', 'fonts')
FONT_SHA256 = '679b5c1e09cab3156bb8ef529735f9382bf31ca7ac737382ab959297f8d82ad4'

# PSP movie -> PS2 subtitle track
MOVIES = {
    '002': '00001', '003': '00002', '004': '00003', '005': '00004',
    '006': '00005', '008': '00007', '009': '00008', '011': '00010',
    '012': '00007',
}
ISO_PATH = '/PSP_GAME/USRDIR/movie/%s.pmf'
# extra overlays: the PSP's own staff roll in the ending (psp_credits.py)
OVERLAYS = {'006': (os.path.join(HERE, 'psp_credits.ass'),)}
FIRST_RATE = 0.92  # first attempt: 92 % of each unit's capacity
FRAME_BYTES = 480 * 272 * 3 // 2
RETRIES = 8
UNIT_SQUEEZE = 0.7  # bitrate factor applied to a unit that does not fit, per retry
LATE_AFTER = 2  # from this try on, units that cannot be on time may arrive late (see psp_pmf)
KEY_Q = 36  # quantizer for a unit's first picture that is too big to arrive in time (+4 per retry)

STYLE = ('Style: Default,Ubuntu,17,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,'
         '-1,0,0,0,100,100,0,0,1,1.6,0,2,16,16,8,1')


def find_ffmpeg(path=None):
    candidates = [path] if path else [shutil.which('ffmpeg')]
    if not path:
        try:
            import imageio_ffmpeg
            candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
        except ImportError:
            pass
    for exe in candidates:
        if not exe:
            continue
        filters = subprocess.run([exe, '-hide_banner', '-filters'], capture_output=True, text=True).stdout
        encoders = subprocess.run([exe, '-hide_banner', '-encoders'], capture_output=True, text=True).stdout
        if re.search(r'\ssubtitles\s', filters) and 'libx264' in encoders:
            return exe
    raise SystemExit('no FFmpeg with libass and libx264 found (pass --ffmpeg, or pip install imageio-ffmpeg)')


def check_font():
    import hashlib
    path = os.path.join(FONTS, 'Ubuntu-Bold.ttf')
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != FONT_SHA256:
        raise SystemExit('the pinned font %s has changed' % path)


def read_srt(path):
    cues = []
    text = open(path, encoding='utf-8-sig').read().replace('\r', '').strip()
    for block in re.split(r'\n\s*\n', text):
        lines = block.split('\n')
        m = re.match(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)$', lines[1].strip())
        if not m:
            raise ValueError('%s: bad cue %r' % (path, lines[:2]))
        a = [int(x) for x in m.groups()]
        start = a[0] * 3600 + a[1] * 60 + a[2] + a[3] / 1000
        end = a[4] * 3600 + a[5] * 60 + a[6] + a[7] / 1000
        if end <= start or (cues and start < cues[-1][0]):
            raise ValueError('%s: cue %s is out of order' % (path, lines[0]))
        cues.append((start, end, ' '.join(l.strip() for l in lines[2:] if l.strip())))
    return cues


def write_ass(cues, path):
    def ts(t):
        cs = round(t * 100)
        return '%d:%02d:%02d.%02d' % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('[Script Info]\nScriptType: v4.00+\nPlayResX: 480\nPlayResY: 272\nWrapStyle: 0\n'
                'ScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, '
                'PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, '
                'StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, '
                'MarginL, MarginR, MarginV, Encoding\n' + STYLE + '\n\n[Events]\nFormat: Layer, Start, '
                'End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
        for start, end, text in cues:
            f.write('Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n' % (ts(start), ts(end), text))


def render(ffmpeg, src, ass, frames, out, overlays=()):
    """Decode the PSP video and burn the subtitles (and any extra ASS
    overlays, e.g. the staff roll) into raw 4:2:0 frames."""
    esc = lambda p: p.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
    vf = ','.join("subtitles=filename='%s':fontsdir='%s'" % (esc(a), esc(FONTS)) for a in (ass,) + tuple(overlays))
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', src, '-an', '-vf', vf, '-fps_mode', 'passthrough',
                    '-pix_fmt', 'yuv420p', '-f', 'rawvideo', out], check=True)
    if os.path.getsize(out) != frames * FRAME_BYTES:
        raise ValueError('rendered %d frames, the original has %d' % (os.path.getsize(out) // FRAME_BYTES, frames))


def encode_unit(ffmpeg, raw, first, count, keys, kbps, out, work, key_q=None):
    """Encode pictures first .. first+count-1 of the rendered video on their
    own (a unit starts with an IDR and nothing refers across it). key_q
    forces a quantizer on the unit's first picture, to make it smaller."""
    # weightp=0: the retail movies use no weighted prediction, and x264's
    # default (weighted P frames, weighted_pred_flag 1 in the PPS) is the
    # first thing a strict hardware decoder may refuse; software decoders
    # (PPSSPP's FFmpeg) play either
    params = ['ref=1', 'bframes=0', 'weightp=0', 'cabac=1', 'aud=1', 'repeat-headers=1', 'nal-hrd=vbr',
              'pic-struct=1', 'vbv-maxrate=3000', 'vbv-bufsize=3000', 'keyint=infinite',
              'scenecut=0', 'sar=1/1', 'force-cfr=1']
    if key_q:
        params.append('zones=0,0,q=%d' % key_q)
    params = ':'.join(params)
    expr = 'expr:' + '+'.join('eq(n,%d)' % (k - first) for k in keys)
    log = os.path.join(work, 'x264_%d' % first)
    base = [ffmpeg, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', '480x272',
            '-r', '30000/1001', '-i', 'pipe:0', '-c:v', 'libx264', '-profile:v', 'main', '-level', '2.1',
            '-b:v', '%dk' % max(kbps, 8), '-maxrate', '3000k', '-bufsize', '3000k',
            '-force_key_frames', expr, '-forced-idr', '1', '-x264-params', params, '-passlogfile', log]
    with open(raw, 'rb') as f:
        f.seek(first * FRAME_BYTES)
        frames = f.read(count * FRAME_BYTES)
    subprocess.run(base + ['-pass', '1', '-f', 'null', os.devnull], input=frames, check=True, cwd=work)
    subprocess.run(base + ['-pass', '2', '-f', 'h264', out], input=frames, check=True, cwd=work)
    pics = [strip_user_data(p) for p in psp_pmf.pictures(open(out, 'rb').read())]
    if len(pics) != count or not psp_pmf.is_idr(pics[0]):
        raise ValueError('unit at picture %d: encoded %d pictures' % (first, len(pics)))
    if any(weighted_prediction(p) for p in pics):
        raise ValueError('unit at picture %d: the encoder wrote weighted prediction' % first)
    return pics


def _ue(bits, pos):
    zeros = 0
    while bits[pos] == '0':
        zeros += 1; pos += 1
    pos += 1
    return (1 << zeros) - 1 + (int(bits[pos:pos + zeros], 2) if zeros else 0), pos + zeros


def weighted_prediction(pic):
    """True if a picture parameter set in pic enables weighted prediction
    (weighted_pred_flag or weighted_bipred_idc). The retail movies have
    neither."""
    p = pic.find(b'\x00\x00\x01')
    while p != -1:
        if pic[p + 3] & 31 == 8:
            raw = pic[p + 4:p + 40].replace(b'\x00\x00\x03', b'\x00\x00')
            bits = ''.join('{:08b}'.format(c) for c in raw)
            pos = 0
            for _ in range(2):                   # pps id, sps id
                _, pos = _ue(bits, pos)
            pos += 2                             # entropy coding, pic order present
            groups, pos = _ue(bits, pos)
            if groups:
                raise ValueError('PPS with slice groups')
            for _ in range(2):                   # active reference counts
                _, pos = _ue(bits, pos)
            if bits[pos:pos + 3] != '000':        # weighted_pred_flag, weighted_bipred_idc
                return True
        p = pic.find(b'\x00\x00\x01', p + 3)
    return False


def strip_user_data(pic):
    """Drop x264's version banner (an SEI with payload type 5); the PSP
    files carry no such message and it costs about 600 bytes."""
    out = bytearray()
    i = 0
    while i < len(pic):
        j = pic.find(b'\x00\x00\x01', i + 3)
        j = len(pic) if j == -1 else (j - 1 if pic[j - 1] == 0 else j)
        nal = pic[i:j]
        sc = 4 if nal[:4] == b'\x00\x00\x00\x01' else 3
        if not (nal[sc] & 31 == 6 and nal[sc + 1] == 5):
            out += nal
        i = j
    return bytes(out)


def build_movie(ffmpeg, src_pmf, srt, out_pmf, work, log=print, overlays=()):
    os.makedirs(work, exist_ok=True)
    original = open(src_pmf, 'rb').read()
    movie = psp_pmf.parse(original)
    units, pics, *_ = psp_pmf.layout(movie)
    capacity = psp_pmf.unit_capacities(movie)
    idr = [i for i, p in enumerate(pics) if psp_pmf.is_idr(p)]
    seconds = len(pics) * psp_pmf.FRAME / 90000
    cues = read_srt(srt)
    if cues[-1][1] > seconds + 1:
        raise ValueError('%s: cues run past the movie end' % srt)
    ass = os.path.join(work, 'subtitles.ass')
    write_ass(cues, ass)
    raw = os.path.join(work, 'frames.yuv')
    render(ffmpeg, src_pmf, ass, len(pics), raw, overlays)
    factor = [FIRST_RATE] * len(units)
    key_q = [None] * len(units)
    new = [None] * len(pics)
    todo = list(range(len(units)))
    try:
        for attempt in range(RETRIES):
            def job(u):
                start, end, first, count = units[u]
                keys = [k for k in idr if first <= k < first + count]
                kbps = int(capacity[u] * factor[u] * 8 / (count * psp_pmf.FRAME / 90000) / 1000)
                return u, encode_unit(ffmpeg, raw, first, count, keys, kbps,
                                      os.path.join(work, 'unit_%d.h264' % u), work, key_q[u])
            with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
                for u, unit_pics in pool.map(job, todo):
                    first = units[u][2]
                    new[first:first + len(unit_pics)] = unit_pics
            try:
                data = psp_pmf.rebuild(original, new, allow_late=attempt >= LATE_AFTER)
            except psp_pmf.UnitOverflow as e:
                todo = [u for u, _, _, _ in e.units]
                for u, _, _, late_key in e.units:
                    if late_key:
                        key_q[u] = KEY_Q if key_q[u] is None else min(51, key_q[u] + 4)
                    else:
                        factor[u] *= UNIT_SQUEEZE
                log('  units %s do not fit, encoding them smaller%s' % (
                    todo, ' (key frame of %s)' % [u for u, _, _, l in e.units if l] if any(l for *_, l in e.units) else ''))
                continue
            stats = psp_pmf.buffer_stats(data)
            late = dict(psp_pmf.rebuild.late)
            if stats['peak'] > stats['size'] or (stats['margin'] <= 0 and not late):
                raise SystemExit('%s: decoder buffer check failed: %r' % (src_pmf, stats))
            open(out_pmf, 'wb').write(data)
            log('  %d cues, %d units, video %.0f %% of the original size, buffer peak %d of %d, margin %.3f s'
                % (len(cues), len(units), 100 * sum(map(len, new)) / sum(map(len, pics)),
                   stats['peak'], stats['size'], stats['margin'] / 90000))
            if late:
                log('  units arriving after their pack time (PTS paced players are fine; check these '
                    'moments in the boot test): %s' % ', '.join(
                        '%d at %.1f s (%.2f s late)' % (u, units[u][2] * psp_pmf.FRAME / 90000, -m / 90000)
                        for u, m in sorted(late.items())))
            if psp_pmf.rebuild.relaxed:
                log('  units placed with a wider window (lead in s): %s'
                    % ', '.join('%d (%.2f)' % (u, l / 90000) for u, l in psp_pmf.rebuild.relaxed))
            return out_pmf
        raise SystemExit('%s: units still do not fit after %d tries' % (src_pmf, RETRIES))
    finally:
        if os.path.exists(raw):
            os.remove(raw)


def build(iso, work, ffmpeg=None, only=None, log=print):
    """Subtitled PMFs for the ISO; returns [(ISO path, file)] for psp_iso.replace."""
    ffmpeg = find_ffmpeg(ffmpeg)
    check_font()
    os.makedirs(work, exist_ok=True)
    out = []
    for psp, ps2 in sorted(MOVIES.items()):
        if only and psp not in only:
            continue
        src = os.path.join(work, psp + '.orig.pmf')
        psp_iso.extract(iso, ISO_PATH % psp, src)
        dst = os.path.join(work, psp + '.pmf')
        log('movie %s (PS2 %s):' % (psp, ps2))
        build_movie(ffmpeg, src, os.path.join(SUBTITLES, ps2 + '.en.srt'), dst,
                    os.path.join(work, psp + '.work'), log, OVERLAYS.get(psp, ()))
        out.append((ISO_PATH % psp, dst))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('iso')
    ap.add_argument('work')
    ap.add_argument('--ffmpeg')
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args(argv)
    for path, f in build(a.iso, a.work, a.ffmpeg, a.only):
        print(path, '<-', f)


if __name__ == '__main__':
    main()
