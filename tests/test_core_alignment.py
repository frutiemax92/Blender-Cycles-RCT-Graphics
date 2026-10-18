import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import alignment, jobs, postprocess, projection  # noqa: E402


def box_sprite(size_x, size_y, height, view=0, colour=100):
    """Rasterize a box centred on the tile like the renderer does (pixel centres)."""
    hx, hy = size_x / 2.0, size_y / 2.0
    corners = np.array([(x, y, z) for x in (-hx, hx) for y in (-hy, hy) for z in (0.0, height)])
    screen = projection.to_screen(corners, view)
    x0, y0 = np.floor(screen.min(axis=0)).astype(int) - 1
    x1, y1 = np.ceil(screen.max(axis=0)).astype(int) + 1
    hull = _hull(screen)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    px, py = xs + 0.5, ys + 0.5
    inside = np.ones(px.shape, dtype=bool)
    for (ax, ay), (bx, by) in zip(hull, np.roll(hull, -1, axis=0)):
        inside &= (bx - ax) * (py - ay) - (by - ay) * (px - ax) >= 0
    indices = np.where(inside, colour, 0).astype(np.uint8)
    job = jobs.small_scenery("FULL")[view]
    return postprocess.make_sprite(indices, int(x0), int(y0), job.anchor())


def _hull(points):
    pts = sorted(map(tuple, points))

    def build(sequence):
        chain = []
        for p in sequence:
            while len(chain) >= 2 and np.cross(np.subtract(chain[-1], chain[-2]), np.subtract(p, chain[-2])) <= 0:
                chain.pop()
            chain.append(p)
        return chain

    lower, upper = build(pts), build(reversed(pts))
    return np.array(lower[:-1] + upper[:-1])


class CompositeTests(unittest.TestCase):
    def setUp(self):
        sprite = box_sprite(4.0, 4.0, projection.HEIGHT_STEP)
        self.sprites = {i: (sprite.indices, sprite.x, sprite.y) for i in range(4)}
        self.anchors = {i: projection.game_offset_to_screen(15, 15, 0) for i in range(4)}

    def test_tile_sized_box_tiles_without_pinholes(self):
        for layout in alignment.arrangements("SMALL", clearance=16):
            self.assertEqual(alignment.pinholes(self.sprites, self.anchors, layout), 0, layout.name)

    def test_flat_tiles_partition_the_screen(self):
        sprite = box_sprite(4.0, 4.0, 0.0)
        sprites = {i: (sprite.indices, sprite.x, sprite.y) for i in range(4)}
        for layout in alignment.arrangements("SMALL", clearance=0):
            _, coverage, _ = alignment.compose(sprites, self.anchors, layout.placements, grid=False)
            # Neighbouring tiles share no pixel and leave none uncovered.
            self.assertEqual(int((coverage > 1).sum()), 0, layout.name)
            self.assertEqual(int((coverage == 1).sum()), 3 * 64 * 32 // 2, layout.name)

    def test_enclosed_holes(self):
        coverage = np.ones((5, 5), dtype=np.int32)
        coverage[2, 2] = 0
        coverage[0, 0] = 0
        holes = alignment.enclosed_holes(coverage)
        self.assertTrue(holes[2, 2])
        self.assertFalse(holes[0, 0])

    def test_preview_sheet(self):
        sheet = alignment.preview_sheet(self.sprites, self.anchors, alignment.arrangements("SMALL")[:3])
        self.assertEqual(sheet.shape[2], 4)
        self.assertGreater(sheet.shape[1], 3 * 64)


class GeometryReportTests(unittest.TestCase):
    def test_exact_block(self):
        findings = alignment.geometry_report((-2, -2, 0), (2, 2, projection.HEIGHT_STEP), "SMALL")
        self.assertTrue(all(f.ok for f in findings), findings)

    def test_short_block(self):
        findings = alignment.geometry_report((-1.75, -2, 0), (2, 2, 1.0), "SMALL")
        x = next(f for f in findings if f.axis == "x")
        self.assertAlmostEqual(x.error_units, 2.0)
        self.assertIn("short of", x.message)
        z = [f for f in findings if f.axis == "z"]
        self.assertFalse(z[-1].ok)

    def test_wall_only_needs_outer_edge(self):
        findings = alignment.geometry_report((1.8, -2, 0), (2, 2, projection.HEIGHT_STEP), "WALL")
        self.assertTrue(all(f.ok for f in findings), findings)

    def test_snap_box(self):
        low, high = alignment.snap_box((-1.9, -2.1, 0.1), (1.9, 2.05, 1.7), "SMALL")
        np.testing.assert_allclose(low, (-2, -2, 0))
        np.testing.assert_allclose(high, (2, 2, projection.HEIGHT_STEP))
        low, high = alignment.snap_box((1.7, -1.9, 0), (1.95, 1.9, 1.0), "WALL")
        np.testing.assert_allclose((low[0], high[0]), (1.75, 2.0))

    def test_snap_box_quarter(self):
        low, high = alignment.snap_box((-1.9, -2.1, 0), (1.9, 2.05, 1.0), "SMALL", shape="QUARTER")
        np.testing.assert_allclose((low[0], low[1], high[0], high[1]), (-1, -1, 1, 1))
        findings = alignment.geometry_report((-1, -1, 0), (1, 1, projection.HEIGHT_STEP), "SMALL", shape="QUARTER")
        self.assertTrue(all(f.ok for f in findings), findings)
        steps = {a.step for a in alignment.arrangements("SMALL", 0, shape="QUARTER")}
        self.assertEqual(steps, {16})

    def test_large_cell(self):
        cell = alignment.expected_cell("LARGE", (2, 3))
        self.assertEqual(cell["x"], (-6.0, 2.0))
        self.assertEqual(cell["y"], (-10.0, 2.0))

    def test_clearance_from_height(self):
        self.assertEqual(alignment.clearance_from_height(projection.HEIGHT_STEP), 16)
        self.assertEqual(alignment.clearance_from_height(1.0), 16)
        self.assertEqual(alignment.clearance_from_height(0.1), 8)


if __name__ == "__main__":
    unittest.main()
