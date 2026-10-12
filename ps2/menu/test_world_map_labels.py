"""Check the known map layouts without requiring proprietary game files."""
import struct
import unittest
import md1text as M
import md1patch as P
import world_map_labels as W


def fixture(name, originals=None):
    """A file with every label of `name` in its own slot and the donors in
    place. originals: {old offset: text} to start from something else."""
    originals = originals or {}
    data = bytearray(0x101000)
    for label in W.LABELS[name]:
        data[label.member:label.member + 4] = b'SCED'
        text_start = label.member + 0x2000
        struct.pack_into('<I', data, label.member + 8, text_start - label.member)
        data[label.instruction] = 0xF8
        struct.pack_into('<H', data, label.instruction + 1, label.old - text_start)
        text = P.encode(originals.get(label.old, label.japanese)) + b'\0'
        data[label.old:label.old + len(text)] = text
        donor = P.encode(label.donor) + b'\0'
        data[label.target - len(donor):label.target] = donor
    return bytes(data)


class WorldMapLabels(unittest.TestCase):
    def test_relocation_changes_only_reference_and_spare_space(self):
        for name, labels in W.LABELS.items():
            starts = [{}] + [{label.old: former} for label in labels for former in label.former]
            for originals in starts:
                with self.subTest(name=name, originals=originals):
                    self.check_relocation(name, labels, originals)

    def check_relocation(self, name, labels, originals):
        source = fixture(name, originals)
        data = bytearray(source)
        self.assertEqual(W.apply(data, name), (len(labels), 0))
        self.assertEqual(len(data), len(source))
        allowed = set()
        for label in labels:
            self.assertEqual(M.decode_at(data, label.target)[0], label.text)
            allowed.update(range(label.instruction + 1, label.instruction + 3))
            allowed.update(range(label.target, label.target + len(label.text) + 1))
        self.assertTrue(all(a == b or i in allowed
                            for i, (a, b) in enumerate(zip(source, data))))
        result = bytes(data)
        self.assertEqual(W.apply(data, name), (0, len(labels)))
        self.assertEqual(bytes(data), result)

    def test_rejects_changed_pointer_and_occupied_padding(self):
        for name, labels in W.LABELS.items():
            source = fixture(name)
            for label in labels:
                for at in (label.instruction + 1, label.target):
                    data = bytearray(source)
                    data[at] ^= 0x80
                    before = bytes(data)
                    with self.assertRaises(ValueError):
                        W.apply(data, name)
                    self.assertEqual(bytes(data), before)

    def test_cleared_padding_is_written_again(self):
        # a later rewrite of the donor zero-fills its slot, the label with it
        for name, labels in W.LABELS.items():
            data = bytearray(fixture(name))
            W.apply(data, name)
            good = bytes(data)
            label = labels[-1]
            data[label.target:label.target + len(label.text) + 1] = bytes(len(label.text) + 1)
            self.assertEqual(W.apply(data, name), (1, len(labels) - 1))
            self.assertEqual(bytes(data), good)

    def test_labels_fit_and_do_not_collide(self):
        for name, labels in W.LABELS.items():
            spans = []
            for label in labels:
                self.assertGreater(len(P.encode(label.text)), len(P.encode(label.japanese)),
                                   'a label that fits its slot needs no relocation')
                spans.append((label.target, label.target + len(P.encode(label.text)) + 1))
            spans.sort()
            for (_, end), (start, _) in zip(spans, spans[1:]):
                self.assertLessEqual(end, start)


if __name__ == '__main__':
    unittest.main()
