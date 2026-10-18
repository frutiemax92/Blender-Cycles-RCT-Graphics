import bpy

from . import materials, scene_setup


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
            box.prop(props, "small_anchor")

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
        col.prop(props, "filter_width")
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


classes = (RCT_PT_main, RCT_PT_materials, RCT_PT_render_settings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
