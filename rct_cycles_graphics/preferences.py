import os

import bpy
from bpy.props import StringProperty


class RCTGraphicsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    openrct2_directory: StringProperty(
        name="OpenRCT2 User Folder",
        description=(
            "Folder holding OpenRCT2's 'object' directory (for example "
            "~/.config/OpenRCT2 on Linux or Documents/OpenRCT2 on Windows)"
        ),
        subtype="DIR_PATH",
        default="",
    )

    def draw(self, context):
        self.layout.prop(self, "openrct2_directory")


def get(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def openrct2_object_directory(context):
    prefs = get(context)
    if prefs is None or not prefs.openrct2_directory:
        return None
    return os.path.join(bpy.path.abspath(prefs.openrct2_directory), "object")


classes = (RCTGraphicsPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
