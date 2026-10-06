"""Check the known map layouts without requiring proprietary game files."""
import struct
import unittest
import md1text as M
import md1patch as P
import world_map_labels as W


def fixture(name, original='Laguna'):
    old, instruction, member, target = W.LABELS[name]
    data = bytearray(0x101000)
    data[member:member + 4] = b'SCED'
    text_start = member + 0x2000
    struct.pack_into('<I', data, member + 8, text_start - member)
    data[instruction] = 0xF8
    struct.pack_into('<H', data, instruction + 1, old - text_start)
    label = P.encode(original) + b'\0'
    data[old:old + len(label)] = label
    donor = P.encode(W.DONOR) + b'\0'
    data[target - len(donor):target] = donor
    return bytes(data)


class WorldMapLabels(unittest.TestCase):
    def test_relocation_changes_only_reference_and_spare_space(self):
        for name, (_, instruction, _, target) in W.LABELS.items():
            for original in ('ラグナ遺跡', 'Laguna'):
                with self.subTest(name=name, original=original):
                    self.check_relocation(name, instruction, target, original)

    def check_relocation(self, name, instruction, target, original):
        source = fixture(name, original)
        data = bytearray(source)
        self.assertEqual(W.apply(data, name), (1, 0))
        self.assertEqual(len(data), len(source))
        self.assertEqual(M.decode_at(data, target)[0], W.TEXT)
        allowed = set(range(instruction + 1, instruction + 3))
        allowed.update(range(target, target + len(W.TEXT) + 1))
        self.assertTrue(all(a == b or i in allowed
                            for i, (a, b) in enumerate(zip(source, data))))
        result = bytes(data)
        self.assertEqual(W.apply(data, name), (0, 1))
        self.assertEqual(bytes(data), result)

    def test_rejects_changed_pointer_and_occupied_padding(self):
        for name, (_, instruction, _, target) in W.LABELS.items():
            source = fixture(name)
            for at in (instruction + 1, target):
                data = bytearray(source)
                data[at] ^= 0x80
                before = bytes(data)
                with self.assertRaises(ValueError):
                    W.apply(data, name)
                self.assertEqual(bytes(data), before)


if __name__ == '__main__':
    unittest.main()
