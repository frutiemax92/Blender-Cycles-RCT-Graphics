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

    small_shape: EnumProperty(
        name="Shape",
        description=(
            "How the object occupies its tile. The game anchors the sprite "
            "differently for each shape; offsets are computed from it so the "
            "images JSON never needs manual edits"
        ),
        items=(
            ("FULL", "Full Tile", "Occupies the whole tile (shape 4/4)"),
            ("THREE_QUARTERS", "Three Quarters", "Occupies three quarters (shape 3/4)"),
            ("HALF", "Half Tile", "Occupies half a tile (shape 2/4)"),
            ("QUARTER", "Quarter Tile", "Occupies one quarter; model it around the origin (shape 1/4)"),
            ("FULL_CENTRED", "Full Tile, Centred", "Full tile with SMALL_SCENERY_FLAG_VOFFSET_CENTRE"),
            (
                "FULL_CENTRED_NO_WALLS",
                "Full Tile, Centred, No Walls",
                "Full tile with SMALL_SCENERY_FLAG_VOFFSET_CENTRE and prohibitWalls",
            ),
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

    # Object description (object.json) ----------------------------------

    object_id: StringProperty(
        name="Object ID",
        description="Unique identifier, usually author.type.name (also the .parkobj file name)",
        default="custom.scenery.my_object",
    )

    object_name: StringProperty(
        name="Name",
        description="Name shown in the game (en-GB)",
        default="My Object",
    )

    object_authors: StringProperty(
        name="Authors",
        description="Comma separated list of authors",
        default="",
    )

    price: IntProperty(name="Price", description="Build price", default=10, min=0)

    removal_price: IntProperty(name="Removal Price", description="Removal price (small and large scenery)", default=0)

    scenery_group: StringProperty(
        name="Scenery Group",
        description="Optional scenery group object ID to list the object in",
        default="",
    )

    animation_delay: IntProperty(
        name="Animation Delay",
        description="Game ticks per animation frame, as a power of two (frame = ticks >> delay)",
        default=2,
        min=0,
        max=15,
    )

    build_parkobj: BoolProperty(
        name="Build .parkobj After Render",
        description="Write object.json and pack the .parkobj after every render",
        default=False,
    )

    copy_to_openrct2: BoolProperty(
        name="Copy to OpenRCT2",
        description="Copy the .parkobj into OpenRCT2's object folder (set it in the add-on preferences)",
        default=False,
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
