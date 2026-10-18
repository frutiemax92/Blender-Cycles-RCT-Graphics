import json
import os
import sys
import tempfile
import unittest
import zipfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import export, objectjson, postprocess  # noqa: E402


class ObjectJsonTests(unittest.TestCase):
    def test_small_scenery_properties(self):
        info = objectjson.ObjectInfo("me.scenery_small.block", "Block", ["Me"], "SMALL")
        info.remaps = {1, 2}
        info.clearance = 16
        props = objectjson.properties_for(info)
        self.assertEqual(props["shape"], "4/4")
        self.assertEqual(props["height"], 16)
        self.assertTrue(props["hasPrimaryColour"] and props["hasSecondaryColour"])
        self.assertNotIn("hasTertiaryColour", props)

    def test_small_scenery_is_stackable_by_default(self):
        props = objectjson.properties_for(objectjson.ObjectInfo("a.b.c", "A", [], "SMALL"))
        self.assertIs(props["isStackable"], True)
        self.assertIs(props["isRotatable"], True)
        self.assertIs(props["prohibitWalls"], False)

    def test_flags_follow_the_object_type(self):
        info = objectjson.ObjectInfo("a.b.c", "A", [], "SMALL")
        info.flags["isStackable"] = False
        info.flags["isTree"] = True
        info.shape = "FULL_CENTRED_NO_WALLS"
        props = objectjson.properties_for(info)
        self.assertIs(props["isStackable"], False)
        self.assertIs(props["isTree"], True)
        self.assertIs(props["prohibitWalls"], True)

        info = objectjson.ObjectInfo("a.b.c", "A", [], "LARGE")
        info.flags.update(hasSupports=True, isPhotogenic=True)
        props = objectjson.properties_for(info)
        self.assertIs(props["isPhotogenic"], True)
        self.assertNotIn("hasSupports", props)
        self.assertNotIn("isStackable", props)
        self.assertTrue(all(t["hasSupports"] and not t["allowSupportsAbove"] for t in props["tiles"]))

        info = objectjson.ObjectInfo("a.b.c", "A", [], "WALL")
        info.flags["isTransparent"] = True
        self.assertIs(objectjson.properties_for(info)["isTransparent"], True)

    def test_unticked_flag_clears_existing_object_json(self):
        info = objectjson.ObjectInfo("a.b.c", "A", [], "SMALL")
        info.flags["isTree"] = False
        data = objectjson.build_object(info, [], {"properties": {"isTree": True}})
        self.assertIs(data["properties"]["isTree"], False)

    def test_animation_frame_offsets_cover_the_mask(self):
        info = objectjson.ObjectInfo("a.b.c", "A", [], "SMALL")
        info.frames = 3
        props = objectjson.properties_for(info)
        self.assertEqual(props["animationMask"], 3)
        self.assertEqual(props["frameOffsets"], [0, 1, 2, 0])
        self.assertTrue(props["SMALL_SCENERY_FLAG_VISIBLE_WHEN_ZOOMED"])

    def test_large_scenery_tiles_and_wall_height(self):
        info = objectjson.ObjectInfo("a.b.c", "A", [], "LARGE")
        info.footprint = (2, 1)
        info.clearance = 40
        tiles = objectjson.properties_for(info)["tiles"]
        self.assertEqual([(t["x"], t["y"], t["clearance"]) for t in tiles], [(0, 0, 40), (32, 0, 40)])
        info.object_type = "WALL"
        self.assertEqual(objectjson.properties_for(info)["height"], 5)

    def test_existing_fields_survive(self):
        info = objectjson.ObjectInfo("a.b.c", "Name", ["Me"], "SMALL")
        existing = {"id": "old", "properties": {"canWither": True, "price": 99}, "strings": {"name": {"fr-FR": "Nom"}}}
        data = objectjson.build_object(info, ["x"], existing)
        self.assertEqual(data["id"], "a.b.c")
        self.assertTrue(data["properties"]["canWither"])
        self.assertEqual(data["properties"]["price"], 10)
        self.assertEqual(data["strings"]["name"], {"fr-FR": "Nom", "en-GB": "Name"})

    def test_write_parkobj(self):
        with tempfile.TemporaryDirectory() as tmp:
            sprite = postprocess.Sprite(np.full((2, 2), 248, dtype=np.uint8), -1, -2)
            export.write_sprites(tmp, {0: sprite, 1: sprite})
            info = objectjson.ObjectInfo("me.scenery_small.test", "Test", ["Me"], "SMALL")
            info.remaps = objectjson.used_remaps(tmp)
            self.assertEqual(info.remaps, {1})
            path = objectjson.write_parkobj(tmp, info)
            with zipfile.ZipFile(path) as archive:
                names = sorted(archive.namelist())
                data = json.loads(archive.read("object.json"))
        self.assertEqual(names, ["images/0000.png", "images/0001.png", "object.json"])
        self.assertEqual(data["objectType"], "scenery_small")
        self.assertEqual(data["images"][1]["y"], -2)


if __name__ == "__main__":
    unittest.main()
