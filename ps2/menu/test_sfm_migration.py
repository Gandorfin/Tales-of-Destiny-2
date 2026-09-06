"""Regression test for already-patched Quiz Book terminology changes."""
import csv
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sfm_text as S


def sfm_with_string(rel, text):
    code_start = 0x20
    code_end = 0x26
    data_start = 0x28
    data_len = rel + 0x20
    total = data_start + data_len
    data = bytearray(total)
    S.HDR.pack_into(
        data, 0, b'SFM_', 0x3FC, total, code_end,
        data_len, code_start, data_start, 0
    )
    data[code_start:code_end] = b'\x03\x00' + struct.pack('<L', rel)
    encoded = text.encode('ascii') + b'\0'
    data[data_start + rel:data_start + rel + len(encoded)] = encoded
    return bytes(data)


class FormerTranslationMigration(unittest.TestCase):
    def test_kronos_is_migrated_to_miktran_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            module = os.path.join(folder, '06189.sfm')
            with open(module, 'wb') as fh:
                fh.write(sfm_with_string(0x4E91, 'Kronos'))
            table = os.path.join(folder, 'translations.csv')
            with open(table, 'w', encoding='utf-8', newline='') as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=['file', 'offset', 'budget', 'pinned',
                                'japanese', 'english']
                )
                writer.writeheader()
                writer.writerow({
                    'file': '06189.sfm',
                    'offset': '0x4E91',
                    'budget': '10',
                    'pinned': '',
                    'japanese': 'ミクトラン',
                    'english': 'Miktran',
                })

            class Args:
                csv = table
                dry_run = False
                no_backup = True

            Args.folder = folder
            S.cmd_build(Args)
            _raw, _packed, data = S.read_module(module)
            self.assertEqual(S.SFM(data).strings()[0x4E91]['text'], 'Miktran')
            first = data
            S.cmd_build(Args)
            _raw, _packed, second = S.read_module(module)
            self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
