"""Writing sprites and the OpenRCT2 ``images`` table."""

import json
import os

import numpy as np

from . import palette, png

IMAGES_DIR = "images"
IMAGES_JSON = "images.json"


def sprite_file_name(index):
    return "{:04d}.png".format(index)


def write_sprites(output_dir, sprites):
    """Write ``{image_index: Sprite}`` and merge them into images.json.

    Existing entries of images.json not rendered this time are kept, so an
    object can be rendered in several passes (e.g. walls then slopes).
    Returns the full images list.
    """
    image_dir = os.path.join(output_dir, IMAGES_DIR)
    os.makedirs(image_dir, exist_ok=True)

    json_path = os.path.join(output_dir, IMAGES_JSON)
    images = []
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as handle:
            images = json.load(handle)

    for index in sorted(sprites):
        sprite = sprites[index]
        while len(images) <= index:
            images.append("")
        if sprite.empty:
            # OpenRCT2 accepts an empty string for blank images.
            images[index] = ""
            continue
        name = sprite_file_name(index)
        png.write_indexed(os.path.join(image_dir, name), sprite.indices, palette.PALETTE)
        images[index] = {"path": IMAGES_DIR + "/" + name, "x": int(sprite.x), "y": int(sprite.y)}

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(images, handle, indent=4)
    return images


def load_sprites(output_dir):
    """Read back images.json and its PNGs as ``{index: (indices, x, y)}``."""
    json_path = os.path.join(output_dir, IMAGES_JSON)
    with open(json_path, "r", encoding="utf-8") as handle:
        images = json.load(handle)
    result = {}
    for index, entry in enumerate(images):
        if not isinstance(entry, dict):
            continue
        indices, _ = png.read_indexed(os.path.join(output_dir, entry["path"]))
        result[index] = (np.array(indices), entry["x"], entry["y"])
    return result
