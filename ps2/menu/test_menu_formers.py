"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_menu_formers.py'

A folder patched by an older release holds older English. The patcher must
take it as a starting point, or the file stays at the old text for good."""
import csv, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md1patch as P, md1text as M, pak3


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
        with open(os.path.join(HERE, 'menu_translations.csv'), encoding='utf-8', newline='') as f:
            current = {(r['file'], int(r['offset'], 16)): r for r in csv.DictReader(f)}
        formers = pak3.load_formers()
        self.assertGreater(len(formers), 100)
        for key, texts in formers.items():
            self.assertIn(key, current)
            self.assertNotIn(current[key]['english'], texts)

    def test_wordings_this_table_replaced_are_known(self):
        formers = pak3.load_formers()
        self.assertIn('Egg of God', formers[('09032.pak0', 0x1001BD)])
        self.assertIn('Western Mine - NW Exit', formers[('09032.pak0', 0x1000D9)])
        self.assertIn('One moment.', formers[('06799.md1', 0x6B84)])
        self.assertIn('  Buy', formers[('06803.md1', 0x89E8)])


if __name__ == '__main__':
    unittest.main()
