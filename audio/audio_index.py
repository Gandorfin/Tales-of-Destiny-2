#!/usr/bin/env python3
"""Index every audio file of the PS2 or PSP disc, optionally export WAVs.

    python3 audio/audio_index.py index GAME.iso OUT.csv [--wav DIR] [--kind voice,battle voice]
    python3 audio/audio_index.py pair ps2_audio.csv psp_audio.csv OUT.csv

`index` finds the platform from the image (SLPS_251.72 or PSP_GAME) and writes
one row per audio member of FILE.FPB / file.fpb: member index, offset and size
inside the archive, format, sample rate, channels, duration and a kind guess.
`--wav DIR` also writes DIR/<platform>_<member>.wav for every row whose kind is
listed in --kind (default: voice and battle voice). PS2 audio is decoded here
(Sony SPU ADPCM); PSP ATRAC3plus goes through FFmpeg (imageio-ffmpeg or an
ffmpeg on PATH, --ffmpeg to choose one).

`pair` lines up the voice files of both discs by order and duration (the PSP
voices are the PS2 voices re-encoded, in the same order with a few extra
files on each side) and writes which PS2 member is which PSP member, so a
transcript of one disc can be reused for the other.

What the discs hold (found 2026-10-15):
  PS2  FILE.FPB members typed "at3" in ps2/PyTOD2/FPB.json are headerless SPU
       ADPCM, mono. Story and skit voice tracks: 48000 Hz (one file per scene
       or skit, several lines each). Battle voices from member 7185 on:
       22050 Hz (one line each). Members 50..53 are stereo 48 kHz music
       (interleaved, listed but not exported). IECS members, at3pak
       (compressed IECS) and the "at3" member in front of each IECS pair
       (its sample body) are sound effects.
  PSP  RIFF WAVE ATRAC3plus: mono 44100 Hz = story and skit voices, stereo =
       music. VAGp (SPU ADPCM with a header and a name such as 069_000 or
       BTL_10_12_11) = battle voices, 22050 Hz. MThd = MIDI music sequences,
       d2_* = .phd/.pbd sound banks.
"""
import argparse, csv, json, os, shutil, struct, subprocess, sys, wave, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'psp', 'tools'))
import psp_iso, psp_fpb

SECTOR = 0x800
FIELDS = ['platform', 'member', 'offset', 'size', 'format', 'rate', 'channels',
          'seconds', 'kind', 'name']

# PS2: FILE.FPB member table in SLPS_251.72 (same constants as PyTOD2)
PS2_TABLE = (0xDD320, 0xE62EF)
PS2_LOW_BITS = 0x3F
PS2_VOICE_RATE = 48000
PS2_BATTLE_RATE = 22050
PS2_BATTLE_FIRST = 7185          # battle voices run from here to the last "at3"
# stereo 48 kHz music streams (as stereo, 51 and 53 last exactly as long as
# the PSP's stereo ATRAC3plus members 138 and 140)
PS2_MUSIC = range(50, 54)
PS2_FIRST_VOICE = 57             # earlier "at3" members are bank bodies, music, a jingle
PSP_VAG_HEADER = 0x30

# SPU ADPCM prediction filters (x/64)
FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))


def decode_adpcm(data):
    """Mono SPU ADPCM (16-byte frames, 28 samples each) -> 16-bit PCM bytes.
    Stops at a frame with the end flag (bit 0 of byte 1) when it is not part
    of a loop."""
    out = bytearray()
    s1 = s2 = 0
    for pos in range(0, len(data) - 15, 16):
        head, flags = data[pos], data[pos + 1]
        shift, filt = head & 0x0F, min(head >> 4, 4)
        f0, f1 = FILTERS[filt]
        for b in data[pos + 2:pos + 16]:
            for nib in (b & 0x0F, b >> 4):
                v = nib - 16 if nib & 8 else nib
                v = (v << 12) >> shift
                v += (s1 * f0 + s2 * f1 + 32) >> 6
                v = max(-32768, min(32767, v))
                s2, s1 = s1, v
                out += struct.pack('<h', v)
        if flags & 1 and not flags & 2:
            break
    return bytes(out)


def adpcm_samples(data):
    """Samples up to the end flag or the last frame that is not silent."""
    last = 0
    for pos in range(0, len(data) - 15, 16):
        frame = data[pos:pos + 16]
        if any(frame[2:]) or frame[0] & 0x0F:
            last = pos // 16 + 1
        if frame[1] & 1 and not frame[1] & 2:
            return (pos // 16 + 1) * 28
    return last * 28


def write_wav(path, pcm, rate, channels=1):
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def iso_files(path):
    with open(path, 'rb') as f:
        return {p.upper(): (l * SECTOR, s) for p, l, s, _ in psp_iso.listing(f)}


def read_at(f, offset, size):
    f.seek(offset)
    return f.read(size)


def ps2_members(iso, files):
    """(member, archive offset, size, data) for every member of FILE.FPB."""
    so, sl = files['/SLPS_251.72']
    fo, _ = files['/FILE.FPB']
    f = open(iso, 'rb')          # stays open: rows read their data on export
    slps = read_at(f, so, sl)
    n = (PS2_TABLE[1] - PS2_TABLE[0]) // 4
    ptrs = struct.unpack_from('<%dI' % n, slps, PS2_TABLE[0])
    for i in range(len(ptrs) - 1):
        rem = ptrs[i] & PS2_LOW_BITS
        start = ptrs[i] & ~PS2_LOW_BITS
        end = (ptrs[i + 1] & ~PS2_LOW_BITS) - rem
        if end > start:
            yield i, start, end - start, lambda s=start, z=end - start: read_at(f, fo + s, z)


def index_ps2(iso, files):
    types = json.load(open(os.path.join(ROOT, 'ps2', 'PyTOD2', 'FPB.json')))
    rows = []
    for i, start, size, read in ps2_members(iso, files):
        kind = types.get('%05d' % i)
        row = dict(platform='ps2', member=i, offset=start, size=size, name='')
        if kind == 'at3':
            data = read()
            if types.get('%05d' % (i + 1)) == 'iecs':
                # sample body of the IECS sound bank that follows it
                row.update(format='spu-adpcm bank body', rate='', channels='', seconds='',
                           kind='sound effects')
            elif i < PS2_FIRST_VOICE and i not in PS2_MUSIC:
                row.update(format='spu-adpcm', rate=PS2_VOICE_RATE, channels=1,
                           seconds='%.3f' % (adpcm_samples(data) / PS2_VOICE_RATE),
                           kind='sound effects')
            elif i in PS2_MUSIC:
                row.update(format='spu-adpcm interleaved', rate=PS2_VOICE_RATE, channels=2,
                           seconds='%.3f' % (len(data) // 16 * 28 / 2 / PS2_VOICE_RATE),
                           kind='music')
            else:
                rate = PS2_BATTLE_RATE if i >= PS2_BATTLE_FIRST else PS2_VOICE_RATE
                row.update(format='spu-adpcm', rate=rate, channels=1,
                           seconds='%.3f' % (adpcm_samples(data) / rate),
                           kind='battle voice' if i >= PS2_BATTLE_FIRST else 'voice')
        elif kind in ('iecs', 'at3pak'):
            row.update(format='IECS bank' + (' (compressed)' if kind == 'at3pak' else ''),
                       rate='', channels='', seconds='', kind='sound effects')
        else:
            continue
        row['_read'] = read
        rows.append(row)
    return rows


def riff_info(head):
    info, pos = {}, 12
    while pos + 8 <= len(head):
        cid, cl = head[pos:pos + 4], struct.unpack_from('<I', head, pos + 4)[0]
        if cid == b'fmt ':
            info['fmt'], info['channels'], info['rate'] = struct.unpack_from('<HHI', head, pos + 8)
        elif cid == b'fact':
            info['samples'] = struct.unpack_from('<I', head, pos + 8)[0]
        elif cid == b'data':
            break
        pos += 8 + cl + (cl & 1)
    return info


def index_psp(iso, files):
    bo, bl = files['/PSP_GAME/SYSDIR/BOOT.BIN']
    po, _ = files['/PSP_GAME/USRDIR/FILE.FPB']
    rows = []
    f = open(iso, 'rb')          # stays open: rows read their data on export
    boot = read_at(f, bo, bl)
    for i, (start, size) in enumerate(psp_fpb.member_ranges(psp_fpb.read_table(boot))):
        if not size:
            continue
        head = read_at(f, po + start, min(size, 512))
        read = lambda s=start, z=size: read_at(f, po + s, z)
        row = dict(platform='psp', member=i, offset=start, size=size, name='')
        if head[:4] == b'RIFF':
            info = riff_info(head)
            ch, rate = info.get('channels', 0), info.get('rate', 0)
            fmt = 'atrac3plus' if info.get('fmt') == 0xFFFE else 'riff 0x%04x' % info.get('fmt', 0)
            secs = info['samples'] / rate if rate and 'samples' in info else ''
            row.update(format=fmt, rate=rate, channels=ch,
                       seconds='%.3f' % secs if secs != '' else '',
                       kind='voice' if ch == 1 else 'music')
        elif head[:4] == b'VAGp':
            data_size, rate = struct.unpack_from('>II', head, 12)
            name = head[32:48].split(b'\0')[0].decode('ascii', 'replace')
            samples = adpcm_samples(read()[PSP_VAG_HEADER:PSP_VAG_HEADER + data_size])
            row.update(format='vag', rate=rate, channels=1, seconds='%.3f' % (samples / rate),
                       kind='battle voice', name=name)
        elif head[:4] == b'MThd':
            row.update(format='midi', rate='', channels='', seconds='', kind='music')
        elif head[:3] == b'd2_' or head[:4] == b'd2se':
            name = head[:16].split(b'\0')[0].decode('ascii', 'replace')
            row.update(format='phd/pbd banks', rate='', channels='', seconds='',
                       kind='sound effects', name=name)
        else:
            continue
        row['_read'] = read
        rows.append(row)
    return rows


def find_ffmpeg(given=None):
    if given:
        return given
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return shutil.which('ffmpeg')


def export(rows, outdir, kinds, ffmpeg=None):
    os.makedirs(outdir, exist_ok=True)
    done = 0
    for row in rows:
        if row['kind'] not in kinds:
            continue
        name = '%s_%05d%s.wav' % (row['platform'], row['member'],
                                  '_' + row['name'] if row['name'] else '')
        path = os.path.join(outdir, name)
        data = row['_read']()
        if row['format'] == 'spu-adpcm':
            write_wav(path, decode_adpcm(data), row['rate'])
        elif row['format'] == 'vag':
            size = struct.unpack_from('>I', data, 12)[0]
            write_wav(path, decode_adpcm(data[PSP_VAG_HEADER:PSP_VAG_HEADER + size]), row['rate'])
        elif row['format'] == 'atrac3plus':
            ff = find_ffmpeg(ffmpeg)
            if not ff:
                raise SystemExit('ATRAC3plus needs FFmpeg: pip install imageio-ffmpeg or pass --ffmpeg')
            tmp = path[:-4] + '.at3'
            open(tmp, 'wb').write(data)
            subprocess.run([ff, '-v', 'error', '-y', '-i', tmp, path], check=True)
            os.remove(tmp)
        else:
            continue
        done += 1
        if done % 500 == 0:
            print('  %d WAV files...' % done, flush=True)
    return done


def index(iso, out_csv, wav=None, kinds=('voice', 'battle voice'), ffmpeg=None):
    files = iso_files(iso)
    if '/SLPS_251.72' in files:
        rows = index_ps2(iso, files)
    elif '/PSP_GAME/USRDIR/FILE.FPB' in files:
        rows = index_psp(iso, files)
    else:
        raise SystemExit('neither the PS2 (SLPS_251.72) nor the PSP (ULJS-00097) disc')
    with open(out_csv, 'w', newline='', encoding='utf-8') as o:
        w = csv.DictWriter(o, FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    print('%s: %d audio members %s -> %s' % (rows[0]['platform'] if rows else '?', len(rows),
                                              counts, out_csv))
    if wav:
        print('%d WAV files written to %s' % (export(rows, wav, kinds, ffmpeg), wav))
    return rows


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def align(a, b, tolerance=0.08, slack=0.35):
    """Order preserving match of two duration lists (seconds). Two items match
    when their durations differ by less than `slack` s + `tolerance` x length;
    unmatched items on either side are allowed (files only one disc has)."""
    n, m = len(a), len(b)
    gap = 1.0
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0], move[i][0] = -gap * i, 1
    for j in range(1, m + 1):
        score[0][j], move[0][j] = -gap * j, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d = abs(a[i - 1] - b[j - 1])
            ok = d <= slack + tolerance * max(a[i - 1], b[j - 1])
            best, mv = score[i - 1][j - 1] + (1.0 - d / (1 + d) if ok else -5.0), 0
            if score[i - 1][j] - gap > best:
                best, mv = score[i - 1][j] - gap, 1
            if score[i][j - 1] - gap > best:
                best, mv = score[i][j - 1] - gap, 2
            score[i][j], move[i][j] = best, mv
    pairs, i, j = [], n, m
    while i or j:
        mv = move[i][j]
        if i and j and mv == 0:
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i and (mv == 1 or not j):
            pairs.append((i - 1, None)); i -= 1
        else:
            pairs.append((None, j - 1)); j -= 1
    return pairs[::-1]


def keep_runs(pairs, length):
    """Split matches that are not part of `length` consecutive matches back
    into two unmatched entries (a lone duration match is a coincidence)."""
    out, run = [], []
    def flush():
        if len(run) >= length:
            out.extend(run)
        else:
            for x, y in run:
                out.extend([(x, None), (None, y)])
        run.clear()
    for x, y in pairs:
        if x is not None and y is not None:
            run.append((x, y))
        else:
            flush()
            out.append((x, y))
    flush()
    return out


def pair(ps2_csv, psp_csv, out_csv):
    ps2, psp = read_csv(ps2_csv), read_csv(psp_csv)
    out = []
    for kind in ('voice', 'battle voice'):
        a = [r for r in ps2 if r['kind'] == kind]
        b = [r for r in psp if r['kind'] == kind]
        secs = lambda rows, idx: [float(rows[k]['seconds']) for k in idx]
        first = align(secs(a, range(len(a))), secs(b, range(len(b))))
        # second pass: blocks stored at a different place on each disc (PS2
        # 5731..5747 sit among the story voices, PSP 8122..8138 among the
        # battle voices) are aligned again among the leftovers
        left_a = [x for x, y in first if y is None]
        left_b = [y for x, y in first if x is None]
        second = [(left_a[x] if x is not None else None, left_b[y] if y is not None else None)
                  for x, y in align(secs(a, left_a), secs(b, left_b), tolerance=0.01, slack=0.15)]
        second = keep_runs(second, 3)
        result = [p for p in first if p[0] is not None and p[1] is not None] + second
        result.sort(key=lambda p: (int(a[p[0]]['member']) if p[0] is not None else 10 ** 6,
                                   int(b[p[1]]['member']) if p[1] is not None else 0))
        for x, y in result:
            ra = a[x] if x is not None else None
            rb = b[y] if y is not None else None
            out.append(dict(kind=kind,
                            ps2_member=ra['member'] if ra else '',
                            ps2_seconds=ra['seconds'] if ra else '',
                            psp_member=rb['member'] if rb else '',
                            psp_seconds=rb['seconds'] if rb else '',
                            psp_name=rb['name'] if rb else ''))
    with open(out_csv, 'w', newline='', encoding='utf-8') as o:
        w = csv.DictWriter(o, ['kind', 'ps2_member', 'ps2_seconds', 'psp_member',
                               'psp_seconds', 'psp_name'])
        w.writeheader()
        w.writerows(out)
    both = sum(1 for r in out if r['ps2_member'] and r['psp_member'])
    print('%d pairs, %d PS2 only, %d PSP only -> %s' % (
        both, sum(1 for r in out if not r['psp_member']),
        sum(1 for r in out if not r['ps2_member']), out_csv))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('index')
    s.add_argument('iso')
    s.add_argument('csv')
    s.add_argument('--wav', metavar='DIR', help='also export WAV files here')
    s.add_argument('--kind', default='voice,battle voice',
                   help='kinds to export with --wav, comma separated (default: voice,battle voice)')
    s.add_argument('--ffmpeg', help='FFmpeg executable for the PSP ATRAC3plus files')
    s = sub.add_parser('pair')
    s.add_argument('ps2_csv')
    s.add_argument('psp_csv')
    s.add_argument('out_csv')
    a = p.parse_args(argv)
    if a.command == 'index':
        index(a.iso, a.csv, a.wav, tuple(k.strip() for k in a.kind.split(',')), a.ffmpeg)
    else:
        pair(a.ps2_csv, a.psp_csv, a.out_csv)


if __name__ == '__main__':
    main()
