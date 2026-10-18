import os
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import alignment, g1, jobs, palette, projection, terrain  # noqa: E402


def write_g1(path, sprites):
    """Write a g1.dat holding ``[(indices, x, y, rle)]``."""
    blobs = []
    for indices, _, _, rle in sprites:
        if not rle:
            blobs.append(indices.tobytes())
            continue
        rows = []
        for row in indices:
            runs = b""
            columns = np.nonzero(row)[0]
            if len(columns) == 0:
                runs = bytes([0x80, 0])
            else:
                start, end = columns.min(), columns.max() + 1
                runs = bytes([0x80 | (end - start), start]) + row[start:end].tobytes()
            rows.append(runs)
        table, offset = b"", 2 * len(rows)
        for runs in rows:
            table += struct.pack("<H", offset)
            offset += len(runs)
        blobs.append(table + b"".join(rows))
    data, entries = b"", b""
    for (indices, x, y, rle), blob in zip(sprites, blobs):
        height, width = indices.shape
        entries += g1.ENTRY.pack(len(data), width, height, x, y, g1.FLAG_RLE if rle else g1.FLAG_BMP, 0)
        data += blob
    with open(path, "wb") as handle:
        handle.write(g1.HEADER.pack(len(sprites), len(data)) + entries + data)


class G1Tests(unittest.TestCase):
    def test_decodes_raw_and_rle_sprites(self):
        raw = np.arange(12, dtype=np.uint8).reshape(3, 4)
        grass = terrain.fallback_grass()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "g1.dat")
            write_g1(path, [(raw, 1, 2, False), (grass, -32, 0, True)])
            first = g1.read_sprite(path, 0)
            second = g1.read_sprite(path, 1)
            with self.assertRaises(ValueError):
                g1.read_sprite(path, 2)
        np.testing.assert_array_equal(first.indices, raw)
        self.assertEqual((first.x, first.y), (1, 2))
        np.testing.assert_array_equal(second.indices, grass)
        self.assertEqual((second.x, second.y), (-32, 0))

    def test_finds_g1_from_openrct2_config(self):
        with tempfile.TemporaryDirectory() as directory:
            game = os.path.join(directory, "Rollercoaster Tycoon 2")
            os.makedirs(os.path.join(game, "Data"))
            open(os.path.join(game, "Data", "g1.dat"), "wb").close()
            user = os.path.join(directory, "OpenRCT2")
            os.makedirs(user)
            with open(os.path.join(user, "config.ini"), "w") as handle:
                handle.write('[general]\ngame_path = "{}"\n'.format(game))
            self.assertEqual(g1.openrct2_game_path(user), game)
            self.assertEqual(g1.find_g1(game), os.path.join(game, "Data", "g1.dat"))
            self.assertIsNone(g1.find_g1(user))
            self.assertIsNone(g1.openrct2_game_path(game))


class TerrainTests(unittest.TestCase):
    def test_fallback_grass_fills_a_tile_with_a_darker_grid(self):
        indices, x, y = terrain.fallback_grass()
        self.assertEqual(indices.shape, (31, 64))
        self.assertEqual((x, y), (-32, 0))
        mask = terrain.tile_mask()
        self.assertTrue((indices[mask] >= 70).all() and (indices[mask] <= 74).all())
        self.assertTrue((indices[~mask] == palette.TRANSPARENT).all())
        edge = mask & ~terrain.tile_mask(inset=2)
        self.assertTrue((indices[edge] <= 73).all())
        # Same pixel count as the game's SPR_TERRAIN_GRASS_GRID.
        self.assertEqual(mask.sum(), 1024)

    def test_ground_tiles_surround_the_footprint(self):
        tiles = terrain.ground_tiles((2, 1), margin=1)
        self.assertEqual(len(tiles), 4 * 3)
        self.assertIn((0.0, 0.0), tiles)
        self.assertIn((-8.0, 0.0), tiles)
        self.assertIn((4.0, 4.0), tiles)

    def test_sprite_stands_on_its_tile(self):
        ground = terrain.fallback_grass()
        tiles = terrain.ground_tiles(margin=0)
        sprite = np.full((4, 2), 166, dtype=np.uint8)
        for view in range(4):
            job = jobs.small_scenery("FULL")[view]
            ax, ay = job.anchor()
            # Bottom pixel of the sprite on the game's paint anchor.
            sprites = {view: (sprite, -1, -4)}
            canvas = terrain.compose_view(view, ground, tiles, sprites, [(view, (ax, ay), job.tile_center)], margin=0)
            red = np.all(canvas[..., :3] == palette.PALETTE[166], axis=-1)
            grass = np.isin(canvas[..., 1], palette.PALETTE[70:75, 1])
            self.assertEqual(red.sum(), 8)
            ys, xs = np.nonzero(red)
            # Full tile objects are anchored 15 units in, one pixel above the
            # tile's centre: the sprite's bottom row sits on the grass.
            self.assertTrue(grass[ys.max() + 1, xs].all())
            self.assertEqual(canvas.shape[:2], (31, 64))

    def test_back_tiles_are_drawn_first(self):
        ground = terrain.fallback_grass()
        tiles = terrain.ground_tiles((2, 1), margin=0)
        sprite = np.full((40, 40), 1, dtype=np.uint8)
        near = np.full((40, 40), 2, dtype=np.uint8)
        view = 0
        placements = []
        for seq, centre in enumerate(((0.0, 0.0), (-4.0, 0.0))):
            top = projection.tile_top_vertex(centre[0], centre[1], view)
            placements.append((seq, top, centre))
        sprites = {0: (sprite, -20, 0), 1: (near, -20, 0)}
        canvas = terrain.compose_view(view, ground, tiles, sprites, placements, margin=0)
        # Game x grows towards Blender -X: tile 1 is in front in view 0.
        front = projection.tile_top_vertex(-4.0, 0.0, view)
        back = projection.tile_top_vertex(0.0, 0.0, view)
        self.assertGreater(front[1], back[1])
        colours = {tuple(c) for c in canvas[..., :3].reshape(-1, 3)}
        self.assertIn(tuple(palette.PALETTE[2]), colours)
        self.assertIn(tuple(palette.PALETTE[1]), colours)

    def test_sheet_aligns_bottoms_and_scales(self):
        views = [np.full((h, 5, 4), 200, dtype=np.uint8) for h in (3, 6)]
        sheet = terrain.preview_sheet(views, spacing=2, scale=2)
        self.assertEqual(sheet.shape, (12, 24, 4))
        self.assertTrue((sheet[:6, :10] == alignment.BACKGROUND).all())
        self.assertTrue((sheet[6:, :10] == 200).all())


if __name__ == "__main__":
    unittest.main()
