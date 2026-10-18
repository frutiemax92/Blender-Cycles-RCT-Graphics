"""Reading sprites from RollerCoaster Tycoon 2's ``Data/g1.dat``.

The file is a header (entry count, data size), a table of 16 byte entries
(data offset, width, height, x/y offset, flags, zoomed offset) and the pixel
data. Sprites are either raw palette indices or run-length encoded: a table
of 16-bit row offsets, then per row runs of (length | 0x80 on the last run,
x start, pixels). See OpenRCT2's Drawing.Sprite.cpp and X8DrawingEngine.
"""

import configparser
import os
import struct

import numpy as np

HEADER = struct.Struct("<II")
ENTRY = struct.Struct("<IhhhhHH")

FLAG_BMP = 0x01
FLAG_RLE = 0x04

#: Flat grass tile with the grid drawn on its edges (Paint.Surface.h,
#: SPR_TERRAIN_GRASS_GRID; slope variant 0 is the flat tile).
GRASS_GRID = 1934
#: The same tile without grid lines.
GRASS = 1915


class Sprite:
    """Palette indices (0 transparent) and the offset of the top-left pixel."""

    def __init__(self, indices, x, y):
        self.indices = indices
        self.x = x
        self.y = y


def read_sprite(path, index):
    """Decode sprite ``index`` of the g1.dat at ``path``."""
    with open(path, "rb") as handle:
        count, size = HEADER.unpack(handle.read(HEADER.size))
        if not 0 <= index < count:
            raise ValueError("g1.dat has no image {}".format(index))
        handle.seek(HEADER.size + index * ENTRY.size)
        offset, width, height, x, y, flags, _ = ENTRY.unpack(handle.read(ENTRY.size))
        data_start = HEADER.size + count * ENTRY.size
        end = size
        if index + 1 < count:
            handle.seek(HEADER.size + (index + 1) * ENTRY.size)
            end = ENTRY.unpack(handle.read(ENTRY.size))[0]
        handle.seek(data_start + offset)
        # Entries are stored in data order, so the next offset bounds this one.
        data = handle.read(end - offset if end > offset else size - offset)
    return Sprite(decode(data, width, height, flags), x, y)


def decode(data, width, height, flags):
    indices = np.zeros((height, width), dtype=np.uint8)
    if flags & FLAG_RLE:
        for row in range(height):
            (pos,) = struct.unpack_from("<H", data, row * 2)
            while True:
                length, start = data[pos], data[pos + 1]
                run = length & 0x7F
                indices[row, start : start + run] = np.frombuffer(data, np.uint8, run, pos + 2)
                pos += 2 + run
                if length & 0x80:
                    break
    elif flags & FLAG_BMP:
        indices[...] = np.frombuffer(data, np.uint8, width * height).reshape(height, width)
    else:
        raise ValueError("Unsupported g1 sprite format (flags {:#x})".format(flags))
    return indices


def find_g1(rct2_directory):
    """``Data/g1.dat`` inside the RCT2 folder, whatever the case of its names."""
    if not rct2_directory or not os.path.isdir(rct2_directory):
        return None
    current = rct2_directory
    for part in ("data", "g1.dat"):
        names = {name.lower(): name for name in os.listdir(current)}
        if part not in names:
            return None
        current = os.path.join(current, names[part])
    return current if os.path.isfile(current) else None


def openrct2_game_path(openrct2_directory):
    """The RCT2 folder OpenRCT2 is set up with (``game_path`` in config.ini)."""
    path = os.path.join(openrct2_directory, "config.ini")
    if not os.path.isfile(path):
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
        value = parser.get("general", "game_path", fallback="")
    except (configparser.Error, UnicodeDecodeError):
        return None
    return value.strip().strip('"') or None


def default_openrct2_directories():
    home = os.path.expanduser("~")
    return [
        os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")), "OpenRCT2"),
        os.path.join(home, "Documents", "OpenRCT2"),
        os.path.join(home, "Library", "Application Support", "OpenRCT2"),
    ]
