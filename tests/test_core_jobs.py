import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import export, jobs, postprocess  # noqa: E402


class JobTests(unittest.TestCase):
    def test_small_scenery_layout(self):
        job_list = jobs.small_scenery("FULL", frames=2, start_index=10)
        self.assertEqual([j.index for j in job_list], list(range(10, 18)))
        self.assertEqual([j.view for j in job_list], [0, 1, 2, 3] * 2)
        self.assertEqual([j.frame for j in job_list], [0] * 4 + [1] * 4)

    def test_small_scenery_anchor_is_view_independent(self):
        for anchor, expected in (("FULL", (0, -1)), ("CENTRED", (0, -13)), ("NO_WALLS", (0, -15))):
            anchors = {j.anchor() for j in jobs.small_scenery(anchor)}
            self.assertEqual(anchors, {expected})


class SpriteTests(unittest.TestCase):
    def test_make_sprite_trims_and_offsets(self):
        indices = np.zeros((10, 10), dtype=np.uint8)
        indices[3:5, 2:7] = 100
        sprite = postprocess.make_sprite(indices, -20, -30, (0, -1))
        self.assertEqual(sprite.indices.shape, (2, 5))
        self.assertEqual((sprite.x, sprite.y), (-18, -26))

    def test_write_sprites_merges_existing_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = postprocess.Sprite(np.full((2, 2), 50, dtype=np.uint8), -1, -2)
            export.write_sprites(tmp, {0: first})
            images = export.write_sprites(tmp, {2: first})
            self.assertEqual(images[0]["path"], "images/0000.png")
            self.assertEqual(images[1], "")
            self.assertEqual(images[2]["x"], -1)
            loaded = export.load_sprites(tmp)
            self.assertEqual(sorted(loaded), [0, 2])


if __name__ == "__main__":
    unittest.main()


class RemapTests(unittest.TestCase):
    def test_remap_ramps_have_increasing_luminance(self):
        from rct_cycles_graphics.core import palette

        for remap, indices in palette.REMAP_RANGES.items():
            lum = postprocess.luminance(palette.PALETTE[list(indices)].astype(np.float32))
            self.assertTrue(np.all(np.diff(lum) > 0), remap)

    def test_remap_pixels_stay_in_their_ramp(self):
        from rct_cycles_graphics.core import palette

        rgba = np.zeros((4, 4, 4), dtype=np.float32)
        rgba[...] = (0.2, 0.5, 0.1, 1.0)
        remap = np.zeros((4, 4), dtype=np.int32)
        remap[:, 2:] = 2
        out = postprocess.to_indices(rgba, postprocess.Settings(), remap=remap)
        self.assertTrue(set(out[:, 2:].ravel()) <= set(palette.REMAP_RANGES[2]))
        self.assertFalse(set(out[:, :2].ravel()) & set(palette.REMAP_RANGES[2]))

    def test_remap_classes_from_premultiplied_aov(self):
        alpha = np.array([[1.0, 0.5, 0.0]])
        aov = np.array([[2.0, 1.0, 0.0]])
        np.testing.assert_array_equal(postprocess.remap_classes(aov, alpha), [[2, 2, 0]])
