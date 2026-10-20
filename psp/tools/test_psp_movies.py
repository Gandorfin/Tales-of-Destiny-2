"""Run from psp/tools: python -m unittest test_psp_movies

No game files needed: the parameter sets below are copied from movie 011."""
import unittest

import psp_movies

AUD = b'\x00\x00\x00\x01\x09\x10'
RETAIL_PPS = b'\x00\x00\x00\x01\x28\xee\x38\x80'          # retail 011.pmf
WEIGHTED_PPS = b'\x00\x00\x00\x01\x68\xef\x02\xf2\xc8'    # PSP 0.3.2 011.pmf (x264 defaults)
FIXED_PPS = b'\x00\x00\x00\x01\x68\xee\x02\xf2\xc8'       # weightp=0


class WeightedPredictionTests(unittest.TestCase):
    def test_retail_has_none(self):
        self.assertFalse(psp_movies.weighted_prediction(AUD + RETAIL_PPS))

    def test_x264_default_is_found(self):
        self.assertTrue(psp_movies.weighted_prediction(AUD + WEIGHTED_PPS))

    def test_weightp_off_passes(self):
        self.assertFalse(psp_movies.weighted_prediction(AUD + FIXED_PPS))

    def test_picture_without_pps(self):
        self.assertFalse(psp_movies.weighted_prediction(AUD + b'\x00\x00\x01\x65\x88'))


if __name__ == '__main__':
    unittest.main()
