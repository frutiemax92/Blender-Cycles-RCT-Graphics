import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import tree  # noqa: E402


def trunk(data):
    return data.polylines[0]


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_tree(self):
        params = tree.preset_params("GNARLED_OAK", seed=7)
        data_a, mesh_a = tree.build(params)
        data_b, mesh_b = tree.build(params)
        np.testing.assert_array_equal(mesh_a.verts, mesh_b.verts)
        np.testing.assert_array_equal(data_a.blobs, data_b.blobs)
        self.assertEqual(mesh_a.faces, mesh_b.faces)

    def test_different_seed_different_tree(self):
        _, mesh_a = tree.build(tree.preset_params("BROADLEAF", seed=1))
        _, mesh_b = tree.build(tree.preset_params("BROADLEAF", seed=2))
        self.assertFalse(len(mesh_a.verts) == len(mesh_b.verts) and np.allclose(mesh_a.verts, mesh_b.verts))

    def test_branch_count_does_not_change_the_trunk(self):
        params = dict(straightness=0.3, gnarl=0.5, seed=3)
        a = tree.generate(tree.make_params(branch_count=2, **params))
        b = tree.generate(tree.make_params(branch_count=9, **params))
        np.testing.assert_array_equal(trunk(a).points, trunk(b).points)

    def test_unknown_parameter(self):
        with self.assertRaises(KeyError):
            tree.make_params(leaf_count=3)


class TrunkTests(unittest.TestCase):
    def test_straight_trunk_is_vertical(self):
        data = tree.generate(tree.make_params(straightness=1.0, lean_angle=0.0, gnarl=0.0))
        np.testing.assert_allclose(trunk(data).points[:, :2], 0.0, atol=1e-12)
        self.assertAlmostEqual(trunk(data).points[-1, 2], 0.55 * 6.5)

    def test_crooked_trunk_bends_but_stays_anchored(self):
        data = tree.generate(tree.make_params(straightness=0.0, gnarl=1.0))
        points = trunk(data).points
        np.testing.assert_allclose(points[0], 0.0, atol=1e-12)
        self.assertGreater(np.abs(points[:, :2]).max(), 0.1)

    def test_lean(self):
        data = tree.generate(tree.make_params(lean_angle=30.0, lean_direction=90.0, straightness=1.0))
        end = trunk(data).points[-1]
        self.assertAlmostEqual(math.degrees(math.atan2(end[1], end[2])), 30.0, places=5)
        self.assertAlmostEqual(end[0], 0.0, places=9)

    def test_taper_never_grows_above_the_flare(self):
        params = tree.make_params(root_flare=0.8, root_flare_height=0.1, taper_curve=2.0)
        t = np.linspace(0.1, 1.0, 50)
        radius = tree.trunk_radius(params, params.trunk_base_radius, t)
        self.assertTrue(np.all(np.diff(radius) <= 1e-12))
        self.assertAlmostEqual(float(tree.trunk_radius(params, 0.16, 0.0)), 0.16 * 1.8)

    def test_trunk_fits_the_footprint(self):
        params = tree.make_params(size="QUARTER", trunk_base_radius=1.5, root_flare=1.0)
        radii = trunk(tree.generate(params)).radii
        self.assertLessEqual(radii.max(), 0.8 * 1.0 + 1e-9)

    def test_fork(self):
        data = tree.generate(tree.make_params(fork_count=3, branch_count=0))
        stems = [data.polylines[i] for i in data.skeleton.stems]
        self.assertEqual(len(stems), 3)
        for stem in stems:
            np.testing.assert_allclose(stem.points[0], trunk(data).points[-1])
            self.assertAlmostEqual(stem.radii[0], trunk(data).radii[-1] / math.sqrt(3), places=2)

    def test_no_trunk(self):
        data = tree.generate(tree.preset_params("SHRUB"))
        self.assertEqual(data.polylines, [])
        self.assertGreater(len(data.blobs), 0)


class BranchTests(unittest.TestCase):
    def test_counts(self):
        data = tree.generate(tree.make_params(branch_count=7, sub_branches=3))
        self.assertEqual(data.branch_counts, (7, 21))
        self.assertFalse(data.skeleton.capped)

    def test_segment_cap(self):
        data = tree.generate(tree.make_params(branch_count=200, sub_branches=8))
        self.assertLessEqual(data.skeleton.segments, tree.MAX_SEGMENTS)
        self.assertTrue(data.skeleton.capped)
        self.assertTrue(any("limit" in w for w in data.warnings()))

    def test_branches_start_on_the_trunk_within_range(self):
        params = tree.make_params(branch_count=6, branch_start=0.3, branch_end=0.8, jitter=0.0, straightness=1.0)
        data = tree.generate(params)
        trunk_height = params.trunk_length * params.height
        for polyline in data.polylines[1:]:
            self.assertAlmostEqual(polyline.points[0][0], 0.0)
            self.assertGreaterEqual(polyline.points[0][2], 0.3 * trunk_height - 1e-9)
            self.assertLessEqual(polyline.points[0][2], 0.8 * trunk_height + 1e-9)

    def test_whorls(self):
        params = tree.make_params(branch_count=8, whorl_size=4, branch_spread="WHORLED", jitter=0.0)
        heights = sorted({round(p.points[0][2], 6) for p in tree.generate(params).polylines[1:]})
        self.assertEqual(len(heights), 2)

    def test_thin_branches_get_no_tube(self):
        data = tree.generate(tree.make_params(branch_radius_ratio=0.1))
        self.assertTrue(all(not p.mesh for p in data.polylines[1:]))
        self.assertEqual(len(tree.tube_mesh(data).faces), (trunk(data).segments + 2) * 6)


class EnvelopeTests(unittest.TestCase):
    def check(self, envelope, inside, outside):
        self.assertTrue(np.all(envelope.sdf(inside) < 0.0), envelope.shape)
        self.assertTrue(np.all(envelope.sdf(outside) > 0.0), envelope.shape)

    def test_shapes(self):
        outside = [(0.0, 0.0, 4.2), (0.0, 0.0, -0.2), (2.1, 0.0, 2.0), (0.0, -2.1, 2.0)]
        self.check(tree.Envelope("ELLIPSOID", (0, 0), 2.0, 0.0, 4.0), [(0, 0, 2), (1.9, 0, 2), (0, 0, 3.9)], outside)
        self.check(tree.Envelope("CYLINDER", (0, 0), 2.0, 0.0, 4.0), [(1.9, 0, 0.1), (0, 1.9, 3.9)], outside)
        self.check(tree.Envelope("CONE", (0, 0), 2.0, 0.0, 4.0), [(1.8, 0, 0.1), (0, 0, 3.9)], outside + [(1.5, 0, 3.0)])
        self.check(tree.Envelope("BELL", (0, 0), 2.0, 0.0, 4.0), [(1.9, 0, 0.05), (0, 0, 3.9)], outside + [(1.9, 0, 3.0)])
        heart = tree.Envelope("HEART", (0, 0), 2.0, 0.0, 4.0)
        self.check(heart, [(1.0, 0, 3.0), (-1.0, 0, 3.0), (0, 0, 0.5)], outside + [(0, 0, 3.95), (1.5, 0, 0.5)])

    def test_sphere_sits_at_the_top(self):
        sphere = tree.Envelope("SPHERE", (1.0, 0.0), 2.0, 0.0, 10.0)
        self.assertEqual((sphere.radius, sphere.bottom), (2.0, 6.0))
        self.check(sphere, [(1.0, 0.0, 8.0), (2.9, 0.0, 8.0)], [(1.0, 0.0, 5.0), (3.1, 0.0, 8.0)])
        self.assertAlmostEqual(sphere.sdf([(1.0, 0.0, 11.0)])[0], 1.0, places=6)

    def test_radius_at(self):
        cone = tree.Envelope("CONE", (0, 0), 2.0, 0.0, 4.0)
        self.assertAlmostEqual(cone.radius_at(2.0), 1.0, places=2)
        self.assertEqual(cone.radius_at(5.0), 0.0)

    def test_topiary_surface_lies_on_the_envelope(self):
        for shape in ("SPHERE", "CONE", "HEART", "BELL"):
            envelope = tree.Envelope(shape, (0, 0), 1.5, 2.0, 6.0)
            verts, faces = tree.envelope_surface(envelope, 0.12)
            self.assertLess(np.abs(envelope.sdf(verts)).max(), 1e-3, shape)
            self.assertGreater(len(faces), 300)


SIZES = [
    dict(size="FULL"),
    dict(size="QUARTER"),
    dict(size="FULL_CENTRED", overhang=1.3, canopy_width=1.5),
    dict(size="LARGE", large_width=2, large_length=3),
]


class BoundsTests(unittest.TestCase):
    def test_blobs_stay_inside_the_footprint_and_height(self):
        for preset in ("BROADLEAF", "GNARLED_OAK", "WEEPING", "CYPRESS", "LAYERED", "SHRUB"):
            for size in SIZES:
                params = tree.preset_params(preset, lean_angle=25.0, **size)
                data = tree.generate(params)
                limit = params.overhang * data.half_width
                blobs = data.blobs
                reach = np.hypot(blobs[:, 0] - data.anchor[0], blobs[:, 1] - data.anchor[1])
                reach += blobs[:, 3] * np.maximum(blobs[:, 4], 1.0)
                label = "{} {}".format(preset, size)
                self.assertLessEqual(reach.max(), limit + 1e-6, label)
                self.assertLessEqual((blobs[:, 2] + blobs[:, 3] * blobs[:, 5]).max(), params.height + 1e-6, label)
                self.assertGreaterEqual((blobs[:, 2] - blobs[:, 3] * blobs[:, 5]).min(), -1e-6, label)

    def test_canopy_mesh_within_displacement_of_the_limits(self):
        for size in SIZES:
            params = tree.preset_params("BROADLEAF", **size)
            data, mesh = tree.build(params)
            leaves = mesh.verts[np.unique([i for f, m in zip(mesh.faces, mesh.material) if m == tree.LEAVES for i in f])]
            limit = params.overhang * data.half_width + tree.displacement_amplitude(params)
            reach = np.hypot(leaves[:, 0] - data.anchor[0], leaves[:, 1] - data.anchor[1])
            self.assertLessEqual(reach.max(), limit + 1e-6, size)
            self.assertLessEqual(leaves[:, 2].max(), params.height + 1e-6)

    def test_needles_stay_inside_the_footprint_and_height(self):
        # A palm leaning 25 degrees has its crown outside the footprint: no needles.
        for preset, lean in (("CONIFER", 25.0), ("SNOWY_CONIFER", 25.0), ("PALM", 10.0)):
            for size in SIZES:
                params = tree.preset_params(preset, lean_angle=lean, **size)
                data, mesh = tree.build(params)
                label = "{} {}".format(preset, size)
                self.assertEqual(len(data.blobs), 0, label)
                needles = mesh.verts[np.unique([i for f, m in zip(mesh.faces, mesh.material) if m != tree.TRUNK for i in f])]
                self.assertGreater(len(needles), 0, label)
                # The base corners may stick out by half a needle width.
                limit = params.overhang * data.half_width + params.needle_width
                reach = np.hypot(needles[:, 0] - data.anchor[0], needles[:, 1] - data.anchor[1])
                self.assertLessEqual(reach.max(), limit + 1e-6, label)
                self.assertLessEqual(needles[:, 2].max(), params.height + 1e-6, label)
                self.assertGreaterEqual(needles[:, 2].min(), -1e-6, label)

    def test_large_tree_is_centred_on_its_footprint(self):
        data = tree.generate(tree.make_params(size="LARGE", large_width=3, large_length=2))
        self.assertEqual(data.anchor, (-4.0, -2.0))
        self.assertEqual(data.half_width, 4.0)
        np.testing.assert_allclose(trunk(data).points[0], (-4.0, -2.0, 0.0))

    def test_height_warning(self):
        self.assertTrue(tree.generate(tree.make_params(height=14.0)).warnings())
        self.assertFalse(tree.generate(tree.make_params(height=14.0, size="LARGE")).warnings())


class PresetTests(unittest.TestCase):
    def test_every_preset_builds(self):
        for name, preset in tree.PRESETS.items():
            params = tree.preset_params(name)
            data, mesh = tree.build(params)
            roles = set(mesh.material)
            if params.trunk_length > 0:
                self.assertIn(tree.TRUNK, roles, name)
            if params.canopy_style != "NONE":
                self.assertIn(tree.LEAVES, roles, name)
            if params.accent_mode != "NONE":
                self.assertIn(tree.ACCENT, roles, name)
            self.assertLessEqual(data.skeleton.segments, tree.MAX_SEGMENTS, name)
            self.assertFalse(data.skeleton.capped, name)
            self.assertIn("outline_shades", preset["look"])
            for f in mesh.faces:
                self.assertGreaterEqual(len(set(f)), 3, name)
            self.assertLess(max(max(f) for f in mesh.faces), len(mesh.verts))

    def test_preset_parameters_exist(self):
        for preset in tree.PRESETS.values():
            tree.make_params(**preset["params"])
            for key in preset["colours"]:
                self.assertIn(key, tree.DEFAULT_COLOURS)

    def test_enum_values_are_valid(self):
        for preset in tree.PRESETS.values():
            for p in tree.PARAMETERS:
                if p.items and p.name in preset["params"]:
                    self.assertIn(preset["params"][p.name], [item[0] for item in p.items], p.name)


class MeshTests(unittest.TestCase):
    def test_tube_normals_point_outwards(self):
        polyline = tree.Polyline([(0, 0, 0), (0, 0, 1), (0.3, 0, 2)], [0.3, 0.2, 0.1])
        mesh = tree.tube(polyline, 6, cap_start=True)
        normals = tree.face_normals(mesh.verts, mesh.faces)
        centre = mesh.verts.mean(axis=0)
        for face, normal in zip(mesh.faces, normals):
            self.assertGreater(np.dot(mesh.verts[list(face)].mean(axis=0) - centre, normal), 0.0)
        self.assertEqual(len(mesh.uvs), len(mesh.faces))

    def test_base_normals_point_outwards(self):
        for style in ("MOUND", "POT"):
            mesh = tree.base_mesh(tree.make_params(base_style=style), 2.0, (0.0, 0.0))
            normals = tree.face_normals(mesh.verts, mesh.faces)
            # Volume by the divergence theorem is positive for outward normals.
            tris, _ = tree.triangles(mesh.faces)
            v = mesh.verts[tris]
            volume = np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0
            self.assertGreater(volume, 0.0, style)
            self.assertEqual(len(normals), len(mesh.faces))

    def test_metaball_settings_keep_the_isolated_radius(self):
        for merge in (0.1, 0.6, 1.0):
            threshold, stiffness, factor = tree.metaball_settings(merge)
            # Field of an element of radius `factor` at distance 1.
            field = stiffness * (1.0 - 1.0 / factor**2) ** 3
            self.assertAlmostEqual(field, threshold)
        self.assertLess(tree.metaball_settings(0.1)[2], tree.metaball_settings(0.9)[2])

    def test_needles_are_thin_upward_triangles(self):
        params = tree.preset_params("CONIFER", needle_width=0.02)
        data = tree.generate(params)
        verts, faces = tree.needle_surface(data)
        self.assertGreater(len(faces), 500)
        self.assertTrue(all(len(f) == 3 for f in faces))
        tris = verts[np.array(faces)]
        np.testing.assert_allclose(np.linalg.norm(tris[:, 1] - tris[:, 0], axis=1), 0.02)
        self.assertTrue((tree.face_normals(verts, faces)[:, 2] >= -1e-9).all())
        self.assertLessEqual(np.linalg.norm(tris[:, 2] - tris[:, 0], axis=1).max(), params.needle_length * 1.25 + 0.02)

    def test_needles_follow_spacing_and_hollow(self):
        def count(**values):
            return len(tree.needle_surface(tree.generate(tree.preset_params("CONIFER", **values)))[1])

        self.assertGreater(count(needle_spacing=0.05), 3 * count(needle_spacing=0.2))
        self.assertLess(count(hollow=0.6), 0.6 * count(hollow=0.0))

    def test_top_facing_share(self):
        verts, faces = tree.envelope_surface(tree.Envelope("ELLIPSOID", (0, 0), 2.0, 0.0, 4.0), 0.1)
        params = tree.make_params(accent_threshold=0.5, accent_amount=0.4)
        mask = tree.top_facing(verts, faces, params)
        up = tree.face_normals(verts, faces)[:, 2] >= 0.5
        self.assertFalse((mask & ~up).any())
        self.assertAlmostEqual(mask.sum() / up.sum(), 0.4, delta=0.02)

    def test_accent_dots(self):
        params = tree.preset_params("FLOWERING_SHRUB")
        _, mesh = tree.build(params)
        dots = mesh.material.count(tree.ACCENT)
        self.assertGreater(dots, 0)
        self.assertEqual(dots % 80, 0)

    def test_bases(self):
        for style in ("MOUND", "POT", "ROCKS"):
            _, mesh = tree.build(tree.make_params(base_style=style))
            self.assertIn(tree.BASE, mesh.material, style)
            self.assertGreaterEqual(mesh.verts[:, 2].min(), -1e-9)


class NoiseTests(unittest.TestCase):
    def test_range_continuity_and_seed(self):
        noise = tree.Noise(5)
        points = np.random.RandomState(0).uniform(-50, 50, (5000, 3))
        values = noise(points)
        self.assertLessEqual(np.abs(values).max(), 1.1)
        self.assertGreater(values.std(), 0.1)
        np.testing.assert_allclose(noise(np.zeros((1, 3))), 0.0)
        step = noise(points + 1e-4) - values
        self.assertLess(np.abs(step).max(), 1e-2)
        self.assertFalse(np.allclose(tree.Noise(6)(points), values))
        np.testing.assert_array_equal(tree.Noise(5)(points), values)
        self.assertLessEqual(np.abs(noise.fbm(points)).max(), 1.1)

    def test_stage_seeds_are_stable(self):
        self.assertEqual(tree.stage_seed(1, "trunk"), tree.stage_seed(1, "trunk"))
        self.assertNotEqual(tree.stage_seed(1, "trunk"), tree.stage_seed(1, "clumps"))
        self.assertEqual(tree.stage_seed(1, "trunk"), 2295934729)


if __name__ == "__main__":
    unittest.main()
