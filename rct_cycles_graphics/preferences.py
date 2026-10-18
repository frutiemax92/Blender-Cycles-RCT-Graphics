import os

import bpy
from bpy.props import StringProperty

from .core import g1


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
    rct2_directory: StringProperty(
        name="RCT2 Folder",
        description=(
            "RollerCoaster Tycoon 2 install, whose Data/g1.dat holds the grass used by "
            "Preview on Grass. Leave empty to use the game_path from OpenRCT2's config.ini"
        ),
        subtype="DIR_PATH",
        default="",
    )

    def draw(self, context):
        self.layout.prop(self, "openrct2_directory")
        self.layout.prop(self, "rct2_directory")


def get(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def openrct2_object_directory(context):
    prefs = get(context)
    if prefs is None or not prefs.openrct2_directory:
        return None
    return os.path.join(bpy.path.abspath(prefs.openrct2_directory), "object")


def g1_path(context):
    """RCT2's g1.dat: the RCT2 folder setting, else the folder OpenRCT2 uses."""
    prefs = get(context)
    if prefs is not None and prefs.rct2_directory:
        return g1.find_g1(bpy.path.abspath(prefs.rct2_directory))
    candidates = g1.default_openrct2_directories()
    if prefs is not None and prefs.openrct2_directory:
        candidates.insert(0, bpy.path.abspath(prefs.openrct2_directory))
    for directory in candidates:
        path = g1.find_g1(g1.openrct2_game_path(directory))
        if path is not None:
            return path
    return None


classes = (RCTGraphicsPreferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
