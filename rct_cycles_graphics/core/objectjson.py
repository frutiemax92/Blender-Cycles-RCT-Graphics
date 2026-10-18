"""Building object.json and packing .parkobj files (plain zip archives)."""

import json
import os
import zipfile

import numpy as np

from . import export, jobs, palette

OBJECT_TYPES = {"SMALL": "scenery_small", "LARGE": "scenery_large", "WALL": "scenery_wall"}

_REMAP_FLAGS = {1: "hasPrimaryColour", 2: "hasSecondaryColour", 3: "hasTertiaryColour"}

# Boolean object.json flags offered as checkboxes, per object type, as
# (JSON key, label, description, default). They come from the ReadJson
# methods of SmallSceneryObject, LargeSceneryObject and WallObject in
# OpenRCT2. Flags that need extra sprites (canWither, hasGlass, doors,
# fountains, clocks, ...) or are computed by the add-on (colours, animation,
# shape) are left out. Large scenery tile flags are applied to every tile.
OBJECT_FLAGS = {
    "SMALL": (
        (
            "isStackable",
            "Stackable",
            "Can be raised with Shift and stacked on other objects or built over water "
            "(SmallSceneryPlaceAction rejects raised placement without it)",
            True,
        ),
        ("isRotatable", "Rotatable", "Can be rotated before placing", True),
        ("requiresFlatSurface", "Requires Flat Surface", "Cannot be placed on sloped land", False),
        ("prohibitWalls", "Prohibit Walls", "Walls cannot be built on the same tile", False),
        ("hasNoSupports", "No Supports", "Never draw wooden supports below the raised object", False),
        (
            "allowSupportsAbove",
            "Allow Supports Above",
            "Paths and track supports may be built on top of the object",
            False,
        ),
        (
            "supportsHavePrimaryColour",
            "Coloured Supports",
            "Draw the supports in the object's primary colour",
            False,
        ),
        (
            "isTree",
            "Tree",
            "Treated as a tree: protected by the no tree removal rule, exempt from the height limit",
            False,
        ),
        ("canBeWatered", "Can Be Watered", "Handymen water it", False),
    ),
    "LARGE": (
        ("hasSupports", "Supports", "Draw wooden supports below the raised object (all tiles)", False),
        (
            "allowSupportsAbove",
            "Allow Supports Above",
            "Paths and track supports may be built on top of the object (all tiles)",
            False,
        ),
        ("isPhotogenic", "Photogenic", "Guests take pictures of it", False),
        (
            "isTree",
            "Tree",
            "Treated as a tree: protected by the no tree removal rule, exempt from the height limit",
            False,
        ),
    ),
    "WALL": (
        ("isTransparent", "Transparent", "Guests can see through it, for the scenery rating", False),
    ),
}

_TILE_FLAGS = {"hasSupports", "allowSupportsAbove"}


def default_flags(object_type):
    return {key: default for key, _, _, default in OBJECT_FLAGS[object_type]}


def used_remaps(output_dir):
    """Remap numbers (1-3) present in the rendered sprites."""
    used = set()
    for indices, _, _ in export.load_sprites(output_dir).values():
        values = np.unique(indices)
        for remap, ramp in palette.REMAP_RANGES.items():
            if np.isin(values, list(ramp)).any():
                used.add(remap)
    return used


class ObjectInfo:
    """Everything needed to describe the object, gathered from the add-on settings."""

    def __init__(self, object_id, name, authors, object_type):
        self.object_id = object_id
        self.name = name
        self.authors = authors
        self.object_type = object_type
        self.version = "1.0"
        self.price = 10
        self.removal_price = 0
        self.clearance = 16
        self.remaps = set()
        self.shape = "FULL"
        self.frames = 1
        self.animation_delay = 2
        self.footprint = (1, 1)
        self.wall_double_sided = False
        self.wall_sloped = True
        self.scenery_group = ""
        self.flags = default_flags(object_type)


def properties_for(info):
    """The type specific ``properties`` block of object.json."""
    props = {"price": info.price}
    for remap in sorted(info.remaps):
        props[_REMAP_FLAGS[remap]] = True
    # Every exposed flag is written, false ones too, so unticking a box
    # also clears it from an existing object.json on re-export.
    flags = default_flags(info.object_type)
    flags.update((key, bool(value)) for key, value in info.flags.items() if key in flags)
    tile_flags = {key: flags.pop(key) for key in _TILE_FLAGS & set(flags)} if info.object_type == "LARGE" else {}
    props.update(flags)

    if info.object_type == "SMALL":
        shape = jobs.SMALL_SCENERY_SHAPES[info.shape]
        props["removalPrice"] = info.removal_price
        props["cursor"] = "CURSOR_STATUE_DOWN"
        props["height"] = int(info.clearance)
        props["shape"] = shape["shape"]
        props.update(shape["flags"])
        if info.frames > 1:
            mask = 1
            while mask < info.frames:
                mask <<= 1
            props["isAnimated"] = True
            props["SMALL_SCENERY_FLAG_VISIBLE_WHEN_ZOOMED"] = True
            props["animationDelay"] = int(info.animation_delay)
            props["animationMask"] = mask - 1
            props["numFrames"] = mask
            props["frameOffsets"] = [i % info.frames for i in range(mask)]
    elif info.object_type == "LARGE":
        props["removalPrice"] = info.removal_price
        props["cursor"] = "CURSOR_STATUE_DOWN"
        props["tiles"] = [
            {"x": tile["x"], "y": tile["y"], "z": 0, "clearance": int(info.clearance), **tile_flags}
            for tile in jobs.large_scenery_tiles(*info.footprint)
        ]
    elif info.object_type == "WALL":
        props["cursor"] = "CURSOR_FENCE_DOWN"
        # Wall heights are counted in clearance units of 8 z units.
        props["height"] = max(1, int(info.clearance) // 8)
        props["isAllowedOnSlope"] = bool(info.wall_sloped)
        props["isDoubleSided"] = bool(info.wall_double_sided)
    if info.scenery_group:
        props["sceneryGroup"] = info.scenery_group
    return props


def build_object(info, images, existing=None):
    """Return the object.json content.

    ``existing`` (a previously written or hand edited object.json) is kept
    as the base: only ``images`` and the properties the add-on computes are
    replaced, so manual additions survive re-exports.
    """
    data = dict(existing or {})
    data["id"] = info.object_id
    data.setdefault("authors", [a for a in info.authors if a])
    data.setdefault("version", info.version)
    data["objectType"] = OBJECT_TYPES[info.object_type]
    properties = dict(data.get("properties", {}))
    properties.update(properties_for(info))
    data["properties"] = properties
    strings = dict(data.get("strings", {}))
    names = dict(strings.get("name", {}))
    names["en-GB"] = info.name
    strings["name"] = names
    data["strings"] = strings
    data["images"] = images
    return data


def write_parkobj(output_dir, info):
    """Write object.json next to the sprites and pack ``<id>.parkobj``.

    Returns the path of the .parkobj file.
    """
    with open(os.path.join(output_dir, export.IMAGES_JSON), "r", encoding="utf-8") as handle:
        images = json.load(handle)

    object_path = os.path.join(output_dir, "object.json")
    existing = None
    if os.path.exists(object_path):
        with open(object_path, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    data = build_object(info, images, existing)
    with open(object_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)

    parkobj = os.path.join(output_dir, info.object_id + ".parkobj")
    with zipfile.ZipFile(parkobj, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(object_path, "object.json")
        for entry in images:
            if isinstance(entry, dict):
                archive.write(os.path.join(output_dir, entry["path"]), entry["path"])
    return parkobj
