"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_shop_prompt.py'

The shop's sell confirmation, and the byte-length rule of the arte
extension banners in menu_translations.csv."""
import csv, os, struct, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import md1patch as P
import shop_prompt as S

CSV = os.path.join(HERE, "menu_translations.csv")


def rows(file_name):
    with open(CSV, encoding="utf-8") as f:
        return {int(r["offset"], 16): r for r in csv.DictReader(f) if r["file"] == file_name}


class ShopSellPrompt(unittest.TestCase):
    """The sell confirmation of 06803.md1 showed "iH*": the 2008 patch wrote
    the address of its English prompt over the start of the Japanese prompt
    instead of into the pointer. shop_prompt.apply makes the pointer follow."""

    def module(self):
        d = bytearray(S.PROMPT + len(S.TEXT) + 16)
        struct.pack_into("<L", d, S.POINTER, S.BASE + S.STRAY)
        struct.pack_into("<L", d, S.STRAY, S.BASE + S.PROMPT)
        d[S.PROMPT:S.PROMPT + len(S.TEXT)] = S.TEXT
        return d

    def test_the_stray_address_reads_as_the_text_the_game_showed(self):
        self.assertEqual(bytes(self.module()[S.STRAY:S.STRAY + 4]), b"iH*\0")

    def test_pointer_is_repaired_once(self):
        d = self.module()
        before = bytes(d)
        self.assertEqual(S.apply(d), (1, 0))
        self.assertEqual(struct.unpack_from("<L", d, S.POINTER)[0], S.BASE + S.PROMPT)
        self.assertEqual([i for i in range(len(d)) if d[i] != before[i]],
                         list(range(S.POINTER, S.POINTER + 2)))     # 0x4518 -> 0x4869
        after = bytes(d)
        self.assertEqual(S.apply(d), (0, 1))
        self.assertEqual(bytes(d), after)

    def test_unknown_layouts_are_refused_untouched(self):
        for at in (S.POINTER, S.STRAY, S.PROMPT + 2):
            d = self.module()
            d[at] ^= 0x40
            before = bytes(d)
            with self.assertRaises(ValueError):
                S.apply(d)
            self.assertEqual(bytes(d), before)


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
