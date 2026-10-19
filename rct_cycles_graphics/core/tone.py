"""Matching the tones of a render to the original RCT2 trees.

The original sprites sit low on the palette ramps: most pixels use the four
darkest shades of their ramp, and the top shades are kept for a few
highlights. A render is matched to that by moving every pixel along its own
ramp, so a yellow tree stays yellow and only its shading changes. The curve is
fitted once over every render of the object, so all views and frames get the
same correction.
"""

import numpy as np

from . import palette, postprocess, quantize

SHADE_COUNT = 12

#: Share of each shade (0 darkest to 11 lightest) in the sprites of the 33
#: vanilla RCT2 trees (snow-covered ones excluded, each tree weighted alike),
#: without the rim pixels: those get the outline, not the shading.
REFERENCE_SHADES = np.array(
    [0.0542, 0.1287, 0.1879, 0.1945, 0.1606, 0.1270, 0.0807, 0.0397, 0.0187, 0.0064, 0.0013, 0.0003]
)

#: Same, rim included: what finished sprites are compared with.
REFERENCE_SHADES_ALL = np.array(
    [0.0693, 0.1471, 0.1936, 0.1890, 0.1517, 0.1149, 0.0738, 0.0361, 0.0171, 0.0059, 0.0012, 0.0002]
)

#: Mean HSV saturation of the same sprites (rim excluded).
REFERENCE_SATURATION = 0.56

#: Saturation is only nudged: some trees are meant to be duller or brighter.
SATURATION_GAIN_RANGE = (0.85, 1.25)

#: Points of the brightness distribution the curve passes through. The
#: curve is smooth between them, so the render's own shading is kept.
QUANTILES = np.array([0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98])

#: Steepest the curve may get, so a narrow band of shades is not stretched
#: into banding.
MAX_SLOPE = 4.0


def _build_ramps():
    ramps = [np.array(list(r)) for r in palette.RAMPS.values()]
    ramps += [np.array(list(r)) for r in palette.REMAP_RANGES.values()]
    ramp_of = np.full(256, -1, dtype=np.int32)
    position_of = np.full(256, -1, dtype=np.int32)
    for number, ramp in enumerate(ramps):
        ramp_of[ramp] = number
        position_of[ramp] = np.arange(SHADE_COUNT)
    for index, name in palette.EXTRA_COLOURS.items():
        shade = palette.shift_shade(index, 0)
        ramp_of[index] = ramp_of[shade]
        position_of[index] = position_of[shade]
    colours = np.stack([palette.PALETTE[r].astype(np.float32) for r in ramps])
    return ramps, ramp_of, position_of, colours


_RAMPS, _RAMP_OF, _POSITION_OF, _RAMP_COLOURS = _build_ramps()
_RAMP_LUMINANCE = postprocess.luminance(_RAMP_COLOURS)
_REMAP_RAMP = {remap: _RAMP_OF[r[0]] for remap, r in palette.REMAP_RANGES.items()}


def reference_quantiles(shares=REFERENCE_SHADES, quantiles=QUANTILES):
    """Continuous shade (0-11) at each quantile of a shade histogram.

    Shade k stands for the interval [k - 0.5, k + 0.5], clipped to the ramp.
    """
    edges = np.concatenate([[0.0], np.arange(SHADE_COUNT - 1) + 0.5, [SHADE_COUNT - 1.0]])
    cdf = np.concatenate([[0.0], np.cumsum(shares) / np.sum(shares)])
    return np.interp(quantiles, cdf, edges)


def pixel_ramps(rgb, classes, allowed):
    """Ramp number of each pixel: its remap ramp, or the ramp of its nearest colour."""
    ramps = np.zeros(classes.shape, dtype=np.int32)
    for cls, indices in allowed.items():
        selected = classes == cls
        if not selected.any():
            continue
        if cls > 0:
            ramps[selected] = _REMAP_RAMP[cls]
        else:
            ramps[selected] = _RAMP_OF[quantize.nearest(rgb[selected], indices)]
    return ramps


def shade_of(rgb, ramps):
    """Continuous position (0-11) of each colour's brightness on its ramp."""
    lum = postprocess.luminance(rgb)
    shade = np.zeros(lum.shape, dtype=np.float32)
    positions = np.arange(SHADE_COUNT, dtype=np.float32)
    for ramp in np.unique(ramps):
        selected = ramps == ramp
        shade[selected] = np.interp(lum[selected], _RAMP_LUMINANCE[ramp], positions)
    return shade


def ramp_colour(ramps, shade):
    """Colour of each ramp at a continuous shade position."""
    shade = np.clip(shade, 0, SHADE_COUNT - 1)
    low = np.floor(shade).astype(np.int32)
    high = np.minimum(low + 1, SHADE_COUNT - 1)
    t = (shade - low)[..., None]
    return _RAMP_COLOURS[ramps, low] * (1.0 - t) + _RAMP_COLOURS[ramps, high] * t


def saturation(rgb):
    """Mean HSV saturation of (N, 3) colours."""
    if len(rgb) == 0:
        return 0.0
    high = rgb.max(axis=-1)
    low = rgb.min(axis=-1)
    return float(np.mean(np.where(high > 1e-6, (high - low) / np.maximum(high, 1e-6), 0.0)))


class ToneCurve:
    """Moves pixels along their ramps; see :func:`fit`."""

    def __init__(self, source, target, saturation_gain=1.0, strength=1.0):
        source = np.maximum.accumulate(np.asarray(source, dtype=np.float64))
        # Keep the curve's slope below MAX_SLOPE, even where the render's
        # shades bunch up.
        target = np.asarray(target, dtype=np.float64)
        steps = np.maximum(np.maximum(np.diff(source), np.diff(target) / MAX_SLOPE), 1e-3)
        self.source = np.concatenate([[source[0]], source[0] + np.cumsum(steps)])
        self.target = target
        self.saturation_gain = saturation_gain
        self.strength = strength

    def map_shade(self, shade):
        x, y = self.source, self.target
        mapped = np.interp(shade, x, y)
        # Beyond the outer quantiles, carry on with the end segments' slope.
        first = (y[1] - y[0]) / (x[1] - x[0])
        last = (y[-1] - y[-2]) / (x[-1] - x[-2])
        mapped = np.where(shade < x[0], y[0] + (shade - x[0]) * first, mapped)
        mapped = np.where(shade > x[-1], y[-1] + (shade - x[-1]) * last, mapped)
        mapped = np.clip(mapped, 0, SHADE_COUNT - 1)
        return shade + self.strength * (mapped - shade)

    def apply(self, rgb, classes, allowed):
        """Return the (H, W, 3) sRGB 0-255 colours ``rgb`` with matched tones."""
        selected = classes >= 0
        if not selected.any():
            return rgb
        pixels = rgb[selected]
        ramps = pixel_ramps(pixels, classes[selected], allowed)
        out = rgb.copy()
        out[selected] = self._apply_pixels(pixels, ramps, classes[selected])
        return out

    def _apply_pixels(self, pixels, ramps, classes):
        shade = shade_of(pixels, ramps)
        # Shift by the ramp's own change between the two shades, which keeps
        # each pixel's offset from the ramp (its texture) and its hue.
        out = pixels + ramp_colour(ramps, self.map_shade(shade)) - ramp_colour(ramps, shade)
        gain = 1.0 + self.strength * (self.saturation_gain - 1.0)
        if gain != 1.0:
            # Recolourable pixels keep their brightness only.
            plain = classes == 0
            lum = postprocess.luminance(out[plain])[:, None]
            out[plain] = lum + (out[plain] - lum) * gain
        return np.clip(out, 0.0, 255.0)


def fit(samples, strength=1.0, match_saturation=True):
    """Fit a :class:`ToneCurve` on every render of an object.

    samples: (rgb, classes, allowed) triples as returned by
    :func:`postprocess.prepare`. The fit ignores rim pixels, which the outline
    darkens anyway. Returns None when there is nothing to fit on.
    """
    shades, colours, ramp_list, class_list = [], [], [], []
    for rgb, classes, allowed in samples:
        opaque = classes >= 0
        interior = opaque & ~postprocess.edge_pixels(opaque)
        if not interior.any():
            interior = opaque
        if not interior.any():
            continue
        pixels = rgb[interior]
        ramps = pixel_ramps(pixels, classes[interior], allowed)
        shades.append(shade_of(pixels, ramps))
        colours.append(pixels)
        ramp_list.append(ramps)
        class_list.append(classes[interior])
    if not shades:
        return None
    shade = np.concatenate(shades)
    curve = ToneCurve(np.quantile(shade, QUANTILES), reference_quantiles(), 1.0, 1.0)
    if match_saturation:
        mapped = curve._apply_pixels(np.concatenate(colours), np.concatenate(ramp_list), np.concatenate(class_list))
        current = saturation(mapped)
        if current > 1e-3:
            curve.saturation_gain = float(np.clip(REFERENCE_SATURATION / current, *SATURATION_GAIN_RANGE))
    curve.strength = strength
    return curve


def shade_histogram(index_arrays):
    """Share of each shade among the ramp pixels of palette images."""
    counts = np.zeros(SHADE_COUNT)
    for indices in index_arrays:
        positions = _POSITION_OF[np.asarray(indices).ravel()]
        positions = positions[positions >= 0]
        counts += np.bincount(positions, minlength=SHADE_COUNT)
    total = counts.sum()
    return counts / total if total else counts


def _bands(shares):
    return [round(100 * shares[:3].sum()), round(100 * shares[3:6].sum()), round(100 * shares[6:].sum())]


def report(index_arrays):
    """Lines comparing finished sprites' shades with the RCT2 trees."""
    shares = shade_histogram(index_arrays)
    if not shares.any():
        return []
    shades = np.arange(SHADE_COUNT)
    return [
        "Average shade {:.1f} of 11 (RCT2 trees {:.1f})".format(
            (shares * shades).sum(), (REFERENCE_SHADES_ALL * shades).sum()
        ),
        "Dark / mid / light: {} / {} / {}% (RCT2 trees {} / {} / {}%)".format(
            *(_bands(shares) + _bands(REFERENCE_SHADES_ALL))
        ),
    ]
