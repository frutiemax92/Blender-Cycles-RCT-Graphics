"""Matching the tones of a render to the original RCT2 trees.

The original sprites sit low on the palette ramps: most pixels use the four
darkest shades of their ramp, and the top shades are kept for a few
highlights. How low varies a lot from tree to tree, so a render is matched to
the RCT2 trees about as bright as itself (or to one chosen tree), by moving
every pixel along its own ramp: a yellow tree stays yellow and only its
shading changes. The curve is fitted once over every render of the object, so
all views and frames get the same correction.
"""

import numpy as np

from . import palette, postprocess, quantize

SHADE_COUNT = 12

#: Snow-covered trees: mostly white, so not a reference for shading foliage.
SNOW_TREES = ("TCFS", "TNSS", "TRFS")

#: The vanilla RCT2 trees, from tools/measure_rct2_tones.py: code, name,
#: share of each shade (0 darkest to 11 lightest) without the rim pixels
#: (those get the outline, not the shading), the same with the rim (what
#: finished sprites are compared with), and the mean HSV saturation without
#: the rim. The trees differ a lot: a Norway Spruce averages shade 1.8, a
#: White Poplar 5.3, so no single histogram stands for all of them.
RCT2_TREES = (
    ("TAP", "Aleppo Pine",
     (0.0622, 0.1701, 0.2488, 0.2093, 0.1479, 0.0924, 0.0417, 0.0150, 0.0126, 0.0000, 0.0000, 0.0000),
     (0.1153, 0.1993, 0.2309, 0.1838, 0.1294, 0.0808, 0.0365, 0.0131, 0.0111, 0.0000, 0.0000, 0.0000),
     0.610),
    ("TAC", "Arizona Cypress",
     (0.0091, 0.0519, 0.1161, 0.1616, 0.1648, 0.1696, 0.1420, 0.0932, 0.0559, 0.0194, 0.0096, 0.0069),
     (0.0203, 0.0702, 0.1274, 0.1648, 0.1624, 0.1569, 0.1299, 0.0850, 0.0504, 0.0179, 0.0086, 0.0062),
     0.424),
    ("TAS", "Aspen",
     (0.0239, 0.0828, 0.1235, 0.1426, 0.2017, 0.1971, 0.1168, 0.0724, 0.0308, 0.0087, 0.0000, 0.0000),
     (0.0491, 0.1277, 0.1347, 0.1341, 0.1783, 0.1741, 0.1032, 0.0639, 0.0272, 0.0077, 0.0000, 0.0000),
     0.416),
    ("TBP", "Black Poplar",
     (0.0962, 0.1927, 0.2801, 0.2228, 0.1453, 0.0446, 0.0142, 0.0036, 0.0006, 0.0000, 0.0000, 0.0000),
     (0.1273, 0.2117, 0.2670, 0.2041, 0.1324, 0.0406, 0.0130, 0.0032, 0.0005, 0.0000, 0.0000, 0.0000),
     0.590),
    ("TCT", "Cabbage Tree",
     (0.0277, 0.0640, 0.1685, 0.1730, 0.2032, 0.1860, 0.1135, 0.0493, 0.0140, 0.0008, 0.0000, 0.0000),
     (0.0304, 0.0737, 0.1638, 0.1673, 0.1935, 0.1790, 0.1167, 0.0566, 0.0177, 0.0013, 0.0000, 0.0000),
     0.563),
    ("TH1", "Canary Palm",
     (0.0496, 0.1180, 0.2021, 0.2041, 0.1748, 0.1236, 0.0693, 0.0300, 0.0194, 0.0071, 0.0020, 0.0000),
     (0.0508, 0.1151, 0.2011, 0.2066, 0.1842, 0.1237, 0.0684, 0.0278, 0.0155, 0.0052, 0.0015, 0.0000),
     0.579),
    ("TCF", "Caucasian Fir",
     (0.0299, 0.1485, 0.2134, 0.2678, 0.1405, 0.1207, 0.0484, 0.0236, 0.0049, 0.0024, 0.0000, 0.0000),
     (0.0388, 0.1802, 0.2223, 0.2550, 0.1265, 0.1079, 0.0426, 0.0205, 0.0042, 0.0020, 0.0000, 0.0000),
     0.589),
    ("TCL", "Cedar of Lebanon",
     (0.0377, 0.1172, 0.1581, 0.2045, 0.1764, 0.1354, 0.0841, 0.0537, 0.0243, 0.0072, 0.0014, 0.0000),
     (0.0560, 0.1478, 0.1791, 0.2005, 0.1580, 0.1169, 0.0704, 0.0445, 0.0200, 0.0058, 0.0011, 0.0000),
     0.529),
    ("TCC", "Chinese Cedar",
     (0.0558, 0.0778, 0.2164, 0.1414, 0.1754, 0.1174, 0.1590, 0.0173, 0.0346, 0.0039, 0.0011, 0.0000),
     (0.0766, 0.1043, 0.2664, 0.1222, 0.1871, 0.0472, 0.1368, 0.0060, 0.0401, 0.0105, 0.0027, 0.0000),
     0.549),
    ("TCO", "Common Oak",
     (0.0978, 0.1611, 0.2115, 0.1652, 0.1458, 0.1010, 0.0609, 0.0308, 0.0211, 0.0045, 0.0004, 0.0000),
     (0.1222, 0.1640, 0.2103, 0.1604, 0.1392, 0.0943, 0.0569, 0.0285, 0.0196, 0.0042, 0.0004, 0.0000),
     0.734),
    ("TCY", "Common Yew",
     (0.0243, 0.1400, 0.2399, 0.2705, 0.1406, 0.1214, 0.0422, 0.0191, 0.0021, 0.0000, 0.0000, 0.0000),
     (0.0296, 0.1697, 0.2477, 0.2626, 0.1311, 0.1055, 0.0359, 0.0162, 0.0017, 0.0000, 0.0000, 0.0000),
     0.602),
    ("TCRP", "Corsican Pine",
     (0.0774, 0.1389, 0.1773, 0.2110, 0.1556, 0.1364, 0.0549, 0.0399, 0.0085, 0.0000, 0.0000, 0.0000),
     (0.1316, 0.2138, 0.1722, 0.1753, 0.1244, 0.1045, 0.0416, 0.0303, 0.0064, 0.0000, 0.0000, 0.0000),
     0.583),
    ("TEL", "European Larch",
     (0.0213, 0.1154, 0.2248, 0.2790, 0.1698, 0.1310, 0.0378, 0.0181, 0.0025, 0.0003, 0.0000, 0.0000),
     (0.0244, 0.1387, 0.2380, 0.2768, 0.1551, 0.1168, 0.0328, 0.0151, 0.0020, 0.0003, 0.0000, 0.0000),
     0.609),
    ("TGHC", "Golden Hinoki Cypress",
     (0.0394, 0.1359, 0.1682, 0.2724, 0.1256, 0.1287, 0.0611, 0.0395, 0.0162, 0.0127, 0.0003, 0.0000),
     (0.0430, 0.1427, 0.1779, 0.2715, 0.1211, 0.1231, 0.0572, 0.0368, 0.0148, 0.0116, 0.0003, 0.0000),
     0.616),
    ("THL", "Honey Locust",
     (0.0353, 0.1112, 0.1553, 0.1814, 0.1881, 0.1458, 0.0930, 0.0578, 0.0216, 0.0074, 0.0030, 0.0000),
     (0.0451, 0.1207, 0.1524, 0.1770, 0.1849, 0.1419, 0.0939, 0.0548, 0.0199, 0.0070, 0.0024, 0.0000),
     0.467),
    ("TIC", "Incense Cedar",
     (0.0073, 0.1346, 0.1711, 0.1683, 0.1623, 0.1356, 0.0990, 0.0575, 0.0341, 0.0227, 0.0076, 0.0000),
     (0.0105, 0.1567, 0.1779, 0.1715, 0.1561, 0.1252, 0.0911, 0.0526, 0.0309, 0.0206, 0.0070, 0.0000),
     0.542),
    ("TITC", "Italian Cypress",
     (0.0912, 0.1761, 0.2284, 0.2474, 0.1223, 0.0947, 0.0320, 0.0079, 0.0000, 0.0000, 0.0000, 0.0000),
     (0.1116, 0.1918, 0.2301, 0.2318, 0.1121, 0.0864, 0.0290, 0.0072, 0.0000, 0.0000, 0.0000, 0.0000),
     0.592),
    ("TLC", "Lawson Cypress",
     (0.0078, 0.0694, 0.1254, 0.2103, 0.2009, 0.1811, 0.0926, 0.0717, 0.0330, 0.0073, 0.0005, 0.0000),
     (0.0085, 0.0879, 0.1349, 0.2154, 0.1951, 0.1673, 0.0869, 0.0667, 0.0302, 0.0066, 0.0004, 0.0000),
     0.533),
    ("TLP", "Lombardy Poplar",
     (0.1624, 0.1459, 0.1619, 0.1777, 0.1507, 0.1096, 0.0570, 0.0190, 0.0107, 0.0051, 0.0000, 0.0000),
     (0.1977, 0.1586, 0.1664, 0.1626, 0.1357, 0.0977, 0.0505, 0.0168, 0.0095, 0.0045, 0.0000, 0.0000),
     0.596),
    ("TMP", "Monkey-Puzzle",
     (0.0102, 0.0537, 0.1064, 0.1773, 0.2273, 0.1929, 0.1517, 0.0722, 0.0082, 0.0000, 0.0000, 0.0000),
     (0.0113, 0.0693, 0.1126, 0.1854, 0.2186, 0.1807, 0.1408, 0.0688, 0.0126, 0.0000, 0.0000, 0.0000),
     0.479),
    ("TMC", "Monterey Cypress",
     (0.0808, 0.1701, 0.1750, 0.2524, 0.1127, 0.1109, 0.0528, 0.0288, 0.0091, 0.0075, 0.0000, 0.0000),
     (0.0892, 0.1782, 0.1831, 0.2487, 0.1078, 0.1038, 0.0481, 0.0261, 0.0083, 0.0068, 0.0000, 0.0000),
     0.479),
    ("TMZP", "Montezuma Pine",
     (0.0781, 0.1926, 0.2428, 0.2029, 0.1411, 0.0902, 0.0307, 0.0125, 0.0091, 0.0000, 0.0000, 0.0000),
     (0.1024, 0.2156, 0.2331, 0.1877, 0.1298, 0.0832, 0.0283, 0.0115, 0.0084, 0.0000, 0.0000, 0.0000),
     0.619),
    ("TNS", "Norway Spruce",
     (0.2274, 0.2782, 0.2295, 0.1153, 0.0783, 0.0638, 0.0076, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000),
     (0.2431, 0.3037, 0.2114, 0.1092, 0.0706, 0.0559, 0.0061, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000),
     0.677),
    ("TPM", "Palm Tree",
     (0.0731, 0.1131, 0.1594, 0.1553, 0.1480, 0.1508, 0.1393, 0.0601, 0.0010, 0.0000, 0.0000, 0.0000),
     (0.0534, 0.1001, 0.1648, 0.1825, 0.1443, 0.1597, 0.1347, 0.0598, 0.0007, 0.0000, 0.0000, 0.0000),
     0.443),
    ("TH2", "Palm Tree (Tall)",
     (0.0098, 0.0930, 0.2153, 0.2271, 0.2051, 0.1465, 0.0733, 0.0230, 0.0069, 0.0000, 0.0000, 0.0000),
     (0.0090, 0.1031, 0.2173, 0.2354, 0.2102, 0.1343, 0.0649, 0.0200, 0.0058, 0.0000, 0.0000, 0.0000),
     0.426),
    ("TRF", "Red Fir",
     (0.0296, 0.1799, 0.2797, 0.2452, 0.1308, 0.0991, 0.0306, 0.0052, 0.0000, 0.0000, 0.0000, 0.0000),
     (0.0260, 0.2182, 0.3044, 0.2279, 0.1121, 0.0830, 0.0237, 0.0047, 0.0000, 0.0000, 0.0000, 0.0000),
     0.598),
    ("TRF2", "Red Fir (Narrow)",
     (0.0372, 0.2131, 0.2892, 0.2332, 0.1183, 0.0811, 0.0247, 0.0033, 0.0000, 0.0000, 0.0000, 0.0000),
     (0.0366, 0.2111, 0.3245, 0.2261, 0.1043, 0.0742, 0.0206, 0.0025, 0.0000, 0.0000, 0.0000, 0.0000),
     0.602),
    ("TSP", "Scots Pine",
     (0.1230, 0.1989, 0.2240, 0.1758, 0.1421, 0.0807, 0.0383, 0.0146, 0.0025, 0.0000, 0.0000, 0.0000),
     (0.2248, 0.2191, 0.1943, 0.1453, 0.1120, 0.0626, 0.0290, 0.0110, 0.0019, 0.0000, 0.0000, 0.0000),
     0.676),
    ("TSB", "Silver Birch",
     (0.0849, 0.1491, 0.2444, 0.0274, 0.2234, 0.0207, 0.1419, 0.0173, 0.0702, 0.0183, 0.0024, 0.0000),
     (0.0963, 0.1523, 0.2538, 0.0355, 0.2154, 0.0220, 0.1329, 0.0137, 0.0604, 0.0156, 0.0021, 0.0000),
     0.559),
    ("TVL", "Voss's Laburnum",
     (0.0023, 0.0183, 0.0747, 0.1698, 0.1323, 0.2312, 0.1671, 0.1268, 0.0515, 0.0223, 0.0034, 0.0002),
     (0.0062, 0.0285, 0.0935, 0.1763, 0.1299, 0.2217, 0.1553, 0.1178, 0.0476, 0.0200, 0.0030, 0.0002),
     0.619),
    ("TWN", "Walnut",
     (0.0514, 0.1602, 0.1753, 0.2290, 0.2054, 0.0878, 0.0540, 0.0304, 0.0031, 0.0035, 0.0000, 0.0000),
     (0.0681, 0.1820, 0.1721, 0.2190, 0.1922, 0.0819, 0.0503, 0.0283, 0.0029, 0.0032, 0.0000, 0.0000),
     0.605),
    ("TWW", "Weeping Willow",
     (0.0210, 0.0456, 0.1190, 0.1982, 0.2158, 0.1812, 0.1363, 0.0606, 0.0157, 0.0060, 0.0006, 0.0000),
     (0.0252, 0.0545, 0.1292, 0.2173, 0.2099, 0.1642, 0.1202, 0.0588, 0.0141, 0.0061, 0.0005, 0.0000),
     0.601),
    ("TWP", "White Poplar",
     (0.0027, 0.0294, 0.0760, 0.0989, 0.1279, 0.1838, 0.1962, 0.1350, 0.0928, 0.0437, 0.0113, 0.0020),
     (0.0082, 0.0428, 0.0942, 0.0976, 0.1431, 0.1764, 0.1866, 0.1213, 0.0806, 0.0379, 0.0096, 0.0018),
     0.439),
)

TREE_NAMES = {code: name for code, name, _, _, _ in RCT2_TREES}
_TREE_CODES = [code for code, _, _, _, _ in RCT2_TREES]
_TREE_SHADES = np.array([shades for _, _, shades, _, _ in RCT2_TREES])
_TREE_SHADES_ALL = np.array([shades for _, _, _, shades, _ in RCT2_TREES])
_TREE_SATURATION = np.array([sat for _, _, _, _, sat in RCT2_TREES])
_TREE_MEANS = _TREE_SHADES @ np.arange(SHADE_COUNT)
_TREE_MEANS_ALL = _TREE_SHADES_ALL @ np.arange(SHADE_COUNT)

#: The average tree, each tree weighted alike.
REFERENCE_SHADES = _TREE_SHADES.mean(axis=0)
REFERENCE_SHADES_ALL = _TREE_SHADES_ALL.mean(axis=0)
REFERENCE_SATURATION = float(_TREE_SATURATION.mean())

#: How closely, in shades, the trees blended by the "AUTO" reference must
#: match the render's mean shade.
CLOSEST_BANDWIDTH = 0.35


class Reference:
    """Shade histograms and saturation the render is matched to."""

    def __init__(self, shades, shades_all, saturation, label):
        self.shades = shades
        self.shades_all = shades_all
        self.saturation = saturation
        self.label = label


def reference(key="AUTO", mean_shade=None, rim_included=False):
    """The :class:`Reference` for ``key``.

    key: "AVERAGE" (the average tree), a tree code from :data:`RCT2_TREES`,
    or "AUTO": the trees whose mean shade is closest to ``mean_shade``, which
    is first brought within the range of the trees. So a light tree is
    matched to light RCT2 trees and keeps its brightness, and only a render
    darker or lighter than every RCT2 tree is brought back into their range.
    rim_included: whether ``mean_shade`` counts the rim pixels.
    """
    if key == "AVERAGE" or (key == "AUTO" and mean_shade is None):
        weights = np.ones(len(RCT2_TREES))
        label = "RCT2 trees"
    elif key == "AUTO":
        means = _TREE_MEANS_ALL if rim_included else _TREE_MEANS
        target = np.clip(mean_shade, means.min(), means.max())
        weights = np.exp(-0.5 * ((means - target) / CLOSEST_BANDWIDTH) ** 2)
        label = "closest RCT2 trees"
    else:
        weights = (np.array(_TREE_CODES) == key).astype(np.float64)
        if not weights.any():
            raise ValueError("Unknown RCT2 tree {!r}".format(key))
        label = TREE_NAMES[key]
    weights = weights / weights.sum()
    return Reference(weights @ _TREE_SHADES, weights @ _TREE_SHADES_ALL, float(weights @ _TREE_SATURATION), label)


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


def fit(samples, strength=1.0, match_saturation=True, reference_key="AUTO"):
    """Fit a :class:`ToneCurve` on every render of an object.

    samples: (rgb, classes, allowed) triples as returned by
    :func:`postprocess.prepare`. The fit ignores rim pixels, which the outline
    darkens anyway. reference_key: see :func:`reference`. Returns None when
    there is nothing to fit on.
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
    target = reference(reference_key, float(shade.mean()))
    curve = ToneCurve(np.quantile(shade, QUANTILES), reference_quantiles(target.shades), 1.0, 1.0)
    if match_saturation:
        mapped = curve._apply_pixels(np.concatenate(colours), np.concatenate(ramp_list), np.concatenate(class_list))
        current = saturation(mapped)
        if current > 1e-3:
            curve.saturation_gain = float(np.clip(target.saturation / current, *SATURATION_GAIN_RANGE))
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


def report(index_arrays, reference_key="AUTO"):
    """Lines comparing finished sprites' shades with the RCT2 trees."""
    shares = shade_histogram(index_arrays)
    if not shares.any():
        return []
    shades = np.arange(SHADE_COUNT)
    mean = (shares * shades).sum()
    target = reference(reference_key, mean, rim_included=True)
    return [
        "Average shade {:.1f} of 11 ({} {:.1f})".format(mean, target.label, (target.shades_all * shades).sum()),
        "Dark / mid / light: {} / {} / {}% ({} {} / {} / {}%)".format(
            *(_bands(shares) + [target.label] + _bands(target.shades_all))
        ),
    ]
