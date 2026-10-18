"""Checking that objects line up when the game repeats them.

Sprite offsets are derived from the game's own paint anchors and the camera
is pixel aligned, so a model that exactly fills its cell always produces
sprites that tile without gaps or overlaps. What remains to check is the
model itself:

* :func:`geometry_report` compares the model's bounds with the tile edges
  and with the clearance height, in game units, and says how to fix it
  (see the Snap to Grid operator).
* :func:`compose` / :func:`preview_sheet` composite the sprites exactly the
  way OpenRCT2 draws them (tile top corner + paint offset + image offset,
  back to front) along each axis, over a ground grid, so the result can be
  inspected without starting the game. :func:`enclosed_holes` finds
  pinholes left between copies.
"""

import numpy as np

from . import palette, projection

GRID_COLOUR = (90, 90, 110, 255)
BACKGROUND = (24, 24, 32, 255)


class Placement:
    """One copy of an image at game position (gx, gy, gz) in view-local coordinates."""

    def __init__(self, image, gx=0, gy=0, gz=0):
        self.image = image
        self.gx = gx
        self.gy = gy
        self.gz = gz

    def screen(self):
        """Screen offset of the copy's tile top corner (Translate3DTo2DWithZ)."""
        return self.gy - self.gx, ((self.gx + self.gy) >> 1) - self.gz

    def depth(self):
        return (self.gx + self.gy, self.gz)


class Arrangement:
    """A named test layout: copies of one image plus the axis being tested."""

    def __init__(self, name, view, placements, axis, step):
        self.name = name
        self.view = view
        self.placements = placements
        self.axis = axis
        self.step = step


def arrangements(object_type, clearance=16, footprint=(1, 1), start_index=0):
    """Test layouts for each view.

    clearance: object height in game z units, used for vertical stacking.
    footprint: (width, length) of large scenery in tiles.
    start_index: image index of the object's first sprite.
    """
    result = _arrangements(object_type, clearance, footprint)
    for layout in result:
        for placement in layout.placements:
            placement.image += start_index
    return result


def _arrangements(object_type, clearance, footprint):
    result = []
    if object_type == "SMALL":
        for view in range(4):
            result.append(_row(view, view, "x", 32))
            result.append(_row(view, view, "y", 32))
            if clearance > 0:
                result.append(_row(view, view, "z", clearance))
    elif object_type == "LARGE":
        width, length = footprint
        for view in range(4):
            # Whole objects next to each other; image = preview of this view.
            result.append(_row(view, view, "x", 32 * (width if view % 2 == 0 else length)))
            result.append(_row(view, view, "y", 32 * (length if view % 2 == 0 else width)))
    elif object_type == "WALL":
        # Image 1 runs along the game y axis, image 0 along x.
        result.append(_row(0, 1, "y", 32))
        result.append(_row(3, 0, "x", 32))
        if clearance > 0:
            result.append(_row(0, 1, "z", clearance))
            result.append(_row(3, 0, "z", clearance))
    return result


def _row(view, image, axis, step, count=3):
    placements = []
    for i in range(count):
        offset = {"x": (i * step, 0, 0), "y": (0, i * step, 0), "z": (0, 0, i * step)}[axis]
        placements.append(Placement(image, *offset))
    name = "view {} image {} along {}".format(view, image, axis)
    return Arrangement(name, view, placements, axis, step)


def colourize(indices):
    rgba = np.zeros(indices.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = palette.PALETTE[indices]
    rgba[..., 3] = np.where(indices != palette.TRANSPARENT, 255, 0)
    return rgba


def compose(sprites, anchors, placements, margin=8, grid=True, shift=None):
    """Composite the placements back to front.

    sprites: {image: (indices, x, y)} as stored in images.json.
    anchors: {image: (ax, ay)} paint anchor of each image relative to the
    top corner of the tile it belongs to.
    shift: optional (dx, dy) pixel shift applied to every copy but the first,
    used to measure how far copies are from fitting.
    Returns (rgba canvas, coverage count per pixel, index of the copy that
    drew each pixel, -1 for none).
    """
    boxes = []
    for number, placement in enumerate(placements):
        indices, x, y = sprites[placement.image]
        sx, sy = placement.screen()
        ax, ay = anchors[placement.image]
        left, top = sx + ax + x, sy + ay + y
        if shift is not None and number > 0:
            left += shift[0] * number
            top += shift[1] * number
        boxes.append((left, top, indices, placement, number))

    min_x = min(b[0] for b in boxes) - margin - 32
    min_y = min(b[1] for b in boxes) - margin - 16
    max_x = max(b[0] + b[2].shape[1] for b in boxes) + margin + 32
    max_y = max(b[1] + b[2].shape[0] for b in boxes) + margin + 16
    width, height = max_x - min_x, max_y - min_y

    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    canvas[...] = BACKGROUND
    if grid:
        for placement in placements:
            sx, sy = placement.screen()
            if placement.gz == 0:
                _draw_tile(canvas, sx - min_x, sy - min_y)
    coverage = np.zeros((height, width), dtype=np.int32)
    owner = np.full((height, width), -1, dtype=np.int32)

    for left, top, indices, placement, number in sorted(boxes, key=lambda b: b[3].depth()):
        h, w = indices.shape
        region = (slice(top - min_y, top - min_y + h), slice(left - min_x, left - min_x + w))
        opaque = indices != palette.TRANSPARENT
        canvas[region][opaque] = colourize(indices)[opaque]
        coverage[region] += opaque
        owner[region][opaque] = number
    return canvas, coverage, owner


def _draw_tile(canvas, top_x, top_y):
    """Outline of a 64x32 ground tile whose top corner is at (top_x, top_y)."""
    height, width = canvas.shape[:2]
    for i in range(32):
        dy = i // 2
        for x, y in (
            (top_x + i, top_y + dy),
            (top_x - 1 - i, top_y + dy),
            (top_x + 31 - i, top_y + 16 + dy),
            (top_x - 32 + i, top_y + 16 + dy),
        ):
            if 0 <= x < width and 0 <= y < height:
                canvas[y, x] = GRID_COLOUR


def enclosed_holes(coverage):
    """Transparent pixels that cannot reach the canvas border (gaps between copies)."""
    empty = coverage == 0
    outside = np.zeros_like(empty)
    outside[0, :] = empty[0, :]
    outside[-1, :] = empty[-1, :]
    outside[:, 0] = empty[:, 0]
    outside[:, -1] = empty[:, -1]
    while True:
        grown = outside.copy()
        grown[1:, :] |= outside[:-1, :]
        grown[:-1, :] |= outside[1:, :]
        grown[:, 1:] |= outside[:, :-1]
        grown[:, :-1] |= outside[:, 1:]
        grown &= empty
        if (grown == outside).all():
            break
        outside = grown
    return empty & ~outside


#: Height granularity of the game (one clearance unit), in z units / pixels.
CLEARANCE_UNIT = 8


class Finding:
    def __init__(self, axis, message, error_units=0.0):
        self.axis = axis
        self.message = message
        self.error_units = error_units

    @property
    def ok(self):
        return abs(self.error_units) < 0.5

    def __repr__(self):
        return "Finding({!r}, {!r})".format(self.axis, self.message)


def _units_per_bu(axis):
    return 16.0 / projection.HEIGHT_STEP if axis == "z" else projection.GAME_UNITS_PER_BU


def _to_units(value_bu, axis):
    return value_bu * _units_per_bu(axis)


def _describe_side(axis, side, delta_units):
    """Text for one side of the model; positive delta means it stops short."""
    if abs(delta_units) < 0.5:
        return None
    where = "short of" if delta_units > 0 else "past"
    return "{}: {} side is {:.1f} game units ({:.3f} BU) {} the tile edge".format(
        axis, side, abs(delta_units), abs(delta_units) / _units_per_bu(axis), where
    )


def expected_cell(object_type, footprint=(1, 1)):
    """Blender (min, max) per horizontal axis of the cell a tiling model fills."""
    half = projection.TILE_SIZE / 2.0
    if object_type == "LARGE":
        width, length = footprint
        return {
            "x": (half - width * projection.TILE_SIZE, half),
            "y": (half - length * projection.TILE_SIZE, half),
        }
    return {"x": (-half, half), "y": (-half, half)}


def geometry_report(bounds_min, bounds_max, object_type, footprint=(1, 1)):
    """Compare a model's world bounds with the grid the game repeats it on.

    Returns a list of :class:`Finding`. Horizontal findings only matter for
    objects meant to tile (base blocks, roofs, walls, ...); a tree is not
    supposed to fill its tile. Heights should be a multiple of the clearance
    unit (8 z units) so stacked copies meet exactly.
    """
    cell = expected_cell(object_type, footprint)
    findings = []
    names = {"x": ("-X", "+X"), "y": ("-Y", "+Y")}
    for i, axis in enumerate(("x", "y")):
        if object_type == "WALL" and axis == "x":
            # Walls only need to reach the +X edge.
            delta = _to_units(cell["x"][1] - bounds_max[0], "x")
            message = _describe_side("x", "+X", delta) or "x: the wall's outer face sits on the +X edge"
            findings.append(Finding("x", message, delta))
            continue
        low = _to_units(bounds_min[i] - cell[axis][0], axis)
        high = _to_units(cell[axis][1] - bounds_max[i], axis)
        parts = [m for m in (_describe_side(axis, names[axis][0], low), _describe_side(axis, names[axis][1], high)) if m]
        error = low if abs(low) >= abs(high) else high
        findings.append(Finding(axis, "; ".join(parts) if parts else axis + ": fills the tile edges exactly", error))

    bottom = _to_units(bounds_min[2], "z")
    if abs(bottom) >= 0.5:
        findings.append(Finding("z", "z: bottom is {:.1f} z units {} the ground".format(abs(bottom), "above" if bottom > 0 else "below"), bottom))
    height = _to_units(bounds_max[2], "z")
    nearest = max(CLEARANCE_UNIT, int(round(height / CLEARANCE_UNIT)) * CLEARANCE_UNIT)
    error = nearest - height
    if abs(error) >= 0.5:
        findings.append(
            Finding(
                "z",
                "z: top at {:.1f} z units; stacking needs a multiple of {} (nearest {}, {:+.3f} BU)".format(
                    height, CLEARANCE_UNIT, nearest, error * projection.HEIGHT_STEP / 16.0
                ),
                error,
            )
        )
    else:
        findings.append(Finding("z", "z: height {} z units ({} clearance units)".format(nearest, nearest // CLEARANCE_UNIT)))
    return findings


def clearance_from_height(top_bu):
    """Clearance in z units for a model whose top is at ``top_bu``, rounded up."""
    units = _to_units(top_bu, "z")
    return max(CLEARANCE_UNIT, int(np.ceil(units / CLEARANCE_UNIT - 1e-3)) * CLEARANCE_UNIT)


def snap_box(bounds_min, bounds_max, object_type, footprint=(1, 1), snap_horizontal=True, snap_height=True):
    """Target bounds after snapping to the tile grid and the clearance unit."""
    target_min = list(bounds_min)
    target_max = list(bounds_max)
    if snap_horizontal:
        cell = expected_cell(object_type, footprint)
        if object_type == "WALL":
            width = bounds_max[0] - bounds_min[0]
            target_max[0] = cell["x"][1]
            target_min[0] = cell["x"][1] - width
        else:
            target_min[0], target_max[0] = cell["x"]
        target_min[1], target_max[1] = cell["y"]
    if snap_height:
        target_min[2] = 0.0
        units = _to_units(bounds_max[2] - bounds_min[2], "z")
        steps = max(1, int(round(units / CLEARANCE_UNIT)))
        target_max[2] = steps * CLEARANCE_UNIT * projection.HEIGHT_STEP / 16.0
    return target_min, target_max


def pinholes(sprites, anchors, arrangement):
    """Number of transparent pixels enclosed by the copies of an arrangement."""
    coverage = compose(sprites, anchors, arrangement.placements, grid=False)[1]
    return int(enclosed_holes(coverage).sum())


def preview_sheet(sprites, anchors, layouts, spacing=8):
    """Side by side composites of the given arrangements, for visual checking."""
    images = [compose(sprites, anchors, a.placements)[0] for a in layouts]
    height = max(i.shape[0] for i in images)
    width = sum(i.shape[1] for i in images) + spacing * (len(images) - 1)
    sheet = np.zeros((height, width, 4), dtype=np.uint8)
    sheet[...] = BACKGROUND
    x = 0
    for image in images:
        sheet[: image.shape[0], x : x + image.shape[1]] = image
        x += image.shape[1] + spacing
    return sheet
