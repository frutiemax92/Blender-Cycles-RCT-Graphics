"""Reading RollerCoaster Tycoon 2 small scenery objects (``ObjData/*.DAT``).

A DAT file is a 16 byte object entry (flags, 8 character name, checksum)
followed by one Sawyer chunk: an encoding byte, a 32-bit length and the
encoded data. Decoded small scenery data is a 0x1C byte header, a string
table, the scenery group entry, optional frame offsets and an image table
in the g1 format. See OpenRCT2's SawyerChunkReader.cpp and
SmallSceneryObject::ReadLegacy.
"""

import os
import struct

import numpy as np

from . import g1

OBJECT_TYPE_SMALL_SCENERY = 1
#: SmallSceneryFlag::hasFrameOffsets.
FLAG_FRAME_OFFSETS = 1 << 15
#: RCT2 treats small scenery taller than this as a tree (ReadLegacy).
TREE_MIN_HEIGHT = 64
#: RCT2 language id of British English, preferred for names.
ENGLISH_UK = 0

_ENCODING_NONE, _ENCODING_RLE, _ENCODING_RLE_REPEAT, _ENCODING_ROTATE = range(4)


class SmallScenery:
    def __init__(self, identifier, name, flags, height, images):
        self.identifier = identifier
        self.name = name
        self.flags = flags
        #: Clearance in game z units.
        self.height = height
        #: List of :class:`g1.Sprite`.
        self.images = images

    @property
    def is_tree(self):
        return self.height > TREE_MIN_HEIGHT


def decode_chunk(data):
    """Decode a Sawyer chunk (header included); returns (bytes, bytes read)."""
    encoding, length = struct.unpack_from("<BI", data, 0)
    body = data[5 : 5 + length]
    if len(body) < length:
        raise ValueError("Truncated chunk")
    if encoding == _ENCODING_NONE:
        result = bytes(body)
    elif encoding == _ENCODING_RLE:
        result = _decode_rle(body)
    elif encoding == _ENCODING_RLE_REPEAT:
        result = _decode_repeat(_decode_rle(body))
    elif encoding == _ENCODING_ROTATE:
        result = _decode_rotate(body)
    else:
        raise ValueError("Unknown chunk encoding {}".format(encoding))
    return result, 5 + length


def _decode_rle(data):
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        length = 1 if code & 0x80 else code + 1
        if i + 1 + length > len(data):
            raise ValueError("Corrupt RLE chunk")
        if code & 0x80:
            out += bytes([data[i + 1]]) * (257 - code)
        else:
            out += data[i + 1 : i + 1 + length]
        i += 1 + length
    return bytes(out)


def _decode_repeat(data):
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0xFF:
            if i + 1 >= len(data):
                raise ValueError("Corrupt repeat chunk")
            out.append(data[i + 1])
            i += 2
        else:
            count = (data[i] & 7) + 1
            start = len(out) + (data[i] >> 3) - 32
            if start < 0 or start + count > len(out):
                raise ValueError("Corrupt repeat chunk")
            out += out[start : start + count]
            i += 1
    return bytes(out)


def _decode_rotate(data):
    out = bytearray(len(data))
    code = 1
    for i, value in enumerate(data):
        out[i] = ((value >> code) | (value << (8 - code))) & 0xFF
        code = (code + 2) % 8
    return bytes(out)


def object_type(path):
    """Object type of a DAT file from its entry flags (1 is small scenery)."""
    with open(path, "rb") as handle:
        header = handle.read(16)
    if len(header) < 16:
        return None
    return header[0] & 0x0F


def read_small_scenery(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) < 21 or raw[0] & 0x0F != OBJECT_TYPE_SMALL_SCENERY:
        raise ValueError("{} is not a small scenery object".format(os.path.basename(path)))
    identifier = raw[4:12].decode("latin-1").strip()
    data, _ = decode_chunk(raw[16:])

    flags, height = struct.unpack_from("<IB", data, 6)
    pos = 0x1C
    names = {}
    while data[pos] != 0xFF:
        language = data[pos]
        end = data.index(0, pos + 1)
        names.setdefault(language, data[pos + 1 : end].decode("cp1252", "replace").strip())
        pos = end + 1
    pos += 1 + 16  # string table end, scenery group entry
    if flags & FLAG_FRAME_OFFSETS:
        pos = data.index(0xFF, pos + 1) + 1
    name = names.get(ENGLISH_UK) or next(iter(names.values()), identifier)
    return SmallScenery(identifier, name, flags, height, read_image_table(data, pos))


def read_image_table(data, pos):
    count, size = struct.unpack_from("<II", data, pos)
    table = pos + 8
    base = table + count * g1.ENTRY.size
    images = []
    for i in range(count):
        offset, width, height, x, y, flags, _ = g1.ENTRY.unpack_from(data, table + i * g1.ENTRY.size)
        if width <= 0 or height <= 0:
            images.append(g1.Sprite(np.zeros((0, 0), dtype=np.uint8), x, y))
            continue
        images.append(g1.Sprite(g1.decode(data[base + offset :], width, height, flags), x, y))
    return images


def find_objdata(rct2_directory):
    """The ``ObjData`` folder of an RCT2 install, whatever its case."""
    if not rct2_directory or not os.path.isdir(rct2_directory):
        return None
    names = {name.lower(): name for name in os.listdir(rct2_directory)}
    if "objdata" not in names:
        return None
    return os.path.join(rct2_directory, names["objdata"])


#: Small scenery flags used to place the sprite (SmallSceneryFlag bits).
FLAG_FULL_TILE = 1 << 0
FLAG_VOFFSET_CENTRE = 1 << 1
FLAG_PROHIBIT_WALLS = 1 << 18
FLAG_HALF_TILE = 1 << 24
#: SceneryQuadrantOffsets (Scenery.cpp), indexed by (quadrant + rotation) & 3.
QUADRANT_OFFSETS = ((8, 8), (8, 24), (24, 24), (24, 8))


def paint_offset(flags, view, quadrant=0):
    """Game paint offset (x, y, z) of a small scenery sprite, as in Paint.SmallScenery.cpp."""
    if flags & FLAG_FULL_TILE:
        if flags & FLAG_HALF_TILE:
            return (3, 3, 0)
        if flags & FLAG_VOFFSET_CENTRE:
            return (1, 1, 0) if flags & FLAG_PROHIBIT_WALLS else (3, 3, 0)
        return (15, 15, 0)
    x, y = QUADRANT_OFFSETS[(quadrant + view) & 3]
    return (x - 1, y - 1, 0)


#: RCT2's own trees (file name without .DAT, name), for comparison previews.
VANILLA_TREES = (
    ("TAP", "Aleppo Pine"),
    ("TAC", "Arizona Cypress"),
    ("TAS", "Aspen"),
    ("TBP", "Black Poplar"),
    ("TCT", "Cabbage Tree"),
    ("TH1", "Canary Palm"),
    ("TCF", "Caucasian Fir"),
    ("TCL", "Cedar of Lebanon"),
    ("TCC", "Chinese Cedar"),
    ("TCO", "Common Oak"),
    ("TCY", "Common Yew"),
    ("TCRP", "Corsican Pine"),
    ("TEL", "European Larch"),
    ("TGHC", "Golden Hinoki Cypress"),
    ("THL", "Honey Locust"),
    ("TIC", "Incense Cedar"),
    ("TITC", "Italian Cypress"),
    ("TLC", "Lawson Cypress"),
    ("TLP", "Lombardy Poplar"),
    ("TMP", "Monkey-Puzzle"),
    ("TMC", "Monterey Cypress"),
    ("TMZP", "Montezuma Pine"),
    ("TNS", "Norway Spruce"),
    ("TPM", "Palm Tree"),
    ("TH2", "Palm Tree (Tall)"),
    ("TRF", "Red Fir"),
    ("TRF2", "Red Fir (Narrow)"),
    ("TSP", "Scots Pine"),
    ("TSB", "Silver Birch"),
    ("TCFS", "Snow-covered Caucasian Fir"),
    ("TNSS", "Snow-covered Norway Spruce"),
    ("TRFS", "Snow-covered Red Fir"),
    ("TVL", "Voss's Laburnum"),
    ("TWN", "Walnut"),
    ("TWW", "Weeping Willow"),
    ("TWP", "White Poplar"),
)


def find_object(objdata_directory, name):
    """``<name>.DAT`` in the ObjData folder, whatever its case."""
    if not objdata_directory or not os.path.isdir(objdata_directory):
        return None
    wanted = name.lower() + ".dat"
    for entry in os.listdir(objdata_directory):
        if entry.lower() == wanted:
            return os.path.join(objdata_directory, entry)
    return None
