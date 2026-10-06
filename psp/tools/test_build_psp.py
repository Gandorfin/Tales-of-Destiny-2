"""Exercise both PSP builders with synthetic assets; no game image required."""
import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

_IMPORT_PATH = list(sys.path)
import build_psp
import psp_lowercase as lc
import psp_font


def collaborator_builder():
    path = Path(__file__).resolve().parents[1] / 'jazz tools' / 'build_psp.py'
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location('collaborator_build_psp', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDERS = [build_psp]
collaborator = collaborator_builder()
if collaborator is not None:
    BUILDERS.append(collaborator)
sys.path[:] = _IMPORT_PATH


def retail_boot():
    boot = bytearray(lc.U8_TABLE + 0x100)
    struct.pack_into('<H', boot, 0x2c, 3)
    for i in range(26):
        boot[lc.U8_TABLE + 0x41 + i] = 0x17 + i
        boot[lc.U8_TABLE + 0x61 + i] = 0x17 + i
    boot[lc.U8_TABLE + 0x27] = lc.APOSTROPHE_SLOT
    for offset in lc.FONT_SELECT:
        boot[offset] = lc.FONT_SELECT_FROM
    struct.pack_into('<I', boot, lc.BOLD_LUI, lc.BOLD_LUI_WORD)
    struct.pack_into('<I', boot, lc.BOLD_ADDIU, lc.BOLD_ADDIU_WORD)
    return bytes(boot)


class BuildFontChoiceTests(unittest.TestCase):
    def run_build(self, builder, enabled=None, verify=True):
        original = retail_boot()
        font = psp_font.reswizzle(bytes(lc.W * psp_font.H))
        captured = {}
        with tempfile.TemporaryDirectory() as work, contextlib.ExitStack() as stack:
            def mock(target, **kwargs):
                return stack.enter_context(patch(target, **kwargs))

            def extract(iso, path, dest):
                Path(dest).write_bytes(original if path.endswith('BOOT.BIN') else b'archive')

            def pool(data):
                b = bytearray(data)
                offset = len(b)
                b += b'pool'
                struct.pack_into('<H', b, 0x2c, 4)
                struct.pack_into('<8I', b, 0x34 + 3 * 32,
                                 1, offset, lc.POOL_VADDR, lc.POOL_VADDR, 4, 4, 4, 0x40)
                return bytes(b), {}

            def build(boot, fpb, text, new_fpb, new_boot, extra):
                captured['boot'] = Path(boot).read_bytes()
                captured['extra'] = dict(extra)
                shutil.copyfile(boot, new_boot)
                shutil.copyfile(fpb, new_fpb)

            mock(f'{builder.__name__}.psp_iso.extract', side_effect=extract)
            mock(f'{builder.__name__}.psp_names.patch_names', side_effect=lambda b: (b, 6))
            menu = mock(f'{builder.__name__}.psp_menu.patch_menu', side_effect=lambda b: (b, {}))
            mock(f'{builder.__name__}.psp_pool.relocate_menu', side_effect=pool)
            mock(f'{builder.__name__}.psp_text.extract')
            match = mock(f'{builder.__name__}.psp_text.match')
            mock(f'{builder.__name__}.psp_fpb.read_member', return_value=(font, 'compressed'))
            monsters = mock(f'{builder.__name__}.psp_monsters.build_changed_members',
                            return_value=({8331: b'English monster names'}, {}))
            mock(f'{builder.__name__}.psp_text.build', side_effect=build)
            mock(f'{builder.__name__}.psp_text.verify', return_value=verify)
            replace = mock(f'{builder.__name__}.psp_iso.replace')
            if hasattr(builder, 'psp_title'):
                mock(f'{builder.__name__}.psp_title.build_member', return_value=(b'title credit', None))
            kwargs = {'keep': work}
            if enabled is not None:
                kwargs['lowercase_font'] = enabled
            if hasattr(builder, 'psp_title'):
                kwargs['version'] = '0.2.0'
            with contextlib.redirect_stdout(io.StringIO()):
                if verify:
                    builder.main('clean.iso', 'english.iso', **kwargs)
                else:
                    with self.assertRaisesRegex(SystemExit, 'verification failed'):
                        builder.main('clean.iso', 'english.iso', **kwargs)
            menu.assert_called_once()
            match.assert_called_once()
            monsters.assert_called_once()
            if verify:
                replace.assert_called_once()
                self.assertEqual([p for p, _ in replace.call_args.args[2]], [
                    '/PSP_GAME/USRDIR/file.fpb', '/PSP_GAME/SYSDIR/BOOT.BIN',
                    '/PSP_GAME/SYSDIR/EBOOT.BIN'])
            else:
                replace.assert_not_called()
        self.assertEqual(captured['extra'][8331], b'English monster names')
        if hasattr(builder, 'psp_title'):
            self.assertEqual(captured['extra'][2], b'title credit')
        return original, font, captured

    def test_off_preserves_retail_font_mapping_and_renderer(self):
        for builder in BUILDERS:
            with self.subTest(builder=builder.__name__):
                original, _, built = self.run_build(builder, False)
                boot = built['boot']
                self.assertNotIn(0, built['extra'])
                self.assertEqual(boot[lc.U8_TABLE:lc.U8_TABLE + 0x100],
                                 original[lc.U8_TABLE:lc.U8_TABLE + 0x100])
                for offset in lc.FONT_SELECT:
                    self.assertEqual(boot[offset], original[offset])
                self.assertEqual(boot[lc.BOLD_LUI:lc.BOLD_ADDIU + 4],
                                 original[lc.BOLD_LUI:lc.BOLD_ADDIU + 4])
                self.assertEqual(len(boot), len(original) + 4)

    def test_on_installs_glyphs_and_keeps_bold_menu_capitals(self):
        for builder in BUILDERS:
            with self.subTest(builder=builder.__name__):
                original, font, built = self.run_build(builder, True)
                boot = built['boot']
                self.assertNotEqual(built['extra'][0], font)
                self.assertEqual(boot[lc.U8_TABLE + 0x61:lc.U8_TABLE + 0x7b], bytes(lc.LOWER_SLOTS))
                self.assertEqual(boot[lc.U8_TABLE + 0x27], lc.APOSTROPHE_SLOT)
                for offset in lc.FONT_SELECT:
                    self.assertEqual(boot[offset], lc.FONT_SELECT_TO)
                self.assertEqual(boot[-0x100:], original[lc.U8_TABLE:lc.U8_TABLE + 0x100])
                self.assertNotEqual(boot[lc.BOLD_LUI:lc.BOLD_ADDIU + 4],
                                    original[lc.BOLD_LUI:lc.BOLD_ADDIU + 4])

    def test_default_is_identical_to_explicit_on(self):
        for builder in BUILDERS:
            with self.subTest(builder=builder.__name__):
                self.assertEqual(self.run_build(builder)[2], self.run_build(builder, True)[2])

    def test_failed_verification_never_writes_iso_in_either_mode(self):
        for builder in BUILDERS:
            for enabled in (True, False):
                with self.subTest(builder=builder.__name__, enabled=enabled):
                    self.run_build(builder, enabled, verify=False)

    def test_cli_choices_and_existing_options(self):
        for builder in BUILDERS:
            with self.subTest(builder=builder.__name__):
                self.assertEqual(builder.parse_args(['clean.iso', 'out.iso']).lowercase_font, 'on')
                for choice in ('on', 'off'):
                    argv = ['clean.iso', 'out.iso', '--lowercase-font', choice,
                            '--probe', '--keep', 'work dir']
                    if hasattr(builder, 'psp_title'):
                        argv += ['--version', '0.2.0']
                    args = builder.parse_args(argv)
                    self.assertEqual(args.lowercase_font, choice)
                    self.assertTrue(args.probe)
                    self.assertEqual(args.keep, 'work dir')
                    if hasattr(builder, 'psp_title'):
                        self.assertEqual(args.version, '0.2.0')
                for bad in (['--lowercase-font'], ['--lowercase-font', 'invalid']):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        builder.parse_args(['clean.iso', 'out.iso'] + bad)
                    self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
