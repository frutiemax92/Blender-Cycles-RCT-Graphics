"""The RollerCoaster Tycoon 2 / OpenRCT2 standard palette.

Colour values come from OpenRCT2's ``StandardPalette`` (ImageImporter.h),
converted from BGR to RGB. Sprites written with exactly these colours are
imported by OpenRCT2 without any colour conversion.
"""

import numpy as np

# fmt: off
_BGR = [
    # 0 transparent, 1-9 special (font, water, chain lift)
    (0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4), (5, 5, 5), (6, 6, 6), (7, 7, 7), (8, 8, 8), (9, 9, 9),
    # 10-21 grey
    (35, 35, 23), (51, 51, 35), (67, 67, 47), (83, 83, 63), (99, 99, 75), (115, 115, 91),
    (131, 131, 111), (151, 151, 131), (175, 175, 159), (195, 195, 183), (219, 219, 211), (243, 243, 239),
    # 22-33 olive
    (0, 47, 51), (0, 59, 63), (11, 75, 79), (19, 91, 91), (31, 107, 107), (47, 123, 119),
    (59, 139, 135), (79, 155, 151), (95, 175, 167), (115, 191, 187), (139, 207, 203), (163, 227, 223),
    # 34-45 light brown
    (7, 43, 67), (11, 59, 87), (23, 75, 111), (31, 87, 127), (39, 99, 143), (51, 115, 159),
    (67, 131, 179), (87, 151, 191), (111, 175, 203), (135, 199, 219), (163, 219, 231), (195, 239, 247),
    # 46-57 yellow (tertiary remap)
    (0, 27, 71), (0, 43, 95), (0, 63, 119), (7, 83, 143), (7, 111, 167), (15, 139, 191),
    (19, 167, 215), (27, 203, 243), (47, 231, 255), (95, 243, 255), (143, 251, 255), (195, 255, 255),
    # 58-69 indian red
    (0, 0, 35), (0, 0, 79), (7, 7, 95), (15, 15, 111), (27, 27, 127), (39, 39, 143),
    (59, 59, 163), (79, 79, 179), (103, 103, 199), (127, 127, 215), (159, 159, 235), (191, 191, 255),
    # 70-81 grass green
    (19, 51, 27), (23, 63, 35), (31, 79, 47), (39, 95, 59), (43, 111, 71), (51, 127, 87),
    (59, 143, 99), (67, 155, 115), (75, 171, 131), (83, 187, 147), (95, 203, 163), (103, 219, 183),
    # 82-93 olive green
    (27, 55, 31), (35, 71, 47), (43, 83, 59), (55, 99, 75), (67, 111, 91), (79, 135, 111),
    (95, 159, 135), (111, 183, 159), (127, 207, 183), (147, 219, 195), (167, 231, 207), (191, 247, 223),
    # 94-105 green
    (0, 63, 15), (0, 83, 19), (0, 103, 23), (0, 123, 31), (7, 143, 39), (23, 159, 55),
    (39, 175, 71), (63, 191, 91), (87, 207, 111), (115, 223, 139), (143, 239, 163), (179, 255, 195),
    # 106-117 tan
    (19, 43, 79), (27, 55, 99), (43, 71, 119), (59, 87, 139), (67, 99, 167), (83, 115, 187),
    (99, 131, 207), (115, 151, 215), (131, 171, 227), (151, 191, 239), (171, 207, 247), (195, 227, 255),
    # 118-129 indigo
    (55, 19, 15), (87, 43, 39), (103, 55, 51), (119, 67, 63), (139, 83, 83), (155, 99, 99),
    (175, 119, 119), (191, 139, 139), (207, 159, 159), (223, 183, 183), (239, 211, 211), (255, 239, 239),
    # 130-141 blue
    (111, 27, 0), (151, 39, 0), (167, 51, 7), (187, 67, 15), (203, 83, 27), (223, 103, 43),
    (227, 135, 67), (231, 163, 91), (239, 187, 119), (243, 211, 143), (251, 231, 175), (255, 247, 215),
    # 142-153 sea green
    (15, 43, 11), (23, 55, 15), (31, 71, 23), (43, 83, 35), (59, 99, 47), (75, 115, 59),
    (95, 135, 79), (119, 155, 99), (139, 175, 123), (167, 199, 147), (195, 219, 175), (223, 243, 207),
    # 154-165 purple
    (95, 0, 63), (115, 7, 75), (127, 15, 83), (143, 31, 95), (155, 43, 107), (171, 63, 123),
    (187, 83, 135), (199, 103, 155), (215, 127, 171), (231, 155, 191), (243, 195, 215), (255, 235, 243),
    # 166-177 red
    (0, 0, 63), (0, 0, 87), (0, 0, 115), (0, 0, 143), (0, 0, 171), (0, 0, 199),
    (0, 7, 227), (0, 7, 255), (67, 79, 255), (115, 123, 255), (163, 171, 255), (215, 219, 255),
    # 178-189 orange
    (0, 39, 79), (0, 51, 111), (0, 63, 147), (0, 71, 183), (0, 79, 219), (0, 83, 255),
    (23, 111, 255), (51, 139, 255), (79, 163, 255), (107, 183, 255), (135, 203, 255), (163, 219, 255),
    # 190-201 water blue
    (47, 51, 0), (55, 63, 0), (67, 75, 0), (79, 87, 0), (99, 107, 7), (119, 127, 23),
    (143, 147, 43), (163, 167, 71), (187, 187, 99), (207, 207, 131), (231, 231, 171), (255, 255, 207),
    # 202-213 pink (secondary remap)
    (27, 0, 63), (51, 0, 103), (63, 11, 123), (79, 23, 143), (95, 31, 163), (111, 39, 183),
    (143, 59, 219), (171, 91, 239), (187, 119, 243), (203, 151, 247), (223, 183, 251), (239, 215, 255),
    # 214-225 brown
    (0, 19, 39), (7, 31, 55), (15, 47, 71), (31, 63, 91), (51, 83, 107), (75, 103, 123),
    (107, 127, 143), (127, 147, 163), (147, 171, 187), (171, 195, 207), (195, 219, 231), (223, 243, 255),
    # 226 extra grey, 227-229 extra yellows
    (75, 75, 55), (0, 183, 255), (0, 219, 255), (0, 255, 255),
    # 230-234 water waves, 235-239 water sparkles (animated, special)
    (135, 143, 39), (123, 131, 27), (95, 103, 7), (87, 95, 0), (111, 119, 15),
    (255, 255, 199), (227, 227, 155), (175, 175, 83), (151, 155, 51), (203, 203, 123),
    # 240-242 extra grey
    (91, 91, 67), (107, 107, 83), (123, 123, 99),
    # 243-254 primary remap
    (47, 51, 111), (47, 55, 131), (51, 63, 151), (51, 67, 171), (47, 75, 191), (43, 79, 211),
    (35, 87, 231), (31, 95, 255), (39, 127, 255), (51, 155, 255), (63, 183, 255), (75, 207, 255),
    # 255 pure white (special)
    (255, 255, 255),
]
# fmt: on

assert len(_BGR) == 256

#: 256 x 3 array of RGB colours, uint8.
PALETTE = np.array([(r, g, b) for (b, g, r) in _BGR], dtype=np.uint8)

TRANSPARENT = 0

#: The twelve-shade colour ramps of the palette, darkest first.
RAMPS = {
    "grey": range(10, 22),
    "olive": range(22, 34),
    "light_brown": range(34, 46),
    "yellow": range(46, 58),
    "indian_red": range(58, 70),
    "grass_green": range(70, 82),
    "olive_green": range(82, 94),
    "green": range(94, 106),
    "tan": range(106, 118),
    "indigo": range(118, 130),
    "blue": range(130, 142),
    "sea_green": range(142, 154),
    "purple": range(154, 166),
    "red": range(166, 178),
    "orange": range(178, 190),
    "water_blue": range(190, 202),
    "pink": range(202, 214),
    "brown": range(214, 226),
}

#: Single colours outside the twelve-shade ramps, with the ramp they extend.
EXTRA_COLOURS = {226: "grey", 227: "yellow", 228: "yellow", 229: "yellow", 240: "grey", 241: "grey", 242: "grey"}

#: Remap (recolourable) ranges, indexed by remap number 1-3.
REMAP_RANGES = {
    1: range(243, 255),  # primary
    2: range(202, 214),  # secondary
    3: range(46, 58),  # tertiary
}

#: Human readable names for the UI, in display order.
RAMP_TITLES = [
    ("grey", "Grey"),
    ("olive", "Olive"),
    ("light_brown", "Light Brown"),
    ("yellow", "Yellow"),
    ("indian_red", "Indian Red"),
    ("grass_green", "Grass Green"),
    ("olive_green", "Olive Green"),
    ("green", "Green"),
    ("tan", "Tan"),
    ("indigo", "Indigo"),
    ("blue", "Blue"),
    ("sea_green", "Sea Green"),
    ("purple", "Purple"),
    ("red", "Red"),
    ("orange", "Orange"),
    ("water_blue", "Water Blue"),
    ("pink", "Pink"),
    ("brown", "Brown"),
]


def is_special(index):
    """True for palette entries the game reserves (animated water, text, ...)."""
    return index <= 9 or 230 <= index <= 239 or index == 255


def normal_indices(ramps=None, used_remaps=()):
    """Palette indices a non-recolourable pixel may be quantized to.

    ``ramps`` restricts the result to the named ramps (all when None).
    Ranges claimed by ``used_remaps`` are excluded, as is the primary remap
    range, which OpenRCT2 never uses for plain colours.
    """
    names = set(RAMPS) if ramps is None else set(ramps)
    excluded = set(REMAP_RANGES[1])
    for remap in used_remaps:
        excluded.update(REMAP_RANGES[remap])
    indices = []
    for name in RAMPS:
        if name in names:
            indices.extend(i for i in RAMPS[name] if i not in excluded)
    for index, ramp in EXTRA_COLOURS.items():
        if ramp in names and index not in excluded:
            indices.append(index)
    return sorted(indices)


def remap_indices(remap):
    """Palette indices for a recolourable pixel of remap ``remap`` (1-3)."""
    return list(REMAP_RANGES[remap])


def _build_ramp_lookup():
    """For every palette index, the ramp (as a list) it belongs to and its position."""
    lookup = {}
    for ramp in list(RAMPS.values()) + list(REMAP_RANGES.values()):
        shades = list(ramp)
        for position, index in enumerate(shades):
            lookup[index] = (shades, position)
    return lookup


_RAMP_LOOKUP = _build_ramp_lookup()


def _luminance(index):
    r, g, b = (int(c) for c in PALETTE[index])
    return 0.299 * r + 0.587 * g + 0.114 * b


def shift_shade(index, steps):
    """Move ``index`` ``steps`` shades along its ramp (negative = darker).

    Indices outside the ramps (extra greys and yellows) are first matched to
    the closest-luminance shade of the ramp they extend. Special and
    transparent indices are returned unchanged.
    """
    if index == TRANSPARENT or is_special(index):
        return index
    if index in EXTRA_COLOURS:
        ramp = list(RAMPS[EXTRA_COLOURS[index]])
        lum = _luminance(index)
        position = min(range(len(ramp)), key=lambda p: abs(_luminance(ramp[p]) - lum))
    else:
        ramp, position = _RAMP_LOOKUP[index]
    position = max(0, min(len(ramp) - 1, position + steps))
    return ramp[position]


def shade_shift_table(steps):
    """256-entry lookup table applying :func:`shift_shade` to every index."""
    return np.array([shift_shade(i, steps) for i in range(256)], dtype=np.uint8)
