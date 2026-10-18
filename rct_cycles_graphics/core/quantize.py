"""Palette quantization and dithering, in numpy.

Pixels are split into classes: class 0 holds plain colours, classes 1-3 the
recolourable (remap) pixels. Every class has its own set of allowed palette
indices, and dithering error never crosses from one class to another, which
mirrors what OpenRCT2's own importer does.
"""

import numpy as np

from .palette import PALETTE

# Resolution of the nearest-colour lookup cube used while dithering.
_LUT_BITS = 6
_LUT_SIZE = 1 << _LUT_BITS
_LUT_STEP = 256 // _LUT_SIZE

_BAYER_4 = (
    np.array(
        [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5],
        ],
        dtype=np.float32,
    )
    + 0.5
) / 16.0 - 0.5


def _distances(rgb, colours):
    """Weighted ("redmean") squared colour distances, shape (N, K)."""
    diff = rgb[:, None, :] - colours[None, :, :]
    mean_red = (rgb[:, None, 0] + colours[None, :, 0]) * 0.5
    wr = 2.0 + mean_red / 256.0
    wb = 2.0 + (255.0 - mean_red) / 256.0
    return wr * diff[..., 0] ** 2 + 4.0 * diff[..., 1] ** 2 + wb * diff[..., 2] ** 2


def nearest(rgb, allowed, chunk=65536):
    """Index of the nearest allowed palette colour for each RGB row (0-255 floats)."""
    allowed = np.asarray(allowed, dtype=np.int64)
    colours = PALETTE[allowed].astype(np.float32)
    rgb = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    out = np.empty(len(rgb), dtype=np.uint8)
    for start in range(0, len(rgb), chunk):
        part = rgb[start : start + chunk]
        out[start : start + chunk] = allowed[np.argmin(_distances(part, colours), axis=1)]
    return out


class _Lut:
    """Cached nearest-colour cube for one allowed index set."""

    _cache = {}

    @classmethod
    def get(cls, allowed):
        key = tuple(allowed)
        lut = cls._cache.get(key)
        if lut is None:
            axis = np.arange(_LUT_SIZE, dtype=np.float32) * _LUT_STEP + _LUT_STEP / 2.0
            grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
            lut = nearest(grid.reshape(-1, 3), allowed).reshape(_LUT_SIZE, _LUT_SIZE, _LUT_SIZE)
            cls._cache[key] = lut
        return lut


def quantize(rgb, classes, allowed_by_class, method="FLOYD_STEINBERG", strength=1.0):
    """Quantize an image to palette indices.

    rgb: (H, W, 3) float array, sRGB 0-255.
    classes: (H, W) int array; -1 marks transparent pixels, which become index 0.
    allowed_by_class: dict mapping class -> list of allowed palette indices.
    method: "NONE", "ORDERED" or "FLOYD_STEINBERG".
    strength: 0-1 scale of the dithering.
    """
    height, width = classes.shape
    result = np.zeros((height, width), dtype=np.uint8)
    rgb = np.asarray(rgb, dtype=np.float32)

    if method == "FLOYD_STEINBERG" and strength > 0:
        _floyd_steinberg(rgb, classes, allowed_by_class, strength, result)
        return result

    work = rgb
    if method == "ORDERED" and strength > 0:
        ys, xs = np.mgrid[0:height, 0:width]
        threshold = _BAYER_4[ys % 4, xs % 4][..., None]
        work = np.clip(rgb + threshold * 32.0 * strength, 0, 255)

    for cls, allowed in allowed_by_class.items():
        mask = classes == cls
        if mask.any():
            result[mask] = nearest(work[mask], allowed)
    return result


def _floyd_steinberg(rgb, classes, allowed_by_class, strength, result):
    height, width = classes.shape
    work = rgb.copy()
    palette = PALETTE.astype(np.float64).tolist()
    luts = {cls: _Lut.get(allowed).ravel().tolist() for cls, allowed in allowed_by_class.items()}
    step = _LUT_STEP
    bits = _LUT_BITS
    cls_rows = classes.tolist()
    rows = work.tolist()

    for y in range(height):
        row = rows[y]
        cls_row = cls_rows[y]
        has_next = y + 1 < height
        next_row = rows[y + 1] if has_next else None
        next_cls = cls_rows[y + 1] if has_next else None
        out_row = result[y]
        indices = [0] * width
        for x in range(width):
            cls = cls_row[x]
            if cls < 0:
                continue
            lut = luts.get(cls)
            if lut is None:
                continue
            r, g, b = row[x]
            ri = min(255, max(0, int(r))) // step
            gi = min(255, max(0, int(g))) // step
            bi = min(255, max(0, int(b))) // step
            index = lut[(((ri << bits) | gi) << bits) | bi]
            indices[x] = index
            pr, pg, pb = palette[index]
            er = (r - pr) * strength
            eg = (g - pg) * strength
            eb = (b - pb) * strength
            if x + 1 < width and cls_row[x + 1] == cls:
                _add(row[x + 1], er, eg, eb, 7.0 / 16.0)
            if has_next:
                if x > 0 and next_cls[x - 1] == cls:
                    _add(next_row[x - 1], er, eg, eb, 3.0 / 16.0)
                if next_cls[x] == cls:
                    _add(next_row[x], er, eg, eb, 5.0 / 16.0)
                if x + 1 < width and next_cls[x + 1] == cls:
                    _add(next_row[x + 1], er, eg, eb, 1.0 / 16.0)
        out_row[:] = indices


def _add(pixel, er, eg, eb, weight):
    pixel[0] += er * weight
    pixel[1] += eg * weight
    pixel[2] += eb * weight
