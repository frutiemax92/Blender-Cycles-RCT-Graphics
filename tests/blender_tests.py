"""End-to-end tests that render through Cycles. Run inside Blender:

    blender -b --factory-startup --python tests/blender_tests.py

Exits with status 1 when a test fails.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import rct_cycles_graphics as addon  # noqa: E402
from rct_cycles_graphics import materials  # noqa: E402
from rct_cycles_graphics.core import export, jobs, palette, projection  # noqa: E402


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    bpy.ops.rct_graphics.initialize()
    props = bpy.context.scene.rct_graphics
    props.samples = 8
    props.check_after_render = False
    return bpy.context.scene, props


def tile_box(name="Box", size=(4.0, 4.0), height=projection.HEIGHT_STEP, center=(0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(center[0], center[1], height / 2.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0], size[1], height)
    return obj


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="rct_test_")
        self.scene, self.props = reset_scene()
        bpy.data.objects.remove(bpy.data.objects["Cube"])
        self.props.output_directory = self.out

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def render(self):
        self.assertEqual(bpy.ops.rct_graphics.render(), {"FINISHED"})
        return export.load_sprites(self.out)

    def test_small_scenery_offsets_match_the_game(self):
        tile_box()
        sprites = self.render()
        self.assertEqual(sorted(sprites), [0, 1, 2, 3])
        for indices, x, y in sprites.values():
            # A 16 z unit tall full tile box: 64 px wide, top corner 16 px up.
            self.assertEqual(indices.shape[1], 64)
            self.assertEqual((x, y), (-32, -31))

    def test_remap_materials_use_remap_ranges(self):
        box = tile_box()
        box.data.materials.append(bpy.data.materials.new("Plain"))
        box.data.materials.append(materials.new_remap_material(1))
        box.data.materials.append(materials.new_remap_material(3))
        for polygon in box.data.polygons:
            if polygon.normal.z > 0.5:
                polygon.material_index = 1
            elif polygon.normal.y < -0.5:
                polygon.material_index = 2
        indices = self.render()[0][0]
        values = set(np.unique(indices)) - {0}
        self.assertTrue(values & set(palette.REMAP_RANGES[1]))
        self.assertTrue(values & set(palette.REMAP_RANGES[3]))
        self.assertFalse(values & set(palette.REMAP_RANGES[2]))

    def test_large_scenery_tiles_recompose_the_preview(self):
        tile_box(size=(8.0, 4.0), center=(-2.0, 0.0))
        self.props.object_type = "LARGE"
        self.props.tiles_width = 2
        self.props.tiles_length = 1
        sprites = self.render()
        tiles = jobs.large_scenery_tiles(2, 1)
        for view in range(4):
            preview = _paint({}, sprites[view], projection.tile_top_vertex(0, 0, view))
            parts = {}
            for tile in tiles:
                top = projection.tile_top_vertex(tile["center"][0], tile["center"][1], view)
                _paint(parts, sprites[4 + 4 * tile["seq"] + view], top)
            self.assertEqual(preview, parts, "view {}".format(view))

    def test_wall_images(self):
        tile_box(size=(0.25, 4.0), height=2 * projection.HEIGHT_STEP, center=(1.875, 0.0))
        self.props.object_type = "WALL"
        self.props.wall_double_sided = True
        self.props.wall_sloped = True
        sprites = self.render()
        self.assertEqual(sorted(sprites), list(range(12)))
        flat, down, up = sprites[1][0], sprites[3][0], sprites[5][0]
        # Image 1 runs down-right on screen. Sloping upwards (towards game +y)
        # cancels the 16 px slant, sloping downwards doubles it.
        self.assertEqual(flat.shape[1], 34)
        self.assertAlmostEqual(up.shape[0], flat.shape[0] - 16, delta=1)
        self.assertAlmostEqual(down.shape[0], flat.shape[0] + 16, delta=1)

    def test_snap_and_alignment_report(self):
        box = tile_box(size=(3.7, 4.1), height=1.7)
        bpy.ops.rct_graphics.check_alignment()
        self.assertIn("FIX", self.props.alignment_report)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.rct_graphics.snap_to_grid()
        # 1.7 BU is 16.7 z units: rounded to two clearance units (16 z units).
        np.testing.assert_allclose(tuple(box.dimensions), (4.0, 4.0, projection.HEIGHT_STEP), atol=1e-5)
        self.render()
        bpy.ops.rct_graphics.check_alignment()
        self.assertNotIn("FIX", self.props.alignment_report)
        self.assertTrue(os.path.exists(os.path.join(self.out, "alignment_preview.png")))

    def test_snap_quarter_tile(self):
        box = tile_box(size=(3.7, 4.1), height=1.7, center=(0.5, -0.3))
        self.props.small_shape = "QUARTER"
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.rct_graphics.snap_to_grid()
        np.testing.assert_allclose(tuple(box.dimensions), (2.0, 2.0, projection.HEIGHT_STEP), atol=1e-5)
        np.testing.assert_allclose(tuple(box.location)[:2], (0.0, 0.0), atol=1e-5)
        self.render()
        bpy.ops.rct_graphics.check_alignment()
        self.assertNotIn("FIX", self.props.alignment_report)

    def test_parkobj(self):
        tile_box()
        self.props.object_id = "test.scenery_small.box"
        self.props.build_parkobj = True
        self.render()
        path = os.path.join(self.out, "test.scenery_small.box.parkobj")
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("object.json"))
            self.assertIn("images/0003.png", archive.namelist())
        self.assertEqual(data["properties"]["height"], 16)
        self.assertEqual(len(data["images"]), 4)
        self.assertIs(data["properties"]["isStackable"], True)
        self.props.flag_small_isStackable = False
        bpy.ops.rct_graphics.export_parkobj()
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("object.json"))
        self.assertIs(data["properties"]["isStackable"], False)


def _paint(store, sprite, top):
    indices, x, y = sprite
    ys, xs = np.nonzero(indices)
    for yy, xx in zip(ys.tolist(), xs.tolist()):
        key = (top[0] + x + xx, top[1] + y + yy)
        store[key] = int(indices[yy, xx])
    return store


if __name__ == "__main__":
    addon.register()
    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
