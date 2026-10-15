"""Skit text comes from the PS2 twin skit, and the build refuses to run
without the files it needs from the rest of the repository."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import build_psp
import psp_text

DIV = psp_text.DIVIDER + '\n'


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


class TwinMatchTests(unittest.TestCase):
    def run_match(self, psp_records, ps2_files):
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, 'work')
            root = os.path.join(tmp, 'repo')
            for name, records in psp_records.items():
                write(os.path.join(work, 'skit', name + '.txt'), ''.join(r + '\n' + DIV for r in records))
            write(os.path.join(work, 'pointers.json'), json.dumps(
                {name: {'kind': 'skit', 'member': 0, 'records': len(r), 'addrs': []}
                 for name, r in psp_records.items()}))
            write(os.path.join(root, 'Third pass Quality-Safe Output', '06470.txt'), '')
            for name, pairs in ps2_files.items():
                write(os.path.join(root, 'third pass skits safe output', name),
                      ''.join('#%s\n%s\n' % (jp, en) + DIV for jp, en in pairs))
            with contextlib.redirect_stdout(io.StringIO()):
                psp_text.match(work, root)
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

    def test_supplement_skit_rows_are_single_full_length_lines(self):
        sup = psp_text.load_supplement(os.path.join(os.path.dirname(psp_text.__file__), 'psp_supplement.tsv'))
        self.assertTrue(sup['skit'])
        for key, english in sup['skit'].items():
            self.assertEqual(len(english), 1, key)  # a skit shows one line per record


class SourceCheckTests(unittest.TestCase):
    def test_current_repository_passes(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            build_psp.check_sources(movies=True)
        self.assertIn('third pass skits safe output', out.getvalue())
        self.assertIn('fingerprint', out.getvalue())

    def test_missing_folder_is_named(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_psp, 'ROOT', tmp):
            with self.assertRaises(SystemExit) as stop:
                build_psp.check_sources()
        message = str(stop.exception)
        self.assertIn(os.path.join(tmp, 'third pass skits safe output'), message)
        self.assertIn(os.path.join(tmp, 'ps2', 'PyTOD2', 'skit_speeds.json'), message)
        self.assertIn('git pull', message)

    def test_old_speed_table_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_psp, 'ROOT', tmp):
            for what, rel, pattern, least, when in build_psp.SOURCES:
                path = os.path.join(tmp, *rel.split('/'))
                if pattern is None:
                    write(path, '{"00056_02.sced": [[58, 7, 30]]}' if rel.endswith('skit_speeds.json') else 'x')
                else:
                    for i in range(least):
                        write(os.path.join(path, '%05d_02.sced.txt' % i if 'Output' in rel or 'output' in rel
                                           else '%05d.en.srt' % i), 'x')
            with self.assertRaises(SystemExit) as stop:
                build_psp.check_sources(movies=True)
        self.assertIn('no window column', str(stop.exception))


if __name__ == '__main__':
    unittest.main()
