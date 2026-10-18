import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import projection as proj  # noqa: E402


def game_screen(x, y, z):
    """OpenRCT2 Translate3DTo2DWithZ for rotation 0."""
    return (y - x, (x + y) / 2.0 - z)


def blender_from_game(x, y, z):
    """Blender point of game coords (x, y, z) inside the tile centred on the origin."""
    return (2.0 - x / 8.0, 2.0 - y / 8.0, z / 16.0 * proj.HEIGHT_STEP)


class ProjectionTests(unittest.TestCase):
    def test_matches_game_projection(self):
        top = np.array(game_screen(0, 0, 0))
        for point in [(0, 0, 0), (32, 0, 0), (0, 32, 0), (32, 32, 0), (15, 15, 0), (7, 23, 40)]:
            expected = np.array(game_screen(*point)) - top
            got = proj.to_screen(blender_from_game(*point), 0)[0] - proj.tile_top_vertex(0, 0, 0)
            np.testing.assert_allclose(got, expected, atol=1e-9)

    def test_tile_is_64_by_32_pixels_in_every_view(self):
        for view in range(4):
            screen = proj.to_screen(proj.tile_corners(0, 0), view)
            self.assertAlmostEqual(np.ptp(screen[:, 0]), 64.0)
            self.assertAlmostEqual(np.ptp(screen[:, 1]), 32.0)
            self.assertEqual(proj.tile_top_vertex(0, 0, view), (0, -16))

    def test_height_step_is_16_pixels(self):
        screen = proj.to_screen([(0, 0, 0), (0, 0, proj.HEIGHT_STEP)], 0)
        self.assertAlmostEqual(screen[0, 1] - screen[1, 1], 16.0)

    def test_view_rotation_turns_object_clockwise(self):
        # Game direction +1 maps the -x edge (Blender +X) to the +y edge (Blender -Y).
        edge = proj.to_screen([(2.0, 0.0, 0.0)], 1)[0]
        expected = proj.to_screen([(0.0, -2.0, 0.0)], 0)[0]
        np.testing.assert_allclose(edge, expected, atol=1e-9)

    def test_game_offset_to_screen_full_tile_anchor(self):
        self.assertEqual(proj.game_offset_to_screen(15, 15, 0), (0, 15))
        self.assertEqual(proj.game_offset_to_screen(2, 1, 0), (-1, 1))

    def test_camera_placement_maps_bounds_to_image(self):
        bounds = (-40, -70, 41, 23)
        placement = proj.camera_placement(bounds, 2, 100.0)
        right, up, forward = proj.camera_basis(2)
        location = np.array(placement["location"])
        # Project the origin with the camera basis and compare to the bounds.
        rel = -location
        px = rel.dot(right) * proj.PIXELS_PER_BU + placement["resolution"][0] / 2.0
        py = -rel.dot(up) * proj.PIXELS_PER_BU + placement["resolution"][1] / 2.0
        self.assertAlmostEqual(px, -bounds[0])
        self.assertAlmostEqual(py, -bounds[1])
        self.assertAlmostEqual(np.dot(forward, right), 0.0)
        self.assertAlmostEqual(forward[2], -0.5)
        # Sensor fit is horizontal: one pixel is 1 / PIXELS_PER_BU wide even
        # for images taller than wide.
        self.assertAlmostEqual(placement["ortho_scale"] * proj.PIXELS_PER_BU, bounds[2] - bounds[0])


if __name__ == "__main__":
    unittest.main()
