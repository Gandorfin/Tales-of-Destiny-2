"""Run: python3 -B -m unittest discover -s ps2/menu -p 'test_enemy_names.py'

Synthetic enemy packs only, no game files needed."""
import os, struct, sys, unittest, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enemy_text as E
import lzss
import md1patch as P

def param_block(jp, tail=0x37):
    """A 24-byte enemy name field: TBL name, NUL padding, one data byte."""
    enc = P.encode(jp)
    return enc + b'\0' * (E.NAME_FIELD - 1 - len(enc)) + bytes([tail])

def end_member(*fields):
    body = b'ENd\0' + struct.pack('<IIII', 100, 2, 252, 1) + b'\x0a\x05' + b'\x00' * 30
    for f in fields:
        body += b'\x11\x00\x00\x00' + f + struct.pack('<I', 782)
    return lzss.pack(body, 3)

def pack(*members):
    return E.build_pak1(list(members))

class NameFields(unittest.TestCase):
    def setUp(self):
        self.names = {'オウルベア': 'Owlbear', 'デス': 'Death', 'デスナイト': 'Death Knight',
                      'ロックバブーン': 'Rock Baboon', 'ロック': 'Roc'}

    def test_finds_only_whole_fields(self):
        data = lzss.unpack(end_member(param_block('デスナイト'), param_block('ロックバブーン')))
        hits = E.find_name_fields(data, self.names)
        self.assertEqual([jp for _, jp in hits], ['デスナイト', 'ロックバブーン'])

    def test_patch_pack_writes_english_and_keeps_the_rest(self):
        raw = pack(b'HEAD' * 4, end_member(param_block('オウルベア', 0x08)), b'model' * 50,
                   end_member(param_block('デス', 0x33)))
        out, changed = E.patch_name_fields(raw, self.names)
        self.assertEqual(changed, 2)
        members = E.parse_pak1(out)
        self.assertEqual(members[0], b'HEAD' * 4)
        self.assertEqual(members[2], b'model' * 50)
        m1 = lzss.unpack(members[1])
        o = m1.find(b'Owlbear')
        self.assertGreater(o, 0)
        self.assertEqual(m1[o:o + E.NAME_FIELD], b'Owlbear' + b'\0' * 16 + b'\x08')   # data byte kept
        self.assertEqual(struct.unpack_from('<I', m1, o + E.NAME_FIELD)[0], 782)      # HP kept
        m3 = lzss.unpack(members[3])
        self.assertIn(b'Death' + b'\0' * 18 + b'\x33', m3)

    def test_idempotent_and_untouched_when_nothing_matches(self):
        raw = pack(b'x', end_member(param_block('オウルベア')))
        once, c1 = E.patch_name_fields(raw, self.names)
        twice, c2 = E.patch_name_fields(once, self.names)
        self.assertEqual((c1, c2), (1, 0))
        self.assertEqual(once, twice)
        other = pack(b'x', end_member(param_block('ゴーレム')))
        self.assertEqual(E.patch_name_fields(other, self.names), (other, 0))

    def test_too_long_english_is_rejected(self):
        raw = pack(b'x', end_member(param_block('オウルベア')))
        with self.assertRaises(ValueError):
            E.patch_name_fields(raw, {'オウルベア': 'A' * (E.NAME_FIELD - 1)})

class BuildCommand(unittest.TestCase):
    def test_build_names_patches_folder(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, '08670.pak1'), 'wb').write(pack(b'x', end_member(param_block('オウルベア'))))
            open(os.path.join(d, '08999.pak1'), 'wb').write(pack(b'x', b'not packed'))
            class A: folder = d; dry_run = False; no_backup = True
            names = {'オウルベア': 'Owlbear'}
            files, fields, errors = E.build_names(A, names)
            self.assertEqual((files, fields, errors), (1, 1, 0))
            m = lzss.unpack(E.parse_pak1(open(os.path.join(d, '08670.pak1'), 'rb').read())[1])
            self.assertIn(b'Owlbear', m)
            self.assertEqual(E.build_names(A, names), (0, 0, 0))

if __name__ == '__main__':
    unittest.main()
