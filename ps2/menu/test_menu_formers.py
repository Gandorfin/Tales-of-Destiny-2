"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_menu_formers.py'

A folder patched by an older release holds older English. The patcher must
take it as a starting point, or the file stays at the old text for good."""
import contextlib, csv, io, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md1patch as P, md1text as M, pak3
import update_former_translations as U


def module(text, room=40):
    d = bytearray(0x100)
    enc = P.encode(text)
    d[0x20:0x20 + len(enc)] = enc
    d[0x20 + room] = 0x41                 # the next string
    return bytes(d)


class EarlierWording(unittest.TestCase):
    RECS = [(0x20, '東：リーネ方面', 'E: toward Lienea')]

    def test_earlier_english_is_replaced(self):
        former = {0x20: {'E: toward Lien'}}
        out, patched, done, errs = pak3.apply_records(module('E: toward Lien'), self.RECS, former)
        self.assertEqual((patched, done, errs), (1, 0, []))
        self.assertEqual(M.decode_at(out, 0x20)[0], 'E: toward Lienea')
        self.assertEqual(pak3.apply_records(out, self.RECS, former)[1:], (0, 1, []))

    def test_unknown_text_is_still_refused(self):
        source = module('E: somewhere')
        out, patched, done, errs = pak3.apply_records(source, self.RECS, {0x20: {'E: toward Lien'}})
        self.assertEqual((out, patched), (source, 0))
        self.assertEqual(len(errs), 1)

    def test_a_module_in_earlier_wording_is_still_identified(self):
        groups = {'08055.md1': self.RECS}
        source = module('E: toward Lien')
        self.assertIsNone(pak3.identify(source, groups))
        self.assertEqual(pak3.identify(source, groups, {('08055.md1', 0x20): {'E: toward Lien'}}), '08055.md1')


class Table(unittest.TestCase):
    def test_every_earlier_wording_belongs_to_a_current_record_and_differs(self):
        with open(os.path.join(HERE, 'menu_translations.csv'), encoding='utf-8', newline=None) as f:
            current = {(r['file'], int(r['offset'], 16)): r for r in csv.DictReader(f)}
        formers = pak3.load_formers()
        self.assertTrue(formers)
        for key, texts in formers.items():
            self.assertIn(key, current)
            self.assertNotIn(current[key]['english'], texts)

    def test_wordings_this_table_replaced_are_known(self):
        formers = pak3.load_formers()
        self.assertIn('Egg of God', formers[('09032.pak0', 0x1001BD)])
        self.assertIn('Western Mine - NW Exit', formers[('09032.pak0', 0x1000D9)])
        self.assertIn('One moment.', formers[('06799.md1', 0x6B84)])
        self.assertIn('  Buy', formers[('06803.md1', 0x89E8)])


class CSVNewlines(unittest.TestCase):
    def test_crlf_alias_matches_decoded_multiline_game_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'former.csv')
            with open(path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, lineterminator='\r\n')
                writer.writerow(('file', 'offset', 'english'))
                writer.writerow(('08055.md1', '0x20', 'Old\r\nprompt'))
            aliases = pak3.load_formers(path)
            self.assertEqual(aliases[('08055.md1', 0x20)], {'Old\nprompt'})
            records = [(0x20, '元の文章', 'New\nprompt')]
            out, patched, done, errs = pak3.apply_records(
                module('Old\nprompt'), records, {0x20: aliases[('08055.md1', 0x20)]})
            self.assertEqual((patched, done, errs), (1, 0, []))
            self.assertEqual(M.decode_at(out, 0x20)[0], 'New\nprompt')

    def test_generator_filters_equivalent_current_and_japanese_wordings(self):
        def table(english, newline):
            stream = io.StringIO(newline='')
            writer = csv.writer(stream, lineterminator=newline)
            writer.writerow(('file', 'offset', 'japanese', 'english'))
            writer.writerow(('08055.md1', '0x20', '元の\n文章', english))
            return stream.getvalue()

        history = {
            'current': table('New\nprompt', '\n'),
            'old_lf': table('Old\nprompt', '\n'),
            'old_crlf': table('Old\r\nprompt', '\r\n'),
            'japanese': table('元の\r\n文章', '\r\n'),
        }

        def git(*args):
            if args[0] == 'log':
                return b'current\nold_lf\nold_crlf\njapanese\n'
            self.assertEqual(args[0], 'show')
            return history[args[1].split(':', 1)[0]].encode('utf-8')

        with tempfile.TemporaryDirectory() as folder:
            current = os.path.join(folder, 'menu_translations.csv')
            output = os.path.join(folder, 'former.csv')
            with open(current, 'w', encoding='utf-8', newline='') as f:
                f.write(table('New\r\nprompt', '\r\n'))
            with mock.patch.object(U, 'HERE', folder), mock.patch.object(U, 'OUT', output), \
                    mock.patch.object(U, 'git', side_effect=git), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(U.main(), 0)
                with open(output, 'rb') as f:
                    first = f.read()
                self.assertEqual(U.main(), 0)
                with open(output, 'rb') as f:
                    self.assertEqual(f.read(), first)
            self.assertEqual(pak3.load_formers(output), {('08055.md1', 0x20): {'Old\nprompt'}})


if __name__ == '__main__':
    unittest.main()
