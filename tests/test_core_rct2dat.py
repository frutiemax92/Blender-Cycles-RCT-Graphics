import os
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rct_cycles_graphics.core import g1, projection, rct2dat, terrain  # noqa: E402


def encode_rle(data):
    """Literal runs only, which the decoder must accept."""
    out = bytearray()
    for start in range(0, len(data), 128):
        chunk = data[start : start + 128]
        out += bytes([len(chunk) - 1]) + chunk
    return bytes(out)


def small_scenery_dat(name, title, flags, height, images, frame_offsets=None):
    """Bytes of a DAT file holding a raw-image small scenery object."""
    header = bytearray(0x1C)
    struct.pack_into("<IB", header, 6, flags, height)
    body = bytes(header)
    body += b"\x00" + title.encode("cp1252") + b"\x00" + b"\x01Other\x00" + b"\xff"
    body += bytes(16)
    if frame_offsets is not None:
        body += bytes(frame_offsets) + b"\xff"
    entries, data = b"", b""
    for indices, x, y in images:
        height_px, width = indices.shape
        entries += g1.ENTRY.pack(len(data), width, height_px, x, y, g1.FLAG_BMP, 0)
        data += indices.tobytes()
    body += struct.pack("<II", len(images), len(data)) + entries + data
    encoded = encode_rle(body)
    entry = bytes([rct2dat.OBJECT_TYPE_SMALL_SCENERY, 0, 0, 0]) + name.ljust(8).encode() + bytes(4)
    return entry + struct.pack("<BI", 1, len(encoded)) + encoded


class ChunkTests(unittest.TestCase):
    def test_rle_runs_and_repeats(self):
        # Literal "ab", then 3 x "c".
        data = bytes([1]) + b"ab" + bytes([257 - 3]) + b"c"
        self.assertEqual(rct2dat._decode_rle(data), b"abccc")
        # Literal "xy", then copy 2 bytes from 2 back.
        repeat = b"\xffx\xffy" + bytes([((32 - 2) << 3) | 1])
        self.assertEqual(rct2dat._decode_repeat(repeat), b"xyxy")
        for corrupt in (bytes([3]) + b"ab", bytes([257 - 3])):
            with self.assertRaises(ValueError):
                rct2dat._decode_rle(corrupt)
        with self.assertRaises(ValueError):
            rct2dat._decode_repeat(bytes([((32 - 2) << 3) | 1]))

    def test_rotate_undoes_rct2_rotation(self):
        plain = bytes(range(20))
        rotated = bytearray()
        code = 1
        for value in plain:
            rotated.append(((value << code) | (value >> (8 - code))) & 0xFF)
            code = (code + 2) % 8
        chunk = struct.pack("<BI", 3, len(rotated)) + bytes(rotated)
        self.assertEqual(rct2dat.decode_chunk(chunk), (plain, 5 + len(plain)))


class ObjectTests(unittest.TestCase):
    def test_reads_names_flags_and_images(self):
        images = [(np.full((3, 2), 70 + i, dtype=np.uint8), -1, -3) for i in range(4)]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "TTEST.DAT")
            with open(path, "wb") as handle:
                handle.write(small_scenery_dat("TTEST", "Test Tree", 0x1 | rct2dat.FLAG_FRAME_OFFSETS, 96, images, [0, 1]))
            self.assertEqual(rct2dat.find_object(directory, "ttest"), path)
            self.assertEqual(rct2dat.object_type(path), rct2dat.OBJECT_TYPE_SMALL_SCENERY)
            obj = rct2dat.read_small_scenery(path)
        self.assertEqual((obj.identifier, obj.name, obj.height), ("TTEST", "Test Tree", 96))
        self.assertTrue(obj.is_tree)
        self.assertEqual(len(obj.images), 4)
        np.testing.assert_array_equal(obj.images[2].indices, images[2][0])
        self.assertEqual((obj.images[2].x, obj.images[2].y), (-1, -3))

    def test_rejects_other_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "RIDE.DAT")
            with open(path, "wb") as handle:
                handle.write(bytes(32))
            with self.assertRaises(ValueError):
                rct2dat.read_small_scenery(path)

    def test_paint_offsets_follow_the_game(self):
        self.assertEqual(rct2dat.paint_offset(0x1, 0), (15, 15, 0))
        self.assertEqual(rct2dat.paint_offset(0x3, 2), (3, 3, 0))
        self.assertEqual(rct2dat.paint_offset(0x3 | rct2dat.FLAG_PROHIBIT_WALLS, 1), (1, 1, 0))
        self.assertEqual(rct2dat.paint_offset(0x1 | rct2dat.FLAG_HALF_TILE, 0), (3, 3, 0))
        # Quarter tile objects stay in their quadrant as the view turns.
        self.assertEqual([rct2dat.paint_offset(0x2, v) for v in range(4)], [(7, 7, 0), (7, 23, 0), (23, 23, 0), (23, 7, 0)])

    def test_vanilla_trees_are_unique(self):
        names = [name for name, _ in rct2dat.VANILLA_TREES]
        self.assertEqual(len(names), len(set(names)))


class LayoutTests(unittest.TestCase):
    def test_row_tiles_stand_side_by_side(self):
        for view in range(4):
            origin = projection.tile_top_vertex(0.0, 0.0, view)
            tiles = terrain.row_tiles(view, 4)
            tops = [projection.tile_top_vertex(x, y, view) for x, y in tiles]
            self.assertEqual([t[1] for t in tops], [origin[1]] * 4)
            self.assertEqual(sorted(t[0] - origin[0] for t in tops), [-128, -64, 64, 128])

    def test_row_tiles_skip_the_footprint(self):
        occupied = terrain.ground_tiles((2, 2), margin=0)
        for view in range(4):
            tiles = terrain.row_tiles(view, 3, occupied)
            self.assertEqual(len(tiles), 3)
            self.assertFalse(set(tiles) & set(occupied))

    def test_tiles_around(self):
        tiles = terrain.tiles_around([(0.0, 0.0), (4.0, -4.0)], margin=1)
        self.assertEqual(len(tiles), 9 + 9 - 4)
        self.assertIn((8.0, -8.0), tiles)


if __name__ == "__main__":
    unittest.main()
