"""Which images to render for each object type, and where they are anchored.

A job says: render view ``view`` at animation frame ``frame``, keep the
pixels belonging to tile ``tile`` (None for all) and store the sprite as
image ``index``, with its offset measured from the game's paint anchor:
the top corner of tile ``tile_center`` plus the game paint offset
``game_offset`` (x, y, z in game units).
"""

from . import projection

# Small scenery shapes: JSON shape/flags and the paint offset that
# Paint.SmallScenery.cpp anchors the sprite on.
SMALL_SCENERY_SHAPES = {
    "FULL": {"shape": "4/4", "flags": {}, "offset": (15, 15, 0)},
    "THREE_QUARTERS": {"shape": "3/4", "flags": {}, "offset": (15, 15, 0)},
    "HALF": {"shape": "2/4", "flags": {}, "offset": (3, 3, 0)},
    # Quarter tile objects are anchored one unit before their quadrant's
    # centre, the same as full tile objects relative to the tile centre, so
    # they are modelled around the origin too.
    "QUARTER": {"shape": "1/4", "flags": {}, "offset": (15, 15, 0)},
    "FULL_CENTRED": {
        "shape": "4/4",
        "flags": {"SMALL_SCENERY_FLAG_VOFFSET_CENTRE": True},
        "offset": (3, 3, 0),
    },
    "FULL_CENTRED_NO_WALLS": {
        "shape": "4/4",
        "flags": {"SMALL_SCENERY_FLAG_VOFFSET_CENTRE": True, "prohibitWalls": True},
        "offset": (1, 1, 0),
    },
}


class Job:
    def __init__(self, view, frame, index, game_offset, tile_center=(0.0, 0.0), tile=None, variant=None):
        self.view = view
        self.frame = frame
        self.index = index
        self.game_offset = game_offset
        self.tile_center = tile_center
        self.tile = tile
        self.variant = variant

    @property
    def render_key(self):
        """Jobs sharing a key can reuse the same render."""
        return (self.view, self.frame, self.variant)

    def anchor(self):
        top_x, top_y = projection.tile_top_vertex(self.tile_center[0], self.tile_center[1], self.view)
        off_x, off_y = projection.game_offset_to_screen(*self.game_offset)
        return top_x + off_x, top_y + off_y

    def __repr__(self):
        return "Job(view={}, frame={}, index={}, tile={}, variant={})".format(
            self.view, self.frame, self.index, self.tile, self.variant
        )


def animation_frames(count=1, first=1, step=1):
    """Scene frame numbers of an animation with ``count`` sprites."""
    return [first + i * step for i in range(max(1, count))]


def small_scenery(shape="FULL", frames=(1,), start_index=0):
    """Images 0-3 are the four rotations of the (first frame of the) object.

    Animated objects then store frame k at 4 + 4 * k + view: with
    SMALL_SCENERY_FLAG_VISIBLE_WHEN_ZOOMED, Paint.SmallScenery.cpp draws
    ``image + 4 + 4 * frameOffsets[frame] + direction`` instead of the base
    image.
    """
    offset = SMALL_SCENERY_SHAPES[shape]["offset"]
    jobs = [Job(view, frames[0], start_index + view, offset) for view in range(4)]
    if len(frames) > 1:
        for number, frame in enumerate(frames):
            for view in range(4):
                jobs.append(Job(view, frame, start_index + 4 + number * 4 + view, offset))
    return jobs


# Wall images, from Paint.Wall.cpp. The model stands on the tile's +X edge in
# Blender, which is the game's x = 0 edge (direction 0). Rendering view k
# shows it on the edge of direction k. Each entry is
# image offset -> (view, paint offset, slope variant), where slope "up" is
# the game's EDGE_SLOPE_UPWARDS (1) and "down" EDGE_SLOPE_DOWNWARDS (2).
WALL_IMAGES = {
    0: (3, (2, 1, 0), None),
    1: (0, (0, 0, 0), None),
    2: (3, (2, 1, 0), "up"),
    3: (0, (0, 0, 0), "down"),
    4: (3, (2, 1, 0), "down"),
    5: (0, (0, 0, 0), "up"),
}
# Double sided walls show their other face on the near edges (directions 1, 2).
WALL_BACK_IMAGES = {
    6: (1, (1, 31, 0), None),
    7: (2, (31, 0, 0), None),
    8: (1, (1, 31, 0), "down"),
    9: (2, (31, 0, 0), "up"),
    10: (1, (1, 31, 0), "up"),
    11: (2, (31, 0, 0), "down"),
}


def wall(double_sided=False, sloped=False, start_index=0, frame=1):
    """Jobs for a wall: images 0-1 flat, 2-5 sloped, 6-11 the back face."""
    layout = dict(WALL_IMAGES)
    if double_sided:
        layout.update(WALL_BACK_IMAGES)
    jobs = []
    for offset, (view, game_offset, slope) in sorted(layout.items()):
        if slope is not None and not sloped:
            continue
        jobs.append(Job(view, frame, start_index + offset, game_offset, variant=slope))
    return jobs


def wall_slope_matrix(slope):
    """4x4 world-space shear raising a wall on the +X edge by one land step.

    "up" rises towards game +y (Blender -Y), "down" towards Blender +Y.
    """
    rise = projection.HEIGHT_STEP / projection.TILE_SIZE
    half = projection.HEIGHT_STEP / 2.0
    dz_dy = -rise if slope == "up" else rise
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, dz_dy, 1.0, half),
        (0.0, 0.0, 0.0, 1.0),
    )


def large_scenery_tiles(width, length):
    """Tiles of a ``width`` x ``length`` footprint in sequence order.

    Tile (i, j) is centred on Blender (-4 i, -4 j) and sits at game offset
    (32 i, 32 j) from the first tile, since game +x is Blender -X.
    Returns a list of dicts with ``seq``, ``i``, ``j``, ``center`` and ``x``/``y``.
    """
    tiles = []
    for j in range(length):
        for i in range(width):
            tiles.append(
                {
                    "seq": len(tiles),
                    "i": i,
                    "j": j,
                    "center": (-projection.TILE_SIZE * i, -projection.TILE_SIZE * j),
                    "x": 32 * i,
                    "y": 32 * j,
                }
            )
    return tiles


def large_scenery(width, length, start_index=0, frame=1):
    """Preview images 0-3, then one image per tile and view: 4 + 4 * seq + view.

    Matches Paint.LargeScenery.cpp: ``image + 4 + (sequence << 2) + direction``.
    Every tile sprite is anchored on its own tile's top corner.
    """
    tiles = large_scenery_tiles(width, length)
    jobs = []
    for view in range(4):
        jobs.append(Job(view, frame, start_index + view, (0, 0, 0)))
    for tile in tiles:
        for view in range(4):
            jobs.append(
                Job(
                    view,
                    frame,
                    start_index + 4 + 4 * tile["seq"] + view,
                    (0, 0, 0),
                    tile_center=tile["center"],
                    tile=tile["seq"],
                )
            )
    return jobs


def tile_map(position, alpha, width, length):
    """Sequence number of the footprint tile under each pixel (-1 if empty).

    ``position`` is Cycles' Position pass, which is coverage weighted at the
    silhouette, hence the division by alpha. Geometry overhanging the
    footprint is given to the nearest tile.
    """
    import numpy as np

    safe = np.where(alpha > 1e-6, alpha, 1.0)
    x = position[..., 0] / safe
    y = position[..., 1] / safe
    half = projection.TILE_SIZE / 2.0
    i = np.clip(np.floor((half - x) / projection.TILE_SIZE), 0, width - 1).astype(np.int32)
    j = np.clip(np.floor((half - y) / projection.TILE_SIZE), 0, length - 1).astype(np.int32)
    result = j * width + i
    result[alpha <= 1e-6] = -1
    return result
