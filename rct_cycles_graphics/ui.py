import bpy

from . import scene_setup


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

        col = layout.column(heading="Palette")
        col.prop(props, "dither_method")
        sub = col.column()
        sub.active = props.dither_method != "NONE"
        sub.prop(props, "dither_strength")


classes = (RCT_PT_main, RCT_PT_render_settings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
