"""Previewing sprites standing on the game's grass, in all four views.

Every sprite is placed at its paint anchor (the projection of the tile's top
corner plus the paint offset, see :mod:`jobs`), the same screen space the
grass tiles are drawn in, so the composite matches what OpenRCT2 shows with
gridlines on.
"""

import numpy as np

from . import alignment, palette, projection

#: Grass ramp indices (palette 70-81) of the game's grass tile; its grid
#: lines darken the edge pixels by one shade.
_GRASS_SHADES = (71, 72, 73, 74)


def tile_mask(inset=0):
    """Pixels of a flat 64 x 31 ground tile, as drawn by the game.

    inset: pixels taken off both ends of every row (the grid is 2 wide).
    """
    rows = np.arange(31)[:, None]
    cols = np.arange(64)[None, :]
    half = 2 + 2 * np.minimum(rows, 30 - rows) - inset
    return np.abs(cols - 31.5) < half


def fallback_grass(grid=True, seed=1):
    """A grass tile in the game's palette, for when g1.dat is not available.

    Returns (indices, x, y) with the offset relative to the tile's top corner,
    like SPR_TERRAIN_GRASS_GRID.
    """
    mask = tile_mask()
    rng = np.random.default_rng(seed)
    indices = np.where(mask, rng.choice(_GRASS_SHADES, size=mask.shape), 0).astype(np.uint8)
    if grid:
        edge = mask & ~tile_mask(inset=2)
        indices[edge] -= 1
    return indices, -32, 0


def ground_tiles(footprint=(1, 1), margin=2):
    """Blender centres of the tiles under a footprint plus ``margin`` tiles around it."""
    width, length = footprint
    size = projection.TILE_SIZE
    return [
        (-size * i, -size * j)
        for i in range(-margin, width + margin)
        for j in range(-margin, length + margin)
    ]


def tiles_around(centres, margin=2):
    """Blender centres of every tile within ``margin`` tiles of the given ones."""
    size = projection.TILE_SIZE
    cells = set()
    for cx, cy in centres:
        i, j = int(round(cx / size)), int(round(cy / size))
        for di in range(-margin, margin + 1):
            for dj in range(-margin, margin + 1):
                cells.add((i + di, j + dj))
    return [(size * i, size * j) for i, j in sorted(cells)]


def row_tiles(view, count, occupied=()):
    """``count`` tile centres beside the origin tile, on one screen row of ``view``.

    The tiles alternate right and left of the origin, one tile apart, so
    objects placed on them stand side by side at the same depth. Tiles in
    ``occupied`` (Blender centres) are skipped.
    """
    angle = projection.view_angle(view)
    c, s = round(np.cos(angle)), round(np.sin(angle))
    taken = {(round(x), round(y)) for x, y in occupied}
    result = []
    step = 1
    while len(result) < count:
        for k in (step, -step):
            # Screen right in view 0 is (+X, -Y); rotate it into Blender space.
            vx, vy = k * projection.TILE_SIZE, -k * projection.TILE_SIZE
            centre = (vx * c - vy * s, vx * s + vy * c)
            if (round(centre[0]), round(centre[1])) not in taken and len(result) < count:
                result.append(centre)
        step += 1
    return result


def compose_view(view, ground, tiles, sprites, placements, margin=8):
    """Grass tiles plus the sprites of one view.

    ground: (indices, x, y) of the tile sprite relative to the tile top corner.
    tiles: Blender centres of the ground tiles.
    sprites: {image: (indices, x, y)} as stored in images.json.
    placements: [(image, (anchor_x, anchor_y), tile_centre)], drawn back to
    front by tile.
    """
    layers = []
    ground_indices, gx, gy = ground
    for cx, cy in tiles:
        tx, ty = projection.tile_top_vertex(cx, cy, view)
        layers.append((tx + gx, ty + gy, ground_indices))

    def depth(placement):
        tx, ty = projection.tile_top_vertex(placement[2][0], placement[2][1], view)
        return ty, tx

    for image, (ax, ay), _ in sorted(placements, key=depth):
        indices, x, y = sprites[image]
        if indices.size:
            layers.append((ax + x, ay + y, indices))

    min_x = min(left for left, _, _ in layers) - margin
    min_y = min(top for _, top, _ in layers) - margin
    max_x = max(left + i.shape[1] for left, _, i in layers) + margin
    max_y = max(top + i.shape[0] for _, top, i in layers) + margin
    canvas = np.zeros((max_y - min_y, max_x - min_x, 4), dtype=np.uint8)
    canvas[...] = alignment.BACKGROUND
    for left, top, indices in layers:
        h, w = indices.shape
        region = canvas[top - min_y : top - min_y + h, left - min_x : left - min_x + w]
        opaque = indices != palette.TRANSPARENT
        region[opaque] = alignment.colourize(indices)[opaque]
    return canvas


def preview_sheet(views, spacing=8, scale=1):
    """The view composites side by side, bottoms aligned, optionally enlarged."""
    height = max(v.shape[0] for v in views)
    width = sum(v.shape[1] for v in views) + spacing * (len(views) - 1)
    sheet = np.zeros((height, width, 4), dtype=np.uint8)
    sheet[...] = alignment.BACKGROUND
    x = 0
    for image in views:
        sheet[height - image.shape[0] :, x : x + image.shape[1]] = image
        x += image.shape[1] + spacing
    if scale > 1:
        sheet = sheet.repeat(scale, axis=0).repeat(scale, axis=1)
    return sheet
