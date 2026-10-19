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
from rct_cycles_graphics import materials, render, tree_generator  # noqa: E402
from rct_cycles_graphics.core import export, jobs, palette, png, postprocess, projection, tree  # noqa: E402


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

    def test_face_edges_do_not_blend(self):
        # Edge pixels mixing two faces' colours show as seams in game once
        # blocks are stacked: every pixel must take a single face's colour.
        tile_box()
        self.props.samples = 64
        with render.Renderer(bpy.context) as renderer:
            result = renderer.render(0, 1)
        rgb = postprocess.unpremultiply(result.rgba)[result.opaque]
        # The three visible faces are the three most common brightnesses.
        lum = np.round(postprocess.luminance(rgb), 2)
        values, counts = np.unique(lum, return_counts=True)
        faces = np.array([np.median(rgb[lum == v], axis=0) for v in values[np.argsort(counts)[-3:]]])
        distance = np.min(np.linalg.norm(rgb[:, None] - faces[None], axis=-1), axis=1)
        # Noise stays within a few percent; blended edges are 50% off.
        self.assertLess(distance.max() / np.linalg.norm(faces, axis=-1).min(), 0.15)

    def test_stacked_blocks_fit_exactly(self):
        box = tile_box()
        low = self.render()
        bpy.data.objects.remove(box)
        tile_box(height=2 * projection.HEIGHT_STEP)
        tall = self.render()
        for view in range(4):
            stacked = _paint({}, low[view], (0, 0))
            _paint(stacked, low[view], (0, -16))
            self.assertEqual(set(stacked), set(_paint({}, tall[view], (0, 0))), "view {}".format(view))

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
        # The button renders the sprites again before packing them.
        os.remove(os.path.join(self.out, "images", "0003.png"))
        self.assertEqual(bpy.ops.rct_graphics.export_parkobj(), {"FINISHED"})
        self.assertTrue(os.path.exists(os.path.join(self.out, "images", "0003.png")))
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("object.json"))
        self.assertIs(data["properties"]["isStackable"], False)


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="rct_test_")
        self.scene, self.props = reset_scene()
        bpy.data.objects.remove(bpy.data.objects["Cube"])
        self.props.output_directory = self.out

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def edit(self, obj, **values):
        # Auto update defers changes made within 50 ms to a timer, which
        # never runs in background mode.
        for key, value in values.items():
            tree_generator._last_finished = 0.0
            setattr(obj.rct_tree, key, value)

    def add(self, preset="BROADLEAF"):
        self.scene.rct_tree_preset = preset
        self.assertEqual(bpy.ops.rct_graphics.tree_add(), {"FINISHED"})
        return bpy.context.active_object

    def test_every_preset(self):
        for preset in tree.PRESETS:
            obj = self.add(preset)
            mesh = obj.data
            self.assertEqual(len(mesh.materials), 4, preset)
            self.assertGreater(len(mesh.polygons), 0, preset)
            indices = np.empty(len(mesh.polygons), dtype=np.int32)
            mesh.polygons.foreach_get("material_index", indices)
            self.assertLess(indices.max(), 4, preset)
            for index in np.unique(indices):
                self.assertIsNotNone(mesh.materials[int(index)], preset)
            self.assertTrue(self.props.flag_small_isTree)
            bpy.data.objects.remove(obj)

    def test_regenerating_keeps_edited_materials(self):
        obj = self.add()
        leaves = obj.rct_tree.material_leaves
        node = leaves.node_tree.nodes[tree_generator.GROUP_NODE_NAME]
        node.inputs["Colour A"].default_value = (1.0, 0.0, 0.0, 1.0)
        obj.rct_tree.seed = 5
        bpy.ops.rct_graphics.tree_load_preset()
        self.assertIs(obj.data.materials[1], leaves)
        self.assertEqual(tuple(node.inputs["Colour A"].default_value), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(obj.rct_tree.seed, 5)

    def test_slot_edits_are_adopted(self):
        obj = self.add()
        custom = bpy.data.materials.new("Custom Bark")
        obj.material_slots[0].material = custom
        bpy.ops.rct_graphics.tree_regenerate()
        self.assertIs(obj.rct_tree.material_trunk, custom)
        self.assertIs(obj.data.materials[0], custom)

    def test_auto_update_and_cleanup(self):
        obj = self.add()
        faces = len(obj.data.polygons)
        for seed in range(20):
            self.edit(obj, seed=seed + 2)
        self.edit(obj, branch_count=12)
        self.assertNotEqual(len(obj.data.polygons), faces)
        self.assertEqual(len(bpy.data.metaballs), 0)
        self.assertFalse([o for o in bpy.data.objects if o.name.startswith(tree_generator.METABALL_NAME)])
        self.assertFalse([m.name for m in bpy.data.meshes if m.users == 0 and m.name.startswith(tree_generator.TREE_NAME)])

    def test_make_unique(self):
        first = self.add()
        second = self.add()
        self.assertIs(first.rct_tree.material_leaves, second.rct_tree.material_leaves)
        bpy.ops.rct_graphics.tree_make_unique()
        self.assertIsNot(first.rct_tree.material_leaves, second.rct_tree.material_leaves)
        self.assertIs(second.data.materials[1], second.rct_tree.material_leaves)

    def test_remap_leaves_render(self):
        obj = self.add()
        obj.rct_tree.colour_leaves = "1"
        self.assertEqual(materials.get_remap(obj.rct_tree.material_leaves), 1)
        self.props.object_id = "test.scenery_small.tree"
        self.props.build_parkobj = True
        sprites = self.render()
        self.assertEqual(sorted(sprites), [0, 1, 2, 3])
        self.assertTrue(set(np.unique(sprites[0][0])) & set(palette.REMAP_RANGES[1]))
        path = os.path.join(self.out, "test.scenery_small.tree.parkobj")
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("object.json"))
        self.assertIs(data["properties"]["hasPrimaryColour"], True)
        self.assertIs(data["properties"]["isTree"], True)

    def test_quarter_and_large_trees(self):
        obj = self.add("SHRUB")
        self.edit(obj, size="QUARTER")
        self.assertEqual(self.props.small_shape, "QUARTER")
        self.assertEqual(len(self.render()), 4)
        co = _vertices(obj)
        self.assertLess(np.abs(co[:, :2]).max(), 1.0 + tree.displacement_amplitude(tree_generator.to_params(obj.rct_tree)))
        bpy.data.objects.remove(obj)
        obj = self.add("BROADLEAF")
        self.edit(obj, size="LARGE")
        co = _vertices(obj)
        centre = (co.min(axis=0) + co.max(axis=0))[:2] / 2.0
        np.testing.assert_allclose(centre, (-2.0, -2.0), atol=0.5)
        self.assertEqual((self.props.object_type, self.props.tiles_width, self.props.tiles_length), ("LARGE", 2, 2))
        self.assertTrue(self.props.flag_large_isTree)
        self.assertEqual(len(self.render()), 4 + 4 * 4)

    def test_terrain_preview(self):
        self.add()
        # The button renders the sprites first.
        self.assertEqual(bpy.ops.rct_graphics.terrain_preview(margin=1, scale=1), {"FINISHED"})
        indices, _ = png.read_indexed(os.path.join(self.out, "images", "0000.png"))
        image = bpy.data.images["RCT Terrain Preview"]
        width, height = image.size
        # Four views of 3 x 3 tiles (192 px wide each) plus spacing.
        self.assertGreaterEqual(width, 4 * 192 + 3 * 8)
        self.assertGreater(height, indices.shape[0])
        pixels = np.array(image.pixels[:]).reshape(height, width, 4)
        greens = np.round(palette.PALETTE[70:75] / 255.0, 3)
        rgb = np.round(pixels[..., :3], 3).reshape(-1, 3)
        grass = (rgb[:, None, :] == greens[None, :, :]).all(axis=-1).any(axis=-1)
        self.assertGreater(grass.sum(), 4 * 9 * 1024 // 4)

    def test_scene_mismatch(self):
        obj = self.add()
        self.assertTrue(tree_generator.matches_scene(obj.rct_tree, self.props))
        self.props.small_shape = "HALF"
        self.assertFalse(tree_generator.matches_scene(obj.rct_tree, self.props))
        bpy.ops.rct_graphics.tree_match_scene()
        self.assertEqual(self.props.small_shape, "FULL")

    def test_hair_canopy(self):
        obj = self.add("HAIR_PALM")
        settings = obj.rct_tree
        hair = settings.hair_object
        self.assertIs(hair.parent, obj)
        self.assertFalse(hair.show_instancer_for_render)
        self.assertIs(hair.data.materials[0], settings.material_leaves)
        evaluated = hair.evaluated_get(bpy.context.evaluated_depsgraph_get())
        psys = evaluated.particle_systems[0]
        self.assertEqual(len(psys.particles), len(hair.data.polygons))
        self.assertEqual(settings.stat_strands, len(hair.data.polygons) * (1 + settings.hair_children))
        # Each strand grows along its emitter triangle to its own length
        # (co_hair reads the children instead when there are any).
        self.edit(obj, hair_children=0)
        evaluated = hair.evaluated_get(bpy.context.evaluated_depsgraph_get())
        psys = evaluated.particle_systems[0]
        data, _ = tree.build(tree_generator.to_params(settings))
        steps = 2**psys.settings.display_step
        tips = np.array([psys.co_hair(evaluated, particle_no=i, step=steps) for i in range(len(psys.particles))])
        expected = data.strands.tips
        nearest = np.linalg.norm(tips[:, None, :] - expected[None, :, :], axis=-1).min(axis=1)
        self.assertLess(nearest.max(), 0.02)

        sprites = self.render()
        self.assertEqual(len(sprites), 4)
        custom = bpy.data.materials.new("Custom Fronds")
        settings.material_leaves = custom
        self.assertIs(hair.data.materials[0], custom)

        self.edit(obj, canopy_style="BLOBS")
        self.assertIsNone(settings.hair_object)
        self.assertNotIn(tree_generator.HAIR_NAME, [o.name for o in bpy.data.objects])
        self.assertEqual(len(bpy.data.particles), 0)
        self.assertFalse([m for m in bpy.data.meshes if m.users == 0 and m.name.startswith(tree_generator.HAIR_NAME)])

    def test_strand_shadows_and_hair_shading(self):
        obj = self.add("HAIR_BROADLEAF")
        hair = obj.rct_tree.hair_object
        self.assertTrue(hair.visible_shadow)
        self.edit(obj, hair_shadows=False)
        self.assertFalse(hair.visible_shadow)
        group = obj.rct_tree.material_leaves.node_tree.nodes[tree_generator.GROUP_NODE_NAME].node_tree
        self.assertTrue([n for n in group.nodes if n.type == "HAIR_INFO"])

    def test_leaf_instances(self):
        obj = self.add("LEAFY_BROADLEAF")
        settings = obj.rct_tree
        self.assertIsNone(settings.hair_object)
        mesh = obj.data
        attribute = mesh.attributes[tree_generator.LEAF_ATTRIBUTE]
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        attribute.data.foreach_get("vector", values)
        flags = values.reshape(-1, 3)[:, 2]
        self.assertTrue(0 < flags.sum() < len(flags))
        self.assertEqual(settings.stat_strands, settings.hair_count)
        group = settings.material_leaves.node_tree.nodes[tree_generator.GROUP_NODE_NAME].node_tree
        names = [n.attribute_name for n in group.nodes if n.type == "ATTRIBUTE"]
        self.assertEqual(names, [tree_generator.LEAF_ATTRIBUTE])
        self.assertEqual(len(self.render()), 4)

        # A custom leaf: one quad per leaf.
        self.edit(obj, hair_count=100, leaf_shape="CUSTOM")
        self.assertIn("Leaf Object", settings.warnings)
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.5, 0.0, 0.0))
        bpy.ops.object.transform_apply(location=True)
        leaf = bpy.context.active_object
        leaf.hide_render = True
        bpy.context.view_layer.objects.active = obj
        self.edit(obj, leaf_object=leaf)
        leaves = sum(1 for p in obj.data.polygons if p.material_index == tree.LEAVES)
        self.assertEqual(leaves, settings.stat_strands)
        self.assertNotIn("Leaf Object", settings.warnings)
        leaf.hide_render = False
        tree_generator.regenerate(obj)
        self.assertIn("hide it from renders", settings.warnings)

    def test_make_leaf_object(self):
        obj = self.add("ROSETTE_BROADLEAF")
        settings = obj.rct_tree
        before = np.empty(len(obj.data.vertices) * 3)
        obj.data.vertices.foreach_get("co", before)
        self.assertEqual(bpy.ops.rct_graphics.tree_make_leaf_object(), {"FINISHED"})
        leaf = settings.leaf_object
        self.assertEqual(settings.leaf_shape, "CUSTOM")
        self.assertTrue(leaf.hide_render)
        self.assertEqual(len(leaf.data.polygons), len(tree.leaf_template("ROSETTE", settings.leaf_width)[1]))
        self.assertFalse([w for w in settings.warnings.split("\n") if "Leaf Object" in w])
        # The editable copy gives the same tree as the built-in shape.
        after = np.empty(len(obj.data.vertices) * 3)
        obj.data.vertices.foreach_get("co", after)
        np.testing.assert_allclose(after, before, atol=1e-5)
        self.assertFalse(bpy.ops.rct_graphics.tree_make_leaf_object.poll())

    def test_old_role_groups_are_replaced(self):
        name = "{} {}".format(tree_generator.TREE_NAME, tree.ROLES[tree.LEAVES])
        old = tree_generator._build_role_group(name, tree.TRUNK)
        material = bpy.data.materials.new("Old Leaves")
        material.use_nodes = True
        node = material.node_tree.nodes.new("ShaderNodeGroup")
        node.node_tree = old
        group = tree_generator.role_group(tree.LEAVES)
        self.assertEqual(group.name, name)
        self.assertIs(node.node_tree, group)
        self.assertEqual(group["rct_version"], tree_generator.ROLE_GROUP_VERSION)
        self.assertEqual(len([g for g in bpy.data.node_groups if g.name.startswith(name)]), 1)
        self.assertIs(tree_generator.role_group(tree.LEAVES), group)

    def test_hair_broadleaf_look(self):
        obj = self.add("HAIR_BROADLEAF")
        self.assertTrue(tree_generator.look_differs(obj.rct_tree, self.props))
        bpy.ops.rct_graphics.tree_use_look()
        self.assertFalse(tree_generator.look_differs(obj.rct_tree, self.props))
        self.assertEqual(self.props.palette_mode, "CUSTOM")

    def test_hair_object_survives_regeneration_and_duplication(self):
        obj = self.add("HAIR_PALM")
        hair = obj.rct_tree.hair_object
        self.edit(obj, hair_count=200, hair_children=3)
        self.assertIs(obj.rct_tree.hair_object, hair)
        self.assertEqual(len(hair.data.polygons), 200)
        self.assertEqual(hair.particle_systems[0].settings.rendered_child_count, 3)
        copy = obj.copy()
        copy.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(copy)
        tree_generator.regenerate(copy)
        self.assertIsNot(copy.rct_tree.hair_object, hair)
        self.assertIs(copy.rct_tree.hair_object.parent, copy)
        self.assertIs(hair.parent, obj)

    def test_apply_freezes_the_mesh(self):
        obj = self.add()
        mesh = obj.data
        bpy.ops.rct_graphics.tree_apply("EXEC_DEFAULT")
        self.assertFalse(obj.rct_tree.enabled)
        self.edit(obj, seed=9)
        self.assertIs(obj.data, mesh)

    def render(self):
        self.assertEqual(bpy.ops.rct_graphics.render(), {"FINISHED"})
        return export.load_sprites(self.out)


def _vertices(obj):
    co = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


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
