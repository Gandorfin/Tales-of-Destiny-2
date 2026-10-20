"""Run from psp/tools: python -m unittest test_psp_pic1 (needs Pillow)"""
import io
import unittest

import psp_pic1


@unittest.skipUnless(psp_pic1.available(), 'Pillow not installed')
class Pic1Tests(unittest.TestCase):
    def picture(self):
        from PIL import Image
        img = Image.new('RGB', psp_pic1.SIZE)
        px = img.load()
        for y in range(psp_pic1.SIZE[1]):
            for x in range(psp_pic1.SIZE[0]):
                px[x, y] = (x % 64, y % 64, 128)
        out = io.BytesIO(); img.save(out, 'PNG')
        return out.getvalue(), img

    def test_only_the_text_areas_change(self):
        from PIL import Image
        png, before = self.picture()
        after = Image.open(io.BytesIO(psp_pic1.build(png, '0.3.3'))).convert('RGB')
        self.assertEqual(after.size, psp_pic1.SIZE)
        for xy in ((5, 5), (240, 100), (200, 260), (479, 0), (10, 265)):
            self.assertEqual(after.getpixel(xy), before.getpixel(xy))
        self.assertNotEqual(after.crop((298, 207, 474, 255)).tobytes(), before.crop((298, 207, 474, 255)).tobytes())

    def test_wrong_size_is_refused(self):
        from PIL import Image
        out = io.BytesIO(); Image.new('RGB', (144, 80)).save(out, 'PNG')
        with self.assertRaises(ValueError):
            psp_pic1.build(out.getvalue(), '0.3.3')


if __name__ == '__main__':
    unittest.main()
