"""Procedural trees: per-object settings, mesh building, materials and operators.

The geometry comes from ``core/tree.py``. This module turns it into one mesh
object with four material slots (trunk, leaves, accent, base), merges canopy
blobs with a temporary metaball, and keeps the scene's object type in step
with the tree's footprint. The hair canopy style adds a child object whose
hidden emitter mesh grows the strands as particle hair; the leaf instance
style copies a leaf mesh (built in, or the user's Leaf Object) into the tree.
"""

import math
import time
from contextlib import contextmanager
from itertools import chain

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Vector

from . import materials, scene_setup
from .core import projection, tree
from .properties import flag_property

TREE_NAME = "RCT Tree"
HAIR_NAME = "RCT Tree Hair"
#: Vertex group scaling each strand's length.
HAIR_LENGTH_GROUP = "Length"
#: Hair segments; from 5 on, the length vertex group scales strands linearly.
HAIR_STEPS = 5
#: Point attribute of leaf instances: (root-to-tip position, random value per leaf, 1).
LEAF_ATTRIBUTE = "rct_leaf"
#: Base name of the temporary metaball. Metaballs sharing a base name fuse,
#: so it must not match anything a user would create.
METABALL_NAME = "RCT_TreeCanopyTemp"
ROLE_KEYS = ("trunk", "leaves", "accent", "base")
#: Auto update skips regenerations closer together than this (seconds).
THROTTLE = 0.05

HEIGHT_UNITS = (
    ("BU", "BU", "Blender units", 0),
    ("CLEARANCE", "Clearance", "Clearance units of 8 game z units (about 0.816 BU)", 1),
    ("LAND_STEPS", "Land Steps", "Land height steps of 16 game z units (about 1.633 BU)", 2),
)
_UNIT_SIZE = {"BU": 1.0, "CLEARANCE": projection.HEIGHT_STEP / 2.0, "LAND_STEPS": projection.HEIGHT_STEP}

REMAP_ITEMS = (
    ("0", "Plain", "Quantized to the normal palette", 0),
    ("1", "Remap 1 (Primary)", "Recoloured in game with the primary colour", 1),
    ("2", "Remap 2 (Secondary)", "Recoloured in game with the secondary colour", 2),
    ("3", "Remap 3 (Tertiary)", "Recoloured in game with the tertiary colour", 3),
)
REMAP_NOTE = (
    "Remap pixels are quantized by brightness only, so hue variation is lost; "
    "a remap's colours are also excluded from plain pixels"
)

SIZE_DESCRIPTIONS = {
    "FULL": "Small Scenery, Full Tile",
    "FULL_CENTRED": "Small Scenery, Full Tile Centred",
    "QUARTER": "Small Scenery, Quarter Tile",
}

_suspended = 0
_last_finished = 0.0
_pending = set()


@contextmanager
def suspended_updates():
    """Set several settings without regenerating after each one."""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


# Settings <-> core parameters -------------------------------------------------


def to_params(settings):
    values = {}
    for param in tree.PARAMETERS:
        value = getattr(settings, param.name)
        values[param.name] = math.degrees(value) if param.unit == "deg" else value
    return tree.make_params(**values)


#: Footprint and seed survive loading a preset.
_KEPT_ON_PRESET = {"size", "large_width", "large_length", "seed"}


def apply_preset(settings, name):
    values = tree.PRESETS[name]["params"]
    with suspended_updates():
        for param in tree.PARAMETERS:
            if param.name in _KEPT_ON_PRESET:
                continue
            value = values.get(param.name, param.default)
            setattr(settings, param.name, math.radians(value) if param.unit == "deg" else value)
        settings.preset = name


# Scene coupling ------------------------------------------------------------------


def size_description(settings):
    if settings.size == "LARGE":
        return "Large Scenery, {} x {} Tiles".format(settings.large_width, settings.large_length)
    return SIZE_DESCRIPTIONS[settings.size]


def matches_scene(settings, props):
    if settings.size == "LARGE":
        return (
            props.object_type == "LARGE"
            and props.tiles_width == settings.large_width
            and props.tiles_length == settings.large_length
        )
    return props.object_type == "SMALL" and props.small_shape == settings.size


def write_scene(settings, props):
    """Set the scene's object type and footprint from the tree; returns a status message."""
    if settings.size == "LARGE":
        props.tiles_width = settings.large_width
        props.tiles_length = settings.large_length
        props.object_type = "LARGE"
        setattr(props, flag_property("LARGE", "isTree"), True)
    else:
        props.object_type = "SMALL"
        props.small_shape = settings.size
        setattr(props, flag_property("SMALL", "isTree"), True)
    return "Object type set to " + size_description(settings)


def size_from_scene(settings, props):
    if props.object_type == "LARGE":
        settings.size = "LARGE"
        settings.large_width = props.tiles_width
        settings.large_length = props.tiles_length
    elif props.small_shape in ("QUARTER", "FULL_CENTRED"):
        settings.size = props.small_shape
    else:
        settings.size = "FULL"


def look_differs(settings, props):
    preset = tree.PRESETS.get(settings.preset)
    if preset is None:
        return False
    return any(_look_value(getattr(props, key)) != value for key, value in preset["look"].items())


def _look_value(value):
    # Vector properties (the palette ramps) compare as tuples.
    return tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


# Materials -------------------------------------------------------------------------


def _colour_key(role, params):
    if role == tree.ACCENT:
        return "snow" if params.accent_mode == "TOP_FACING" else "dots"
    return ROLE_KEYS[role]


def role_used(role, params):
    if role == tree.ACCENT:
        return params.accent_mode != "NONE"
    if role == tree.BASE:
        return params.base_style != "NONE"
    return True


def _link(group, from_node, from_socket, to_node, to_socket):
    group.links.new(from_node.outputs[from_socket], to_node.inputs[to_socket])


def _math(group, operation, location, a=None, b=None, clamp=False):
    node = group.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.use_clamp = clamp
    node.location = location
    if a is not None:
        node.inputs[0].default_value = a
    if b is not None:
        node.inputs[1].default_value = b
    return node


def _map_range(group, location, from_min, from_max, to_min=0.0, to_max=1.0):
    node = group.nodes.new("ShaderNodeMapRange")
    node.location = location
    node.clamp = True
    node.inputs["From Min"].default_value = from_min
    node.inputs["From Max"].default_value = from_max
    node.inputs["To Min"].default_value = to_min
    node.inputs["To Max"].default_value = to_max
    return node


def _mix_colours(group, location):
    node = group.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.location = location
    return node


def _colour_socket(sockets, name, kind="RGBA"):
    # A Mix node has float, vector and colour sockets of the same name.
    return next(s for s in sockets if s.name == name and s.type == kind)


#: Bumped when the role groups change; older groups in a file are replaced.
ROLE_GROUP_VERSION = 3


def role_group(role):
    """Shared node group of a role, exposing Colour A/B, Speckle Scale and Bump Strength."""
    name = "{} {}".format(TREE_NAME, tree.ROLES[role])
    old = bpy.data.node_groups.get(name)
    if old is not None and (old.library is not None or old.get("rct_version", 1) >= ROLE_GROUP_VERSION):
        return old
    group = _build_role_group(name, role)
    if old is not None:
        old.user_remap(group)
        bpy.data.node_groups.remove(old)
        group.name = name
    group["rct_version"] = ROLE_GROUP_VERSION
    return group


def _build_role_group(name, role):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    interface = group.interface
    interface.new_socket("Colour A", in_out="INPUT", socket_type="NodeSocketColor")
    interface.new_socket("Colour B", in_out="INPUT", socket_type="NodeSocketColor")
    interface.new_socket("Speckle Scale", in_out="INPUT", socket_type="NodeSocketFloat")
    interface.new_socket("Bump Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    interface.new_socket("Normal", in_out="OUTPUT", socket_type="NodeSocketVector")

    nodes = group.nodes
    inputs = nodes.new("NodeGroupInput")
    inputs.location = (-900, 0)
    outputs = nodes.new("NodeGroupOutput")
    outputs.location = (500, 0)
    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = (-900, 300)
    bump = nodes.new("ShaderNodeBump")
    bump.location = (250, -200)
    _link(group, inputs, "Bump Strength", bump, "Strength")
    _link(group, bump, "Normal", outputs, "Normal")
    mix = _mix_colours(group, (50, 100))
    mix_a, mix_b = _colour_socket(mix.inputs, "A"), _colour_socket(mix.inputs, "B")
    mix_result = _colour_socket(mix.outputs, "Result")
    # Factor 0 shows Colour A, except on the trunk where Colour B is the base.
    first, second = ("Colour B", "Colour A") if role == tree.TRUNK else ("Colour A", "Colour B")
    group.links.new(inputs.outputs[first], mix_a)
    group.links.new(inputs.outputs[second], mix_b)

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-450, 0)
    noise.inputs["Detail"].default_value = 3.0

    if role == tree.LEAVES:
        # Leaf clusters: Voronoi cells about two pixels wide, broken up by noise.
        voronoi = nodes.new("ShaderNodeTexVoronoi")
        voronoi.location = (-450, 300)
        _link(group, coords, "Object", voronoi, "Vector")
        _link(group, inputs, "Speckle Scale", voronoi, "Scale")
        _link(group, coords, "Object", noise, "Vector")
        scale = _math(group, "MULTIPLY", (-650, -50), b=0.35)
        _link(group, inputs, "Speckle Scale", scale, 0)
        _link(group, scale, 0, noise, "Scale")
        combined = _math(group, "MULTIPLY_ADD", (-250, 150))
        _link(group, noise, "Fac", combined, 0)
        combined.inputs[1].default_value = 0.6
        _link(group, voronoi, "Distance", combined, 2)
        factor = _map_range(group, (-80, 150), 0.35, 1.15)
        _link(group, combined, 0, factor, "Value")
        _link(group, voronoi, "Distance", bump, "Height")
        group.links.new(mix_result, outputs.inputs["Color"])
        # Hair strands and leaf instances: Colour A at the root to Colour B
        # at the tip, each strand or leaf a little lighter or darker, and no
        # speckle or bump, so every strand or leaf reads as one stroke.
        hair = nodes.new("ShaderNodeHairInfo")
        hair.location = (-650, 550)
        brightness = _math(group, "MULTIPLY_ADD", (-450, 550), b=0.8)
        brightness.inputs[2].default_value = 0.4
        _link(group, hair, "Random", brightness, 0)
        strand = _math(group, "MULTIPLY", (-250, 500), clamp=True)
        _link(group, hair, "Intercept", strand, 0)
        _link(group, brightness, 0, strand, 1)
        pick = nodes.new("ShaderNodeMix")
        pick.data_type = "FLOAT"
        pick.location = (-80, 400)
        _link(group, hair, "Is Strand", pick, "Factor")
        # Leaf instances: the same per-leaf brightness, lighter towards the tip.
        attribute = nodes.new("ShaderNodeAttribute")
        attribute.attribute_name = LEAF_ATTRIBUTE
        attribute.location = (-900, 850)
        leaf = nodes.new("ShaderNodeSeparateXYZ")
        leaf.location = (-650, 850)
        _link(group, attribute, "Vector", leaf, "Vector")
        leaf_brightness = _math(group, "MULTIPLY_ADD", (-450, 900), b=0.8)
        leaf_brightness.inputs[2].default_value = 0.4
        _link(group, leaf, "Y", leaf_brightness, 0)
        leaf_along = _math(group, "MULTIPLY_ADD", (-450, 750), b=0.65)
        leaf_along.inputs[2].default_value = 0.35
        _link(group, leaf, "X", leaf_along, 0)
        leaf_value = _math(group, "MULTIPLY", (-250, 800), clamp=True)
        _link(group, leaf_along, 0, leaf_value, 0)
        _link(group, leaf_brightness, 0, leaf_value, 1)
        leaf_pick = nodes.new("ShaderNodeMix")
        leaf_pick.data_type = "FLOAT"
        leaf_pick.location = (-250, 300)
        _link(group, leaf, "Z", leaf_pick, "Factor")
        group.links.new(factor.outputs["Result"], _colour_socket(leaf_pick.inputs, "A", "VALUE"))
        group.links.new(leaf_value.outputs[0], _colour_socket(leaf_pick.inputs, "B", "VALUE"))
        group.links.new(_colour_socket(leaf_pick.outputs, "Result", "VALUE"), _colour_socket(pick.inputs, "A", "VALUE"))
        group.links.new(strand.outputs[0], _colour_socket(pick.inputs, "B", "VALUE"))
        group.links.new(_colour_socket(pick.outputs, "Result", "VALUE"), mix.inputs["Factor"])
        # Bump only on canopy surfaces, not on strands or leaves.
        shaped = _math(group, "MAXIMUM", (-250, -300))
        _link(group, hair, "Is Strand", shaped, 0)
        _link(group, leaf, "Z", shaped, 1)
        surface = _math(group, "SUBTRACT", (-80, -300), a=1.0)
        _link(group, shaped, 0, surface, 1)
        strength = _math(group, "MULTIPLY", (80, -300))
        _link(group, inputs, "Bump Strength", strength, 0)
        _link(group, surface, 0, strength, 1)
        _link(group, strength, 0, bump, "Strength")
    elif role == tree.TRUNK:
        # Colour B at the base fading to Colour A, with bark streaks along Z.
        separate = nodes.new("ShaderNodeSeparateXYZ")
        separate.location = (-650, 300)
        _link(group, coords, "Object", separate, "Vector")
        gradient = _map_range(group, (-450, 300), 0.0, 1.2)
        _link(group, separate, "Z", gradient, "Value")
        _link(group, gradient, "Result", mix, "Factor")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-650, 0)
        _link(group, coords, "Object", mapping, "Vector")
        mapping.inputs["Scale"].default_value = (1.0, 1.0, 0.12)
        _link(group, mapping, "Vector", noise, "Vector")
        _link(group, inputs, "Speckle Scale", noise, "Scale")
        value = _map_range(group, (-250, -100), 0.3, 0.7, 0.7, 1.2)
        _link(group, noise, "Fac", value, "Value")
        hsv = nodes.new("ShaderNodeHueSaturation")
        hsv.location = (250, 100)
        group.links.new(mix_result, hsv.inputs["Color"])
        _link(group, value, "Result", hsv, "Value")
        _link(group, noise, "Fac", bump, "Height")
        _link(group, hsv, "Color", outputs, "Color")
    else:
        # Accent and base: Colour A/B mixed by noise.
        _link(group, coords, "Object", noise, "Vector")
        _link(group, inputs, "Speckle Scale", noise, "Scale")
        factor = _map_range(group, (-250, 100), 0.3, 0.7)
        _link(group, noise, "Fac", factor, "Value")
        _link(group, factor, "Result", mix, "Factor")
        _link(group, noise, "Fac", bump, "Height")
        group.links.new(mix_result, outputs.inputs["Color"])
    return group


#: Speckle Scale, Bump Strength and roughness per role.
_ROLE_DEFAULTS = {
    tree.TRUNK: (4.0, 0.2, 0.85),
    tree.LEAVES: (5.5, 0.4, 0.9),
    tree.ACCENT: (6.0, 0.1, 0.7),
    tree.BASE: (3.0, 0.3, 0.9),
}

GROUP_NODE_NAME = "RCT Tree Group"


def build_material(name, role, colours):
    material = bpy.data.materials.new(name)
    if material.node_tree is None:
        material.use_nodes = True
    nodes = material.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        output = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(bsdf.outputs[0], output.inputs["Surface"])
    scale, bump, roughness = _ROLE_DEFAULTS[role]
    node = nodes.new("ShaderNodeGroup")
    node.name = GROUP_NODE_NAME
    node.node_tree = role_group(role)
    node.location = (bsdf.location.x - 300, bsdf.location.y)
    node.inputs["Colour A"].default_value = colours[0]
    node.inputs["Colour B"].default_value = colours[1]
    node.inputs["Speckle Scale"].default_value = scale
    node.inputs["Bump Strength"].default_value = bump
    material.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    material.node_tree.links.new(node.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = roughness
    material.diffuse_color = tuple((a + b) / 2.0 for a, b in zip(colours[0], colours[1]))
    return material


def default_material(role, params, preset):
    """Shared default material of a role, created on first use."""
    key = _colour_key(role, params)
    colours = tree.preset_colours(preset, key)
    suffix = ""
    if colours != tree.DEFAULT_COLOURS[key]:
        suffix = " ({})".format(tree.PRESETS[preset]["label"])
    elif key == "snow":
        suffix = " (Snow)"
    name = "{} {}{}".format(TREE_NAME, tree.ROLES[role], suffix)
    material = bpy.data.materials.get(name)
    if material is None or material.library is not None:
        material = build_material(name, role, colours)
    return material


def role_material(settings, role):
    return getattr(settings, "material_" + ROLE_KEYS[role])


def _sync_from_slots(obj):
    """Adopt materials the user put straight into the tree's slots."""
    settings = obj.rct_tree
    for role, slot in enumerate(obj.material_slots[: len(ROLE_KEYS)]):
        if slot.material is not None and slot.material != role_material(settings, role):
            with suspended_updates():
                setattr(settings, "material_" + ROLE_KEYS[role], slot.material)


def assign_slots(obj):
    """Put the role materials into the object's four slots."""
    if obj.type != "MESH":
        return
    mesh = obj.data
    while len(mesh.materials) < len(ROLE_KEYS):
        mesh.materials.append(None)
    for role in range(len(ROLE_KEYS)):
        material = role_material(obj.rct_tree, role)
        if mesh.materials[role] != material:
            mesh.materials[role] = material
    _assign_hair_material(obj.rct_tree)


def _assign_hair_material(settings):
    hair = settings.hair_object
    if hair is None or hair.type != "MESH":
        return
    materials_ = hair.data.materials
    leaves = role_material(settings, tree.LEAVES)
    if len(materials_) == 0:
        materials_.append(leaves)
    elif materials_[0] != leaves:
        materials_[0] = leaves


def make_unique(settings):
    copies = 0
    with suspended_updates():
        for key in ROLE_KEYS:
            material = getattr(settings, "material_" + key)
            if material is not None and material.users > 1:
                setattr(settings, "material_" + key, material.copy())
                copies += 1
    return copies


# Mesh building --------------------------------------------------------------------


def polygonize(blobs, params):
    """Merge blobs into one surface with a temporary metaball: (verts, faces)."""
    threshold, stiffness, factor = tree.metaball_settings(params.blob_merge)
    metaball = bpy.data.metaballs.new(METABALL_NAME)
    resolution = max(params.resolution, tree.MIN_RESOLUTION)
    metaball.resolution = resolution
    metaball.render_resolution = resolution
    metaball.threshold = threshold
    for x, y, z, radius, stretch, flatten, yaw in blobs:
        round_blob = abs(stretch - 1.0) < 1e-6 and abs(flatten - 1.0) < 1e-6
        element = metaball.elements.new(type="BALL" if round_blob else "ELLIPSOID")
        element.co = (x, y, z)
        element.radius = radius * factor
        element.stiffness = stiffness
        if not round_blob:
            element.size_x, element.size_y, element.size_z = stretch, 1.0, flatten
            element.rotation = (math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0))
    obj = bpy.data.objects.new(METABALL_NAME, metaball)
    scene = bpy.context.scene
    scene.collection.objects.link(obj)
    mesh = None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
        verts = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", verts)
        loops = np.empty(len(mesh.loops), dtype=np.int64)
        mesh.loops.foreach_get("vertex_index", loops)
        starts = np.empty(len(mesh.polygons), dtype=np.int64)
        totals = np.empty(len(mesh.polygons), dtype=np.int64)
        mesh.polygons.foreach_get("loop_start", starts)
        mesh.polygons.foreach_get("loop_total", totals)
        faces = [tuple(loops[s : s + t].tolist()) for s, t in zip(starts.tolist(), totals.tolist())]
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.metaballs.remove(metaball)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
    return verts.reshape(-1, 3), faces


def write_mesh(name, data):
    """Blender mesh from core MeshData, with roles, smooth flags and UVs."""
    mesh = bpy.data.meshes.new(name)
    faces = data.faces
    if not faces:
        return mesh
    totals = np.fromiter((len(f) for f in faces), dtype=np.int64, count=len(faces))
    starts = np.concatenate([[0], np.cumsum(totals)[:-1]])
    loops = np.fromiter(chain.from_iterable(faces), dtype=np.int64, count=int(totals.sum()))
    mesh.vertices.add(len(data.verts))
    mesh.vertices.foreach_set("co", data.verts.astype(np.float32).ravel())
    mesh.loops.add(len(loops))
    mesh.loops.foreach_set("vertex_index", loops.astype(np.int32))
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", starts.astype(np.int32))
    mesh.polygons.foreach_set("material_index", np.array(data.material, dtype=np.int32))
    mesh.polygons.foreach_set("use_smooth", np.array(data.smooth, dtype=bool))
    uv_layer = mesh.uv_layers.new(name="UVMap")
    uvs = np.fromiter(chain.from_iterable(chain.from_iterable(data.uvs)), dtype=np.float32, count=2 * len(loops))
    uv_layer.data.foreach_set("uv", uvs)
    if data.leaf is not None:
        attribute = mesh.attributes.new(LEAF_ATTRIBUTE, "FLOAT_VECTOR", "POINT")
        attribute.data.foreach_set("vector", data.leaf.astype(np.float32).ravel())
    mesh.update(calc_edges=True)
    mesh.validate(clean_customdata=False)
    return mesh


# Hair --------------------------------------------------------------------------------


def remove_hair(settings):
    """Delete the tree's hair object with its mesh and particle settings."""
    hair = settings.hair_object
    if hair is None:
        return
    settings.hair_object = None
    mesh = hair.data
    particle_settings = [m.particle_system.settings for m in hair.modifiers if m.type == "PARTICLE_SYSTEM"]
    bpy.data.objects.remove(hair, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    for item in particle_settings:
        if item is not None and item.users == 0:
            bpy.data.particles.remove(item)


def _hair_object(obj):
    """The tree's hair object, created (or re-linked) when missing."""
    settings = obj.rct_tree
    hair = settings.hair_object
    if hair is not None and hair.parent != obj:
        # Shared with the tree this one was duplicated from: leave it to that tree.
        hair = None
    if hair is None:
        hair = bpy.data.objects.new(HAIR_NAME, bpy.data.meshes.new(HAIR_NAME))
        hair.parent = obj
        # Clicks select the tree; the emitter triangles never render.
        hair.hide_select = True
        hair.show_instancer_for_render = False
        hair.show_instancer_for_viewport = False
        modifier = hair.modifiers.new("Hair", "PARTICLE_SYSTEM")
        modifier.particle_system.settings.name = HAIR_NAME
        settings.hair_object = hair
    if not hair.users_collection:
        for collection in obj.users_collection or (bpy.context.scene.collection,):
            collection.objects.link(hair)
    return hair


def _configure_hair(psys, params, strands):
    psys.seed = params.seed
    psys.vertex_group_length = HAIR_LENGTH_GROUP
    hair = psys.settings
    hair.type = "HAIR"
    hair.use_advanced_hair = False
    # One strand per emitter triangle, along its normal.
    hair.count = len(strands)
    hair.emit_from = "FACE"
    hair.distribution = "JIT"
    hair.use_emit_random = False
    hair.use_even_distribution = True
    hair.tangent_factor = 0.0
    hair.object_align_factor = (0.0, 0.0, 0.0)
    hair.factor_random = 0.0
    hair.normal_factor = 1.0
    # Hair length rescales the normal factor, so it comes after it.
    hair.hair_length = float(strands.lengths.max())
    hair.hair_step = HAIR_STEPS
    hair.display_step = 3
    hair.render_step = 3
    hair.material = 1
    hair.root_radius = 1.0
    hair.tip_radius = params.hair_tip_width
    hair.radius_scale = params.hair_width
    children = params.hair_children
    hair.child_type = "SIMPLE" if children > 0 else "NONE"
    hair.child_percent = children
    hair.rendered_child_count = children
    hair.child_radius = params.hair_child_radius
    hair.clump_factor = params.hair_clump
    hair.roughness_endpoint = params.hair_roughness


def sync_hair(obj, params, strands):
    """Create, update or remove the hair object of the tree ``obj``."""
    settings = obj.rct_tree
    if params.canopy_style != "HAIR" or len(strands) == 0:
        remove_hair(settings)
        return
    hair = _hair_object(obj)
    verts, faces, weights = tree.hair_emitter(strands)
    old = hair.data
    hair.data = write_mesh(HAIR_NAME, tree.MeshData(verts, faces, 0, False))
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    _assign_hair_material(settings)
    group = hair.vertex_groups.get(HAIR_LENGTH_GROUP) or hair.vertex_groups.new(name=HAIR_LENGTH_GROUP)
    # One call per distinct weight; a thousand steps is finer than a pixel.
    levels = np.round(weights * 1000.0).astype(np.int64)
    order = np.argsort(levels, kind="stable")
    values, starts = np.unique(levels[order], return_index=True)
    for value, indices in zip(values.tolist(), np.split(order, starts[1:])):
        group.add(indices.tolist(), value / 1000.0, "REPLACE")
    modifier = next((m for m in hair.modifiers if m.type == "PARTICLE_SYSTEM"), None)
    if modifier is None:
        modifier = hair.modifiers.new("Hair", "PARTICLE_SYSTEM")
    _configure_hair(modifier.particle_system, params, strands)
    hair.visible_shadow = params.hair_shadows


def _leaf_template(settings):
    """(verts, faces) of the Leaf Object's evaluated mesh in its own axes, or None."""
    leaf = settings.leaf_object
    if settings.leaf_shape != "CUSTOM" or leaf is None or leaf.type != "MESH":
        return None
    evaluated = leaf.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        verts = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", verts)
        faces = [tuple(p.vertices) for p in mesh.polygons]
    finally:
        evaluated.to_mesh_clear()
    return verts.reshape(-1, 3), faces


def _footprint_box(settings):
    half = projection.TILE_SIZE / 2.0
    if settings.size == "LARGE":
        return (half - settings.large_width * projection.TILE_SIZE, half - settings.large_length * projection.TILE_SIZE), (half, half)
    if settings.size == "QUARTER":
        return (-half / 2.0, -half / 2.0), (half / 2.0, half / 2.0)
    return (-half, -half), (half, half)


def regenerate(obj):
    """Rebuild the tree mesh of ``obj`` from its settings, keeping its materials."""
    global _last_finished
    settings = obj.rct_tree
    _sync_from_slots(obj)
    params = to_params(settings)
    template = _leaf_template(settings)
    data, mesh_data = tree.build(params, polygonize, template)

    with suspended_updates():
        for role in range(len(ROLE_KEYS)):
            if role_material(settings, role) is None and role_used(role, params):
                setattr(settings, "material_" + ROLE_KEYS[role], default_material(role, params, settings.preset))

    old = obj.data
    obj.data = write_mesh(TREE_NAME, mesh_data)
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    sync_hair(obj, params, data.strands)
    assign_slots(obj)

    warnings = data.warnings()
    faces = len(mesh_data.faces)
    if faces > tree.FACE_WARNING:
        warnings.append("{} faces: lower the resolution or clump count".format(faces))
    if params.canopy_style == "HAIR" and len(data.strands) == 0:
        warnings.append("No hair strands: they need branches inside the footprint")
    if params.canopy_style == "HAIR" and params.accent_mode == "TOP_FACING":
        warnings.append(tree.NOTE + "Top Facing accent has no effect on hair; Dots go on the strand tips")
    if params.canopy_style == "INSTANCES":
        leaf = settings.leaf_object
        if len(data.strands) == 0:
            warnings.append("No leaves: they need branches inside the footprint")
        if params.leaf_shape == "CUSTOM" and (template is None or not template[1]):
            warnings.append("Custom leaf shape needs a Leaf Object with faces; using the blade")
        elif params.leaf_shape == "CUSTOM" and not leaf.hide_render:
            warnings.append(tree.NOTE + "The Leaf Object renders too; hide it from renders")
    settings.stat_faces = faces
    children = params.hair_children if params.canopy_style == "HAIR" else 0
    settings.stat_strands = len(data.strands) * (1 + children)
    verts = mesh_data.verts
    if len(data.strands):
        verts = np.concatenate([verts, data.strands.tips])
    if len(verts):
        settings.stat_top = float(verts[:, 2].max())
        lo, hi = _footprint_box(settings)
        fits = verts[:, 0].min() >= lo[0] - 0.05 and verts[:, 1].min() >= lo[1] - 0.05
        fits = fits and verts[:, 0].max() <= hi[0] + 0.05 and verts[:, 1].max() <= hi[1] + 0.05
        settings.stat_fits = bool(fits)
    settings.warnings = "\n".join(warnings)
    _last_finished = time.perf_counter()


def _run_pending():
    names = list(_pending)
    _pending.clear()
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.rct_tree.enabled:
            regenerate(obj)
    return None


def request_regenerate(obj):
    """Regenerate now, or shortly when the last regeneration was under 50 ms ago."""
    if time.perf_counter() - _last_finished < THROTTLE:
        # The timer runs the last request, so the final slider value wins.
        _pending.add(obj.name)
        if not bpy.app.timers.is_registered(_run_pending):
            bpy.app.timers.register(_run_pending, first_interval=THROTTLE)
        return
    _pending.discard(obj.name)
    regenerate(obj)


def _on_change(self, context):
    if _suspended or not self.enabled or not self.auto_update:
        return
    request_regenerate(self.id_data)


def _on_size_change(self, context):
    if _suspended or not self.enabled:
        return
    obj = self.id_data
    if context.active_object == obj and scene_setup.get_rig(context.scene)[0] is not None:
        write_scene(self, context.scene.rct_graphics)
    if self.auto_update:
        request_regenerate(obj)


def _on_material_change(self, context):
    if _suspended or not self.enabled:
        return
    assign_slots(self.id_data)


def _remap_getter(key):
    def getter(self):
        return materials.get_remap(getattr(self, "material_" + key))

    return getter


def _remap_setter(key):
    def setter(self, value):
        material = getattr(self, "material_" + key)
        if material is None:
            return
        materials.set_remap(material, value)
        if value:
            material.diffuse_color = materials.remap_preview_colour(value)
        else:
            node = material.node_tree.nodes.get(GROUP_NODE_NAME) if material.node_tree else None
            if node is not None:
                material.diffuse_color = tuple(node.inputs["Colour A"].default_value)

    return setter


def _get_height_display(self):
    return self.height / _UNIT_SIZE[self.height_unit]


def _set_height_display(self, value):
    self.height = value * _UNIT_SIZE[self.height_unit]


def _make_property(param):
    update = _on_size_change if param.name in ("size", "large_width", "large_length") else _on_change
    common = dict(name=param.label, description=param.description, update=update)
    if param.kind == "enum":
        return EnumProperty(items=param.items, default=param.default, **common)
    if param.kind == "bool":
        return BoolProperty(default=param.default, **common)
    hard, soft = param.hard, param.soft
    if param.kind == "int":
        return IntProperty(default=param.default, min=hard[0], max=hard[1], soft_min=soft[0], soft_max=soft[1], **common)
    if param.unit == "deg":
        convert = math.radians
        common["subtype"] = "ANGLE"
    else:
        convert = float
        if param.unit == "bu":
            common["subtype"] = "DISTANCE"
        elif param.unit == "rel":
            common["subtype"] = "FACTOR"
    return FloatProperty(
        default=convert(param.default),
        min=convert(hard[0]),
        max=convert(hard[1]),
        soft_min=convert(soft[0]),
        soft_max=convert(soft[1]),
        **common,
    )


class TreeSettings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Generated Tree", default=False, options={"HIDDEN"})
    auto_update: BoolProperty(name="Auto Update", description="Regenerate on every setting change", default=True)
    preset: StringProperty(name="Preset", description="Preset the tree was built from", default="BROADLEAF")
    height_unit: EnumProperty(name="Unit", description="Unit shown for the height", items=HEIGHT_UNITS, default="BU")
    height_display: FloatProperty(
        name="Height",
        description="Total tree height including the canopy",
        get=_get_height_display,
        set=_set_height_display,
        min=0.01,
        soft_max=40.0,
    )
    warnings: StringProperty(default="", options={"HIDDEN"})
    stat_faces: IntProperty(default=0, options={"HIDDEN"})
    stat_top: FloatProperty(default=0.0, options={"HIDDEN"})
    stat_fits: BoolProperty(default=True, options={"HIDDEN"})
    stat_strands: IntProperty(default=0, options={"HIDDEN"})
    hair_object: PointerProperty(type=bpy.types.Object, name="Hair Object", options={"HIDDEN"})
    leaf_object: PointerProperty(
        type=bpy.types.Object,
        name="Leaf Object",
        description=(
            "Mesh copied for every leaf, in its own axes: root at the origin, growing along +X, "
            "upper face towards +Z; scaled so it reaches x = 1. Regenerate after editing it"
        ),
        poll=lambda self, obj: obj.type == "MESH" and not obj.rct_tree.enabled and obj != self.hair_object,
        update=_on_change,
    )


for _param in tree.PARAMETERS:
    TreeSettings.__annotations__[_param.name] = _make_property(_param)
for _role, _key in enumerate(ROLE_KEYS):
    TreeSettings.__annotations__["material_" + _key] = PointerProperty(
        type=bpy.types.Material,
        name=tree.ROLES[_role],
        description="Material of the tree's {} (any material; kept when regenerating)".format(_key),
        update=_on_material_change,
    )
    TreeSettings.__annotations__["colour_" + _key] = EnumProperty(
        name="Colour",
        description=REMAP_NOTE,
        items=REMAP_ITEMS,
        get=_remap_getter(_key),
        set=_remap_setter(_key),
    )


def active_tree(context):
    obj = context.active_object
    if obj is not None and obj.type == "MESH" and obj.rct_tree.enabled:
        return obj
    return None


# Operators --------------------------------------------------------------------------


PRESET_ITEMS = [(key, value["label"], "Start from the {} preset".format(value["label"])) for key, value in tree.PRESETS.items()]


class RCT_OT_tree_add(bpy.types.Operator):
    """Add a procedural tree at the origin and set the object type to match it"""

    bl_idname = "rct_graphics.tree_add"
    bl_label = "Add Tree"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if scene_setup.get_rig(scene)[0] is None:
            scene_setup.initialize(scene)
        props = scene.rct_graphics
        obj = bpy.data.objects.new(TREE_NAME, bpy.data.meshes.new(TREE_NAME))
        collection = context.collection
        if collection is None or collection.name == scene_setup.RIG_COLLECTION:
            collection = scene.collection
        collection.objects.link(obj)
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        settings = obj.rct_tree
        apply_preset(settings, scene.rct_tree_preset)
        with suspended_updates():
            size_from_scene(settings, props)
            settings.enabled = True
        regenerate(obj)
        message = write_scene(settings, props)
        self.report({"INFO"}, "Added {} tree. {}".format(tree.PRESETS[settings.preset]["label"], message))
        return {"FINISHED"}


class _TreeOperator:
    @classmethod
    def poll(cls, context):
        return active_tree(context) is not None


class RCT_OT_tree_regenerate(_TreeOperator, bpy.types.Operator):
    """Rebuild the active tree's mesh from its settings"""

    bl_idname = "rct_graphics.tree_regenerate"
    bl_label = "Regenerate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        regenerate(active_tree(context))
        return {"FINISHED"}


class RCT_OT_tree_randomize(_TreeOperator, bpy.types.Operator):
    """Pick a new random seed and regenerate"""

    bl_idname = "rct_graphics.tree_randomize"
    bl_label = "Randomize Seed"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_tree(context)
        settings = obj.rct_tree
        with suspended_updates():
            settings.seed = (settings.seed * 7919 + int(time.time() * 1000)) % 100000
        regenerate(obj)
        return {"FINISHED"}


class RCT_OT_tree_load_preset(_TreeOperator, bpy.types.Operator):
    """Apply the selected preset to the active tree, keeping its materials, footprint and seed"""

    bl_idname = "rct_graphics.tree_load_preset"
    bl_label = "Load Preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_tree(context)
        apply_preset(obj.rct_tree, context.scene.rct_tree_preset)
        regenerate(obj)
        return {"FINISHED"}


class RCT_OT_tree_make_unique(_TreeOperator, bpy.types.Operator):
    """Copy the shared role materials so this tree's material edits do not affect other trees"""

    bl_idname = "rct_graphics.tree_make_unique"
    bl_label = "Make Unique"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_tree(context)
        copies = make_unique(obj.rct_tree)
        assign_slots(obj)
        self.report({"INFO"}, "Copied {} material(s)".format(copies) if copies else "Materials are already unique")
        return {"FINISHED"}


class RCT_OT_tree_apply(_TreeOperator, bpy.types.Operator):
    """Freeze the tree into a plain mesh that can be edited; it is no longer regenerated"""

    bl_idname = "rct_graphics.tree_apply"
    bl_label = "Apply (Freeze Mesh)"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = active_tree(context)
        obj.rct_tree.enabled = False
        _pending.discard(obj.name)
        return {"FINISHED"}


class RCT_OT_tree_make_leaf_object(_TreeOperator, bpy.types.Operator):
    """Copy the active tree's built-in leaf shape into a mesh object to edit, and use it as the Leaf Object"""

    bl_idname = "rct_graphics.tree_make_leaf_object"
    bl_label = "Make Leaf Object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = active_tree(context)
        return obj is not None and obj.rct_tree.canopy_style == "INSTANCES" and obj.rct_tree.leaf_shape != "CUSTOM"

    def execute(self, context):
        obj = active_tree(context)
        settings = obj.rct_tree
        verts, faces = tree.leaf_template(settings.leaf_shape, settings.leaf_width)
        label = next(label for key, label, _ in tree.LEAF_SHAPES if key == settings.leaf_shape)
        name = "RCT Leaf ({})".format(label)
        leaf = bpy.data.objects.new(name, write_mesh(name, tree.MeshData(verts, faces, 0, False)))
        leaf.data.materials.append(role_material(settings, tree.LEAVES))
        # Beside the tree, out of the renders; only its mesh matters.
        leaf.location = obj.matrix_world.translation + obj.matrix_world.to_3x3() @ Vector((projection.TILE_SIZE, 0.0, 1.0))
        leaf.hide_render = True
        for collection in obj.users_collection or (context.scene.collection,):
            collection.objects.link(leaf)
        with suspended_updates():
            settings.leaf_object = leaf
            settings.leaf_shape = "CUSTOM"
        regenerate(obj)
        self.report({"INFO"}, "Leaf shape copied to {}; edit it, then Regenerate".format(leaf.name))
        return {"FINISHED"}


class RCT_OT_tree_match_scene(_TreeOperator, bpy.types.Operator):
    """Set the scene's object type and footprint from the active tree"""

    bl_idname = "rct_graphics.tree_match_scene"
    bl_label = "Match Scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, write_scene(active_tree(context).rct_tree, context.scene.rct_graphics))
        return {"FINISHED"}


class RCT_OT_tree_use_look(_TreeOperator, bpy.types.Operator):
    """Use the outline, palette and tone settings suggested by the tree's preset"""

    bl_idname = "rct_graphics.tree_use_look"
    bl_label = "Use Suggested Look"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.rct_graphics
        for key, value in tree.PRESETS[active_tree(context).rct_tree.preset]["look"].items():
            setattr(props, key, value)
        return {"FINISHED"}


classes = (
    TreeSettings,
    RCT_OT_tree_add,
    RCT_OT_tree_regenerate,
    RCT_OT_tree_randomize,
    RCT_OT_tree_load_preset,
    RCT_OT_tree_make_unique,
    RCT_OT_tree_apply,
    RCT_OT_tree_make_leaf_object,
    RCT_OT_tree_match_scene,
    RCT_OT_tree_use_look,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.rct_tree = PointerProperty(type=TreeSettings)
    bpy.types.Scene.rct_tree_preset = EnumProperty(
        name="Preset", description="Tree family to start from", items=PRESET_ITEMS, default="BROADLEAF"
    )


def unregister():
    if bpy.app.timers.is_registered(_run_pending):
        bpy.app.timers.unregister(_run_pending)
    _pending.clear()
    del bpy.types.Scene.rct_tree_preset
    del bpy.types.Object.rct_tree
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
