"""RCT Cycles Graphics: render OpenRCT2 object sprites with Cycles.

Successor of the Blender 2.79 "RCT Graphics Helper" add-on, rebuilt for
modern Blender. All post-processing (palette quantization, dithering,
outlines, trimming) runs in Python with numpy; no ImageMagick required.
"""

bl_info = {
    "name": "RCT Cycles Graphics",
    "description": "Render OpenRCT2 object sprites with Cycles",
    "author": "frutiemax92",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > RCT",
    "category": "Render",
}

import importlib

_module_names = ("properties", "operators", "ui")

_modules = []


def _load_modules():
    global _modules
    package = __name__
    loaded = []
    for name in _module_names:
        loaded.append(importlib.import_module("." + name, package))
    _modules = loaded


def register():
    _load_modules()
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
