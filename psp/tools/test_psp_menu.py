"""Run: python -B -m unittest discover -s psp/tools -p test_psp_menu.py -v

Synthetic BOOT bytes only, no game image needed."""
import unittest

import psp_menu
import psp_pool
import psp_text


class FullWidthSpaceTests(unittest.TestCase):
    """Retail menu strings store U+3000 as 0x9940; the TBL encodes it as 0xE499.
    Keys with a space (the shop names) never matched before 0.3.2."""

    def test_key_uses_the_retail_space(self):
        keys = psp_menu.encode_keys('雑貨屋　当たり棒')
        self.assertIn(b'\x99\x40', keys[0])
        self.assertIn(b'\xe4\x99', keys[1])
        self.assertEqual(psp_menu.encode_keys('リファイン'), [psp_text.encode_line('リファイン')])

    def test_in_place_patch_finds_the_retail_form(self):
        jp = psp_menu.encode_keys('武器屋　一騎')[0]
        boot = b'\0' * 8 + jp + b'\0' * 8
        out, st = psp_menu.patch_menu(boot, [('武器屋　一騎', 'Arms')])
        self.assertEqual(st['patched'], 1)
        self.assertIn(b'Arms\0', out)
        self.assertNotIn(jp, out)

    def test_pool_gets_the_retail_form(self):
        seen = []
        orig = psp_pool.add_pool_and_relocate
        psp_pool.add_pool_and_relocate = lambda boot, items: (seen.extend(items), (boot, {}))[1]
        try:
            import tempfile, os
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, 'm.tsv')
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('武器屋　一騎\tWeapon Shop ONE RIDER\t10\t21\treuse\n')
                psp_pool.relocate_menu(b'', path)
        finally:
            psp_pool.add_pool_and_relocate = orig
        self.assertEqual(seen[0][0], psp_menu.encode_keys('武器屋　一騎')[0])
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()


class FullWidthToAsciiTests(unittest.TestCase):
    def enc(self, text):
        import psp_text
        return psp_text.encode_line(text)

    def test_label_becomes_ascii_in_place(self):
        label = self.enc('ＮＥＷ') + b'\x99\x40' + self.enc('ＧＡＭＥ')
        mixed = self.enc('ＨＰ回復')
        boot = b'\0' + label + b'\0' + mixed + b'\0'
        out, n = psp_menu.fullwidth_to_ascii(boot, areas=((0, len(boot)),))
        self.assertEqual(n, 1)
        self.assertEqual(out[1:1 + len(label)], b'NEW GAME' + bytes(len(label) - 8))
        self.assertEqual(out[2 + len(label):], mixed + b'\0')       # mixed text untouched
        self.assertEqual(len(out), len(boot))

    def test_long_runs_are_left_alone(self):
        alphabet = self.enc('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ')
        boot = b'\0' + alphabet + b'\0'
        self.assertEqual(psp_menu.fullwidth_to_ascii(boot, areas=((0, len(boot)),)), (boot, 0))


class StringStartTests(unittest.TestCase):
    """The NUL bytes of a control code argument are not string ends: the
    fragment やめる after <button:00000036> used to be patched in place,
    after which the whole shop confirmation never matched."""

    def test_fragment_after_a_button_code_is_not_a_string(self):
        rec = psp_menu.encode_keys('これでいいですか？<button:00000036>やめる')[0]
        boot = b'\0' * 4 + rec + b'\0' * 4
        out, st = psp_menu.patch_menu(boot, [('やめる', 'Stop')])
        self.assertEqual(out, boot)
        self.assertEqual(st['not_found'], 1)

    def test_whole_record_first(self):
        rec_jp = 'これでいいですか？<button:00000036>やめる'
        boot = b'\0' * 4 + psp_menu.encode_keys(rec_jp)[0] + b'\0' * 4
        out, st = psp_menu.patch_menu(boot, [('やめる', 'Stop'), (rec_jp, 'Okay?<button:00000036>No')])
        self.assertIn(psp_menu.encode_en('Okay?<button:00000036>No') + b'\0', out)
        self.assertEqual(st['patched'], 1)

    def test_code_at_the_end_of_the_previous_string(self):
        prev = psp_menu.encode_keys('<button:00000005>')[0]      # argument low byte 05 is a code value
        boot = b'\0' + prev + b'\0' + psp_menu.encode_keys('戻る')[0] + b'\0'
        out, st = psp_menu.patch_menu(boot, [('戻る', 'Back')])
        self.assertEqual(st['patched'], 1)


class AddressedTests(unittest.TestCase):
    def test_entries_fit_and_keep_formats(self):
        import re
        for fo, jp, en in psp_menu.SJIS_ADDRESSED:
            self.assertLessEqual(len(en.encode('ascii')), len(jp.encode('cp932')), hex(fo))
            self.assertEqual(re.findall(r'%[0-9]*[sdux]', jp), re.findall(r'%[0-9]*[sdux]', en), hex(fo))
        for fo, jp, en in psp_menu.ADDRESSED:
            self.assertLessEqual(len(psp_menu.encode_en(en)), len(psp_menu.encode_keys(jp)[0]), hex(fo))

    def test_patch_in_place_only_when_the_retail_bytes_match(self):
        import collections
        fo, jp, en = psp_menu.SJIS_ADDRESSED[0]
        b = bytearray(fo + 64)
        b[fo:fo + len(jp.encode('cp932'))] = jp.encode('cp932')
        st = collections.Counter()
        psp_menu.patch_addressed(b, st)
        self.assertEqual(bytes(b[fo:fo + len(en)]), en.encode('ascii'))
        self.assertEqual(st['addressed'], 1)


class PinnedCodeTests(unittest.TestCase):
    """The dungeon exit banner hung the game when its <0A:..> place name code
    moved (PSP 0.3.3/0.3.4, Atamoni Ovum anchor)."""

    def test_moved_place_code_is_refused(self):
        jp = '<button:00000035> <0A:00000000>を出る'
        self.assertTrue(psp_menu.pinned_code_moved(jp, '<button:00000035> Leave <0A:00000000>'))
        self.assertTrue(psp_menu.pinned_code_moved(jp, '<button:00000035> Leave <0A:00000000> '))
        self.assertFalse(psp_menu.pinned_code_moved(jp, '<button:00000035> <0A:00000000>: Exit'))

    def test_other_codes_may_move(self):
        self.assertFalse(psp_menu.pinned_code_moved('疾風の<Kyle>', '<Kyle> of the Gale'))

    def test_table_keeps_every_place_code(self):
        rows = [(jp, en) for jp, en in psp_menu.load_table() if '<0A:' in jp]
        self.assertTrue(rows)
        for jp, en in rows:
            self.assertFalse(psp_menu.pinned_code_moved(jp, en), jp)


class InlineBannerTests(unittest.TestCase):
    """Added Arte banners are inline names in BOOT.BIN battle scripts
    (opcode 0A, argument byte, name, NUL); the bytecode goes on after them."""

    def test_names_keep_the_byte_length(self):
        for fo, jp, en in psp_menu.INLINE_BANNERS:
            self.assertEqual(len(psp_menu.encode_en(en)), len(psp_menu.encode_keys(jp)[0]), jp)

    def test_patch_in_place_without_padding(self):
        import collections
        fo, jp, en = psp_menu.INLINE_BANNERS[0]
        jb = psp_menu.encode_keys(jp)[0]
        b = bytearray(b'\x11' * (fo + 64))
        b[fo - 2:fo] = b'\x0a\x00'
        b[fo:fo + len(jb) + 1] = jb + b'\x00'
        after = bytes(b[fo + len(jb):])
        st = collections.Counter()
        psp_menu.patch_addressed(b, st)
        self.assertEqual(bytes(b[fo:fo + len(jb)]), en.encode('ascii'))
        self.assertEqual(bytes(b[fo + len(jb):]), after)
        self.assertEqual(st['banner'], 1)

    def test_other_bytes_are_left_alone(self):
        import collections
        fo, jp, en = psp_menu.INLINE_BANNERS[0]
        b = bytearray(fo + 64)
        st = collections.Counter()
        psp_menu.patch_addressed(b, st)
        self.assertEqual(bytes(b), bytes(fo + 64))
        self.assertEqual(st['banner'], 0)

    def test_every_inline_name_of_the_retail_scan_is_listed(self):
        # the 14 banner names found by scanning retail BOOT.BIN for
        # 0A, any argument byte, 2..14 two-byte codes, NUL
        self.assertEqual(len(psp_menu.INLINE_BANNERS), 14)
        self.assertEqual(len({fo for fo, _, _ in psp_menu.INLINE_BANNERS}), 14)
