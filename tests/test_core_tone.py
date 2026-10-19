import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import palette, postprocess, tone  # noqa: E402

GREEN = list(palette.RAMPS["green"])
ORANGE = list(palette.RAMPS["orange"])
YELLOW = list(palette.RAMPS["yellow"])


def ramp_image(ramp, shades, size=24, seed=0):
    """Square sRGB image of ``ramp`` colours at random continuous ``shades`` (low, high)."""
    rng = np.random.default_rng(seed)
    shade = rng.uniform(*shades, size=(size, size))
    ramps = np.full((size, size), tone._RAMP_OF[ramp[0]])
    return tone.ramp_colour(ramps, shade).astype(np.float32)


def sample(rgb):
    classes = np.zeros(rgb.shape[:2], dtype=np.int32)
    return rgb, classes, {0: palette.normal_indices()}


def mean_shade(rgb, classes, allowed):
    settings = postprocess.Settings(dither_method="NONE")
    indices = postprocess.quantize.quantize(rgb, classes, allowed, method=settings.dither_method)
    shares = tone.shade_histogram([indices])
    return (shares * np.arange(tone.SHADE_COUNT)).sum(), indices


class ReferenceTests(unittest.TestCase):
    def test_reference_quantiles_increase_within_the_ramp(self):
        quantiles = tone.reference_quantiles()
        self.assertTrue(np.all(np.diff(quantiles) > 0))
        self.assertGreaterEqual(quantiles[0], 0)
        self.assertLessEqual(quantiles[-1], 11)
        # Half of the original trees' pixels use the darkest four shades.
        self.assertLess(quantiles[3], 3.5)

    def test_average_is_the_mean_of_the_trees(self):
        shares = np.mean([tone.reference(code).shades for code in tone.TREE_NAMES], axis=0)
        np.testing.assert_allclose(tone.reference("AVERAGE").shades, shares)
        self.assertNotIn("TNSS", tone.TREE_NAMES)

    def test_vanilla_trees_differ_in_brightness(self):
        means = [tone.reference(code).shades @ np.arange(12) for code in tone.TREE_NAMES]
        self.assertGreater(max(means) - min(means), 3)

    def test_closest_trees_follow_the_render(self):
        dark = tone.reference("AUTO", 2.0).shades @ np.arange(12)
        light = tone.reference("AUTO", 5.0).shades @ np.arange(12)
        self.assertLess(dark, 2.6)
        self.assertGreater(light, 4.4)

    def test_shade_of_finds_the_ramp_position(self):
        ramps = np.full(len(GREEN), tone._RAMP_OF[GREEN[0]])
        shade = tone.shade_of(palette.PALETTE[GREEN].astype(np.float32), ramps)
        np.testing.assert_allclose(shade, np.arange(12), atol=1e-4)


class FitTests(unittest.TestCase):
    def test_a_washed_out_render_moves_to_the_reference_shades(self):
        rgb, classes, allowed = sample(ramp_image(GREEN, (4, 8)))
        before, _ = mean_shade(rgb, classes, allowed)
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False, reference_key="AVERAGE")
        after, _ = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        reference = (tone.REFERENCE_SHADES * np.arange(12)).sum()
        self.assertGreater(before, 5.5)
        self.assertAlmostEqual(after, reference, delta=0.5)

    def test_closest_trees_keep_a_brightness_rct2_trees_have(self):
        # A light render is only reshaped: some RCT2 trees are that light.
        rgb, classes, allowed = sample(ramp_image(GREEN, (3, 6)))
        before, _ = mean_shade(rgb, classes, allowed)
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False)
        after, _ = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        self.assertAlmostEqual(after, before, delta=0.4)

    def test_closest_trees_bring_a_washed_out_render_into_range(self):
        rgb, classes, allowed = sample(ramp_image(GREEN, (6, 10)))
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False)
        after, _ = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        lightest = max(tone.reference(code).shades @ np.arange(12) for code in tone.TREE_NAMES)
        self.assertAlmostEqual(after, lightest, delta=0.5)

    def test_a_chosen_tree_is_matched(self):
        rgb, classes, allowed = sample(ramp_image(GREEN, (3, 6)))
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False, reference_key="TNS")
        after, _ = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        self.assertAlmostEqual(after, tone.reference("TNS").shades @ np.arange(12), delta=0.5)

    def test_contrast_is_stretched(self):
        rgb, classes, allowed = sample(ramp_image(GREEN, (2.5, 4.5)))
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False)
        _, indices = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        positions = tone._POSITION_OF[indices]
        self.assertGreaterEqual(positions.max() - positions.min(), 5)

    def test_hue_is_kept(self):
        rgb, classes, allowed = sample(ramp_image(ORANGE, (5, 9)))
        curve = tone.fit([(rgb, classes, allowed)], match_saturation=False)
        _, indices = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        # The darkest oranges are the palette's dark yellows.
        self.assertTrue(np.isin(indices, ORANGE + YELLOW).all())

    def test_zero_strength_changes_nothing(self):
        rgb, classes, allowed = sample(ramp_image(GREEN, (4, 8)))
        curve = tone.fit([(rgb, classes, allowed)], strength=0.0)
        np.testing.assert_allclose(curve.apply(rgb, classes, allowed), rgb, atol=1e-3)

    def test_one_curve_for_every_view(self):
        bright = sample(ramp_image(GREEN, (6, 8), seed=1))
        dark = sample(ramp_image(GREEN, (2, 4), seed=2))
        curve = tone.fit([bright, dark], match_saturation=False)
        bright_after, _ = mean_shade(curve.apply(*bright), *bright[1:])
        dark_after, _ = mean_shade(curve.apply(*dark), *dark[1:])
        # The views keep their difference: neither is matched on its own.
        self.assertGreater(bright_after - dark_after, 2)

    def test_recolourable_pixels_stay_on_their_ramp(self):
        primary = list(palette.REMAP_RANGES[1])
        rgb = ramp_image(primary, (5, 9))
        classes = np.ones(rgb.shape[:2], dtype=np.int32)
        allowed = {0: palette.normal_indices(used_remaps=[1]), 1: primary}
        curve = tone.fit([(rgb, classes, allowed)])
        _, indices = mean_shade(curve.apply(rgb, classes, allowed), classes, allowed)
        self.assertTrue(np.isin(indices, primary).all())

    def test_saturation_is_nudged(self):
        rgb = ramp_image(GREEN, (2, 4))
        grey = postprocess.luminance(rgb)[..., None]
        dull = grey + (rgb - grey) * 0.4
        sample_ = sample(dull)
        curve = tone.fit([sample_])
        self.assertGreater(curve.saturation_gain, 1.0)
        self.assertLessEqual(curve.saturation_gain, tone.SATURATION_GAIN_RANGE[1])
        after = curve.apply(*sample_)
        self.assertGreater(tone.saturation(after.reshape(-1, 3)), tone.saturation(dull.reshape(-1, 3)))

    def test_empty_renders_give_no_curve(self):
        classes = np.full((4, 4), -1, dtype=np.int32)
        self.assertIsNone(tone.fit([(np.zeros((4, 4, 3)), classes, {0: palette.normal_indices()})]))


class PipelineTests(unittest.TestCase):
    def test_to_indices_applies_the_curve(self):
        srgb = ramp_image(GREEN, (5, 8)) / 255.0
        linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
        rgba = np.concatenate([linear, np.ones(linear.shape[:2] + (1,))], axis=-1).astype(np.float32)
        settings = postprocess.Settings(dither_method="NONE")
        curve = tone.fit([postprocess.prepare(rgba, settings)], reference_key="AVERAGE")
        plain = postprocess.to_indices(rgba, settings)
        matched = postprocess.to_indices(rgba, settings, tone=curve)
        self.assertLess(tone._POSITION_OF[matched].mean(), tone._POSITION_OF[plain].mean() - 1)


class ReportTests(unittest.TestCase):
    def test_report_compares_with_the_reference(self):
        indices = np.array([[0, GREEN[0], GREEN[11]]], dtype=np.uint8)
        lines = tone.report([indices], "AVERAGE")
        self.assertIn("Average shade 5.5 of 11 (RCT2 trees", lines[0])
        self.assertIn("50 / 0 / 50%", lines[1])

    def test_report_is_empty_without_pixels(self):
        self.assertEqual(tone.report([np.zeros((2, 2), dtype=np.uint8)]), [])


if __name__ == "__main__":
    unittest.main()
