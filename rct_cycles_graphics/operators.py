import bpy

from . import scene_setup


class RCT_OT_initialize(bpy.types.Operator):
    """Create the RCT camera/light rig and configure Cycles for sprite rendering"""

    bl_idname = "rct_graphics.initialize"
    bl_label = "Initialize / Repair Scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene_setup.initialize(context.scene)
        self.report({"INFO"}, "RCT rig created")
        return {"FINISHED"}


classes = (RCT_OT_initialize,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
