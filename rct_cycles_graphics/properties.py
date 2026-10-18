import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


def _update_footprint(self, context):
    from . import scene_setup

    if scene_setup.get_rig(context.scene)[0] is None:
        return
    if self.object_type == "LARGE":
        scene_setup.build_tile_grid(context.scene, self.tiles_width, self.tiles_length)
    else:
        scene_setup.build_tile_grid(context.scene, 1, 1, wall=self.object_type == "WALL")


class RCTGraphicsProperties(bpy.types.PropertyGroup):
    object_type: EnumProperty(
        name="Object Type",
        items=(
            ("SMALL", "Small Scenery", "Single-tile scenery (trees, base blocks, roofs, ...)"),
            ("LARGE", "Large Scenery", "Multi-tile scenery, split into one sprite per tile"),
            ("WALL", "Wall", "Wall piece rendered along a tile edge"),
        ),
        default="SMALL",
        update=_update_footprint,
    )

    wall_double_sided: BoolProperty(
        name="Double Sided",
        description="Also render the back face, seen when the wall is on a near edge (images 6-11)",
        default=False,
    )

    wall_sloped: BoolProperty(
        name="Sloped",
        description="Also render the wall on sloped land (images 2-5)",
        default=True,
    )

    tiles_width: IntProperty(
        name="Width",
        description="Footprint size in tiles along the game x axis (Blender -X)",
        default=2,
        min=1,
        max=16,
        update=_update_footprint,
    )

    tiles_length: IntProperty(
        name="Length",
        description="Footprint size in tiles along the game y axis (Blender -Y)",
        default=2,
        min=1,
        max=16,
        update=_update_footprint,
    )

    output_directory: StringProperty(
        name="Output Folder",
        description="Folder receiving the sprites and the images JSON",
        subtype="DIR_PATH",
        default="//rct_output",
    )

    start_index: IntProperty(
        name="First Image Index",
        description="Index in the object's image table of the first rendered sprite",
        default=0,
        min=0,
    )

    small_anchor: EnumProperty(
        name="Placement",
        description=(
            "How the game positions the object on its tile. Sprite offsets are "
            "computed from it, so the images JSON never needs manual edits"
        ),
        items=(
            ("FULL", "Full / Quarter Tile", "Default full-tile or quarter-tile scenery (paint offset 15, 15)"),
            ("CENTRED", "Full Tile, Centred / Half Tile", "Objects flagged 'isStackable'-style voffset centre, or half-tile objects (paint offset 3, 3)"),
            ("NO_WALLS", "Full Tile, Centred, No Walls", "Voffset centre combined with 'prohibitWalls' (paint offset 1, 1)"),
        ),
        default="FULL",
    )

    animation_frames: IntProperty(
        name="Animation Frames",
        description="Number of animation frames to render (1 for a still object)",
        default=1,
        min=1,
    )

    animation_first_frame: IntProperty(
        name="First Frame",
        description="Scene frame of the first animation frame",
        default=1,
    )

    animation_frame_step: IntProperty(
        name="Frame Step",
        description="Scene frames between two rendered animation frames",
        default=1,
        min=1,
    )

    check_after_render: BoolProperty(
        name="Check Alignment After Render",
        description="Run the alignment check and refresh the tiling preview after every render",
        default=True,
    )

    alignment_report: StringProperty(
        name="Alignment Report",
        description="Result of the last alignment check",
        default="",
    )

    # Rendering -----------------------------------------------------------

    samples: IntProperty(
        name="Samples",
        description="Cycles samples per pixel. Sprites are tiny, so this is cheap",
        default=64,
        min=1,
        max=4096,
    )

    filter_width: FloatProperty(
        name="Filter Width",
        description=(
            "Pixel filter width used for interior anti-aliasing. 1.0 keeps the "
            "silhouette exact so adjacent tiles line up without gaps"
        ),
        default=1.0,
        min=0.01,
        max=3.0,
    )

    cast_shadows: BoolProperty(
        name="Shadows",
        description="Let the sun lights cast shadows",
        default=True,
    )

    # Default light strengths are calibrated on the original base block sprite,
    # whose left, top and right faces relate as about 0.63 : 1 : 2.25 in
    # linear light.
    main_light_strength: FloatProperty(
        name="Main Light",
        description="Strength of the sun coming from the camera's right",
        default=2.0,
        min=0.0,
        soft_max=10.0,
    )

    fill_light_strength: FloatProperty(
        name="Fill Light",
        description="Strength of the low front fill sun",
        default=3.0,
        min=0.0,
        soft_max=10.0,
    )

    ambient_strength: FloatProperty(
        name="Ambient",
        description="Strength of the uniform world lighting",
        default=0.06,
        min=0.0,
        soft_max=2.0,
    )

    # Silhouette ----------------------------------------------------------

    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        description=(
            "Pixels with at least this much coverage become opaque. The edge is "
            "kept hard (aliased) like the original game sprites while the "
            "interior stays anti-aliased"
        ),
        default=0.5,
        min=0.01,
        max=1.0,
    )

    background_blend: BoolProperty(
        name="Blend Edges with Background",
        description=(
            "Anti-alias the edges against a dark background before cutting the "
            "silhouette, giving the dark fringe typical of RCT1 graphics"
        ),
        default=False,
    )

    # Outline -------------------------------------------------------------

    outline_shades: IntProperty(
        name="Outline Darkening",
        description=(
            "Darken the sprite's rim by this many shades of each pixel's own "
            "palette ramp (0 disables the outline). Many original sprites, "
            "such as trees, have such a dark contour"
        ),
        default=0,
        min=0,
        max=11,
    )

    outline_width: IntProperty(
        name="Outline Width",
        description="Thickness of the darkened rim in pixels",
        default=1,
        min=1,
        max=4,
    )

    outline_diagonal: BoolProperty(
        name="Diagonal Neighbours",
        description="Also treat pixels touching the background only by a corner as rim",
        default=False,
    )

    # Colour --------------------------------------------------------------

    dither_method: EnumProperty(
        name="Dithering",
        items=(
            ("FLOYD_STEINBERG", "Floyd-Steinberg", "Error diffusion, like the original add-on"),
            ("ORDERED", "Ordered", "4x4 Bayer pattern"),
            ("NONE", "None", "Nearest palette colour only"),
        ),
        default="FLOYD_STEINBERG",
    )

    dither_strength: FloatProperty(
        name="Dither Strength",
        description="Fraction of the quantization error that is diffused",
        default=0.35,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )


classes = (RCTGraphicsProperties,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rct_graphics = PointerProperty(type=RCTGraphicsProperties)


def unregister():
    del bpy.types.Scene.rct_graphics
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
