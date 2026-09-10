"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_shop_prompt.py'

Byte-length rules in menu_translations.csv that the game depends on."""
import csv, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md1patch as P

CSV = os.path.join(HERE, "menu_translations.csv")


def rows(file_name):
    with open(CSV, encoding="utf-8") as f:
        return {int(r["offset"], 16): r for r in csv.DictReader(f) if r["file"] == file_name}


class ShopSellPrompt(unittest.TestCase):
    """06803.md1 reaches the sell confirmation by walking the NUL-separated
    strings of the record at 0x89E8, so every string before the prompt must
    keep the byte length of the Japanese (a shorter one adds an empty string
    to the walk and the game lands on the stray "iH*" instead)."""

    def test_record_strings_keep_their_length(self):
        r = rows("06803.md1")
        for off in (0x89E8, 0x89F0):
            self.assertIn(off, r)
            jp, en = P.encode(r[off]["japanese"]), P.encode(r[off]["english"])
            self.assertEqual(len(en), len(jp), "0x%X %r" % (off, r[off]["english"]))


class ArteExtensionBanners(unittest.TestCase):
    """The fourteen extension names in 08055.md1 are inline script literals:
    exactly eight bytes, padded with spaces, never longer."""

    def test_exactly_eight_bytes(self):
        r = {o: x for o, x in rows("08055.md1").items() if 0x4A7BE <= o <= 0x4B187}
        self.assertEqual(len(r), 14)
        for off, x in r.items():
            self.assertEqual(len(x["japanese"]), 4, hex(off))          # four kanji = eight bytes
            self.assertEqual(len(P.encode(x["english"])), 8, "0x%X %r" % (off, x["english"]))


if __name__ == "__main__":
    unittest.main()
