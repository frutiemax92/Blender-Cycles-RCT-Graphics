"""Turning a raw Cycles render into a palette sprite."""

import numpy as np

from . import palette, quantize


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


def remap_classes(remap_aov, alpha):
    """Integer remap number per pixel from the (premultiplied) AOV."""
    safe = np.where(alpha > 1e-6, alpha, 1.0)
    return np.clip(np.rint(remap_aov / safe), 0, 3).astype(np.int32)


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
    ):
        self.alpha_threshold = alpha_threshold
        self.dither_method = dither_method
        self.dither_strength = dither_strength
        self.ramps = ramps


def to_indices(rgba_linear, settings, remap=None, mask=None):
    """Quantize a premultiplied linear RGBA render to palette indices.

    remap: optional (H, W) int array with the recolour number (0-3) per pixel.
    mask: optional (H, W) bool array restricting the opaque pixels further
    (used to split large scenery into tiles).
    Returns an (H, W) uint8 array, 0 being transparent.
    """
    alpha = rgba_linear[..., 3]
    opaque = silhouette(alpha, settings.alpha_threshold)
    if mask is not None:
        opaque &= mask
    rgb = linear_to_srgb(unpremultiply(rgba_linear)) * 255.0

    if remap is None:
        remap = np.zeros(alpha.shape, dtype=np.int32)
    classes = np.where(opaque, remap, -1).astype(np.int32)
    used = sorted(int(c) for c in np.unique(classes) if c > 0)
    allowed = {0: palette.normal_indices(settings.ramps, used)}
    for remap_number in used:
        allowed[remap_number] = palette.remap_indices(remap_number)
        selected = classes == remap_number
        rgb[selected] = project_onto_ramp(rgb[selected], allowed[remap_number])
    return quantize.quantize(
        rgb, classes, allowed, method=settings.dither_method, strength=settings.dither_strength
    )


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
