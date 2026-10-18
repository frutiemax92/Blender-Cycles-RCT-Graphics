"""Recolourable (remap) materials.

A material becomes recolourable by writing 1 into the AOV of its remap
(``rct_remap_1`` to ``rct_remap_3``). Pixels showing it are quantized into the matching remap
ramp of the palette, by brightness only, so the material's own colour does
not matter; the add-on gives new remap materials the ramp's own colour to
make the viewport preview meaningful.
"""

import bpy
from bpy.props import IntProperty

from .core import palette
from .render import REMAP_AOVS

AOV_NODE_NAME = "RCT Remap AOV"

REMAP_NAMES = {1: "Primary", 2: "Secondary", 3: "Tertiary"}


def _srgb_to_linear(value):
    value /= 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def remap_preview_colour(remap):
    """Linear RGBA of the middle shade of the remap ramp."""
    index = list(palette.REMAP_RANGES[remap])[7]
    r, g, b = (_srgb_to_linear(float(c)) for c in palette.PALETTE[index])
    return (r, g, b, 1.0)


def get_remap(material):
    """Remap number of ``material`` (0 when not recolourable)."""
    if material is None or material.node_tree is None:
        return 0
    node = material.node_tree.nodes.get(AOV_NODE_NAME)
    if node is None:
        return 0
    for remap, name in REMAP_AOVS.items():
        if node.aov_name == name:
            return remap
    return 0


def _ensure_node_tree(material):
    # Blender 5 always gives materials a node tree; older versions need use_nodes.
    if material.node_tree is None:
        material.use_nodes = True


def set_remap(material, remap):
    """Make ``material`` recolourable with ``remap`` (1-3), or plain with 0."""
    _ensure_node_tree(material)
    nodes = material.node_tree.nodes
    node = nodes.get(AOV_NODE_NAME)
    if remap == 0:
        if node is not None:
            nodes.remove(node)
        return
    if node is None:
        node = nodes.new("ShaderNodeOutputAOV")
        node.name = AOV_NODE_NAME
        node.label = AOV_NODE_NAME
        output = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        if output is not None:
            node.location = (output.location.x, output.location.y - 160)
    node.aov_name = REMAP_AOVS[remap]
    node.inputs["Value"].default_value = 1.0


def new_remap_material(remap):
    name = "RCT Remap {} ({})".format(remap, REMAP_NAMES[remap])
    material = bpy.data.materials.new(name)
    _ensure_node_tree(material)
    bsdf = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    colour = remap_preview_colour(remap)
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = colour
        bsdf.inputs["Roughness"].default_value = 0.8
    material.diffuse_color = colour
    set_remap(material, remap)
    return material


class RCT_OT_set_material_remap(bpy.types.Operator):
    """Make the active material recolourable in game (or plain again with 0)"""

    bl_idname = "rct_graphics.set_material_remap"
    bl_label = "Set Remap"
    bl_options = {"REGISTER", "UNDO"}

    remap: IntProperty(name="Remap", min=0, max=3)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.active_material is not None

    def execute(self, context):
        set_remap(context.active_object.active_material, self.remap)
        return {"FINISHED"}


class RCT_OT_add_remap_material(bpy.types.Operator):
    """Add a new recolourable material to the active object"""

    bl_idname = "rct_graphics.add_remap_material"
    bl_label = "Add Remap Material"
    bl_options = {"REGISTER", "UNDO"}

    remap: IntProperty(name="Remap", min=1, max=3, default=1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and hasattr(obj.data, "materials")

    def execute(self, context):
        obj = context.active_object
        obj.data.materials.append(new_remap_material(self.remap))
        obj.active_material_index = len(obj.material_slots) - 1
        return {"FINISHED"}


classes = (RCT_OT_set_material_remap, RCT_OT_add_remap_material)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
