"""The PSP text: skit lines from the PS2 twin, PSP overrides that always
win, the sync from the PS2 folders, and the build's source check."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import build_psp
import psp_text
import sync_text_from_ps2 as sync

DIV = psp_text.DIVIDER + '\n'


def write(path, text, newline='\n'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline=newline) as f:
        f.write(text)


def txt(pairs):
    return ''.join('#%s\n%s\n' % (jp, en) + DIV for jp, en in pairs)


class MatchTests(unittest.TestCase):
    def run_match(self, psp_records, skit_files, overrides=''):
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, 'work')
            text = os.path.join(tmp, 'text')
            for name, records in psp_records.items():
                write(os.path.join(work, 'skit', name + '.txt'), ''.join(r + '\n' + DIV for r in records))
            write(os.path.join(work, 'pointers.json'), json.dumps(
                {name: {'kind': 'skit', 'member': 0, 'records': len(r), 'addrs': []}
                 for name, r in psp_records.items()}))
            write(os.path.join(text, 'scenario', '06470.txt'), '')
            for name, pairs in skit_files.items():
                write(os.path.join(text, 'skits', name), txt(pairs))
            write(os.path.join(text, 'overrides.tsv'), overrides)
            with contextlib.redirect_stdout(io.StringIO()):
                psp_text.match(work, text, os.path.join(text, 'overrides.tsv'))
            return {name: [en for jp, en in psp_text.read_txt_pairs(os.path.join(work, 'skit_en', name + '.txt'))]
                    for name in psp_records}

    def test_short_line_takes_the_english_of_its_own_skit(self):
        # うん。 is translated differently in two PS2 skits; the corpus keeps
        # the first, the twin (PSP 00215 = PS2 00056) keeps its own wording
        got = self.run_match(
            {'00215': ['ただいま！', 'うん。']},
            {'00054_02.sced.txt': [('うん。', 'Yeah.')],
             '00056_02.sced.txt': [('ただいま！', "I'm home!"), ('うん。', 'Yep.')]})
        self.assertEqual(got['00215'], [["I'm home!"], ['Yep.']])

    def test_line_with_other_japanese_falls_back_to_the_corpus(self):
        got = self.run_match(
            {'00215': ['べつのせりふ']},
            {'00056_02.sced.txt': [('ただいま！', "I'm home!")],
             '00058_02.sced.txt': [('べつのせりふ', 'Another line.')]})
        self.assertEqual(got['00215'], [['Another line.']])

    def test_override_wins_over_the_synced_text(self):
        skits = {'00056_02.sced.txt': [('ただいま！', "I'm home!"), ('うん。', 'Yep.')]}
        got = self.run_match(
            {'00215': ['ただいま！', 'うん。'], '00217': ['うん。']},
            dict(skits, **{'00058_02.sced.txt': [('うん。', 'Yeah.')]}),
            '# note\nskit\t00215\tただいま！\tBack home!\tPSP wording\n'
            'skit\t*\tうん。\tMm-hm.\teverywhere\n')
        self.assertEqual(got['00215'], [['Back home!'], ['Mm-hm.']])
        self.assertEqual(got['00217'], [['Mm-hm.']])

    def test_bad_override_row_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'overrides.tsv')
            write(path, 'skit\t00215\tただいま！\n')
            with self.assertRaises(ValueError):
                psp_text.load_overrides(path)

    def test_supplement_skit_rows_are_single_full_length_lines(self):
        sup = psp_text.load_supplement(os.path.join(os.path.dirname(psp_text.__file__), 'psp_supplement.tsv'))
        self.assertTrue(sup['skit'])
        for key, english in sup['skit'].items():
            self.assertEqual(len(english), 1, key)  # a skit shows one line per record


class SyncTests(unittest.TestCase):
    def make_repo(self, tmp):
        write(os.path.join(tmp, 'Third pass Quality-Safe Output', '06470_10.sced.txt'), txt([('あ', 'A')]))
        write(os.path.join(tmp, 'third pass skits safe output', '00056_02.sced.txt'), txt([('い', 'I'), ('う', 'U')]))
        write(os.path.join(tmp, 'ps2', 'movies', 'subtitles', '00001.en.srt'), '1\n')
        write(os.path.join(tmp, 'ps2', 'PyTOD2', 'TBL.json'), '{}')
        write(os.path.join(tmp, 'ps2', 'PyTOD2', 'skit_speeds.json'), '{}')

    def snapshot(self, tmp):
        out = {}
        for base, _, files in os.walk(tmp):
            for f in files:
                p = os.path.join(base, f)
                out[os.path.relpath(p, tmp)] = open(p, 'rb').read()
        return out

    def test_sync_copies_then_reports_record_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_repo(tmp)
            first = sync.differences(tmp)
            self.assertEqual({(n, s) for _, n, s, _ in first},
                             {('06470_10.sced.txt', 'new'), ('00056_02.sced.txt', 'new'), ('00001.en.srt', 'new'),
                              ('TBL.json', 'new'), ('skit_speeds.json', 'new')})
            before = self.snapshot(tmp)
            sync.apply(first, tmp)
            after = self.snapshot(tmp)
            # nothing outside psp/text was written
            self.assertEqual({k: v for k, v in after.items() if not k.startswith(os.path.join('psp', 'text'))}, before)
            self.assertEqual(sync.differences(tmp), [])
            write(os.path.join(tmp, 'third pass skits safe output', '00056_02.sced.txt'),
                  txt([('い', 'I'), ('う', 'You')]))
            os.remove(os.path.join(tmp, 'Third pass Quality-Safe Output', '06470_10.sced.txt'))
            self.assertEqual(sorted((n, s, r) for _, n, s, r in sync.differences(tmp)),
                             [('00056_02.sced.txt', 'changed', 1), ('06470_10.sced.txt', 'removed', 0)])

    def test_line_endings_are_not_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_repo(tmp)
            sync.apply(sync.differences(tmp), tmp)
            write(os.path.join(tmp, 'third pass skits safe output', '00056_02.sced.txt'),
                  txt([('い', 'I'), ('う', 'U')]), newline='\r\n')
            self.assertEqual(sync.differences(tmp), [])

    def test_check_only_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_repo(tmp)
            with patch.object(sync, 'ROOT', tmp), patch.object(sync, 'TEXT', os.path.join(tmp, 'psp', 'text')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sync.main(['--check']), 1)
                self.assertFalse(os.path.exists(os.path.join(tmp, 'psp')))
                self.assertEqual(sync.main([]), 0)
                self.assertEqual(sync.main(['--check']), 0)


class SourceCheckTests(unittest.TestCase):
    def test_current_repository_passes(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            build_psp.check_sources(movies=True)
        self.assertIn(os.path.join('psp', 'text', 'skits'), out.getvalue())
        self.assertIn('fingerprint', out.getvalue())

    def test_missing_folder_is_named(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_psp, 'ROOT', tmp):
            with self.assertRaises(SystemExit) as stop:
                build_psp.check_sources()
        message = str(stop.exception)
        self.assertIn(os.path.join(tmp, 'psp', 'text', 'skits'), message)
        self.assertIn(os.path.join(tmp, 'psp', 'text', 'skit_speeds.json'), message)
        self.assertIn('git pull', message)

    def test_no_text_is_read_from_outside_psp(self):
        for what, rel, pattern, least, when in build_psp.SOURCES:
            if rel.endswith(('.txt', '.tsv', '.json', '.srt')) or pattern:
                self.assertTrue(rel.startswith('psp/'), rel)

    def test_old_speed_table_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_psp, 'ROOT', tmp):
            for what, rel, pattern, least, when in build_psp.SOURCES:
                path = os.path.join(tmp, *rel.split('/'))
                if pattern is None:
                    write(path, '{"00056_02.sced": [[58, 7, 30]]}' if rel.endswith('skit_speeds.json') else 'x')
                else:
                    for i in range(least):
                        write(os.path.join(path, '%05d.en.srt' % i if 'subtitles' in rel else '%05d.txt' % i), 'x')
            with self.assertRaises(SystemExit) as stop:
                build_psp.check_sources(movies=True)
        self.assertIn('no window column', str(stop.exception))


if __name__ == '__main__':
    unittest.main()
