import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import export, jobs, postprocess  # noqa: E402


class JobTests(unittest.TestCase):
    def test_small_scenery_layout(self):
        frames = jobs.animation_frames(2, first=5, step=3)
        self.assertEqual(frames, [5, 8])
        job_list = jobs.small_scenery("FULL", frames=frames, start_index=10)
        self.assertEqual([j.index for j in job_list], list(range(10, 18)))
        self.assertEqual([j.view for j in job_list], [0, 1, 2, 3] * 2)
        self.assertEqual([j.frame for j in job_list], [5] * 4 + [8] * 4)

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


class OutlineTests(unittest.TestCase):
    def test_edge_pixels(self):
        opaque = np.zeros((5, 5), dtype=bool)
        opaque[1:4, 1:4] = True
        rim = postprocess.edge_pixels(opaque)
        self.assertEqual(rim.sum(), 8)
        self.assertFalse(rim[2, 2])

    def test_outline_darkens_within_ramp(self):
        from rct_cycles_graphics.core import palette

        indices = np.zeros((5, 5), dtype=np.uint8)
        indices[1:4, 1:4] = 100
        indices[1, 1] = 250
        out = postprocess.apply_outline(indices, postprocess.Settings(outline_shades=2))
        self.assertEqual(out[2, 2], 100)
        self.assertEqual(out[1, 2], 98)
        self.assertEqual(out[1, 1], 248)
        self.assertIn(out[1, 1], palette.REMAP_RANGES[1])
        self.assertEqual(out[0, 0], 0)

    def test_background_blend_darkens_edges(self):
        rgba = np.zeros((1, 2, 4), dtype=np.float32)
        rgba[0, 0] = (0.8, 0.8, 0.8, 1.0)
        rgba[0, 1] = (0.48, 0.48, 0.48, 0.6)
        plain = postprocess.to_indices(rgba, postprocess.Settings(dither_method="NONE"))
        blended = postprocess.to_indices(rgba, postprocess.Settings(dither_method="NONE", background_blend=True))
        self.assertEqual(plain[0, 0], plain[0, 1])
        self.assertNotEqual(blended[0, 0], blended[0, 1])


class LargeSceneryTests(unittest.TestCase):
    def test_layout_matches_game_image_indices(self):
        job_list = jobs.large_scenery(2, 3, start_index=0)
        self.assertEqual(len(job_list), 4 + 2 * 3 * 4)
        tile_jobs = [j for j in job_list if j.tile is not None]
        for job in tile_jobs:
            self.assertEqual(job.index, 4 + 4 * job.tile + job.view)

    def test_tiles_have_game_offsets(self):
        tiles = jobs.large_scenery_tiles(2, 2)
        self.assertEqual([(t["x"], t["y"]) for t in tiles], [(0, 0), (32, 0), (0, 32), (32, 32)])
        self.assertEqual(tiles[3]["center"], (-4.0, -4.0))

    def test_tile_anchor_moves_with_tile(self):
        job = jobs.Job(0, 1, 0, (0, 0, 0), tile_center=(-4.0, 0.0), tile=1)
        # Game tile (32, 0) is 32 px left and 16 px down from tile (0, 0).
        self.assertEqual(job.anchor(), (-32, 0))

    def test_tile_map(self):
        position = np.array([[[0.0, 0.0, 0.0], [-4.0, 0.0, 1.0], [-4.0, -4.0, 0.0], [-9.0, 0.5, 0.0]]])
        alpha = np.array([[1.0, 1.0, 0.5, 1.0]])
        position[0, 2] *= 0.5
        tiles = jobs.tile_map(position, alpha, 2, 2)
        np.testing.assert_array_equal(tiles, [[0, 1, 3, 1]])
