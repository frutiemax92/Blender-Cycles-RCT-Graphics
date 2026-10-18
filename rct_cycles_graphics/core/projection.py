"""Mapping between Blender space and OpenRCT2's isometric screen space.

Conventions (shared with the original RCT Graphics Helper):

* One tile is 4 x 4 Blender units, centred on the origin for a 1x1 object.
* One land height step (16 game z units) is 4 / sqrt(6) ~ 1.633 Blender units.
* The camera is a true orthographic camera looking 30 degrees down, so the
  game's 2:1 projection ``screen = (y - x, (x + y) / 2 - z)`` is reproduced
  exactly.

Screen coordinates here are pixels, x to the right and y downwards, with
(0, 0) at the projection of the Blender origin. View ``k`` (0-3) is the
object seen with the camera rotated by ``90 * k`` degrees around Z, which is
the image the game draws for direction ``k``.
"""

import math

import numpy as np

TILE_SIZE = 4.0
#: Game xy units per Blender unit (a tile is 32 game units).
GAME_UNITS_PER_BU = 32.0 / TILE_SIZE
#: Blender units per land height step (16 game z units).
HEIGHT_STEP = TILE_SIZE / math.sqrt(6.0)
#: Screen pixels per game z unit is 1, so pixels per vertical Blender unit:
Z_PIXELS_PER_BU = 16.0 / HEIGHT_STEP
#: Pixels per Blender unit across the image plane (orthographic scale).
PIXELS_PER_BU = GAME_UNITS_PER_BU * math.sqrt(2.0)

#: Camera tilt: Blender X rotation of the camera (90 - 30 degrees).
CAMERA_TILT = math.radians(60.0)
#: Camera heading for view 0 (looking from -X -Y towards +X +Y).
CAMERA_HEADING = math.radians(-45.0)


def view_angle(view):
    """Rotation of the camera rig around Z for view ``view``, in radians."""
    return math.radians(90.0 * (view % 4))


def to_view_space(points, view):
    """Rotate Blender points (N, 3) into the frame of view 0."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    angle = -view_angle(view)
    c, s = math.cos(angle), math.sin(angle)
    x = points[:, 0] * c - points[:, 1] * s
    y = points[:, 0] * s + points[:, 1] * c
    return np.stack([x, y, points[:, 2]], axis=1)


def to_screen(points, view):
    """Project Blender points (N, 3) to screen pixels (N, 2) for ``view``."""
    q = to_view_space(points, view)
    sx = GAME_UNITS_PER_BU * (q[:, 0] - q[:, 1])
    sy = -0.5 * GAME_UNITS_PER_BU * (q[:, 0] + q[:, 1]) - Z_PIXELS_PER_BU * q[:, 2]
    return np.stack([sx, sy], axis=1)


def tile_corners(center_x, center_y, z=0.0):
    """The four ground corners of the tile centred on (center_x, center_y)."""
    h = TILE_SIZE / 2.0
    return np.array(
        [
            (center_x - h, center_y - h, z),
            (center_x + h, center_y - h, z),
            (center_x + h, center_y + h, z),
            (center_x - h, center_y + h, z),
        ]
    )


def tile_top_vertex(center_x, center_y, view, z=0.0):
    """Screen position of the tile's top (far) corner, the game's paint origin.

    OpenRCT2 positions every sprite of a tile relative to this corner (see
    PaintTileElement / Translate3DTo2DWithZ). The result is always integral.
    """
    screen = to_screen(tile_corners(center_x, center_y, z), view)
    top = screen[np.argmin(screen[:, 1])]
    return int(round(top[0])), int(round(top[1]))


def game_offset_to_screen(ox, oy, oz):
    """Screen offset of a game paint offset (x, y, z), relative to the top corner.

    Mirrors Translate3DTo2DWithZ including the integer halving; the rotation
    cancels out because paint offsets are pre-rotated by the inverse view.
    """
    return int(oy - ox), int(((ox + oy) >> 1) - oz)


def screen_bounds(points, view, margin=2):
    """Integer pixel rectangle (x0, y0, x1, y1) enclosing the projected points."""
    screen = to_screen(points, view)
    x0 = int(math.floor(screen[:, 0].min())) - margin
    y0 = int(math.floor(screen[:, 1].min())) - margin
    x1 = int(math.ceil(screen[:, 0].max())) + margin
    y1 = int(math.ceil(screen[:, 1].max())) + margin
    return x0, y0, x1, y1


def camera_basis(view):
    """World-space (right, up, forward) unit vectors of the camera for ``view``."""
    heading = CAMERA_HEADING + view_angle(view)
    ch, sh = math.cos(heading), math.sin(heading)
    ct, st = math.cos(CAMERA_TILT), math.sin(CAMERA_TILT)
    right = np.array([ch, sh, 0.0])
    # Camera local +Y (up) and -Z (forward) after rotating X by tilt, then Z by heading.
    up_local = np.array([0.0, ct, st])
    fwd_local = np.array([0.0, st, -ct])

    def rotate(v):
        return np.array([v[0] * ch - v[1] * sh, v[0] * sh + v[1] * ch, v[2]])

    return right, rotate(up_local), rotate(fwd_local)


def camera_placement(bounds, view, distance):
    """Camera location, rotation, ortho scale and resolution for a pixel rectangle.

    The camera is placed so that pixel (i, j) of the render covers screen
    rectangle [x0 + i, x0 + i + 1] x [y0 + j, y0 + j + 1]; tile corners hence
    land exactly on pixel corners and repeated tiles line up pixel-perfectly.
    """
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    right, up, forward = camera_basis(view)
    target = right * (cx / PIXELS_PER_BU) - up * (cy / PIXELS_PER_BU)
    location = target - forward * distance
    rotation = (CAMERA_TILT, 0.0, CAMERA_HEADING + view_angle(view))
    # The camera's sensor fit is HORIZONTAL: the orthographic scale spans the
    # image width whatever the aspect ratio.
    ortho_scale = width / PIXELS_PER_BU
    return {
        "location": tuple(location),
        "rotation": rotation,
        "ortho_scale": ortho_scale,
        "resolution": (width, height),
    }
