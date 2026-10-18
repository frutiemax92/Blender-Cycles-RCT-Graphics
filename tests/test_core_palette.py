import os
import sys
import tempfile
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import palette, png, quantize  # noqa: E402


class PaletteTests(unittest.TestCase):
    def test_palette_matches_openrct2_samples(self):
        # A few RGB values cross-checked against OpenRCT2's BGR table.
        self.assertEqual(tuple(palette.PALETTE[10]), (23, 35, 35))
        self.assertEqual(tuple(palette.PALETTE[173]), (255, 7, 0))
        self.assertEqual(tuple(palette.PALETTE[243]), (111, 51, 47))

    def test_allowed_colours_round_trip_in_game(self):
        # OpenRCT2 maps an RGB pixel to the first palette entry with that
        # exact colour; every colour we emit must map back to itself.
        for index in palette.normal_indices() + [i for r in palette.REMAP_RANGES.values() for i in r]:
            colour = tuple(palette.PALETTE[index])
            first = next(i for i in range(256) if tuple(palette.PALETTE[i]) == colour)
            self.assertEqual(first, index)

    def test_normal_indices_exclude_used_remaps(self):
        plain = palette.normal_indices()
        self.assertNotIn(243, plain)
        self.assertIn(202, plain)
        with_remaps = palette.normal_indices(used_remaps=(2, 3))
        self.assertNotIn(202, with_remaps)
        self.assertNotIn(50, with_remaps)
        self.assertFalse(any(palette.is_special(i) for i in plain))

    def test_shift_shade_stays_in_ramp(self):
        self.assertEqual(palette.shift_shade(100, -2), 98)
        self.assertEqual(palette.shift_shade(95, -5), 94)
        self.assertEqual(palette.shift_shade(250, -1), 249)
        self.assertEqual(palette.shift_shade(0, -1), 0)
        self.assertIn(palette.shift_shade(241, -1), palette.RAMPS["grey"])


class QuantizeTests(unittest.TestCase):
    def test_exact_palette_colours_are_preserved(self):
        allowed = palette.normal_indices()
        rgb = palette.PALETTE[allowed].astype(np.float32).reshape(1, -1, 3)
        classes = np.zeros(rgb.shape[:2], dtype=np.int32)
        for method in ("NONE", "ORDERED", "FLOYD_STEINBERG"):
            out = quantize.quantize(rgb, classes, {0: allowed}, method=method, strength=0.0)
            self.assertEqual(out.ravel().tolist(), allowed)
        out = quantize.quantize(rgb, classes, {0: allowed}, method="FLOYD_STEINBERG", strength=1.0)
        self.assertEqual(out.ravel().tolist(), allowed)

    def test_classes_use_their_own_ranges(self):
        rgb = np.full((8, 8, 3), 128, dtype=np.float32)
        classes = np.zeros((8, 8), dtype=np.int32)
        classes[:, 4:] = 1
        classes[0, 0] = -1
        allowed = {0: palette.normal_indices(used_remaps=(1,)), 1: palette.remap_indices(1)}
        out = quantize.quantize(rgb, classes, allowed)
        self.assertEqual(out[0, 0], 0)
        self.assertTrue(set(out[:, 4:].ravel()) <= set(palette.REMAP_RANGES[1]))
        self.assertFalse(set(out[1:, :4].ravel()) & set(palette.REMAP_RANGES[1]))

    def test_dithering_preserves_average_colour(self):
        rgb = np.zeros((32, 32, 3), dtype=np.float32)
        rgb[...] = (90, 140, 60)
        classes = np.zeros((32, 32), dtype=np.int32)
        allowed = palette.normal_indices()
        out = quantize.quantize(rgb, classes, {0: allowed}, method="FLOYD_STEINBERG")
        mean = palette.PALETTE[out].reshape(-1, 3).mean(axis=0)
        self.assertLess(np.abs(mean - (90, 140, 60)).max(), 6)

    def test_floyd_steinberg_speed(self):
        rgb = np.random.default_rng(1).uniform(0, 255, (128, 128, 3)).astype(np.float32)
        classes = np.zeros((128, 128), dtype=np.int32)
        start = time.time()
        quantize.quantize(rgb, classes, {0: palette.normal_indices()})
        self.assertLess(time.time() - start, 5.0)


class PngTests(unittest.TestCase):
    def test_indexed_round_trip(self):
        indices = np.arange(64, dtype=np.uint8).reshape(8, 8)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            png.write_indexed(path, indices, palette.PALETTE)
            back, pal = png.read_indexed(path)
        np.testing.assert_array_equal(back, indices)
        np.testing.assert_array_equal(pal, palette.PALETTE)

    def test_written_png_is_readable_by_pil(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL not available")
        indices = np.array([[0, 100], [243, 21]], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            png.write_indexed(path, indices, palette.PALETTE)
            image = Image.open(path).convert("RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((1, 0)), tuple(palette.PALETTE[100]) + (255,))


if __name__ == "__main__":
    unittest.main()
