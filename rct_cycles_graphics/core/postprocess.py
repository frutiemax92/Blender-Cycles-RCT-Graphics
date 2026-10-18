"""Turning a raw Cycles render into a palette sprite."""

import math

import numpy as np

from . import palette, projection, quantize

#: Sub-pixels whose normals differ by more than this lie on different faces.
SURFACE_NORMAL_COS = math.cos(math.radians(10.0))
#: Sub-pixels further than this (Blender units, half a pixel) from the plane
#: of the pixel's centre lie on a different (e.g. parallel, stepped) face.
SURFACE_PLANE_TOLERANCE = 0.5 / projection.PIXELS_PER_BU


def linear_to_srgb(linear):
    """sRGB transfer function (what Blender's "Standard" view transform applies)."""
    linear = np.clip(linear, 0.0, 1.0)
    low = linear * 12.92
    high = 1.055 * np.power(linear, 1.0 / 2.4) - 0.055
    return np.where(linear <= 0.0031308, low, high)


def unpremultiply(rgba):
    """Straight-alpha RGB of a premultiplied RGBA render."""
    alpha = rgba[..., 3:4]
    safe = np.where(alpha > 1e-6, alpha, 1.0)
    return rgba[..., :3] / safe


def silhouette(alpha, threshold):
    """Hard-edged coverage mask: the sprite edge is aliased, the inside is not."""
    return alpha >= threshold


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def project_onto_ramp(rgb, indices):
    """Replace colours by the ramp colour of equal luminance.

    Recolourable pixels only carry brightness information: the game swaps
    the ramp for the player's colour choice.
    """
    ramp = palette.PALETTE[list(indices)].astype(np.float32)
    ramp_lum = luminance(ramp)
    lum = luminance(rgb)
    return np.stack([np.interp(lum, ramp_lum, ramp[:, c]) for c in range(3)], axis=-1)


def remap_classes(coverage, alpha):
    """Remap number (0-3) per pixel from the per-remap coverage AOVs.

    coverage: (H, W, 3) coverage of remaps 1-3 (each AOV is 1 on surfaces of
    that remap, filtered like alpha). The remainder of alpha is plain
    surface; the largest share wins.
    """
    plain = alpha - coverage.sum(axis=-1)
    shares = np.concatenate([plain[..., None], coverage], axis=-1)
    return np.argmax(shares, axis=-1).astype(np.int32)


def _blocks(array, factor):
    """(H*f, W*f, C) array -> (H, W, f*f, C) array of each pixel's sub-pixels."""
    height, width = array.shape[0] // factor, array.shape[1] // factor
    channels = array.shape[2] if array.ndim == 3 else 1
    blocks = array.reshape(height, factor, width, factor, channels).transpose(0, 2, 1, 3, 4)
    return blocks.reshape(height, width, factor * factor, channels)


def _normalized(vectors):
    length = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(length > 1e-9, length, 1.0)


def resolve_supersampled(rgba, position, normal, classes, factor, alpha_threshold):
    """Downsample a point-sampled render of ``factor`` x ``factor`` sub-pixels per pixel.

    Anti-aliases the inside of faces only, like Blender Internal did: a pixel
    takes the face under its centre sub-pixel and averages the sub-pixels on
    that same face (same normal, same plane, same remap). Face edges hence
    never mix two faces' colours, which would show as seams once sprites are
    stacked or repeated in game, while textures stay smooth.

    rgba: (H*f, W*f, 4) premultiplied render; position, normal: (H*f, W*f, 3)
    world-space passes (coverage weighted); classes: (H*f, W*f) remap numbers.
    ``factor`` must be odd, so a sub-pixel sits on the pixel centre: a pixel
    is opaque when that sample hits the object, as a rasterizer would decide,
    so adjacent tiles split boundary pixels between them exactly.

    Returns (rgba, position, classes, opaque) at pixel resolution. The rgba
    alpha is the pixel's coverage (used to blend edges with a background) and
    its colour is the centre face's, premultiplied; position is the centre
    sample's, premultiplied by the same alpha.
    """
    rgba_s = _blocks(rgba, factor)
    alpha_s = rgba_s[..., 3]
    safe = np.where(alpha_s > 1e-6, alpha_s, 1.0)[..., None]
    position_s = _blocks(position, factor) / safe
    normal_s = _normalized(_blocks(normal, factor))
    classes_s = _blocks(classes, factor)[..., 0]

    centre = (factor // 2) * factor + factor // 2
    alpha_c = alpha_s[..., centre]
    position_c = position_s[:, :, centre : centre + 1]
    normal_c = normal_s[:, :, centre : centre + 1]
    same = (
        (alpha_s > 1e-6)
        & (classes_s == classes_s[..., centre : centre + 1])
        & (np.sum(normal_s * normal_c, axis=-1) >= SURFACE_NORMAL_COS)
        & (np.abs(np.sum((position_s - position_c) * normal_c, axis=-1)) <= SURFACE_PLANE_TOLERANCE)
    )
    weight = np.sum(np.where(same, alpha_s, 0.0), axis=-1)
    colour = np.sum(np.where(same[..., None], rgba_s[..., :3], 0.0), axis=2)
    colour /= np.where(weight > 1e-6, weight, 1.0)[..., None]

    coverage = alpha_s.mean(axis=-1)
    opaque = alpha_c >= alpha_threshold
    out = np.concatenate([colour * coverage[..., None], coverage[..., None]], axis=-1)
    return (
        out.astype(np.float32),
        (position_c[:, :, 0] * coverage[..., None]).astype(np.float32),
        np.where(opaque, classes_s[..., centre], 0).astype(np.int32),
        opaque,
    )


def bounding_box(mask):
    """(x0, y0, x1, y1) of the True pixels, or None when the mask is empty."""
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


class Settings:
    """Post-processing options, decoupled from Blender properties for testing."""

    def __init__(
        self,
        alpha_threshold=0.5,
        dither_method="FLOYD_STEINBERG",
        dither_strength=0.35,
        ramps=None,
        background_blend=False,
        background_colour=(0.041, 0.044, 0.041),
        outline_shades=0,
        outline_width=1,
        outline_diagonal=False,
    ):
        self.alpha_threshold = alpha_threshold
        self.dither_method = dither_method
        self.dither_strength = dither_strength
        self.ramps = ramps
        self.background_blend = background_blend
        self.background_colour = background_colour
        self.outline_shades = outline_shades
        self.outline_width = outline_width
        self.outline_diagonal = outline_diagonal


def edge_pixels(opaque, width=1, diagonal=False):
    """Opaque pixels within ``width`` pixels of a transparent one (inner rim)."""
    height, cols = opaque.shape
    padded = np.zeros((height + 2 * width, cols + 2 * width), dtype=bool)
    padded[width:-width, width:-width] = opaque
    interior = opaque.copy()
    for dy in range(-width, width + 1):
        for dx in range(-width, width + 1):
            if dx == 0 and dy == 0:
                continue
            if not diagonal and abs(dx) + abs(dy) > width:
                continue
            interior &= padded[width + dy : width + dy + height, width + dx : width + dx + cols]
    return opaque & ~interior


def apply_outline(indices, settings):
    """Darken the sprite's rim along each pixel's own palette ramp.

    This reproduces the dark contour of many original sprites (e.g. trees)
    without leaving the palette: a recolourable pixel stays recolourable.
    """
    if settings.outline_shades <= 0:
        return indices
    rim = edge_pixels(indices != palette.TRANSPARENT, settings.outline_width, settings.outline_diagonal)
    table = palette.shade_shift_table(-settings.outline_shades)
    result = indices.copy()
    result[rim] = table[indices[rim]]
    return result


def to_indices(rgba_linear, settings, remap=None, mask=None, opaque=None):
    """Quantize a premultiplied linear RGBA render to palette indices.

    remap: optional (H, W) int array with the recolour number (0-3) per pixel.
    mask: optional (H, W) bool array restricting the opaque pixels further
    (used to split large scenery into tiles).
    opaque: optional (H, W) bool silhouette replacing the alpha threshold
    (see resolve_supersampled).
    Returns an (H, W) uint8 array, 0 being transparent.
    """
    alpha = rgba_linear[..., 3]
    if opaque is None:
        opaque = silhouette(alpha, settings.alpha_threshold)
    else:
        opaque = opaque.copy()
    if mask is not None:
        opaque &= mask
    if settings.background_blend:
        # RCT1 style: edges are anti-aliased against a dark background, which
        # leaves a dark fringe once the silhouette is made hard again.
        background = np.asarray(settings.background_colour, dtype=np.float32)
        linear = rgba_linear[..., :3] + background * (1.0 - alpha[..., None])
    else:
        linear = unpremultiply(rgba_linear)
    rgb = linear_to_srgb(linear) * 255.0

    if remap is None:
        remap = np.zeros(alpha.shape, dtype=np.int32)
    classes = np.where(opaque, remap, -1).astype(np.int32)
    used = sorted(int(c) for c in np.unique(classes) if c > 0)
    allowed = {0: palette.normal_indices(settings.ramps, used)}
    for remap_number in used:
        allowed[remap_number] = palette.remap_indices(remap_number)
        selected = classes == remap_number
        rgb[selected] = project_onto_ramp(rgb[selected], allowed[remap_number])
    indices = quantize.quantize(
        rgb, classes, allowed, method=settings.dither_method, strength=settings.dither_strength
    )
    return apply_outline(indices, settings)


class Sprite:
    """A trimmed palette image with its OpenRCT2 offset."""

    def __init__(self, indices, x, y):
        self.indices = indices
        self.x = x
        self.y = y

    @property
    def empty(self):
        return self.indices.size == 0


def make_sprite(indices, origin_x, origin_y, anchor):
    """Trim ``indices`` and compute the offset relative to the paint anchor.

    origin_x/origin_y: screen position of the image's top-left pixel.
    anchor: screen position the game draws the sprite relative to.
    """
    box = bounding_box(indices != palette.TRANSPARENT)
    if box is None:
        return Sprite(np.zeros((0, 0), dtype=np.uint8), 0, 0)
    x0, y0, x1, y1 = box
    return Sprite(
        indices[y0:y1, x0:x1].copy(),
        origin_x + x0 - anchor[0],
        origin_y + y0 - anchor[1],
    )
