import bpy

from . import materials, scene_setup, tree_generator
from .core import alignment, tree
from .core.jobs import SMALL_SCENERY_SHAPES
from .core.objectjson import OBJECT_FLAGS
from .core.palette import RAMP_TITLES
from .properties import flag_property


def draw_terrain_preview(layout, props):
    """The Preview on Grass button with the vanilla trees to compare with."""
    box = layout.box()
    box.operator("rct_graphics.terrain_preview", icon="IMAGE_BACKGROUND")
    box.label(text="Compare with RCT2 trees:")
    grid = box.grid_flow(columns=2, even_columns=True, align=True)
    for slot in range(1, 5):
        grid.prop(props, "compare_tree_{}".format(slot), text="")


def draw_render_settings(layout, props):
    """The collapsible Render & Colour section, drawn above the Render button."""
    header, layout = layout.panel("RCT_PT_render_settings", default_closed=True)
    header.label(text="Render & Colour")
    if layout is None:
        return
    layout.use_property_split = True
    layout.use_property_decorate = False

    col = layout.column(heading="Cycles")
    col.prop(props, "samples")
    col.prop(props, "supersampling")
    col.prop(props, "cast_shadows")

    col = layout.column(heading="Lighting")
    col.prop(props, "main_light_strength")
    col.prop(props, "fill_light_strength")
    col.prop(props, "ambient_strength")

    col = layout.column(heading="Silhouette")
    col.prop(props, "alpha_threshold")
    col.prop(props, "background_blend")

    col = layout.column(heading="Outline")
    col.prop(props, "outline_shades")
    sub = col.column()
    sub.active = props.outline_shades > 0
    sub.prop(props, "outline_width")
    sub.prop(props, "outline_diagonal")

    col = layout.column(heading="Palette")
    col.prop(props, "palette_mode")
    if props.palette_mode == "CUSTOM":
        grid = col.grid_flow(columns=2, even_columns=True, align=True)
        for i, (_, title) in enumerate(RAMP_TITLES):
            grid.prop(props, "palette_ramps", index=i, text=title, toggle=True)
    col.prop(props, "dither_method")
    sub = col.column()
    sub.active = props.dither_method != "NONE"
    sub.prop(props, "dither_strength")

    col = layout.column(heading="Tones")
    col.prop(props, "tone_match")
    sub = col.column()
    sub.active = props.tone_match
    sub.prop(props, "tone_strength")
    sub.prop(props, "tone_saturation")
    if props.tone_report:
        box = layout.box()
        box.label(text="Last render:")
        for line in props.tone_report.splitlines():
            box.label(text=line)


class RCT_PT_main(bpy.types.Panel):
    bl_label = "RCT Graphics"
    bl_idname = "RCT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RCT"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.rct_graphics

        layout.operator("rct_graphics.initialize", icon="SCENE_DATA")
        if scene_setup.get_rig(scene)[0] is None:
            layout.label(text="Initialize the scene to start", icon="INFO")
            return

        layout.prop(props, "object_type")
        layout.prop(props, "output_directory")
        layout.prop(props, "start_index")

        box = layout.box()
        if props.object_type == "SMALL":
            box.prop(props, "small_shape")
        elif props.object_type == "LARGE":
            row = box.row(align=True)
            row.prop(props, "tiles_width")
            row.prop(props, "tiles_length")
            box.label(text="Tiles extend from the origin tile towards -X / -Y", icon="INFO")
        elif props.object_type == "WALL":
            box.prop(props, "wall_double_sided")
            box.prop(props, "wall_sloped")
            box.label(text="Model the wall on the tile's +X edge", icon="INFO")

        box = layout.box()
        box.prop(props, "animation_frames")
        if props.object_type in {"LARGE", "WALL"}:
            box.label(text="Only the first frame is rendered for this type")
        elif props.animation_frames > 1:
            row = box.row(align=True)
            row.prop(props, "animation_first_frame")
            row.prop(props, "animation_frame_step")

        draw_render_settings(layout, props)
        layout.operator("rct_graphics.render", icon="RENDER_STILL")
        draw_terrain_preview(layout, props)


class RCT_PT_materials(bpy.types.Panel):
    bl_label = "Recolourable Materials"
    bl_idname = "RCT_PT_materials"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RCT"
    bl_parent_id = "RCT_PT_main"

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if obj is None or not hasattr(obj.data, "materials"):
            layout.label(text="Select an object")
            return

        row = layout.row(align=True)
        row.label(text="Add:")
        for remap in (1, 2, 3):
            row.operator("rct_graphics.add_remap_material", text=str(remap)).remap = remap

        for slot in obj.material_slots:
            if slot.material is None:
                continue
            remap = materials.get_remap(slot.material)
            text = slot.material.name
            if remap:
                text += "  (Remap {})".format(remap)
            layout.label(text=text, icon="MATERIAL")

        material = obj.active_material
        if material is not None:
            layout.label(text="Active: " + material.name)
            row = layout.row(align=True)
            for remap, label in ((0, "Plain"), (1, "Remap 1"), (2, "Remap 2"), (3, "Remap 3")):
                op = row.operator(
                    "rct_graphics.set_material_remap",
                    text=label,
                    depress=materials.get_remap(material) == remap,
                )
                op.remap = remap


def _tree_param_active(settings, name):
    """Whether a tree setting has an effect with the current choices."""
    style = settings.canopy_style
    blobs = style not in ("TOPIARY", "NEEDLES", "HAIR", "NONE")
    needles = style == "NEEDLES"
    hair = style == "HAIR"
    hair_children = hair and settings.hair_children > 0
    # Hair from clumps places them as the Blobs style does.
    clumps = blobs or (hair and settings.hair_source == "CLUMPS")
    noisy = style not in ("NEEDLES", "HAIR", "NONE")
    conditions = {
        "large_width": settings.size == "LARGE",
        "large_length": settings.size == "LARGE",
        "bend_frequency": settings.straightness < 1.0,
        "fork_height": settings.fork_count > 1,
        "fork_angle": settings.fork_count > 1,
        "whorl_size": settings.branch_spread == "WHORLED",
        "sub_branch_length": settings.sub_branches > 0,
        "canopy_shape": style != "NONE",
        "clump_size": clumps,
        "clump_size_variation": clumps,
        "clump_count": style in ("BLOBS", "LAYERS", "STRANDS") or (clumps and hair),
        "clumps_per_tip": style in ("BLOBS", "LAYERS", "COLUMN", "STRANDS") or (clumps and hair),
        "clump_flatten": clumps,
        "blob_merge": blobs,
        "droop": clumps,
        "hollow": (clumps and style != "COLUMN") or needles or (hair and settings.hair_source == "BRANCHES"),
        "needle_length": needles,
        "needle_width": needles,
        "needle_spacing": needles,
        "needle_angle": needles,
        "needle_droop": needles,
        "needle_rows": needles,
        "hair_source": hair,
        "hair_count": hair,
        "hair_length": hair,
        "hair_length_variation": hair,
        "hair_spread": hair,
        "hair_flatten": hair and settings.hair_source == "BRANCHES",
        "hair_droop": hair,
        "hair_width": hair,
        "hair_tip_width": hair,
        "hair_shadows": hair,
        "hair_children": hair,
        "hair_child_radius": hair_children,
        "hair_clump": hair_children,
        "hair_roughness": hair_children,
        "lumpiness": noisy,
        "lump_scale": noisy or (settings.accent_mode == "TOP_FACING" and not hair),
        "raggedness": noisy,
        "resolution": noisy,
        "accent_amount": settings.accent_mode == "DOTS" or (settings.accent_mode == "TOP_FACING" and not hair),
        "accent_size": settings.accent_mode == "DOTS",
        "accent_threshold": settings.accent_mode == "TOP_FACING" and not hair,
        "base_radius": settings.base_style != "NONE",
        "base_height": settings.base_style != "NONE",
    }
    return conditions.get(name, True)


class RCT_PT_tree(bpy.types.Panel):
    bl_label = "Tree Generator"
    bl_idname = "RCT_PT_tree"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RCT"
    bl_parent_id = "RCT_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row(align=True)
        row.prop(scene, "rct_tree_preset", text="")
        row.operator("rct_graphics.tree_add", icon="ADD")

        obj = tree_generator.active_tree(context)
        if obj is None:
            layout.label(text="Select a generated tree to edit it", icon="INFO")
            return
        settings = obj.rct_tree
        props = scene.rct_graphics

        row = layout.row(align=True)
        row.prop(settings, "seed")
        row.operator("rct_graphics.tree_randomize", text="", icon="FILE_REFRESH")
        row = layout.row(align=True)
        row.prop(settings, "auto_update")
        row.operator("rct_graphics.tree_regenerate", icon="MOD_BUILD")

        for title, params in tree.GROUPS:
            header, body = layout.panel("rct_tree_" + title.lower().replace(" ", "_"), default_closed=True)
            header.label(text=title)
            if body is None:
                continue
            body.use_property_split = True
            body.use_property_decorate = False
            for param in params:
                col = body.column()
                col.active = _tree_param_active(settings, param.name)
                if param.name == "height":
                    col.prop(settings, "height_display")
                    col.prop(settings, "height_unit")
                else:
                    col.prop(settings, param.name)

        header, body = layout.panel("rct_tree_materials", default_closed=False)
        header.label(text="Materials")
        if body is not None:
            for key, role in zip(tree_generator.ROLE_KEYS, tree.ROLES):
                col = body.column(align=True)
                col.prop(settings, "material_" + key, text=role)
                sub = col.row()
                sub.active = getattr(settings, "material_" + key) is not None
                sub.prop(settings, "colour_" + key, text="Colour")
            body.operator("rct_graphics.tree_make_unique", icon="DUPLICATE")

        box = layout.box()
        clearance = alignment.clearance_from_height(settings.stat_top) / alignment.CLEARANCE_UNIT
        fits = "fits footprint" if settings.stat_fits else "wider than footprint"
        counts = "{:,} faces".format(settings.stat_faces)
        if settings.canopy_style == "HAIR":
            counts += " · {:,} strands".format(settings.stat_strands)
        box.label(
            text="{} · {:g} clearance units · {}".format(counts, clearance, fits).replace(",", " "),
            icon="CHECKMARK" if settings.stat_fits else "INFO",
        )
        for line in filter(None, settings.warnings.split("\n")):
            box.label(text=line, icon="INFO" if line.startswith(tree.NOTE) else "ERROR")
        if not tree_generator.matches_scene(settings, props):
            row = box.row()
            row.label(text="Scene is not " + tree_generator.size_description(settings), icon="ERROR")
            row.operator("rct_graphics.tree_match_scene")
        if tree_generator.look_differs(settings, props):
            box.operator("rct_graphics.tree_use_look", icon="SHADING_RENDERED")
        box.label(text="Regenerating replaces manual mesh edits", icon="INFO")

        row = layout.row(align=True)
        row.operator("rct_graphics.tree_load_preset", icon="PRESET")
        row.operator("rct_graphics.tree_apply", icon="FREEZE")


class RCT_PT_object(bpy.types.Panel):
    bl_label = "Object Export"
    bl_idname = "RCT_PT_object"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RCT"
    bl_parent_id = "RCT_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def draw(self, context):
        layout = self.layout
        props = context.scene.rct_graphics
        layout.prop(props, "object_id")
        layout.prop(props, "object_name")
        layout.prop(props, "object_authors")
        row = layout.row(align=True)
        row.prop(props, "price")
        if props.object_type != "WALL":
            row.prop(props, "removal_price")
        layout.prop(props, "scenery_group")
        if props.object_type == "SMALL" and props.animation_frames > 1:
            layout.prop(props, "animation_delay")

        col = layout.column()
        col.label(text="Flags:")
        forced = SMALL_SCENERY_SHAPES[props.small_shape]["flags"] if props.object_type == "SMALL" else {}
        grid = col.grid_flow(columns=2, even_columns=True)
        for key, _, _, _ in OBJECT_FLAGS[props.object_type]:
            cell = grid.row()
            # Flags implied by the shape are always written.
            cell.enabled = key not in forced
            cell.prop(props, flag_property(props.object_type, key))
        layout.prop(props, "build_parkobj")
        layout.prop(props, "copy_to_openrct2")
        layout.operator("rct_graphics.export_parkobj", icon="PACKAGE")


class RCT_PT_alignment(bpy.types.Panel):
    bl_label = "Alignment"
    bl_idname = "RCT_PT_alignment"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RCT"
    bl_parent_id = "RCT_PT_main"

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def draw(self, context):
        layout = self.layout
        props = context.scene.rct_graphics
        row = layout.row(align=True)
        row.operator("rct_graphics.snap_to_grid", icon="SNAP_GRID")
        row.operator("rct_graphics.check_alignment", icon="VIEWZOOM")
        layout.prop(props, "check_after_render")
        if props.alignment_report:
            box = layout.box()
            for line in props.alignment_report.split("\n"):
                icon = "ERROR" if line.startswith("FIX") else "CHECKMARK" if line.startswith("OK") else "INFO"
                box.label(text=line[4:] if line[:4] in ("FIX ", "OK  ") else line, icon=icon)


classes = (RCT_PT_main, RCT_PT_materials, RCT_PT_tree, RCT_PT_alignment, RCT_PT_object)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
