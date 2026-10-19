"""Procedural tree generator, free of ``bpy``.

A tree is built in three stages, each with its own random stream so that
changing one stage's settings never reshuffles another:

1. A **skeleton** of polylines: the trunk (or the leaders it forks into),
   first-level branches and optional sub-branches.
2. A **canopy** of blobs (ellipsoids) placed from the branch tips and a
   canopy envelope, according to the canopy style. The needle style uses
   no blobs: thin triangles hang from the branches instead. The hair style
   uses straight strands that the Blender side renders as particle hair.
   The leaf instance style places a copy of a small leaf mesh where each
   strand would be, bent and deformed differently every time.
3. **Mesh data**: tubes for the trunk and branches, the canopy surface
   (icospheres here, or a metaball surface supplied by the Blender side;
   needles for the needle style, leaf copies for the leaf instance style),
   noise displacement, accent dots or snow faces, and an optional base.
   Hair strands are returned on the side, as roots, directions and lengths.

Units are Blender units (BU), angles in the parameter table are degrees.
The tile is centred on the origin and z = 0 is the element base, as in the
rest of the add-on. Everything is deterministic: same parameters and seed
give the same vertices on every platform.
"""

import math
import random
import zlib
from functools import lru_cache
from types import SimpleNamespace

import numpy as np

from .palette import RAMP_TITLES
from .projection import HEIGHT_STEP, TILE_SIZE

#: One sprite pixel in BU: a tile's 64 pixel width spans its 4 * sqrt(2) BU diagonal.
SPRITE_PIXEL = TILE_SIZE * math.sqrt(2.0) / 64.0
#: Branches thinner than this get no tube: they would only add noise to the sprite.
MIN_TUBE_RADIUS = 0.03
#: Hard cap on branch polyline segments, to keep regeneration interactive.
MAX_SEGMENTS = 400
#: Finest canopy mesh resolution (about a quarter of a pixel).
MIN_RESOLUTION = 0.02
#: The game clamps a small scenery bounding box to 128 z units.
SMALL_HEIGHT_LIMIT = 128.0 / 16.0 * HEIGHT_STEP
FACE_WARNING = 50000
#: Prefix of warnings that are only informative.
NOTE = "Note: "

ROLES = ("Trunk", "Leaves", "Accent", "Base")
#: Canopy styles placed as strands: hair renders them, leaf instances put a leaf on each.
STRAND_STYLES = ("HAIR", "INSTANCES")
TRUNK, LEAVES, ACCENT, BASE = range(4)

GOLDEN_ANGLE = 137.50776405


class Param:
    """One generator setting. The Blender property group is built from these."""

    def __init__(self, name, default, label, description, soft=None, hard=None, unit=None, items=None):
        self.name = name
        self.default = default
        self.label = label
        self.description = description
        self.soft = soft
        self.hard = hard
        #: "deg" for angles, "rel" for fractions, "bu" for lengths.
        self.unit = unit
        #: Enum items as (identifier, label, description).
        self.items = items

    @property
    def kind(self):
        if self.items is not None:
            return "enum"
        return type(self.default).__name__


def _enum(*names):
    return tuple((name, label, description) for name, label, description in names)


SIZES = _enum(
    ("FULL", "Full Tile", "Small scenery filling one tile"),
    ("FULL_CENTRED", "Full Tile, Centred", "Small scenery, full tile with the centred sprite offset"),
    ("QUARTER", "Quarter Tile", "Small scenery in one quarter of a tile, modelled around the origin"),
    ("LARGE", "Large (Multi-Tile)", "Large scenery covering several tiles"),
)
CANOPY_STYLES = _enum(
    ("BLOBS", "Blobs", "Clumps at the branch tips plus clumps scattered in the envelope"),
    ("LAYERS", "Layers", "One flattened cluster per branch tip"),
    ("NEEDLES", "Needles", "Thin needle planes in a fishbone along each branch (pines)"),
    ("HAIR", "Hair", "Straight strands rendered with Blender's hair particles (fine palm fronds, grasses)"),
    ("INSTANCES", "Leaf Instances", "Copies of a small leaf mesh, each bent and deformed at random (textured, leafy crowns)"),
    ("TIERS", "Tiers", "Elongated, drooping clumps along each branch"),
    ("COLUMN", "Column", "Clumps stacked along the trunk (cypress)"),
    ("TOPIARY", "Topiary", "The envelope itself is the canopy surface"),
    ("STRANDS", "Strands", "Chains of small clumps hanging from the tips (weeping trees)"),
    ("NONE", "None", "No foliage"),
)
CANOPY_SHAPES = _enum(
    ("SPHERE", "Sphere", "Round, at the top of the canopy space"),
    ("ELLIPSOID", "Ellipsoid", "Fills the canopy width and height"),
    ("CONE", "Cone", "Pointed top"),
    ("CYLINDER", "Cylinder", "Straight sides"),
    ("HEART", "Heart", "Two lobes over a point"),
    ("BELL", "Bell", "Rounded top over a flared base"),
)
PROFILES = _enum(
    ("ROUND", "Round", "Longest branches in the middle"),
    ("CONICAL", "Conical", "Longest branches at the bottom"),
    ("INVERTED", "Inverted", "Longest branches at the top"),
    ("CONSTANT", "Constant", "All branches the same length"),
)
SPREADS = _enum(
    ("SPIRAL", "Spiral", "Golden angle spiral around the trunk"),
    ("WHORLED", "Whorled", "Groups of branches at the same height"),
    ("RANDOM", "Random", "Random directions"),
)
ACCENT_MODES = _enum(
    ("NONE", "None", "No accent"),
    ("DOTS", "Dots", "Small spheres on the canopy (flowers, berries)"),
    ("TOP_FACING", "Top Facing", "Upward-facing canopy faces use the accent material (snow)"),
)
HAIR_SOURCES = _enum(
    ("BRANCHES", "Branches", "Along each branch past its bare start, like fronds"),
    ("TIPS", "Branch Tips", "Tufts at the end of each branch and stem"),
    ("CANOPY", "Canopy Surface", "Out of the canopy shape's surface"),
    ("VOLUME", "Canopy Volume", "From all through the canopy shape, pointing outwards (dense bushy crowns)"),
    ("CLUMPS", "Clumps", "Fluffy tufts out of clumps placed as in the Blobs style (irregular bushy crowns)"),
)
LEAF_SHAPES = _enum(
    ("BLADE", "Blade", "A narrow, pointed leaf folded along its midrib"),
    ("OVAL", "Oval", "A broad, rounded leaf"),
    ("SPRIG", "Sprig", "Three blades fanned from one stem"),
    ("CUSTOM", "Custom Object", "The mesh of the Leaf Object: its root at the origin, growing along +X, upper face towards +Z"),
)
BASE_STYLES = _enum(
    ("NONE", "None", "No base"),
    ("MOUND", "Mound", "A low earth mound"),
    ("POT", "Pot", "A flower pot"),
    ("ROCKS", "Rocks", "A few stones around the trunk"),
)

#: Settings grouped as in the panel: (group title, parameters).
GROUPS = (
    (
        "Size",
        (
            Param("size", "FULL", "Footprint", "Object size; also sets the scene's object type and shape", items=SIZES),
            Param("large_width", 2, "Width", "Footprint width in tiles (large scenery)", (1, 4), (1, 16)),
            Param("large_length", 2, "Length", "Footprint length in tiles (large scenery)", (1, 4), (1, 16)),
            Param("height", 6.5, "Height", "Total tree height including the canopy", (0.5, 40.0), (0.1, 200.0), "bu"),
            Param(
                "overhang",
                1.0,
                "Overhang",
                "Allowed canopy half-width as a multiple of the footprint half-width (1 = fits the tile)",
                (0.5, 1.5),
                (0.1, 3.0),
            ),
        ),
    ),
    (
        "Trunk",
        (
            Param(
                "trunk_length",
                0.55,
                "Length",
                "Fraction of the height from the ground to the trunk end (0 = no visible trunk)",
                (0.0, 1.0),
                (0.0, 1.0),
                "rel",
            ),
            Param("trunk_base_radius", 0.16, "Base Radius", "Trunk radius at the ground", (0.02, 1.5), (0.005, 10.0), "bu"),
            Param("trunk_top_radius", 0.06, "Top Radius", "Trunk radius at its end", (0.01, 1.5), (0.005, 10.0), "bu"),
            Param(
                "taper_curve",
                1.0,
                "Taper",
                "Exponent of the base to top radius change (above 1 thins faster near the base)",
                (0.3, 3.0),
                (0.05, 10.0),
            ),
            Param("root_flare", 0.3, "Root Flare", "Extra radius at the very base, relative to the base radius", (0.0, 1.5), (0.0, 5.0)),
            Param(
                "root_flare_height",
                0.08,
                "Flare Height",
                "Height of the root flare as a fraction of the trunk length",
                (0.0, 0.3),
                (0.0, 1.0),
                "rel",
            ),
            Param("trunk_sides", 6, "Sides", "Vertices around the trunk and branches", (3, 16), (3, 64)),
        ),
    ),
    (
        "Trunk Shape",
        (
            Param("straightness", 0.85, "Straightness", "1 is perfectly straight; lower adds slow bends", (0.0, 1.0), (0.0, 1.0), "rel"),
            Param("bend_frequency", 1.5, "Bend Frequency", "Number of bends along the trunk", (0.5, 6.0), (0.1, 20.0)),
            Param("gnarl", 0.0, "Gnarl", "Fast, small kinks of old, twisted trees", (0.0, 1.0), (0.0, 3.0)),
            Param("lean_angle", 0.0, "Lean", "Overall lean from vertical", (0.0, 45.0), (0.0, 80.0), "deg"),
            Param("lean_direction", 0.0, "Lean Direction", "Lean azimuth, 0 = Blender +X", (0.0, 360.0), (-720.0, 720.0), "deg"),
            Param("twist", 0.0, "Twist", "Twist of the bark coordinates and branch directions along the trunk", (-360.0, 360.0), (-3600.0, 3600.0), "deg"),
            Param("fork_count", 1, "Forks", "Number of leaders the trunk splits into (1 = no split)", (1, 4), (1, 8)),
            Param("fork_height", 0.6, "Fork Height", "Where the trunk splits, as a fraction of its length", (0.1, 1.0), (0.01, 1.0), "rel"),
            Param("fork_angle", 25.0, "Fork Angle", "Angle of each leader from the trunk", (0.0, 70.0), (0.0, 89.0), "deg"),
        ),
    ),
    (
        "Branches",
        (
            Param("branch_count", 4, "Count", "First-level branches on the trunk", (0, 40), (0, 200)),
            Param("branch_start", 0.55, "Start", "Lowest branch, as a fraction of the trunk length", (0.0, 1.0), (0.0, 1.0), "rel"),
            Param("branch_end", 0.95, "End", "Highest branch, as a fraction of the trunk length", (0.0, 1.0), (0.0, 1.0), "rel"),
            Param("branch_angle_base", 55.0, "Angle Bottom", "Angle from the trunk of the lowest branch", (0.0, 150.0), (0.0, 180.0), "deg"),
            Param("branch_angle_top", 30.0, "Angle Top", "Angle from the trunk of the highest branch (above 90 droops)", (0.0, 150.0), (0.0, 180.0), "deg"),
            Param("branch_length", 0.30, "Length", "Length of the longest branch, as a fraction of the height", (0.0, 1.0), (0.0, 2.0), "rel"),
            Param("branch_length_profile", "ROUND", "Profile", "How branch length changes with height", items=PROFILES),
            Param(
                "branch_radius_ratio",
                0.5,
                "Radius Ratio",
                "Branch base radius as a fraction of the trunk radius where it starts",
                (0.1, 1.0),
                (0.01, 1.0),
            ),
            Param("branch_curve", 0.2, "Curve", "Bend along each branch: positive curves up, negative droops", (-1.0, 1.0), (-3.0, 3.0)),
            Param("branch_spread", "SPIRAL", "Spread", "How branches are arranged around the trunk", items=SPREADS),
            Param("whorl_size", 4, "Whorl Size", "Branches per whorl when whorled", (2, 8), (1, 16)),
            Param("sub_branches", 0, "Sub-branches", "Second-level branches per branch", (0, 8), (0, 16)),
            Param("sub_branch_length", 0.5, "Sub-branch Length", "Sub-branch length relative to its parent", (0.1, 1.0), (0.01, 2.0)),
            Param("jitter", 0.3, "Jitter", "Random variation of angles, lengths and positions", (0.0, 1.0), (0.0, 1.0)),
        ),
    ),
    (
        "Leaves",
        (
            Param("canopy_style", "BLOBS", "Style", "How the foliage is built", items=CANOPY_STYLES),
            Param("canopy_shape", "SPHERE", "Shape", "Envelope the foliage is confined to", items=CANOPY_SHAPES),
            Param(
                "canopy_width",
                0.9,
                "Width",
                "Canopy half-width relative to the footprint half-width, limited by the overhang",
                (0.1, 1.5),
                (0.01, 3.0),
            ),
            Param("canopy_height", 0.5, "Canopy Height", "Canopy height as a fraction of the tree height", (0.05, 1.0), (0.01, 1.0), "rel"),
            Param(
                "canopy_offset",
                0.0,
                "Offset",
                "Vertical shift of the canopy as a fraction of the height (negative lowers it)",
                (-0.3, 0.3),
                (-1.0, 1.0),
                "rel",
            ),
            Param("clump_size", 0.9, "Clump Size", "Mean clump radius", (0.1, 3.0), (0.02, 10.0), "bu"),
            Param("clump_size_variation", 0.35, "Size Variation", "Random variation of the clump radius", (0.0, 1.0), (0.0, 0.95)),
            Param("clump_count", 0, "Extra Clumps", "Clumps scattered inside the envelope (0 = only at branch tips)", (0, 200), (0, 1000)),
            Param("clumps_per_tip", 2, "Clumps per Tip", "Clumps along the end of each branch", (1, 6), (1, 16)),
            Param("clump_flatten", 0.0, "Flatten", "Vertical squash of each clump", (0.0, 0.8), (0.0, 0.95)),
            Param("blob_merge", 0.6, "Merge", "How much neighbouring clumps fuse (0 = separate spheres)", (0.0, 1.0), (0.0, 1.0)),
            Param("lumpiness", 0.25, "Lumpiness", "Noise displacement of the canopy surface, relative to the clump size", (0.0, 1.0), (0.0, 2.0)),
            Param("lump_scale", 0.35, "Lump Scale", "Feature size of the lumps", (0.05, 2.0), (0.01, 10.0), "bu"),
            Param("raggedness", 0.3, "Raggedness", "Fine displacement giving a ragged silhouette", (0.0, 1.0), (0.0, 3.0)),
            Param("droop", 0.0, "Droop", "Pulls clumps down (weeping trees); also sets the strand length", (0.0, 1.0), (0.0, 2.0)),
            Param(
                "hollow",
                0.0,
                "Hollow",
                "Removes clumps near the trunk so inner branches show; with needles, the bare share of each branch",
                (0.0, 0.8),
                (0.0, 0.95),
            ),
            Param("needle_length", 0.5, "Needle Length", "Reach of the needles from their branch", (0.05, 1.5), (0.01, 5.0), "bu"),
            Param("needle_width", 0.08, "Needle Width", "Width of each needle at its base; one sprite pixel is about 0.09", (0.01, 0.3), (0.002, 2.0), "bu"),
            Param("needle_spacing", 0.06, "Needle Spacing", "Distance between needle pairs along a branch", (0.03, 0.5), (0.01, 5.0), "bu"),
            Param("needle_angle", 50.0, "Needle Angle", "Angle of the needles from their branch, towards its tip", (10.0, 90.0), (0.0, 90.0), "deg"),
            Param("needle_droop", 30.0, "Needle Droop", "How far the needles hang below their branch", (0.0, 80.0), (-60.0, 89.0), "deg"),
            Param("needle_rows", 2, "Needle Rows", "Needles on each side of a branch, fanned from above to below it", (1, 4), (1, 8)),
            Param("hair_source", "BRANCHES", "Grow From", "Where the hair strands or leaves start", items=HAIR_SOURCES),
            Param("hair_count", 600, "Strands", "Number of hair strands (particles) or leaves", (10, 4000), (1, 100000)),
            Param("hair_length", 0.7, "Strand Length", "Length of the longest strands or leaves", (0.05, 3.0), (0.01, 20.0), "bu"),
            Param("hair_length_variation", 0.3, "Length Variation", "Random shortening of each strand or leaf", (0.0, 1.0), (0.0, 1.0)),
            Param(
                "hair_spread",
                60.0,
                "Strand Angle",
                "Angle of the strands from their branch; at tips and on the canopy surface, the widest angle from the outward direction",
                (0.0, 180.0),
                (0.0, 180.0),
                "deg",
            ),
            Param(
                "hair_flatten",
                0.5,
                "Flatten",
                "Along branches: 1 keeps the strands to both sides of the branch (a frond), 0 spreads them all around it",
                (0.0, 1.0),
                (0.0, 1.0),
            ),
            Param("hair_droop", 30.0, "Strand Droop", "Tilts the strands or leaves towards the ground (negative lifts them)", (0.0, 90.0), (-90.0, 90.0), "deg"),
            Param("hair_width", 0.06, "Strand Width", "Strand width at its root; one sprite pixel is about 0.09", (0.01, 0.3), (0.001, 2.0), "bu"),
            Param("hair_tip_width", 0.2, "Tip Width", "Strand width at its tip, relative to the root", (0.0, 1.0), (0.0, 1.0)),
            Param(
                "hair_shadows",
                True,
                "Strand Shadows",
                "Strands shade each other and the trunk; off avoids near-black gaps inside dense crowns",
            ),
            Param("hair_children", 0, "Children", "Extra strands rendered around each strand", (0, 20), (0, 1000)),
            Param("hair_child_radius", 0.08, "Child Spread", "How far the children grow from their strand", (0.0, 0.5), (0.0, 5.0), "bu"),
            Param("hair_clump", 0.0, "Clump", "Pulls the children's tips to their strand (negative spreads them)", (-1.0, 1.0), (-1.0, 1.0)),
            Param("hair_roughness", 0.0, "Roughness", "Random offset of the children's tips", (0.0, 0.5), (0.0, 5.0), "bu"),
            Param("leaf_shape", "BLADE", "Leaf Shape", "Mesh copied for every leaf", items=LEAF_SHAPES),
            Param("leaf_width", 0.3, "Leaf Width", "Leaf width relative to its length", (0.05, 1.0), (0.01, 3.0)),
            Param("leaf_fold", 25.0, "Fold", "Lifts the leaf's edges about its midrib, so its halves catch the light differently", (0.0, 60.0), (-80.0, 80.0), "deg"),
            Param("leaf_bend", 40.0, "Bend", "Curls each leaf towards its underside along its length (negative curls it up)", (-90.0, 180.0), (-360.0, 360.0), "deg"),
            Param("leaf_twist", 30.0, "Twist", "Largest random twist along each leaf", (0.0, 90.0), (0.0, 360.0), "deg"),
            Param(
                "leaf_irregularity",
                0.4,
                "Irregularity",
                "Random change of each leaf's width and bend, and jitter of its vertices",
                (0.0, 1.0),
                (0.0, 3.0),
            ),
            Param("leaf_face_up", 0.6, "Face Up", "1 turns every leaf's upper face to the sky, 0 rolls each leaf at random", (0.0, 1.0), (0.0, 1.0)),
            Param(
                "resolution",
                0.12,
                "Resolution",
                "Canopy mesh resolution; one sprite pixel is about 0.09",
                (MIN_RESOLUTION, 0.5),
                (MIN_RESOLUTION, 2.0),
                "bu",
            ),
        ),
    ),
    (
        "Accent and Base",
        (
            Param("accent_mode", "NONE", "Accent", "Second foliage colour: flowers, berries or snow", items=ACCENT_MODES),
            Param("accent_amount", 0.15, "Amount", "Dot density, or the share of upward faces turned to accent", (0.0, 1.0), (0.0, 1.0)),
            Param("accent_size", 0.1, "Dot Size", "Accent dot radius", (0.04, 0.5), (0.01, 2.0), "bu"),
            Param("accent_threshold", 0.6, "Threshold", "Minimum upward normal for top facing accent", (0.0, 1.0), (-1.0, 1.0)),
            Param("base_style", "NONE", "Base", "Optional base under the trunk", items=BASE_STYLES),
            Param("base_radius", 0.6, "Base Radius", "Base size", (0.1, 2.0), (0.02, 10.0), "bu"),
            Param("base_height", 0.3, "Base Height", "Base height", (0.05, 1.5), (0.01, 10.0), "bu"),
        ),
    ),
)

PARAMETERS = tuple(p for _, params in GROUPS for p in params) + (
    Param("seed", 1, "Seed", "Drives every random choice", (0, 100000), (0, 2**31 - 1)),
)
PARAMETER_NAMES = tuple(p.name for p in PARAMETERS)


def srgb(r, g, b):
    """Linear RGBA from 0-255 sRGB values."""

    def channel(value):
        value /= 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    return (channel(r), channel(g), channel(b), 1.0)


#: Default material colours per role key: (Colour A, Colour B), linear RGBA.
DEFAULT_COLOURS = {
    "trunk": (srgb(99, 63, 31), srgb(112, 124, 140)),
    "leaves": (srgb(20, 52, 26), srgb(72, 124, 64)),
    "dots": (srgb(232, 120, 168), srgb(250, 176, 204)),
    "snow": (srgb(236, 240, 246), srgb(255, 255, 255)),
    "base": (srgb(88, 98, 116), srgb(140, 148, 162)),
}


def _preset(label, params, look=None, colours=None, based_on=None):
    entry = {"label": label, "params": dict(params), "look": {"outline_shades": 2, "palette_mode": "FULL", "tone_match": True}, "colours": {}}
    if based_on is not None:
        entry["params"] = dict(based_on["params"], **params)
        entry["look"] = dict(based_on["look"])
        entry["colours"] = dict(based_on["colours"])
    entry["look"].update(look or {})
    entry["colours"].update(colours or {})
    return entry


# Original tree sprites are about 85 px tall and up to 65 px wide: the
# canopy of a broadleaf reaches the tile's corners (radius ~2.85 BU), hence
# overhangs above 1.
_BROADLEAF = _preset(
    "Broadleaf",
    {
        "height": 7.8,
        "overhang": 1.4,
        "trunk_length": 0.62,
        "trunk_base_radius": 0.2,
        "trunk_top_radius": 0.08,
        "branch_count": 5,
        "branch_start": 0.55,
        "branch_end": 0.95,
        "branch_length": 0.3,
        "canopy_style": "BLOBS",
        "canopy_shape": "ELLIPSOID",
        "canopy_width": 1.4,
        "canopy_height": 0.48,
        "clump_size": 0.75,
        "clump_count": 30,
        "blob_merge": 0.4,
        "lumpiness": 0.3,
        "lump_scale": 0.45,
    },
)
_CONIFER = _preset(
    "Conifer",
    {
        "height": 9.5,
        "trunk_length": 1.0,
        "trunk_base_radius": 0.2,
        "trunk_top_radius": 0.03,
        "root_flare": 0.4,
        "branch_spread": "WHORLED",
        "whorl_size": 5,
        "branch_count": 70,
        "branch_start": 0.12,
        "branch_end": 0.92,
        "branch_angle_base": 100.0,
        "branch_angle_top": 65.0,
        "branch_length": 0.2,
        "branch_length_profile": "CONICAL",
        "branch_curve": -0.4,
        "branch_radius_ratio": 0.2,
        "canopy_style": "NEEDLES",
        "canopy_shape": "CONE",
        "canopy_width": 0.95,
        "canopy_height": 0.9,
        "hollow": 0.15,
        "needle_length": 0.65,
        "needle_width": 0.09,
        "needle_spacing": 0.06,
        "needle_angle": 45.0,
        "needle_droop": 35.0,
        "needle_rows": 3,
    },
)
_SHRUB = _preset(
    "Shrub",
    {
        "height": 2.5,
        "trunk_length": 0.0,
        "branch_count": 0,
        "canopy_shape": "ELLIPSOID",
        "canopy_width": 1.0,
        "canopy_height": 1.0,
        "clump_size": 0.5,
        "clump_count": 30,
        "blob_merge": 0.4,
        "lumpiness": 0.3,
    },
)
_TOPIARY = {
    "height": 8.2,
    "overhang": 1.35,
    "trunk_length": 0.32,
    "trunk_base_radius": 0.25,
    "trunk_top_radius": 0.18,
    "root_flare": 0.1,
    "branch_count": 0,
    "canopy_style": "TOPIARY",
    "canopy_width": 1.3,
    "canopy_height": 0.66,
    "lumpiness": 0.05,
    "lump_scale": 0.3,
    "raggedness": 0.25,
}
_TOPIARY_LOOK = {"outline_shades": 1}
_BRIGHT_LEAVES = {"leaves": (srgb(56, 110, 28), srgb(140, 190, 72))}

_HAIR_BROADLEAF = _preset(
    "Hair Broadleaf",
    {
        "height": 7.0,
        "overhang": 1.5,
        "trunk_length": 0.7,
        "trunk_base_radius": 0.3,
        "trunk_top_radius": 0.2,
        "root_flare": 0.6,
        "fork_count": 3,
        "fork_height": 0.2,
        "fork_angle": 14.0,
        "branch_count": 0,
        "canopy_style": "HAIR",
        "canopy_shape": "ELLIPSOID",
        "canopy_width": 1.2,
        "canopy_height": 0.48,
        "canopy_offset": 0.08,
        "hair_source": "CLUMPS",
        "clump_size": 1.1,
        "clump_size_variation": 0.4,
        "clump_flatten": 0.25,
        "clump_count": 14,
        # Few, wide strands: each one reads as a stroke, as in the originals.
        "hair_count": 2600,
        "hair_length": 0.8,
        "hair_length_variation": 0.4,
        "hair_spread": 70.0,
        "hair_droop": 20.0,
        "hair_width": 0.2,
        "hair_tip_width": 0.5,
    },
    # Deep shadow between the strands would quantize to dark reds and
    # browns; stronger ambient light lifts the crown's shadowed side.
    look={
        "ambient_strength": 1.5,
        "palette_mode": "CUSTOM",
        "palette_ramps": tuple(name in ("grey", "light_brown", "sea_green") for name, _ in RAMP_TITLES),
    },
    colours={
        "trunk": (srgb(150, 95, 40), srgb(200, 140, 70)),
        "leaves": (srgb(35, 95, 55), srgb(150, 205, 160)),
    },
)

#: Presets modelled on the original game's tree families. Parameters a
#: preset omits keep their defaults. ``look`` holds suggested scene render
#: settings and ``colours`` default material colours per role key.
PRESETS = {
    "BROADLEAF": _BROADLEAF,
    "BIRCH": _preset(
        "Birch",
        {
            "trunk_base_radius": 0.12,
            "trunk_top_radius": 0.05,
            "canopy_width": 1.05,
            "canopy_height": 0.55,
            "clump_size": 0.6,
            "clump_count": 25,
        },
        colours={"trunk": (srgb(196, 196, 186), srgb(90, 90, 86)), "leaves": (srgb(48, 92, 30), srgb(126, 170, 70))},
        based_on=_BROADLEAF,
    ),
    "GNARLED_OAK": _preset(
        "Gnarled Oak",
        {
            "height": 8.0,
            "overhang": 1.45,
            "straightness": 0.4,
            "gnarl": 0.6,
            "fork_count": 2,
            "fork_height": 0.7,
            "trunk_length": 0.45,
            "trunk_base_radius": 0.35,
            "trunk_top_radius": 0.15,
            "branch_count": 6,
            "branch_start": 0.5,
            "branch_angle_base": 70.0,
            "branch_angle_top": 45.0,
            "branch_length": 0.32,
            "canopy_width": 1.45,
            "canopy_height": 0.62,
            "clump_size": 0.95,
            "clump_size_variation": 0.5,
            "clump_count": 14,
            "blob_merge": 0.3,
            "lumpiness": 0.45,
            "lump_scale": 0.6,
            "hollow": 0.2,
        },
        colours={"trunk": (srgb(72, 84, 96), srgb(112, 126, 138))},
        based_on=_BROADLEAF,
    ),
    "LAYERED": _preset(
        "Layered",
        {
            "height": 8.0,
            "overhang": 1.4,
            "trunk_length": 0.82,
            "trunk_base_radius": 0.14,
            "trunk_top_radius": 0.05,
            "straightness": 0.7,
            "branch_count": 6,
            "branch_start": 0.6,
            "branch_end": 1.0,
            "branch_angle_base": 70.0,
            "branch_angle_top": 50.0,
            "branch_length": 0.25,
            "canopy_style": "LAYERS",
            "canopy_shape": "ELLIPSOID",
            "canopy_width": 1.4,
            "canopy_height": 0.45,
            "clump_size": 0.7,
            "clumps_per_tip": 5,
            "clump_flatten": 0.6,
            "blob_merge": 0.3,
            "raggedness": 0.7,
            "hollow": 0.3,
        },
        colours={"leaves": (srgb(40, 72, 36), srgb(128, 160, 80)), "trunk": (srgb(62, 70, 74), srgb(150, 120, 100))},
    ),
    "CONIFER": _CONIFER,
    "SNOWY_CONIFER": _preset(
        "Snowy Conifer",
        {"accent_mode": "TOP_FACING", "accent_amount": 0.7, "accent_threshold": 0.45},
        based_on=_CONIFER,
    ),
    "CYPRESS": _preset(
        "Cypress",
        {
            "height": 9.0,
            "trunk_length": 0.1,
            "trunk_base_radius": 0.14,
            "branch_count": 0,
            "canopy_style": "COLUMN",
            "canopy_shape": "ELLIPSOID",
            "canopy_width": 0.42,
            "canopy_height": 0.95,
            "clump_size": 0.35,
            "clumps_per_tip": 3,
            "raggedness": 0.6,
        },
        colours={"leaves": (srgb(16, 48, 28), srgb(60, 108, 60))},
    ),
    "SHRUB": _SHRUB,
    "FLOWERING_SHRUB": _preset("Flowering Shrub", {"accent_mode": "DOTS", "accent_amount": 0.35}, based_on=_SHRUB),
    "TOPIARY_BALL": _preset("Topiary Ball", dict(_TOPIARY, canopy_shape="SPHERE"), _TOPIARY_LOOK, _BRIGHT_LEAVES),
    "TOPIARY_CONE": _preset(
        "Topiary Cone",
        dict(_TOPIARY, canopy_shape="CONE", trunk_length=0.12, canopy_width=1.1, canopy_height=0.88),
        _TOPIARY_LOOK,
        _BRIGHT_LEAVES,
    ),
    "TOPIARY_HEART": _preset(
        "Topiary Heart",
        dict(_TOPIARY, canopy_shape="HEART", trunk_length=0.3, canopy_width=1.35, canopy_height=0.72),
        _TOPIARY_LOOK,
        _BRIGHT_LEAVES,
    ),
    "WEEPING": _preset(
        "Weeping",
        {
            "height": 8.0,
            "trunk_length": 0.9,
            "trunk_base_radius": 0.2,
            "trunk_top_radius": 0.05,
            "branch_count": 14,
            "branch_start": 0.3,
            "branch_end": 1.0,
            "branch_angle_base": 50.0,
            "branch_angle_top": 40.0,
            "branch_curve": -0.6,
            "branch_length": 0.22,
            "canopy_style": "STRANDS",
            "canopy_shape": "ELLIPSOID",
            "canopy_width": 1.0,
            "canopy_height": 0.75,
            "clump_size": 0.5,
            "clumps_per_tip": 3,
            "droop": 0.35,
            "raggedness": 0.5,
        },
        colours={"leaves": (srgb(28, 72, 52), srgb(96, 150, 110)), "trunk": (srgb(70, 84, 88), srgb(110, 124, 128))},
    ),
    "BLOSSOM": _preset(
        "Blossom",
        {"straightness": 0.5, "accent_mode": "DOTS", "accent_amount": 0.5},
        based_on=_BROADLEAF,
    ),
    "PALM": _preset(
        "Palm",
        {
            "height": 7.5,
            "overhang": 1.3,
            "trunk_length": 0.9,
            "trunk_base_radius": 0.15,
            "trunk_top_radius": 0.1,
            "root_flare": 0.5,
            "straightness": 0.6,
            "lean_angle": 10.0,
            "branch_count": 9,
            "branch_start": 0.98,
            "branch_end": 1.0,
            "branch_angle_base": 70.0,
            "branch_angle_top": 60.0,
            "branch_length": 0.3,
            "branch_length_profile": "CONSTANT",
            "branch_curve": -0.7,
            "branch_radius_ratio": 0.3,
            "canopy_style": "NEEDLES",
            "canopy_shape": "ELLIPSOID",
            "canopy_width": 1.3,
            "canopy_height": 0.45,
            "hollow": 0.05,
            "needle_length": 0.75,
            "needle_width": 0.12,
            "needle_spacing": 0.07,
            "needle_angle": 55.0,
            "needle_droop": 35.0,
            "needle_rows": 1,
        },
        colours={"trunk": (srgb(120, 92, 60), srgb(150, 124, 90)), "leaves": (srgb(30, 80, 30), srgb(100, 160, 60))},
    ),
    "HAIR_PALM": _preset(
        "Hair Palm",
        {
            "height": 6.5,
            "overhang": 1.1,
            "trunk_length": 0.65,
            "trunk_base_radius": 0.2,
            "trunk_top_radius": 0.14,
            "root_flare": 0.2,
            "straightness": 0.8,
            "branch_count": 14,
            "branch_start": 0.85,
            "branch_end": 1.0,
            "branch_angle_base": 80.0,
            "branch_angle_top": 25.0,
            "branch_length": 0.3,
            "branch_length_profile": "CONSTANT",
            "branch_curve": -0.5,
            "branch_radius_ratio": 0.2,
            "canopy_style": "HAIR",
            "canopy_shape": "ELLIPSOID",
            "canopy_width": 1.1,
            "canopy_height": 0.55,
            "hollow": 0.1,
            "hair_source": "BRANCHES",
            "hair_count": 1200,
            "hair_length": 0.85,
            "hair_length_variation": 0.35,
            "hair_spread": 55.0,
            "hair_flatten": 0.4,
            "hair_droop": 45.0,
            "hair_width": 0.07,
            "hair_tip_width": 0.3,
            "hair_children": 2,
            "hair_child_radius": 0.08,
        },
        colours={"trunk": (srgb(110, 70, 30), srgb(170, 110, 50)), "leaves": (srgb(20, 70, 40), srgb(90, 150, 90))},
    ),
    "HAIR_BROADLEAF": _HAIR_BROADLEAF,
    "LEAFY_BROADLEAF": _preset(
        "Leafy Broadleaf",
        {
            "height": 7.8,
            "canopy_style": "INSTANCES",
            "canopy_height": 0.55,
            # Long, narrow leaves pointing out of their clump: a spiky
            # silhouette of one-pixel strokes, as in the original sprites.
            "hair_count": 3000,
            "hair_length": 0.95,
            "hair_spread": 40.0,
            "leaf_shape": "BLADE",
            "leaf_width": 0.2,
        },
        based_on=_HAIR_BROADLEAF,
    ),
    "BARE": _preset(
        "Bare",
        {
            "height": 7.0,
            "canopy_style": "NONE",
            "sub_branches": 3,
            "branch_count": 7,
            "branch_length": 0.35,
            "straightness": 0.6,
        },
        look={"outline_shades": 1},
    ),
}


def make_params(**values):
    """Parameter namespace: defaults overridden by ``values``."""
    params = {p.name: p.default for p in PARAMETERS}
    unknown = set(values) - set(params)
    if unknown:
        raise KeyError("Unknown tree parameters: " + ", ".join(sorted(unknown)))
    params.update(values)
    return SimpleNamespace(**params)


def preset_params(name, **values):
    return make_params(**dict(PRESETS[name]["params"], **values))


def preset_colours(name, role_key):
    """(Colour A, Colour B) of a role for a preset, falling back to the defaults."""
    colours = PRESETS[name]["colours"] if name in PRESETS else {}
    return colours.get(role_key, DEFAULT_COLOURS[role_key])


# Randomness ---------------------------------------------------------------


def stage_seed(seed, stage):
    """Stable 32-bit seed of one generation stage (Python's hash() is salted)."""
    return zlib.crc32("{}:{}".format(int(seed), stage).encode("ascii"))


def stage_rng(seed, stage):
    return random.Random(stage_seed(seed, stage))


class Noise:
    """Seeded 3D gradient (Perlin) noise with fractal octaves, values about -1..1."""

    def __init__(self, seed):
        perm = list(range(256))
        random.Random(seed).shuffle(perm)
        self._perm = np.array(perm * 2, dtype=np.int64)

    def __call__(self, points):
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        cell = np.floor(p)
        f = p - cell
        i = cell.astype(np.int64) & 255
        u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0)
        perm = self._perm
        x, y, z = i[:, 0], i[:, 1], i[:, 2]
        a = perm[x] + y
        b = perm[x + 1] + y
        aa, ab = perm[a] + z, perm[a + 1] + z
        ba, bb = perm[b] + z, perm[b + 1] + z
        fx, fy, fz = f[:, 0], f[:, 1], f[:, 2]
        g = _grad
        x1 = _lerp(g(perm[aa], fx, fy, fz), g(perm[ba], fx - 1, fy, fz), u[:, 0])
        x2 = _lerp(g(perm[ab], fx, fy - 1, fz), g(perm[bb], fx - 1, fy - 1, fz), u[:, 0])
        y1 = _lerp(x1, x2, u[:, 1])
        x3 = _lerp(g(perm[aa + 1], fx, fy, fz - 1), g(perm[ba + 1], fx - 1, fy, fz - 1), u[:, 0])
        x4 = _lerp(g(perm[ab + 1], fx, fy - 1, fz - 1), g(perm[bb + 1], fx - 1, fy - 1, fz - 1), u[:, 0])
        y2 = _lerp(x3, x4, u[:, 1])
        return _lerp(y1, y2, u[:, 2])

    def fbm(self, points, octaves=3):
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        total = np.zeros(len(p))
        amplitude, norm = 1.0, 0.0
        for octave in range(octaves):
            # Offsets keep octaves from sharing lattice zeros.
            total += amplitude * self(p * (2.0**octave) + 17.31 * octave)
            norm += amplitude
            amplitude *= 0.5
        return total / norm

    def curve(self, t, channel, octaves=3):
        """1D fractal noise along ``t`` for an independent ``channel``."""
        t = np.asarray(t, dtype=np.float64)
        points = np.stack([t, np.full_like(t, 0.37 + 7.13 * channel), np.full_like(t, 0.61)], axis=-1)
        return self.fbm(points, octaves)


def _lerp(a, b, t):
    return a + (b - a) * t


def _grad(h, x, y, z):
    h = h & 15
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, z))
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


# Small vector helpers --------------------------------------------------------


def _normalize(v):
    v = np.asarray(v, dtype=np.float64)
    length = np.linalg.norm(v)
    return v / length if length > 1e-12 else v


def _rotate(v, axis, angle):
    """Rodrigues rotation of ``v`` around the unit ``axis``."""
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)


def _rotate_towards(v, target, angle):
    cross = np.cross(v, target)
    sin = np.linalg.norm(cross)
    if sin < 1e-6:
        return v
    between = math.atan2(sin, float(np.dot(v, target)))
    return _rotate(v, cross / sin, min(angle, between))


def _perpendicular(v):
    helper = np.array([0.0, 0.0, 1.0]) if abs(v[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    return _normalize(np.cross(v, helper))


def _horizontal(azimuth):
    return np.array([math.cos(azimuth), math.sin(azimuth), 0.0])


def _direction(axis, azimuth, pitch):
    """Unit vector at ``pitch`` from ``axis``, towards the horizontal ``azimuth``."""
    side = _horizontal(azimuth)
    side = side - axis * np.dot(side, axis)
    if np.linalg.norm(side) < 1e-6:
        side = _perpendicular(axis)
    side = _normalize(side)
    return _normalize(axis * math.cos(pitch) + side * math.sin(pitch))


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# Footprint ---------------------------------------------------------------------


def footprint(params):
    """(half-width available to the canopy, anchor xy) for the chosen size."""
    half = TILE_SIZE / 2.0
    if params.size == "QUARTER":
        return half / 2.0, (0.0, 0.0)
    if params.size == "LARGE":
        w, length = params.large_width, params.large_length
        return min(w, length) * half, (-(w - 1) * half, -(length - 1) * half)
    return half, (0.0, 0.0)


# Skeleton --------------------------------------------------------------------


class Polyline:
    """A trunk, leader or branch: points with radii. Level 0 is the trunk."""

    def __init__(self, points, radii, parent=-1, level=0, t_range=(0.0, 1.0)):
        self.points = np.asarray(points, dtype=np.float64)
        self.radii = np.asarray(radii, dtype=np.float64)
        self.parent = parent
        self.level = level
        #: Range of normalised trunk height covered (trunk and leaders).
        self.t_range = t_range
        self.children = 0
        #: Whether it is thick enough to get a tube.
        self.mesh = float(self.radii[0]) >= MIN_TUBE_RADIUS

    @property
    def segments(self):
        return len(self.points) - 1

    @property
    def length(self):
        return float(np.linalg.norm(np.diff(self.points, axis=0), axis=1).sum())

    def sample(self, s):
        """(point, unit tangent, radius) at fraction ``s`` of the polyline."""
        n = self.segments
        x = min(max(s, 0.0), 1.0) * n
        i = min(int(x), n - 1)
        f = x - i
        point = self.points[i] * (1.0 - f) + self.points[i + 1] * f
        radius = self.radii[i] * (1.0 - f) + self.radii[i + 1] * f
        return point, _normalize(self.points[i + 1] - self.points[i]), float(radius)

    def end(self):
        return self.points[-1], _normalize(self.points[-1] - self.points[-2])


class Tip:
    def __init__(self, point, direction, polyline):
        self.point = point
        self.direction = direction
        self.polyline = polyline


def trunk_radius(params, base_radius, t):
    """Trunk radius at normalised trunk height ``t`` (0-1), root flare included."""
    t = np.asarray(t, dtype=np.float64)
    top = min(params.trunk_top_radius, base_radius)
    radius = base_radius + (top - base_radius) * t**params.taper_curve
    if params.root_flare_height > 0.0:
        radius = radius + params.root_flare * base_radius * (1.0 - _smoothstep(t / params.root_flare_height))
    return radius


def _base_radius(params, half_width):
    """Trunk base radius, shrunk so base + flare stays within 0.8 half-widths."""
    radius = params.trunk_base_radius
    widest = radius * (1.0 + params.root_flare)
    if widest > 0.8 * half_width:
        radius *= 0.8 * half_width / widest
    return radius


def _bend_offsets(params, noise, t, channel):
    """Horizontal bend and gnarl offsets along normalised height ``t``, 0 at t = 0."""
    offsets = np.zeros((len(t), 3))
    bend = (1.0 - params.straightness) * 0.15 * params.height
    gnarl = params.gnarl * 1.5 * params.trunk_base_radius
    for axis in range(2):
        c = channel + axis
        if bend > 0.0:
            curve = noise.curve(t * params.bend_frequency, c)
            offsets[:, axis] += bend * (curve - noise.curve(np.zeros(1), c)[0])
        if gnarl > 0.0:
            kinks = noise.curve(t * 12.0, c + 10, octaves=2)
            offsets[:, axis] += gnarl * (kinks - noise.curve(np.zeros(1), c + 10, octaves=2)[0])
    return offsets


class Skeleton:
    def __init__(self):
        self.polylines = []
        self.stems = []
        self.segments = 0
        self.capped = False

    def add(self, polyline):
        self.polylines.append(polyline)
        self.segments += polyline.segments
        return len(self.polylines) - 1


def build_trunk(params, skeleton, half_width, anchor, noise, rng):
    trunk_height = params.trunk_length * params.height
    if trunk_height < 1e-4:
        return
    base_radius = _base_radius(params, half_width)
    lean = math.radians(params.lean_angle)
    lean_dir = math.radians(params.lean_direction)
    lean_axis = np.array([-math.sin(lean_dir), math.cos(lean_dir), 0.0])
    up = _rotate(np.array([0.0, 0.0, 1.0]), lean_axis, lean)
    origin = np.array([anchor[0], anchor[1], 0.0])

    forked = params.fork_count > 1
    t_end = params.fork_height if forked else 1.0
    n = int(min(max(8 * params.bend_frequency, 8), 48))
    count = max(2, int(round(n * t_end)) + 1)
    t = np.linspace(0.0, t_end, count)
    points = origin + np.outer(t * trunk_height, up) + _bend_offsets(params, noise, t, 0)
    trunk = Polyline(points, trunk_radius(params, base_radius, t), level=0, t_range=(0.0, t_end))
    index = skeleton.add(trunk)
    if not forked:
        skeleton.stems.append(index)
        return

    fork_point, tangent, _ = trunk.sample(1.0)
    k = params.fork_count
    angle = math.radians(params.fork_angle)
    remaining = (1.0 - t_end) * trunk_height
    length = remaining / max(math.cos(angle), 0.2)
    m = max(4, int(round(n * (1.0 - t_end))) + 1)
    s = np.linspace(0.0, 1.0, m)
    twist = math.radians(params.twist) * t_end
    for i in range(k):
        azimuth = 2.0 * math.pi * i / k + twist + rng.uniform(-0.5, 0.5) * params.jitter
        direction = _direction(tangent, azimuth, angle)
        leader_t = t_end + (1.0 - t_end) * s
        points = fork_point + np.outer(s * length, direction) + _bend_offsets(params, noise, s, 20 + 2 * i) * 0.5
        radii = trunk_radius(params, base_radius, leader_t) / math.sqrt(k)
        trunk.children += 1
        skeleton.stems.append(skeleton.add(Polyline(points, radii, parent=index, level=0, t_range=(t_end, 1.0))))


def _length_profile(name, t):
    # The lowest and highest branches keep some length, unlike a plain sin(pi t).
    if name == "ROUND":
        return math.sin(math.pi * (0.2 + 0.6 * t))
    if name == "CONICAL":
        return 1.0 - 0.8 * t
    if name == "INVERTED":
        return 0.2 + 0.8 * t
    return 1.0


def _branch_points(start, direction, length, curve, count=5):
    points = [start]
    segment = length / (count - 1)
    target = np.array([0.0, 0.0, 1.0 if curve > 0 else -1.0])
    step = math.radians(abs(curve) * 30.0)
    for _ in range(count - 1):
        points.append(points[-1] + direction * segment)
        direction = _rotate_towards(direction, target, step)
    return np.array(points)


def _clip_length(start, direction, length, curve, inside):
    """Shorten a branch until its tip satisfies ``inside``."""
    points = _branch_points(start, direction, length, curve)
    for _ in range(10):
        if inside(points[-1]):
            break
        length *= 0.85
        points = _branch_points(start, direction, length, curve)
    return points


def build_branches(params, skeleton, envelope, rng):
    if not skeleton.stems or params.branch_count <= 0:
        return
    count = params.branch_count
    jitter = params.jitter
    start, end = sorted((params.branch_start, params.branch_end))
    height = params.height
    # Clumps may hang over the envelope; needles, hair and leaves grow outwards from the branch.
    clump = 0.0 if params.canopy_style in ("NEEDLES",) + STRAND_STYLES else params.clump_size

    def inside(point):
        return point[2] <= height and envelope.sdf(point)[0] <= clump

    first_level = []
    slot = (end - start) / count
    whorl = max(1, params.whorl_size)
    whorls = int(math.ceil(count / whorl))
    trunk_index = skeleton.stems[0] if len(skeleton.stems) == 1 else 0
    for i in range(count):
        if params.branch_spread == "WHORLED":
            w = i // whorl
            rel = w / (whorls - 1) if whorls > 1 else 0.5
            t = start + (end - start) * rel
            azimuth = 2.0 * math.pi * (i % whorl) / whorl + w * math.pi / whorl
        else:
            rel = i / (count - 1) if count > 1 else 0.5
            t = start + (end - start) * rel
            if params.branch_spread == "SPIRAL":
                azimuth = math.radians(i * GOLDEN_ANGLE)
            else:
                azimuth = rng.uniform(0.0, 2.0 * math.pi)
        t = min(max(t + rng.uniform(-0.5, 0.5) * slot * jitter, 0.0), 1.0)
        azimuth += math.radians(params.twist) * t + rng.uniform(-1.0, 1.0) * jitter * math.radians(25.0)

        # Pick the stem carrying height t: the trunk below the fork, leaders above.
        trunk = skeleton.polylines[trunk_index]
        if len(skeleton.stems) > 1 and t > trunk.t_range[1]:
            stem_index = skeleton.stems[i % len(skeleton.stems)]
        else:
            stem_index = trunk_index
        stem = skeleton.polylines[stem_index]
        t0, t1 = stem.t_range
        point, tangent, parent_radius = stem.sample((t - t0) / max(t1 - t0, 1e-6))

        pitch = params.branch_angle_base + (params.branch_angle_top - params.branch_angle_base) * rel
        pitch = math.radians(pitch + rng.uniform(-1.0, 1.0) * jitter * 15.0)
        length = params.branch_length * height * _length_profile(params.branch_length_profile, rel)
        length *= 1.0 + rng.uniform(-0.5, 0.5) * jitter
        if length < 1e-3:
            continue
        if skeleton.segments + 4 > MAX_SEGMENTS:
            skeleton.capped = True
            break
        direction = _direction(tangent, azimuth, pitch)
        points = _clip_length(point, direction, length, params.branch_curve, inside)
        radius = params.branch_radius_ratio * parent_radius
        radii = np.linspace(radius, radius * 0.35, len(points))
        stem.children += 1
        first_level.append(skeleton.add(Polyline(points, radii, parent=stem_index, level=1)))

    for index in first_level:
        branch = skeleton.polylines[index]
        branch_length = branch.length
        for k in range(params.sub_branches):
            if skeleton.segments + 4 > MAX_SEGMENTS:
                skeleton.capped = True
                return
            s = 0.35 + 0.55 * (k + 0.5) / params.sub_branches
            point, tangent, parent_radius = branch.sample(s)
            azimuth = math.atan2(tangent[1], tangent[0]) + (math.pi / 2.0 if k % 2 else -math.pi / 2.0)
            azimuth += rng.uniform(-1.0, 1.0) * jitter * math.radians(40.0)
            pitch = math.radians(40.0 + rng.uniform(-1.0, 1.0) * jitter * 15.0)
            direction = _normalize(_direction(tangent, azimuth, pitch) + np.array([0.0, 0.0, 0.25]))
            length = params.sub_branch_length * branch_length * (1.0 - 0.4 * s) * (1.0 + rng.uniform(-0.5, 0.5) * jitter)
            points = _clip_length(point, direction, length, params.branch_curve, inside)
            radius = params.branch_radius_ratio * parent_radius
            branch.children += 1
            skeleton.add(Polyline(points, np.linspace(radius, radius * 0.35, len(points)), parent=index, level=2))


def collect_tips(skeleton):
    """Ends of the stems and of every branch without children."""
    tips = []
    for index, polyline in enumerate(skeleton.polylines):
        if index in skeleton.stems or (polyline.level > 0 and polyline.children == 0):
            point, direction = polyline.end()
            tips.append(Tip(point, direction, index))
    return tips


# Envelope ---------------------------------------------------------------------


class Envelope:
    """Signed-distance shape the canopy is confined to (negative inside)."""

    def __init__(self, shape, centre_xy, radius, bottom, top):
        self.shape = shape
        self.cx, self.cy = centre_xy
        self.radius = radius
        self.bottom = bottom
        self.top = top
        if shape == "SPHERE":
            # A ball at the top of the canopy space.
            r = min(radius, (top - bottom) / 2.0)
            self.radius = r
            self.bottom = top - 2.0 * r

    @property
    def height(self):
        return self.top - self.bottom

    @property
    def centre(self):
        frac = {"CONE": 0.3, "BELL": 0.4, "HEART": 0.55}.get(self.shape, 0.5)
        return np.array([self.cx, self.cy, self.bottom + frac * self.height])

    def _profile(self, h):
        """Radius at normalised height ``h`` relative to ``radius``, axisymmetric shapes."""
        h = np.clip(h, 0.0, 1.0)
        if self.shape == "CONE":
            return 1.0 - h
        if self.shape == "CYLINDER":
            return np.ones_like(h)
        if self.shape == "BELL":
            return (0.62 + 0.38 * (1.0 - h) ** 3) * np.sqrt(np.clip(1.0 - h**4, 0.0, 1.0))
        return np.sqrt(np.clip(1.0 - (2.0 * h - 1.0) ** 2, 0.0, 1.0))

    def sdf(self, points):
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        dx, dy, z = p[:, 0] - self.cx, p[:, 1] - self.cy, p[:, 2]
        if self.shape == "HEART":
            return self._heart(dx, dy, z)
        if self.shape in ("SPHERE", "ELLIPSOID"):
            radii = np.array([self.radius, self.radius, self.height / 2.0])
            q = np.stack([dx, dy, z - (self.bottom + self.top) / 2.0], axis=-1)
            k0 = np.linalg.norm(q / radii, axis=1)
            k1 = np.linalg.norm(q / (radii * radii), axis=1)
            safe = np.maximum(k1, 1e-12)
            return np.where(k1 > 1e-12, k0 * (k0 - 1.0) / safe, -radii.min())
        rho = np.hypot(dx, dy)
        h = (z - self.bottom) / max(self.height, 1e-9)
        eps = 1e-3
        slope = (self._profile(h + eps) - self._profile(h - eps)) / (2.0 * eps) * self.radius / max(self.height, 1e-9)
        side = (rho - self._profile(h) * self.radius) / np.sqrt(1.0 + slope * slope)
        vertical = np.maximum(self.bottom - z, z - self.top)
        return np.maximum(side, vertical)

    def _heart(self, dx, dy, z):
        # Two round cones from the lobes down to the point, in the X-Z plane,
        # squashed along Y.
        lobe = self.radius / 2.0
        lobe_z = self.top - lobe
        tip_radius = 0.1 * lobe
        tip = np.array([0.0, 0.0, self.bottom + tip_radius])
        p = np.stack([dx, dy / 0.65, z], axis=-1)
        left = _round_cone(p, np.array([-lobe, 0.0, lobe_z]), tip, lobe, tip_radius)
        right = _round_cone(p, np.array([lobe, 0.0, lobe_z]), tip, lobe, tip_radius)
        return np.minimum(left, right) * 0.65

    def gradient(self, points):
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        eps = 1e-3
        grad = np.zeros_like(p)
        for axis in range(3):
            offset = np.zeros(3)
            offset[axis] = eps
            grad[:, axis] = (self.sdf(p + offset) - self.sdf(p - offset)) / (2.0 * eps)
        norms = np.linalg.norm(grad, axis=1, keepdims=True)
        return grad / np.maximum(norms, 1e-12)

    def radius_at(self, z):
        """Horizontal half-width of the envelope at height ``z`` (along +X)."""
        lo, hi = 0.0, self.radius * 1.5
        if self.sdf([self.cx, self.cy, z])[0] > 0.0:
            return 0.0
        for _ in range(30):
            mid = (lo + hi) / 2.0
            if self.sdf([self.cx + mid, self.cy, z])[0] <= 0.0:
                lo = mid
            else:
                hi = mid
        return lo


def _round_cone(p, a, b, r1, r2):
    """Signed distance to a cone with rounded ends (Inigo Quilez's sdRoundCone)."""
    ba = b - a
    l2 = float(np.dot(ba, ba))
    rr = r1 - r2
    a2 = l2 - rr * rr
    il2 = 1.0 / l2
    pa = p - a
    y = pa @ ba
    z = y - l2
    w = pa * l2 - np.outer(y, ba)
    x2 = np.einsum("ij,ij->i", w, w)
    y2 = y * y * l2
    z2 = z * z * l2
    k = math.copysign(1.0, rr) * rr * rr * x2
    far = np.sqrt(x2 + z2) * il2 - r2
    near = np.sqrt(x2 + y2) * il2 - r1
    side = (np.sqrt(np.maximum(x2 * a2 * il2, 0.0)) + y * rr) * il2 - r1
    return np.where(np.sign(z) * a2 * z2 > k, far, np.where(np.sign(y) * a2 * y2 < k, near, side))


def displacement_amplitude(params):
    """Largest distance canopy displacement can move a vertex."""
    return params.lumpiness * params.clump_size + raggedness_amplitude(params)


def raggedness_amplitude(params):
    return params.raggedness * 0.2


def build_envelope(params, half_width, anchor, skeleton):
    height = params.height
    limit = params.overhang * half_width
    radius = min(params.canopy_width * half_width, limit)
    offset = params.canopy_offset * height
    top = height + min(offset, 0.0)
    bottom = max(0.0, height * (1.0 - params.canopy_height) + offset)
    if top - bottom < 0.05 * height:
        bottom = max(0.0, top - 0.05 * height)
    # Centre the canopy over the trunk end, keeping it within the overhang.
    centre = np.array(anchor, dtype=np.float64)
    if skeleton.stems:
        ends = np.array([skeleton.polylines[i].points[-1][:2] for i in skeleton.stems])
        centre = ends.mean(axis=0)
    shift = centre - np.array(anchor)
    room = max(limit - radius, 0.0)
    distance = np.linalg.norm(shift)
    if distance > room:
        centre = np.array(anchor) + shift * (room / distance)
    return Envelope(params.canopy_shape, (float(centre[0]), float(centre[1])), radius, bottom, top)


# Canopy blobs -------------------------------------------------------------------

#: Blob columns: centre x, y, z, radius, scale along yaw, vertical scale, yaw.
BLOB_FIELDS = 7


def _blob(centre, radius, stretch=1.0, flatten=1.0, yaw=0.0):
    return (float(centre[0]), float(centre[1]), float(centre[2]), float(radius), float(stretch), float(flatten), float(yaw))


def _clump_radius(params, rng, scale=1.0):
    variation = params.clump_size_variation
    return params.clump_size * scale * (1.0 + rng.uniform(-variation, variation))


def _blobs_at_tips(params, skeleton, tips, rng):
    blobs = []
    flatten = 1.0 - params.clump_flatten
    count = params.clumps_per_tip
    for tip in tips:
        polyline = skeleton.polylines[tip.polyline]
        for k in range(count):
            s = 1.0 - 0.4 * k / max(count - 1, 1)
            point = polyline.sample(s)[0]
            radius = _clump_radius(params, rng)
            jitter = np.array([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.5, 1)]) * 0.25 * radius
            blobs.append(_blob(point + jitter, radius, flatten=flatten))
    return blobs


def _scatter_in_envelope(params, envelope, count, rng, min_distance):
    """Poisson-disc points inside the envelope, each the centre of a blob."""
    blobs = []
    centres = []
    lo = np.array([envelope.cx - envelope.radius, envelope.cy - envelope.radius, envelope.bottom])
    hi = np.array([envelope.cx + envelope.radius, envelope.cy + envelope.radius, envelope.top])
    flatten = 1.0 - params.clump_flatten
    for _ in range(count * 40):
        if len(blobs) >= count:
            break
        point = lo + (hi - lo) * np.array([rng.random(), rng.random(), rng.random()])
        radius = _clump_radius(params, rng)
        if envelope.sdf(point)[0] > -0.25 * radius:
            continue
        if centres and np.min(np.linalg.norm(np.array(centres) - point, axis=1)) < min_distance:
            continue
        centres.append(point)
        blobs.append(_blob(point, radius, flatten=flatten))
    return blobs


def _envelope_volume(envelope, rng, samples=2000):
    lo = np.array([envelope.cx - envelope.radius, envelope.cy - envelope.radius, envelope.bottom])
    hi = np.array([envelope.cx + envelope.radius, envelope.cy + envelope.radius, envelope.top])
    points = lo + (hi - lo) * np.array([[rng.random() for _ in range(3)] for _ in range(samples)])
    inside = np.count_nonzero(envelope.sdf(points) <= 0.0) / samples
    return float(np.prod(hi - lo)) * inside


def _layer_blobs(params, skeleton, rng):
    blobs = []
    flatten = 1.0 - params.clump_flatten
    ends = [i for i, p in enumerate(skeleton.polylines) if p.level == 1] + list(skeleton.stems)
    for index in ends:
        point = skeleton.polylines[index].end()[0]
        radius = _clump_radius(params, rng)
        blobs.append(_blob(point, radius, flatten=flatten))
        count = params.clumps_per_tip
        start = rng.uniform(0.0, 2.0 * math.pi)
        for k in range(count):
            azimuth = start + 2.0 * math.pi * k / count
            offset = _horizontal(azimuth) * 0.75 * radius + np.array([0.0, 0.0, rng.uniform(-0.2, 0.2) * radius * flatten])
            blobs.append(_blob(point + offset, radius * rng.uniform(0.55, 0.75), flatten=flatten))
    return blobs


def _tier_blobs(params, skeleton, envelope, rng):
    blobs = []
    flatten = 1.0 - max(params.clump_flatten, 0.3)
    for polyline in skeleton.polylines:
        if polyline.level == 0:
            continue
        length = polyline.length
        start, end = polyline.points[0], polyline.points[-1]
        yaw = math.atan2(end[1] - start[1], end[0] - start[0])
        step = max(0.6 * params.clump_size, 0.05)
        count = max(1, int(length * 0.75 / step))
        for k in range(count):
            s = 0.25 + 0.75 * (k + 1) / count
            point = polyline.sample(s)[0]
            radius = _clump_radius(params, rng, 1.0 - 0.45 * s)
            blobs.append(_blob(point, radius, stretch=1.6, flatten=flatten, yaw=yaw))
    # A pointed top along the last part of each stem.
    for index in skeleton.stems:
        stem = skeleton.polylines[index]
        for k in range(4):
            s = 1.0 - 0.06 * k
            radius = params.clump_size * (0.35 + 0.12 * k)
            point = stem.sample(s)[0]
            if point[2] > envelope.bottom:
                blobs.append(_blob(point, radius))
    return blobs


def _column_blobs(params, skeleton, envelope, rng):
    blobs = []
    axis = np.array([envelope.cx, envelope.cy])
    if skeleton.stems:
        axis = skeleton.polylines[skeleton.stems[0]].points[-1][:2]
    step = max(0.45 * params.clump_size, 0.05)
    z = envelope.bottom + step
    while z < envelope.top - step * 0.5:
        width = envelope.radius_at(z)
        if width > 0.05:
            centre = np.array([axis[0], axis[1], z])
            blobs.append(_blob(centre, width * 0.85))
            for _ in range(params.clumps_per_tip):
                azimuth = rng.uniform(0.0, 2.0 * math.pi)
                radius = min(_clump_radius(params, rng), width * 0.55)
                offset = _horizontal(azimuth) * (width - radius) + np.array([0.0, 0.0, rng.uniform(-0.5, 0.5) * step])
                blobs.append(_blob(centre + offset, radius))
        z += step
    return blobs


def _strand_blobs(params, skeleton, tips, rng):
    blobs = []
    small = params.clump_size * 0.35
    for tip in tips:
        blobs.append(_blob(tip.point, _clump_radius(params, rng, 0.6)))
        for _ in range(params.clumps_per_tip):
            azimuth = rng.uniform(0.0, 2.0 * math.pi)
            outward = _horizontal(azimuth)
            point = tip.point + outward * 0.3 * params.clump_size
            length = params.droop * params.height * rng.uniform(0.35, 0.6)
            radius = small * rng.uniform(0.8, 1.2)
            travelled = 0.0
            while travelled <= length:
                blobs.append(_blob(point, radius))
                step = 0.9 * radius
                point = point + np.array([0.0, 0.0, -step]) + outward * step * 0.2
                travelled += step
                radius *= 0.96
    return blobs


def place_blobs(params, skeleton, tips, envelope, rng):
    style = params.canopy_style
    if style in STRAND_STYLES and params.hair_source == "CLUMPS":
        # The clumps only place the hair or leaves; they get no surface.
        style = "BLOBS"
    if style in ("NONE", "TOPIARY", "NEEDLES") + STRAND_STYLES:
        return np.zeros((0, BLOB_FIELDS))
    if style == "LAYERS":
        blobs = _layer_blobs(params, skeleton, rng)
    elif style == "TIERS":
        blobs = _tier_blobs(params, skeleton, envelope, rng)
    elif style == "COLUMN":
        blobs = _column_blobs(params, skeleton, envelope, rng)
    elif style == "STRANDS":
        blobs = _strand_blobs(params, skeleton, tips, rng)
    else:
        blobs = _blobs_at_tips(params, skeleton, tips, rng)
    extra = params.clump_count
    if style == "BLOBS" and not blobs and extra == 0:
        # Nothing to grow from (no trunk): fill the envelope instead.
        volume = _envelope_volume(envelope, rng)
        extra = int(min(max(round(2.5 * volume / (4.0 / 3.0 * math.pi * params.clump_size**3)), 4), 120))
    if extra and style in ("BLOBS", "LAYERS", "STRANDS"):
        blobs += _scatter_in_envelope(params, envelope, extra, rng, 0.6 * params.clump_size)
    blobs = np.array(blobs, dtype=np.float64).reshape(-1, BLOB_FIELDS)
    if len(blobs) == 0:
        return blobs

    if params.hollow > 0.0 and style != "COLUMN":
        distance = np.hypot(blobs[:, 0] - envelope.cx, blobs[:, 1] - envelope.cy)
        keep = distance >= params.hollow * envelope.radius
        if np.count_nonzero(keep) >= 3:
            blobs = blobs[keep]
    if params.droop > 0.0 and style != "STRANDS":
        blobs[:, 2] -= params.droop * blobs[:, 3] * 0.5
        blobs[:, 5] *= 1.0 + 0.5 * params.droop
    return fit_blobs(blobs, envelope, params.height - displacement_amplitude(params))


def fit_blobs(blobs, envelope, top_limit):
    """Move and shrink blobs so they stay inside the envelope and under ``top_limit``."""
    blobs = blobs.copy()
    top_limit = max(top_limit, 0.1)
    for _ in range(4):
        horizontal = blobs[:, 3] * np.maximum(blobs[:, 4], 1.0)
        vertical = blobs[:, 3] * blobs[:, 5]
        margin = 0.5 * np.minimum(horizontal, vertical)
        centres = blobs[:, :3]
        excess = envelope.sdf(centres) + margin
        outside = excess > 0.0
        if not outside.any():
            break
        blobs[outside, :3] -= envelope.gradient(centres[outside]) * excess[outside, None]

    # Hard limits: horizontally within the envelope radius, vertically in [0, top_limit].
    horizontal = blobs[:, 3] * np.maximum(blobs[:, 4], 1.0)
    scale = np.minimum(1.0, envelope.radius / np.maximum(horizontal, 1e-9))
    vertical = blobs[:, 3] * blobs[:, 5]
    scale = np.minimum(scale, top_limit / 2.0 / np.maximum(vertical, 1e-9))
    blobs[:, 3] *= scale
    horizontal = blobs[:, 3] * np.maximum(blobs[:, 4], 1.0)
    vertical = blobs[:, 3] * blobs[:, 5]
    offset = blobs[:, :2] - np.array([envelope.cx, envelope.cy])
    distance = np.linalg.norm(offset, axis=1)
    room = np.maximum(envelope.radius - horizontal, 0.0)
    factor = np.where(distance > room, room / np.maximum(distance, 1e-12), 1.0)
    blobs[:, :2] = np.array([envelope.cx, envelope.cy]) + offset * factor[:, None]
    blobs[:, 2] = np.clip(blobs[:, 2], vertical, top_limit - vertical)
    return blobs


# Generation ------------------------------------------------------------------------


class TreeData:
    """Skeleton, canopy blobs and envelope of one generated tree."""

    def __init__(self, params, skeleton, tips, envelope, blobs, half_width, anchor):
        self.params = params
        self.skeleton = skeleton
        self.polylines = skeleton.polylines
        self.tips = tips
        self.envelope = envelope
        self.blobs = blobs
        self.half_width = half_width
        self.anchor = anchor
        self.strands = Strands()

    @property
    def branch_counts(self):
        levels = [p.level for p in self.polylines]
        return levels.count(1), levels.count(2)

    def warnings(self):
        params = self.params
        result = []
        if params.overhang > 1.0 and params.canopy_width > 1.0:
            result.append(NOTE + "Canopy reaches into neighbouring tiles; scenery there may draw over it")
        if params.size != "LARGE" and params.height > SMALL_HEIGHT_LIMIT:
            result.append("Taller than {:.1f} BU: the game sorts small scenery wrongly above that".format(SMALL_HEIGHT_LIMIT))
        if self.skeleton.capped:
            result.append("Branch limit ({} segments) reached".format(MAX_SEGMENTS))
        return result


def generate(params):
    half_width, anchor = footprint(params)
    seed = params.seed
    skeleton = Skeleton()
    build_trunk(params, skeleton, half_width, anchor, Noise(stage_seed(seed, "trunk_noise")), stage_rng(seed, "trunk"))
    envelope = build_envelope(params, half_width, anchor, skeleton)
    build_branches(params, skeleton, envelope, stage_rng(seed, "branches"))
    tips = collect_tips(skeleton)
    blobs = place_blobs(params, skeleton, tips, envelope, stage_rng(seed, "clumps"))
    return TreeData(params, skeleton, tips, envelope, blobs, half_width, anchor)


# Mesh data ----------------------------------------------------------------------------


class MeshData:
    """Vertices and polygons with per-face role, smooth flag and per-corner UVs.

    ``leaf`` is None, or per vertex (position from root 0 to tip 1, random
    value of its leaf, 1) on leaf instance vertices and (0, 0, 0) elsewhere.
    """

    def __init__(self, verts=None, faces=None, material=0, smooth=False, uvs=None, leaf=None):
        self.verts = np.zeros((0, 3)) if verts is None else np.asarray(verts, dtype=np.float64).reshape(-1, 3)
        self.leaf = None if leaf is None else np.asarray(leaf, dtype=np.float64).reshape(-1, 3)
        self.faces = [tuple(int(i) for i in f) for f in (faces or [])]
        n = len(self.faces)
        self.material = [material] * n if np.isscalar(material) else list(material)
        self.smooth = [smooth] * n if isinstance(smooth, bool) else list(smooth)
        if uvs is None:
            uvs = [tuple((0.0, 0.0) for _ in f) for f in self.faces]
        self.uvs = list(uvs)

    def extend(self, other):
        offset = len(self.verts)
        if self.leaf is not None or other.leaf is not None:
            mine = self.leaf if self.leaf is not None else np.zeros((offset, 3))
            theirs = other.leaf if other.leaf is not None else np.zeros((len(other.verts), 3))
            self.leaf = np.concatenate([mine, theirs])
        self.verts = np.concatenate([self.verts, other.verts])
        self.faces += [tuple(i + offset for i in f) for f in other.faces]
        self.material += other.material
        self.smooth += other.smooth
        self.uvs += other.uvs
        return self


def _tangents(points):
    diff = np.diff(points, axis=0)
    diff /= np.maximum(np.linalg.norm(diff, axis=1, keepdims=True), 1e-12)
    tangents = np.empty_like(points)
    tangents[0], tangents[-1] = diff[0], diff[-1]
    if len(points) > 2:
        mid = diff[:-1] + diff[1:]
        tangents[1:-1] = mid / np.maximum(np.linalg.norm(mid, axis=1, keepdims=True), 1e-12)
    return tangents


def tube(polyline, sides, twist_turns=0.0, cap_start=False):
    """Closed-at-the-tip tube along a polyline, with parallel-transport frames."""
    points, radii = polyline.points, polyline.radii
    tangents = _tangents(points)
    normal = _perpendicular(tangents[0])
    lengths = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    total = max(lengths[-1], 1e-9)
    angles = 2.0 * math.pi * np.arange(sides) / sides
    verts = []
    for i, (point, tangent, radius) in enumerate(zip(points, tangents, radii)):
        normal = normal - tangent * np.dot(normal, tangent)
        normal = _normalize(normal) if np.linalg.norm(normal) > 1e-9 else _perpendicular(tangent)
        binormal = np.cross(tangent, normal)
        verts.append(point + radius * (np.outer(np.cos(angles), normal) + np.outer(np.sin(angles), binormal)))
    verts = np.concatenate(verts)
    if cap_start:
        # A trunk base ring tilted by a bend would dip below the ground.
        verts[:sides, 2] = points[0][2]
    faces, uvs = [], []
    rings = len(points)
    for i in range(rings - 1):
        v0, v1 = lengths[i], lengths[i + 1]
        shift0, shift1 = twist_turns * v0 / total, twist_turns * v1 / total
        for j in range(sides):
            k = (j + 1) % sides
            faces.append((i * sides + j, i * sides + k, (i + 1) * sides + k, (i + 1) * sides + j))
            u0, u1 = j / sides, (j + 1) / sides
            uvs.append(((u0 + shift0, v0), (u1 + shift0, v0), (u1 + shift1, v1), (u0 + shift1, v1)))
    # Tip cap: a low dome.
    tip = len(verts)
    verts = np.concatenate([verts, [points[-1] + tangents[-1] * radii[-1] * 0.5]])
    last = (rings - 1) * sides
    for j in range(sides):
        faces.append((last + j, last + (j + 1) % sides, tip))
        uvs.append(((j / sides, total), ((j + 1) / sides, total), ((j + 0.5) / sides, total)))
    if cap_start:
        base = len(verts)
        verts = np.concatenate([verts, [points[0]]])
        for j in range(sides):
            faces.append(((j + 1) % sides, j, base))
            uvs.append((((j + 1) / sides, 0.0), (j / sides, 0.0), ((j + 0.5) / sides, 0.0)))
    return MeshData(verts, faces, TRUNK, True, uvs)


def tube_mesh(data):
    mesh = MeshData()
    sides = data.params.trunk_sides
    twist_turns = data.params.twist / 360.0
    for polyline in data.polylines:
        if polyline.mesh:
            mesh.extend(tube(polyline, sides, twist_turns, cap_start=polyline.parent < 0))
    return mesh


@lru_cache(maxsize=None)
def _icosphere(subdivisions):
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    verts = [tuple(np.array(v) / np.linalg.norm(v)) for v in verts]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]  # fmt: skip
    for _ in range(subdivisions):
        cache = {}

        def midpoint(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = (np.array(verts[a]) + np.array(verts[b])) / 2.0
                verts.append(tuple(m / np.linalg.norm(m)))
                cache[key] = len(verts) - 1
            return cache[key]

        new_faces = []
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces
    return np.array(verts), tuple(faces)


def icosphere(subdivisions):
    """Unit icosphere (vertices array copy, faces tuple)."""
    verts, faces = _icosphere(subdivisions)
    return verts.copy(), faces


def _subdivisions_for(radius, resolution, lowest=1, highest=5):
    # An icosphere's edge is about 1.1 r / 2^k long.
    level = math.ceil(math.log2(max(1.1 * radius / resolution, 1.0)))
    return int(min(max(level, lowest), highest))


def blob_transform(blob):
    """3x3 matrix taking the unit sphere to the blob ellipsoid (without translation)."""
    _, _, _, radius, stretch, flatten, yaw = blob
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    return rotation @ np.diag([radius * stretch, radius, radius * flatten])


def blob_spheres(blobs, resolution):
    """Separate (unmerged) icosphere per blob, as canopy surface (verts, faces)."""
    mesh = MeshData()
    for blob in blobs:
        level = _subdivisions_for(blob[3] * max(blob[4], 1.0), resolution, 1, 4)
        verts, faces = icosphere(level)
        verts = verts @ blob_transform(blob).T + blob[:3]
        mesh.extend(MeshData(verts, faces))
    return mesh.verts, mesh.faces


def envelope_surface(envelope, resolution):
    """Mesh of the envelope surface: an icosphere projected radially onto it."""
    centre = envelope.centre
    size = max(envelope.radius, envelope.height)
    verts, faces = icosphere(_subdivisions_for(size / 2.0, resolution, 2, 6))
    lo = np.zeros(len(verts))
    hi = np.full(len(verts), 2.0 * size + 1.0)
    for _ in range(32):
        mid = (lo + hi) / 2.0
        inside = envelope.sdf(centre + verts * mid[:, None]) <= 0.0
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    return centre + verts * lo[:, None], faces


def metaball_settings(blob_merge):
    """(threshold, stiffness, element radius factor) for Blender metaballs.

    A Blender metaball element of radius ``R`` and stiffness ``s`` has the
    field ``s (1 - d^2 / R^2)^3``; alone, its surface sits where the field
    equals the threshold, at ``d = R sqrt(1 - (t / s)^(1/3))``. The element
    radius is scaled so that an isolated blob keeps its own radius, while a
    higher threshold ratio lets neighbouring blobs reach further and fuse.
    """
    stiffness = 2.0
    ratio = 0.02 + 0.48 * min(max(blob_merge, 0.0), 1.0)
    factor = 1.0 / math.sqrt(1.0 - ratio ** (1.0 / 3.0))
    return ratio * stiffness, stiffness, factor


def triangles(faces):
    """Fan triangulation: (M, 3) vertex indices and the face index of each triangle."""
    tris, owner = [], []
    for index, face in enumerate(faces):
        for k in range(1, len(face) - 1):
            tris.append((face[0], face[k], face[k + 1]))
            owner.append(index)
    return np.array(tris, dtype=np.int64).reshape(-1, 3), np.array(owner, dtype=np.int64)


def face_normals(verts, faces):
    tris, owner = triangles(faces)
    normals = np.zeros((len(faces), 3))
    if len(tris):
        cross = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
        np.add.at(normals, owner, cross)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def vertex_normals(verts, faces):
    tris, _ = triangles(faces)
    normals = np.zeros_like(verts)
    if len(tris):
        cross = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
        for k in range(3):
            np.add.at(normals, tris[:, k], cross)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def displace(verts, faces, params):
    """Lumpy, ragged canopy: vertices moved along their normals by fractal noise."""
    if len(verts) == 0:
        return verts
    normals = vertex_normals(verts, faces)
    noise = Noise(stage_seed(params.seed, "canopy_noise"))
    scale = max(params.lump_scale, 1e-3)
    amount = params.lumpiness * params.clump_size * noise.fbm(verts / scale, 3)
    amount += raggedness_amplitude(params) * noise.fbm(verts / (scale * 0.25) + 31.7, 2)
    displaced = verts + normals * amount[:, None]
    displaced[:, 2] = np.clip(displaced[:, 2], 0.0, params.height)
    return displaced


def accent_dots(verts, faces, params):
    """Small half-buried spheres scattered on the canopy surface."""
    tris, _ = triangles(faces)
    if len(tris) == 0 or params.accent_amount <= 0.0:
        return MeshData()
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    areas = np.linalg.norm(cross, axis=1) / 2.0
    total = float(areas.sum())
    size = params.accent_size
    spacing = 2.5 * size
    count = int(min(params.accent_amount * total / (spacing * spacing), 300))
    rng = stage_rng(params.seed, "accent")
    cumulative = np.cumsum(areas) / max(total, 1e-12)
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-12)
    chosen = []
    sphere_verts, sphere_faces = icosphere(1)
    mesh = MeshData()
    for _ in range(count * 6):
        if len(chosen) >= count:
            break
        tri = int(min(np.searchsorted(cumulative, rng.random()), len(tris) - 1))
        u, v = rng.random(), rng.random()
        if u + v > 1.0:
            u, v = 1.0 - u, 1.0 - v
        point = a[tri] + (b[tri] - a[tri]) * u + (c[tri] - a[tri]) * v
        if chosen and np.min(np.linalg.norm(np.array(chosen) - point, axis=1)) < spacing:
            continue
        chosen.append(point)
        centre = point - normals[tri] * size * 0.45
        mesh.extend(MeshData(sphere_verts * size + centre, sphere_faces, ACCENT))
    return mesh


def top_facing(verts, faces, params):
    """Mask of canopy faces turned to accent: facing up, thinned by noise."""
    normals = face_normals(verts, faces)
    candidates = normals[:, 2] >= params.accent_threshold
    mask = np.zeros(len(faces), dtype=bool)
    if not candidates.any() or params.accent_amount <= 0.0:
        return mask
    tris, owner = triangles(faces)
    centroids = np.zeros((len(faces), 3))
    np.add.at(centroids, owner, verts[tris].mean(axis=1))
    centroids /= np.maximum(np.bincount(owner, minlength=len(faces)), 1)[:, None]
    noise = Noise(stage_seed(params.seed, "accent")).fbm(centroids / max(params.lump_scale, 1e-3), 2)
    cutoff = np.quantile(noise[candidates], min(params.accent_amount, 1.0))
    mask[candidates] = noise[candidates] <= cutoff
    return mask


def lathe(profile, sides, centre=(0.0, 0.0)):
    """Surface of revolution of a (radius, z) profile running from the bottom axis to the top."""
    verts, rings = [], []
    angles = 2.0 * math.pi * np.arange(sides) / sides
    for rho, z in profile:
        if rho <= 1e-9:
            rings.append([len(verts)] * sides)
            verts.append((centre[0], centre[1], z))
        else:
            rings.append(list(range(len(verts), len(verts) + sides)))
            verts += [(centre[0] + rho * math.cos(a), centre[1] + rho * math.sin(a), z) for a in angles]
    faces = []
    for low, high in zip(rings[:-1], rings[1:]):
        for j in range(sides):
            k = (j + 1) % sides
            face = []
            for index in (low[j], low[k], high[k], high[j]):
                if index not in face:
                    face.append(index)
            if len(face) >= 3:
                faces.append(tuple(face))
    return np.array(verts, dtype=np.float64), faces


def base_mesh(params, half_width, anchor):
    style = params.base_style
    if style == "NONE":
        return MeshData()
    radius = min(params.base_radius, 0.95 * half_width)
    height = params.base_height
    sides = max(12, params.trunk_sides * 2)
    if style == "MOUND":
        angles = np.linspace(0.0, math.pi / 2.0, 6)
        profile = [(0.0, 0.0)] + [(radius * math.cos(a), height * math.sin(a)) for a in angles]
        profile[-1] = (0.0, height)
        verts, faces = lathe(profile, sides, anchor)
        return MeshData(verts, faces, BASE, True)
    if style == "POT":
        rim = radius * 1.08
        profile = [
            (0.0, 0.0),
            (radius * 0.72, 0.0),
            (radius, height * 0.82),
            (rim, height * 0.82),
            (rim, height),
            (radius * 0.9, height),
            (radius * 0.9, height * 0.9),
            (0.0, height * 0.9),
        ]
        verts, faces = lathe(profile, sides, anchor)
        return MeshData(verts, faces, BASE, False)
    # Rocks: a few lumpy stones around the trunk.
    rng = stage_rng(params.seed, "base")
    noise = Noise(stage_seed(params.seed, "base_noise"))
    mesh = MeshData()
    count = 6
    for k in range(count):
        azimuth = 2.0 * math.pi * (k + rng.uniform(-0.3, 0.3)) / count
        size = radius * rng.uniform(0.25, 0.4)
        distance = radius - size
        centre = np.array([anchor[0], anchor[1], 0.0]) + _horizontal(azimuth) * distance
        verts, faces = icosphere(2)
        verts = verts * (1.0 + 0.25 * noise.fbm(verts * 1.5 + k * 5.0, 2))[:, None]
        verts = verts * np.array([size, size, height * rng.uniform(0.7, 1.0)]) + centre
        verts[:, 2] = np.maximum(verts[:, 2], 0.0)
        mesh.extend(MeshData(verts, faces, BASE, False))
    return mesh


def _reach_limit(base, direction, envelope, height):
    """Longest distance from ``base`` along ``direction`` inside the envelope radius and [0, height]."""
    limit = math.inf
    q = base[:2] - np.array([envelope.cx, envelope.cy])
    d = direction[:2]
    a, b, c = float(d @ d), 2.0 * float(q @ d), float(q @ q) - envelope.radius**2
    if c > 0.0:
        return 0.0
    if a > 1e-12:
        limit = (-b + math.sqrt(max(b * b - 4.0 * a * c, 0.0))) / (2.0 * a)
    if direction[2] < -1e-9:
        limit = min(limit, base[2] / -direction[2])
    elif direction[2] > 1e-9:
        limit = min(limit, (height - base[2]) / direction[2])
    return max(limit, 0.0)


def _needle_stations(polyline, start, spacing):
    """Fractions of ``polyline`` from ``start`` to its end, about ``spacing`` apart."""
    count = int((1.0 - start) * polyline.length / max(spacing, 1e-3))
    if count < 1:
        return np.zeros(0)
    return start + (1.0 - start) * (np.arange(count) + 0.5) / count


def needle_surface(data):
    """Needle canopy: thin triangles in a fishbone along the branches, (verts, faces).

    Each branch carries a pair of needles every ``needle_spacing``, one on
    each side, angled ``needle_angle`` towards the tip and hanging
    ``needle_droop`` down; with several ``needle_rows`` they fan out 25
    degrees apart around that droop. Needles are longest a quarter of the
    way along and shrink to the tip; the bare start of a branch is
    ``hollow``. The top of each stem, above the highest branch, gets
    needles all around.
    Needles are kept inside the envelope radius and between the ground and
    the tree height, and their faces point up so snow can settle on them.
    """
    params = data.params
    envelope = data.envelope
    rng = stage_rng(params.seed, "needles")
    jitter = params.jitter
    angle = math.radians(params.needle_angle)
    droop = math.radians(params.needle_droop)
    half_width = params.needle_width / 2.0
    down = np.array([0.0, 0.0, -1.0])
    up = np.array([0.0, 0.0, 1.0])
    verts, faces = [], []

    rows = max(1, params.needle_rows)
    fan = [droop + math.radians(25.0) * (k - (rows - 1) / 2.0) for k in range(rows)]

    def needle(base, tangent, side, length, tilt):
        direction = _normalize(side * math.cos(angle) + tangent * math.sin(angle))
        tilt += rng.uniform(-1.0, 1.0) * jitter * math.radians(10.0)
        if tilt >= 0.0:
            direction = _rotate_towards(direction, down, tilt)
        else:
            direction = _rotate_towards(direction, up, -tilt)
        length *= 1.0 + rng.uniform(-0.25, 0.25) * jitter
        length = min(length, _reach_limit(base, direction, envelope, params.height))
        if length < 2.0 * half_width:
            return
        a, b, c = base - tangent * half_width, base + tangent * half_width, base + direction * length
        if np.cross(b - a, c - a)[2] < 0.0:
            a, b = b, a
        faces.append((len(verts), len(verts) + 1, len(verts) + 2))
        verts.extend((a, b, c))

    stems = set(data.skeleton.stems)
    for index, polyline in enumerate(data.polylines):
        if index in stems or polyline.level == 0:
            continue
        for s in _needle_stations(polyline, params.hollow, params.needle_spacing):
            base, tangent, _ = polyline.sample(s)
            side = np.cross(up, tangent)
            side = _normalize(side) if np.linalg.norm(side) > 1e-6 else _perpendicular(tangent)
            v = (s - params.hollow) / max(1.0 - params.hollow, 1e-6)
            length = params.needle_length * (0.6 + 0.4 * _smoothstep(v / 0.25)) * (1.0 - 0.75 * v**1.5)
            for sign in (1.0, -1.0):
                for tilt in fan:
                    needle(base, tangent, sign * side, length, tilt)

    # The leader: needles all around the stem above the highest branch.
    branched = any(p.level > 0 for p in data.polylines)
    start_z = envelope.bottom
    if branched:
        start_z = max(start_z, max(float(p.points[0][2]) for p in data.polylines if p.level == 1))
    for k, index in enumerate(sorted(stems)):
        stem = data.polylines[index]
        for i, s in enumerate(_needle_stations(stem, 0.0, params.needle_spacing / 2.0)):
            base, tangent, _ = stem.sample(s)
            if base[2] < start_z:
                continue
            longest = params.needle_length * (0.6 if branched else 1.0)
            # Short needles even where the envelope narrows to a point, so the tip is not bare.
            length = min(max(envelope.radius_at(float(base[2])), 0.3 * longest), longest)
            side = _horizontal(math.radians(GOLDEN_ANGLE * (i + 7 * k)))
            side = _normalize(side - tangent * np.dot(side, tangent))
            needle(base, tangent, side, length, droop * 0.5)
    return np.array(verts, dtype=np.float64).reshape(-1, 3), faces


class Strands:
    """Straight hair strands: root points, unit directions and lengths, (N, 3), (N, 3), (N,)."""

    def __init__(self, roots=None, directions=None, lengths=None):
        self.roots = np.zeros((0, 3)) if roots is None else np.asarray(roots, dtype=np.float64).reshape(-1, 3)
        self.directions = np.zeros((0, 3)) if directions is None else np.asarray(directions, dtype=np.float64).reshape(-1, 3)
        self.lengths = np.zeros(0) if lengths is None else np.asarray(lengths, dtype=np.float64).reshape(-1)

    def __len__(self):
        return len(self.lengths)

    @property
    def tips(self):
        return self.roots + self.directions * self.lengths[:, None]


#: Edge of the tiny triangle each strand grows from.
HAIR_CARD_SIZE = 0.01


def _cone_direction(axis, angle, rng):
    """Random unit vector at most ``angle`` (radians) from ``axis``, uniform over the cap."""
    cos_theta = 1.0 - rng.random() * (1.0 - math.cos(angle))
    theta = math.acos(min(max(cos_theta, -1.0), 1.0))
    return _rotate(_rotate(axis, _perpendicular(axis), theta), axis, rng.uniform(0.0, 2.0 * math.pi))


def _droop(direction, droop):
    """Tilt ``direction`` towards the ground by ``droop`` radians (negative lifts it)."""
    if droop >= 0.0:
        return _rotate_towards(direction, np.array([0.0, 0.0, -1.0]), droop)
    return _rotate_towards(direction, np.array([0.0, 0.0, 1.0]), -droop)


def _split(total, weights):
    """``total`` items shared out in proportion to ``weights`` (largest remainders)."""
    weights = np.asarray(weights, dtype=np.float64)
    if len(weights) == 0 or weights.sum() <= 0.0:
        return np.zeros(len(weights), dtype=np.int64)
    exact = total * weights / weights.sum()
    counts = np.floor(exact).astype(np.int64)
    order = np.argsort(-(exact - counts), kind="stable")
    counts[order[: total - int(counts.sum())]] += 1
    return counts


def _hair_on_branches(data, rng):
    """(root, direction, length factor) of strands along the branches, or the stems without branches."""
    params = data.params
    stems = set(data.skeleton.stems)
    lines = [p for i, p in enumerate(data.polylines) if p.level > 0 and i not in stems]
    start = params.hollow
    if not lines:
        # A bare trunk: strands along the stems inside the canopy.
        lines = [data.polylines[i] for i in sorted(stems)]
    angle = math.radians(params.hair_spread)
    up = np.array([0.0, 0.0, 1.0])
    result = []
    for polyline, count in zip(lines, _split(params.hair_count, [p.length for p in lines])):
        for k in range(int(count)):
            s = start + (1.0 - start) * (k + rng.random()) / count
            base, tangent, _ = polyline.sample(s)
            if polyline.level == 0 and base[2] < data.envelope.bottom:
                continue
            side = np.cross(up, tangent)
            side = _normalize(side) if np.linalg.norm(side) > 1e-6 else _perpendicular(tangent)
            # Flatten 1 keeps the strands level with the branch, on either side.
            roll = rng.uniform(-1.0, 1.0) * (1.0 - params.hair_flatten) * math.pi / 2.0
            if rng.random() < 0.5:
                roll += math.pi
            out = _rotate(side, tangent, roll)
            direction = _normalize(tangent * math.cos(angle) + out * math.sin(angle))
            v = (s - start) / max(1.0 - start, 1e-6)
            result.append((base, direction, 1.0 - 0.5 * v**1.5))
    return result


def _hair_at_tips(data, rng):
    params = data.params
    angle = math.radians(params.hair_spread)
    result = []
    for tip, count in zip(data.tips, _split(params.hair_count, np.ones(len(data.tips)))):
        for _ in range(int(count)):
            result.append((tip.point, _cone_direction(tip.direction, angle, rng), 1.0))
    return result


def _hair_on_canopy(data, rng):
    params = data.params
    verts, faces = envelope_surface(data.envelope, 0.25)
    tris, _ = triangles(faces)
    if len(tris) == 0:
        return []
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    cumulative = np.cumsum(np.linalg.norm(cross, axis=1))
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-12)
    angle = math.radians(params.hair_spread)
    result = []
    for _ in range(params.hair_count):
        tri = int(min(np.searchsorted(cumulative, rng.random() * cumulative[-1]), len(tris) - 1))
        u, v = rng.random(), rng.random()
        if u + v > 1.0:
            u, v = 1.0 - u, 1.0 - v
        point = a[tri] + (b[tri] - a[tri]) * u + (c[tri] - a[tri]) * v
        result.append((point, _cone_direction(normals[tri], angle, rng), 1.0))
    return result


def _hair_in_volume(data, rng):
    params = data.params
    envelope = data.envelope
    centre = envelope.centre
    lo = np.array([envelope.cx - envelope.radius, envelope.cy - envelope.radius, envelope.bottom])
    hi = np.array([envelope.cx + envelope.radius, envelope.cy + envelope.radius, envelope.top])
    sampler = np.random.default_rng(rng.getrandbits(32))
    points = np.zeros((0, 3))
    for _ in range(20):
        if len(points) >= params.hair_count:
            break
        batch = lo + (hi - lo) * sampler.random((4 * params.hair_count, 3))
        points = np.concatenate([points, batch[envelope.sdf(batch) <= 0.0]])
    angle = math.radians(params.hair_spread)
    result = []
    for point in points[: params.hair_count]:
        out = point - centre
        # Outwards from the centre, or up from the centre itself.
        axis = _normalize(out) if np.linalg.norm(out) > 1e-6 else np.array([0.0, 0.0, 1.0])
        result.append((point, _cone_direction(axis, angle, rng), 1.0))
    return result


def _hair_in_clumps(data, rng):
    """Strands from inside each clump, pointing away from its centre: a fluffy tuft per clump."""
    params = data.params
    blobs = data.blobs
    if len(blobs) == 0:
        return []
    volumes = blobs[:, 3] ** 3 * blobs[:, 4] * blobs[:, 5]
    angle = math.radians(params.hair_spread)
    result = []
    for blob, count in zip(blobs, _split(params.hair_count, volumes)):
        transform = blob_transform(blob)
        for _ in range(int(count)):
            while True:
                u = np.array([rng.uniform(-1.0, 1.0) for _ in range(3)])
                if u @ u <= 1.0:
                    break
            out = transform @ u
            axis = _normalize(out) if np.linalg.norm(out) > 1e-6 else np.array([0.0, 0.0, 1.0])
            result.append((blob[:3] + out, _cone_direction(axis, angle, rng), 1.0))
    return result


def hair_strands(data):
    """Hair canopy strands (``Strands``), from the branches, the tips, the canopy surface or its volume.

    The leaf instance style places one leaf on each strand, as long as it.

    Every strand tilts ``hair_droop`` towards the ground, loses up to
    ``hair_length_variation`` of its length at random, and is shortened to
    stay within the overhang radius and between the ground and the tree
    height; strands cut below a quarter of their length are dropped.
    """
    params = data.params
    if params.canopy_style not in STRAND_STYLES or params.hair_count <= 0 or params.hair_length <= 0.0:
        return Strands()
    rng = stage_rng(params.seed, "hair")
    source = {
        "BRANCHES": _hair_on_branches,
        "TIPS": _hair_at_tips,
        "CANOPY": _hair_on_canopy,
        "VOLUME": _hair_in_volume,
        "CLUMPS": _hair_in_clumps,
    }[params.hair_source]
    droop = math.radians(params.hair_droop)
    bounds = SimpleNamespace(cx=data.anchor[0], cy=data.anchor[1], radius=params.overhang * data.half_width)
    roots, directions, lengths = [], [], []
    for root, direction, factor in source(data, rng):
        direction = _droop(direction, droop + rng.uniform(-1.0, 1.0) * params.jitter * math.radians(10.0))
        wanted = params.hair_length * factor * (1.0 - params.hair_length_variation * rng.random())
        length = min(wanted, _reach_limit(np.asarray(root, dtype=np.float64), direction, bounds, params.height))
        if length < 0.25 * wanted or length <= 1e-4:
            continue
        roots.append(root)
        directions.append(direction)
        lengths.append(length)
    return Strands(roots, directions, lengths)


def hair_emitter(strands):
    """Emitter mesh for Blender's hair: one tiny triangle per strand, facing along it.

    Hair grows along the emitter's normal; with one particle per (equal)
    triangle and no random emission, each strand starts at its triangle.
    Returns (verts, faces, per-vertex length weight relative to the longest
    strand).
    """
    n = len(strands)
    if n == 0:
        return np.zeros((0, 3)), [], np.zeros(0)
    d = strands.directions
    a = np.cross(d, np.array([0.0, 0.0, 1.0]))
    flat = np.linalg.norm(a, axis=1) < 1e-6
    a[flat] = np.cross(d[flat], np.array([1.0, 0.0, 0.0]))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b = np.cross(d, a)
    # Counter-clockwise around d, so the face normal is d.
    radius = HAIR_CARD_SIZE / math.sqrt(3.0)
    corners = [a * math.cos(t) + b * math.sin(t) for t in (0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0)]
    verts = np.stack([strands.roots + radius * c for c in corners], axis=1).reshape(-1, 3)
    faces = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(n)]
    weights = np.repeat(strands.lengths / strands.lengths.max(), 3)
    return verts, faces, weights


def hair_accents(strands, params):
    """Accent dots (flowers, fruit) at the tips of a share of the strands."""
    if params.accent_mode != "DOTS" or len(strands) == 0 or params.accent_amount <= 0.0:
        return MeshData()
    rng = stage_rng(params.seed, "accent")
    count = int(min(round(params.accent_amount * len(strands)), 300))
    sphere_verts, sphere_faces = icosphere(1)
    mesh = MeshData()
    tips = strands.tips
    for index in sorted(rng.sample(range(len(strands)), count)):
        mesh.extend(MeshData(sphere_verts * params.accent_size + tips[index], sphere_faces, ACCENT))
    return mesh


#: Stations along a leaf blade, between its root and its tip.
LEAF_STATIONS = (0.12, 0.35, 0.6, 0.82)


def _blade(width, profile, start=(0.0, 0.0), length=1.0, yaw=0.0):
    """A flat leaf in the XY plane, rooted at ``start`` and pointing ``yaw`` from +X: (verts, faces).

    ``profile(t)`` is the half-width at ``t`` (0 to 1 along the leaf),
    relative to ``width``. Each station has a midrib vertex and two edge
    vertices, so the leaf can fold along its midrib.
    """
    axis = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    side = np.array([-math.sin(yaw), math.cos(yaw), 0.0])
    origin = np.array([start[0], start[1], 0.0])
    verts = [origin]
    for t in LEAF_STATIONS:
        reach = width * profile(t) * length
        mid = origin + axis * (t * length)
        verts.extend((mid, mid + side * reach, mid - side * reach))
    verts.append(origin + axis * length)
    tip = len(verts) - 1
    faces = []
    for offset in (1, 2):
        # Edge vertex ``offset`` after its midrib vertex: 1 is the +Y edge, 2 the -Y edge.
        half = [(0, 1 + offset, 1)]
        for k in range(len(LEAF_STATIONS) - 1):
            a, b = 1 + 3 * k, 1 + 3 * (k + 1)
            half += [(a, a + offset, b + offset), (a, b + offset, b)]
        last = 1 + 3 * (len(LEAF_STATIONS) - 1)
        half.append((last, last + offset, tip))
        # Counter-clockwise from above on the -Y half; reversed on the +Y half, so both face +Z.
        faces += [tuple(reversed(f)) for f in half] if offset == 1 else half
    return np.array(verts), faces


def _merge(parts):
    verts, faces = [], []
    for part_verts, part_faces in parts:
        faces += [tuple(i + len(verts) for i in f) for f in part_faces]
        verts += list(part_verts)
    return np.array(verts, dtype=np.float64).reshape(-1, 3), faces


def leaf_template(shape, width, custom=None):
    """Leaf mesh of ``shape``, rooted at the origin along +X and about 1 long: (verts, faces).

    ``custom`` is the (verts, faces) of the custom shape, scaled so that it
    reaches x = 1; without one, the custom shape falls back to the blade.
    """
    if shape == "CUSTOM" and custom is not None and len(custom[1]):
        verts = np.asarray(custom[0], dtype=np.float64).reshape(-1, 3)
        reach = float(verts[:, 0].max())
        if reach <= 1e-6:
            reach = float(np.ptp(verts, axis=0).max())
        return verts / max(reach, 1e-6), [tuple(int(i) for i in f) for f in custom[1]]
    half = width / 2.0
    if shape == "OVAL":
        return _blade(half, lambda t: math.sin(math.pi * t) ** 0.6)
    pointed = lambda t: math.sin(math.pi * t**0.75) ** 1.2  # noqa: E731
    if shape == "SPRIG":
        side = math.radians(38.0)
        return _merge(
            (
                _blade(half, pointed),
                _blade(half * 0.9, pointed, (0.22, 0.0), 0.68, side),
                _blade(half * 0.9, pointed, (0.22, 0.0), 0.68, -side),
            )
        )
    return _blade(half, pointed)


def deform_leaves(template, count, params, rng):
    """``count`` deformed copies of a leaf template in its own frame: (count, V, 3).

    Every copy folds about its midrib (``leaf_fold``), twists by up to
    ``leaf_twist`` and curls ``leaf_bend`` towards its underside; with
    ``leaf_irregularity``, its width and bend change and its vertices jitter
    (more towards the tip, so the root stays on its branch).
    """
    verts = np.asarray(template, dtype=np.float64)
    along = np.clip(verts[:, 0], 0.0, 1.0)
    irregular = params.leaf_irregularity
    shape = (count, 1)
    width = 1.0 + irregular * rng.uniform(-0.35, 0.35, shape)
    x = np.broadcast_to(verts[:, 0], (count, len(verts)))
    y = verts[:, 1] * width
    z = verts[:, 2] + np.abs(y) * math.tan(math.radians(params.leaf_fold))
    twist = math.radians(params.leaf_twist) * rng.uniform(-1.0, 1.0, shape) * x
    y, z = y * np.cos(twist) - z * np.sin(twist), y * np.sin(twist) + z * np.cos(twist)
    # Bend: the midrib follows an arc of curvature ``bend`` (per unit length) down towards -Z.
    bend = math.radians(params.leaf_bend) * (1.0 + irregular * rng.uniform(-0.6, 0.6, shape))
    bend = np.where(np.abs(bend) < 1e-6, 1e-6, bend)
    theta = x * bend
    radius = 1.0 / bend + z
    x, z = radius * np.sin(theta), radius * np.cos(theta) - 1.0 / bend
    result = np.stack([x, y, z], axis=-1)
    result += irregular * 0.06 * rng.uniform(-1.0, 1.0, (count, len(verts), 3)) * along[None, :, None]
    return result


def leaf_frames(directions, params, rng):
    """Rotation of each leaf, (N, 3, 3): its +X along the strand, its +Z up as far as ``leaf_face_up`` keeps it."""
    d = np.asarray(directions, dtype=np.float64).reshape(-1, 3)
    up = np.zeros_like(d)
    up[:, 2] = 1.0
    normal = up - d * d[:, 2:3]
    vertical = np.linalg.norm(normal, axis=1) < 1e-6
    normal[vertical] = np.cross(d[vertical], [0.0, 1.0, 0.0])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    side = np.cross(normal, d)
    roll = rng.uniform(-1.0, 1.0, (len(d), 1)) * math.pi * (1.0 - params.leaf_face_up)
    normal, side = normal * np.cos(roll) + side * np.sin(roll), side * np.cos(roll) - normal * np.sin(roll)
    return np.stack([d, side, normal], axis=-1)


def leaf_instances(data, custom=None):
    """Leaf instance canopy: one deformed leaf per strand, (verts, faces, leaf shading).

    Each leaf is as long as its strand and points along it. The shading
    attribute (see ``MeshData``) holds each vertex's position from root to
    tip, one random value per leaf and a leaf flag.
    """
    params = data.params
    strands = data.strands
    template, faces = leaf_template(params.leaf_shape, params.leaf_width, custom)
    count = len(strands)
    if count == 0 or len(faces) == 0:
        return np.zeros((0, 3)), [], np.zeros((0, 3))
    rng = np.random.default_rng(stage_seed(params.seed, "leaves"))
    local = deform_leaves(template, count, params, rng) * strands.lengths[:, None, None]
    frames = leaf_frames(strands.directions, params, rng)
    verts = np.einsum("nij,nvj->nvi", frames, local) + strands.roots[:, None, :]
    verts[:, :, 2] = np.clip(verts[:, :, 2], 0.0, params.height)
    size = len(template)
    all_faces = [tuple(int(i) + n * size for i in f) for n in range(count) for f in faces]
    shade = np.ones((count, size, 3))
    shade[:, :, 0] = np.clip(template[:, 0], 0.0, 1.0)
    shade[:, :, 1] = rng.random((count, 1))
    return verts.reshape(-1, 3), all_faces, shade.reshape(-1, 3)


def canopy_mesh(data, verts, faces, leaf=None):
    """Displaced canopy plus accent, from a raw canopy surface (``leaf`` as in ``MeshData``)."""
    params = data.params
    verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    if params.canopy_style not in ("NEEDLES", "INSTANCES"):
        # Needles and leaves are already irregular; noise would only warp them.
        verts = displace(verts, faces, params)
    material = [LEAVES] * len(faces)
    if params.accent_mode == "TOP_FACING":
        for index in np.flatnonzero(top_facing(verts, faces, params)):
            material[index] = ACCENT
    mesh = MeshData(verts, faces, material, False, leaf=leaf)
    if params.accent_mode == "DOTS":
        mesh.extend(accent_dots(verts, faces, params))
    return mesh


def canopy_surface(data, polygonize=None):
    """Raw canopy surface (verts, faces) before displacement.

    ``polygonize(blobs, params)`` merges blobs into one surface (the Blender
    side uses metaballs); without it, or with ``blob_merge = 0``, each blob
    is a separate icosphere.
    """
    params = data.params
    resolution = max(params.resolution, MIN_RESOLUTION)
    if params.canopy_style == "TOPIARY":
        return envelope_surface(data.envelope, resolution)
    if params.canopy_style == "NEEDLES":
        return needle_surface(data)
    if params.canopy_style in STRAND_STYLES:
        # Hair is rendered by Blender's particles; leaves come from ``leaf_instances``.
        return np.zeros((0, 3)), []
    if len(data.blobs) == 0:
        return np.zeros((0, 3)), []
    if polygonize is not None and params.blob_merge > 0.0:
        return polygonize(data.blobs, params)
    return blob_spheres(data.blobs, resolution)


def build(params, polygonize=None, leaf_template=None):
    """Generate a tree and its full mesh data: (TreeData, MeshData).

    With the hair and leaf instance styles, ``TreeData.strands`` holds the
    strands, one per leaf for the latter. ``leaf_template`` is the
    (verts, faces) of the custom leaf shape.
    """
    data = generate(params)
    mesh = tube_mesh(data)
    data.strands = hair_strands(data)
    leaf = None
    if params.canopy_style == "INSTANCES":
        verts, faces, leaf = leaf_instances(data, leaf_template)
    else:
        verts, faces = canopy_surface(data, polygonize)
    if len(faces):
        mesh.extend(canopy_mesh(data, verts, faces, leaf))
    if params.canopy_style == "HAIR":
        mesh.extend(hair_accents(data.strands, params))
    mesh.extend(base_mesh(params, data.half_width, data.anchor))
    return data, mesh
