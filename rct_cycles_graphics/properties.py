import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


class RCTGraphicsProperties(bpy.types.PropertyGroup):
    object_type: EnumProperty(
        name="Object Type",
        items=(
            ("SMALL", "Small Scenery", "Single-tile scenery (trees, base blocks, roofs, ...)"),
            ("LARGE", "Large Scenery", "Multi-tile scenery, split into one sprite per tile"),
            ("WALL", "Wall", "Wall piece rendered along a tile edge"),
        ),
        default="SMALL",
    )

    output_directory: StringProperty(
        name="Output Folder",
        description="Folder receiving the sprites and the images JSON",
        subtype="DIR_PATH",
        default="//rct_output",
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
