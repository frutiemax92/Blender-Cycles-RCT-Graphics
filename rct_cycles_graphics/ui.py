import bpy

from . import materials, scene_setup
from .core.jobs import SMALL_SCENERY_SHAPES
from .core.objectjson import OBJECT_FLAGS
from .core.palette import RAMP_TITLES
from .properties import flag_property


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

        layout.operator("rct_graphics.render", icon="RENDER_STILL")


class RCT_PT_render_settings(bpy.types.Panel):
    bl_label = "Render & Colour"
    bl_idname = "RCT_PT_render_settings"
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
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(heading="Cycles")
        col.prop(props, "samples")
        col.prop(props, "supersampling")
        sub = col.column()
        sub.active = props.supersampling == "1"
        sub.prop(props, "filter_width")
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


classes = (RCT_PT_main, RCT_PT_materials, RCT_PT_alignment, RCT_PT_object, RCT_PT_render_settings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
