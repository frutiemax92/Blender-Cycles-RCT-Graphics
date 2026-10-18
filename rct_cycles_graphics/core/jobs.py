"""Which images to render for each object type, and where they are anchored.

A job says: render view ``view`` at animation frame ``frame``, keep the
pixels belonging to tile ``tile`` (None for all) and store the sprite as
image ``index``, with its offset measured from the game's paint anchor:
the top corner of tile ``tile_center`` plus the game paint offset
``game_offset`` (x, y, z in game units).
"""

from . import projection

# Paint offsets used by Paint.SmallScenery.cpp, per placement type.
SMALL_SCENERY_ANCHORS = {
    # Full tile objects, and quarter tile objects modelled around the origin.
    "FULL": (15, 15, 0),
    # Full tile objects with SMALL_SCENERY_FLAG_VOFFSET_CENTRE, half tile objects.
    "CENTRED": (3, 3, 0),
    # VOFFSET_CENTRE combined with PROHIBIT_WALLS.
    "NO_WALLS": (1, 1, 0),
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


def small_scenery(anchor="FULL", frames=(1,), start_index=0):
    """Four rotations per animation frame: image = start + 4 * frame + view.

    This is the layout animated small scenery uses in Paint.SmallScenery.cpp
    (``frame * 4 + direction``).
    """
    offset = SMALL_SCENERY_ANCHORS[anchor]
    jobs = []
    for number, frame in enumerate(frames):
        for view in range(4):
            jobs.append(Job(view, frame, start_index + number * 4 + view, offset))
    return jobs


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
