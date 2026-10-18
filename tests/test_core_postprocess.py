import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import postprocess  # noqa: E402

TOP = np.array([0.0, 0.0, 1.0])
FRONT = np.array([0.0, -1.0, 0.0])


def two_faces(factor, split):
    """One pixel row of point samples: the top face above sub-row ``split``, the front face below.

    Both faces meet along the edge y = 0, z = 0 of a box.
    """
    size = factor
    rgba = np.zeros((size, size, 4), dtype=np.float32)
    position = np.zeros((size, size, 3), dtype=np.float32)
    normal = np.zeros((size, size, 3), dtype=np.float32)
    for row in range(size):
        for col in range(size):
            offset = (col + 0.5) / size * 0.1
            if row < split:
                rgba[row, col] = (0.2, 0.0, 0.0, 1.0)
                position[row, col] = (offset, 0.05 * (split - row), 0.0)
                normal[row, col] = TOP
            else:
                rgba[row, col] = (0.8, 0.4, 0.4, 1.0)
                position[row, col] = (offset, 0.0, -0.05 * (row - split + 1))
                normal[row, col] = FRONT
    classes = np.zeros((size, size), dtype=np.int32)
    return rgba, position, normal, classes


class ResolveTests(unittest.TestCase):
    def test_edge_pixel_takes_the_centre_face_only(self):
        rgba, position, normal, classes = two_faces(3, split=2)
        out, _, _, opaque = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        self.assertTrue(opaque[0, 0])
        # The centre sub-pixel is on the top face: the front face never bleeds in.
        np.testing.assert_allclose(out[0, 0], (0.2, 0.0, 0.0, 1.0), atol=1e-6)

        rgba, position, normal, classes = two_faces(3, split=1)
        out, _, _, _ = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        np.testing.assert_allclose(out[0, 0], (0.8, 0.4, 0.4, 1.0), atol=1e-6)

    def test_texture_inside_a_face_is_averaged(self):
        rgba, position, normal, classes = two_faces(3, split=3)
        rgba[..., 0] = np.arange(9, dtype=np.float32).reshape(3, 3) / 8.0
        out, _, _, _ = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        self.assertAlmostEqual(float(out[0, 0, 0]), 0.5, places=6)

    def test_parallel_faces_at_different_depths_are_separate(self):
        rgba, position, normal, classes = two_faces(3, split=3)
        # The bottom row is a lower step of the same orientation.
        position[2, :, 2] -= 1.0
        rgba[2, :, :3] = (1.0, 1.0, 1.0)
        out, _, _, _ = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        np.testing.assert_allclose(out[0, 0, :3], (0.2, 0.0, 0.0), atol=1e-6)

    def test_remaps_are_separate(self):
        rgba, position, normal, classes = two_faces(3, split=3)
        classes[0] = 1
        rgba[0, :, :3] = (1.0, 1.0, 1.0)
        out, _, out_classes, _ = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        self.assertEqual(out_classes[0, 0], 0)
        np.testing.assert_allclose(out[0, 0, :3], (0.2, 0.0, 0.0), atol=1e-6)

    def test_silhouette_follows_the_centre_sample(self):
        rgba, position, normal, classes = two_faces(3, split=3)
        # Only the centre sub-pixel is covered: opaque, with 1/9 coverage.
        mask = np.zeros((3, 3), dtype=bool)
        mask[1, 1] = True
        rgba[~mask] = 0.0
        out, out_position, _, opaque = postprocess.resolve_supersampled(
            rgba, position, normal, classes, 3, 0.5
        )
        self.assertTrue(opaque[0, 0])
        self.assertAlmostEqual(float(out[0, 0, 3]), 1.0 / 9.0, places=6)
        np.testing.assert_allclose(out[0, 0, :3] / out[0, 0, 3], (0.2, 0.0, 0.0), atol=1e-6)
        np.testing.assert_allclose(out_position[0, 0] / out[0, 0, 3], position[1, 1], atol=1e-6)

        # Everything but the centre is covered: transparent.
        rgba, position, normal, classes = two_faces(3, split=3)
        rgba[1, 1] = 0.0
        _, _, _, opaque = postprocess.resolve_supersampled(rgba, position, normal, classes, 3, 0.5)
        self.assertFalse(opaque[0, 0])

    def test_pixels_are_resolved_independently(self):
        rgba, position, normal, classes = two_faces(3, split=2)
        tiled = [np.concatenate([a, a], axis=1) for a in (rgba, position, normal, classes)]
        tiled[0][:, 3:, :3] = (0.0, 0.0, 1.0)
        out, _, _, opaque = postprocess.resolve_supersampled(*tiled, 3, 0.5)
        self.assertEqual(out.shape, (1, 2, 4))
        np.testing.assert_allclose(out[0, 0, :3], (0.2, 0.0, 0.0), atol=1e-6)
        np.testing.assert_allclose(out[0, 1, :3], (0.0, 0.0, 1.0), atol=1e-6)

    def test_opaque_overrides_the_alpha_threshold(self):
        rgba = np.zeros((1, 2, 4), dtype=np.float32)
        rgba[0, :] = (0.05, 0.05, 0.05, 0.1)
        settings = postprocess.Settings(dither_method="NONE")
        indices = postprocess.to_indices(rgba, settings, opaque=np.array([[True, False]]))
        self.assertNotEqual(indices[0, 0], 0)
        self.assertEqual(indices[0, 1], 0)


if __name__ == "__main__":
    unittest.main()
