"""Run: python -B -m unittest discover -s "psp/jazz tools" -p test_psp_sced.py"""
import struct
import unittest

import psp_sced as sc
import psp_text as pt


def script(code, text=b'\0Old\0'):
    return b'SCED' + struct.pack('<II', 12, 12 + len(code)) + code + text


class ScedSafetyTests(unittest.TestCase):
    def test_real_pointer(self):
        d = script(bytes.fromhex('f8 01 00 c0 f1'))
        self.assertEqual(pt.sced_pointers(d)[1], [(13, 1)])

    def test_fake_pointer_in_each_operand_class(self):
        # F8 01 00 looks like a pointer to "Old", but starts inside an operand.
        prefixes = ['f2', 'f3', 'f4', 'f5', '90', 'a0', 'b0',
                    '34', '38', 'e0', 'f6 01 34']
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                code=bytes.fromhex(prefix+' f8 01 00 80 80 f1')
                # Padding allows every width to end cleanly; no raw scan fallback.
                try:
                    ins=list(sc.instructions(script(code)))
                except ValueError:
                    code+=b'\x80'
                    ins=list(sc.instructions(script(code)))
                false_at=12+len(bytes.fromhex(prefix))+1
                self.assertNotIn(false_at,sc.text_operands(script(code)))
                self.assertNotIn(false_at,dict(pt.sced_pointers(script(code))[1]))

    def test_real_pointer_after_f8_constant_not_skipped(self):
        d=script(bytes.fromhex('90 f8 f8 01 00 c0 f1'))
        self.assertEqual(pt.sced_pointers(d)[1],[(15,1)])

    def test_elrane_exact_branch_and_progress_increment(self):
        # Exact failing sequence from SCED 06524: the branch operand F8 33
        # followed by variable 24 1E used to create a false text offset 2433.
        code=bytes.fromhex('24 20 c0 f3 f8 33 24 1e c1 c0 f8 01 00 c0 f1')
        d=script(code,b'\0Old\0'+b'\0'*(0x2433-5)+b'False hit\0')
        self.assertEqual(pt.sced_pointers(d)[1],[(23,1)])
        with self.assertRaisesRegex(ValueError,'re-extract'):
            pt.insert_sced(d,[['Wrong'],['New']],[17,23])
        new,_,_=pt.insert_sced(d,[['New']],[23])
        self.assertEqual(new[12:22],code[:10])

    def test_constant_widths_and_fe(self):
        d=script(bytes.fromhex('80 90 ff a0 ff ff b0 ff ff ff ff fe f1'))
        self.assertEqual([n for _,_,n in sc.instructions(d)],[1,2,3,5,1,1])

    def test_argument_binding_width(self):
        d=script(bytes.fromhex('f6 03 24 20 28 f8 01 fe f8 01 00 f1'))
        self.assertEqual(next(sc.instructions(d)),(12,0xf6,8))
        self.assertEqual(sc.text_operands(d),{21})

    def test_legacy_metadata_rejected_even_if_text_target_valid(self):
        d=script(bytes.fromhex('f3 f8 01 00 80 f1'))
        with self.assertRaisesRegex(ValueError,'re-extract'):
            pt.insert_sced(d,[['New']],[14])
        with self.assertRaisesRegex(ValueError,'re-extract'):
            pt.extract_sced(d,[14])

    def test_append_preserves_code(self):
        d=script(bytes.fromhex('f8 01 00 c0 f1'))
        new,mode,_=pt.insert_sced(d,[['New text']],[13])
        self.assertEqual(mode,'append')
        sc.validate_code_changes(d,new)
        self.assertEqual(pt.extract_sced(new,[13])[0],['New text'])

    def test_rebuild_preserves_code(self):
        d=script(bytes.fromhex('f8 01 00 c0 f1'),b'\0Old\0'+b'\0'*65525)
        new,mode,_=pt.insert_sced(d,[['Longer replacement']],[13])
        self.assertEqual(mode,'rebuild')
        sc.validate_code_changes(d,new)
        self.assertEqual(pt.extract_sced(new,[13])[0],['Longer replacement'])

    def test_code_corruption_detected(self):
        d=script(bytes.fromhex('f3 f8 01 00 80 f1'))
        bad=bytearray(d)
        bad[14:16]=b'\x02\x00'
        with self.assertRaisesRegex(ValueError,'non-text bytecode'):
            sc.validate_code_changes(d,bad)

    def test_truncated_and_unknown_fail_closed(self):
        for code in ('f8 01','90','a0 01','b0 01 02 03','f6 01','f7','ff'):
            with self.subTest(code=code),self.assertRaises(ValueError):
                list(sc.instructions(script(bytes.fromhex(code))))


if __name__ == '__main__':
    unittest.main()
