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
