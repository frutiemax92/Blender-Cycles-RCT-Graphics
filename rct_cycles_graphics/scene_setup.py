"""Creates the camera/light rig and the Cycles settings used for sprites."""

import math

import bpy

from .core import projection

RIG_COLLECTION = "RCT Rig"
RIG_NAME = "RCT_Rig"
CAMERA_NAME = "RCT_Camera"
MAIN_LIGHT_NAME = "RCT_MainLight"
FILL_LIGHT_NAME = "RCT_FillLight"
GRID_NAME = "RCT_TileGrid"
WORLD_NAME = "RCT_World"

CAMERA_DISTANCE = 200.0

# Light directions are given relative to view 0 and rotate with the camera,
# so every view is lit the same way, as in the game. The main light comes
# from the camera's right, low over the horizon, like the original rig.
MAIN_LIGHT_ROTATION = (math.radians(67.5), 0.0, math.radians(90.0 - 45.0))
FILL_LIGHT_ROTATION = (0.0, math.radians(-72.5), math.radians(115.0 - 45.0))
# Lights that Blender's default scene ships with and that would spoil the look.
DEFAULT_SCENE_LIGHTS = ("Light", "Lamp")


def get_rig(scene):
    rig = scene.objects.get(RIG_NAME)
    camera = scene.objects.get(CAMERA_NAME)
    if rig is None or camera is None:
        return None, None
    return rig, camera


def rig_object_names():
    return {RIG_NAME, CAMERA_NAME, MAIN_LIGHT_NAME, FILL_LIGHT_NAME, GRID_NAME}


def _rig_collection(scene):
    collection = bpy.data.collections.get(RIG_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(RIG_COLLECTION)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def _replace_object(name, data, collection):
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    return obj


def _sun(name, strength, angle_degrees, cast_shadows):
    light = bpy.data.lights.get(name)
    if light is None or light.type != "SUN":
        if light is not None:
            bpy.data.lights.remove(light)
        light = bpy.data.lights.new(name, "SUN")
    light.energy = strength
    light.angle = math.radians(angle_degrees)
    light.use_shadow = cast_shadows
    return light


def build_rig(scene):
    """(Re)create the rig: an empty rotated per view with camera and suns attached."""
    collection = _rig_collection(scene)
    props = scene.rct_graphics

    rig = _replace_object(RIG_NAME, None, collection)
    rig.empty_display_type = "ARROWS"
    rig.hide_select = True

    camera_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    camera_data.type = "ORTHO"
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.clip_start = 1.0
    camera_data.clip_end = CAMERA_DISTANCE * 2.0
    camera_data.shift_x = 0.0
    camera_data.shift_y = 0.0
    camera = _replace_object(CAMERA_NAME, camera_data, collection)
    camera.hide_select = True

    for name in DEFAULT_SCENE_LIGHTS:
        default_light = scene.objects.get(name)
        if default_light is not None and default_light.type == "LIGHT":
            bpy.data.objects.remove(default_light, do_unlink=True)

    main = _replace_object(
        MAIN_LIGHT_NAME, _sun(MAIN_LIGHT_NAME, props.main_light_strength, 2.0, props.cast_shadows), collection
    )
    main.rotation_euler = MAIN_LIGHT_ROTATION
    main.parent = rig
    main.hide_select = True

    fill = _replace_object(
        FILL_LIGHT_NAME, _sun(FILL_LIGHT_NAME, props.fill_light_strength, 2.0, props.cast_shadows), collection
    )
    fill.rotation_euler = FILL_LIGHT_ROTATION
    fill.parent = rig
    fill.hide_select = True

    scene.camera = camera
    set_view(scene, 0, (-64, -96, 64, 32))
    build_tile_grid(scene, 1, 1)
    return rig, camera


def set_view(scene, view, bounds):
    """Rotate the rig to ``view`` and frame the screen rectangle ``bounds``."""
    rig, camera = get_rig(scene)
    placement = projection.camera_placement(bounds, view, CAMERA_DISTANCE)
    # The rig only carries the lights, which turn with the view; the camera is
    # placed directly in world space.
    rig.rotation_euler = (0.0, 0.0, projection.view_angle(view))
    rig.location = (0.0, 0.0, 0.0)
    camera.location = placement["location"]
    camera.rotation_euler = placement["rotation"]
    camera.data.ortho_scale = placement["ortho_scale"]
    width, height = placement["resolution"]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0


def build_tile_grid(scene, width, length):
    """Non-rendering wireframe showing the tile footprint (tiles extend to -X/-Y)."""
    collection = _rig_collection(scene)
    size = projection.TILE_SIZE
    half = size / 2.0
    verts = []
    edges = []
    # Lines along Y.
    for i in range(width + 1):
        x = half - i * size
        verts += [(x, half, 0.0), (x, half - length * size, 0.0)]
        edges.append((len(verts) - 2, len(verts) - 1))
    # Lines along X.
    for j in range(length + 1):
        y = half - j * size
        verts += [(half, y, 0.0), (half - width * size, y, 0.0)]
        edges.append((len(verts) - 2, len(verts) - 1))
    mesh = bpy.data.meshes.get(GRID_NAME)
    if mesh is not None:
        old = bpy.data.objects.get(GRID_NAME)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    mesh = bpy.data.meshes.new(GRID_NAME)
    mesh.from_pydata(verts, edges, [])
    grid = _replace_object(GRID_NAME, mesh, collection)
    grid.hide_render = True
    grid.hide_select = True
    grid.display_type = "WIRE"
    return grid


def configure_render(scene):
    """Cycles settings giving flat, crisp, palette friendly renders."""
    props = scene.rct_graphics
    render = scene.render
    render.engine = "CYCLES"
    render.film_transparent = True
    render.use_compositing = False
    render.use_sequencer = False
    render.dither_intensity = 0.0

    cycles = scene.cycles
    cycles.samples = props.samples
    cycles.use_adaptive_sampling = False
    cycles.use_denoising = False
    cycles.pixel_filter_type = "BOX"
    cycles.filter_width = props.filter_width
    cycles.max_bounces = 4
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 2
    cycles.transmission_bounces = 4
    cycles.transparent_max_bounces = 8
    cycles.caustics_reflective = False
    cycles.caustics_refractive = False
    cycles.sample_clamp_indirect = 10.0

    view = scene.view_settings
    view.view_transform = "Standard"
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0

    world = bpy.data.worlds.get(WORLD_NAME) or bpy.data.worlds.new(WORLD_NAME)
    world.use_nodes = True
    background = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if background is None:
        background = world.node_tree.nodes.new("ShaderNodeBackground")
        output = next((n for n in world.node_tree.nodes if n.type == "OUTPUT_WORLD"), None)
        if output is None:
            output = world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(background.outputs[0], output.inputs[0])
    background.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    background.inputs["Strength"].default_value = props.ambient_strength
    scene.world = world

    for name, strength in (
        (MAIN_LIGHT_NAME, props.main_light_strength),
        (FILL_LIGHT_NAME, props.fill_light_strength),
    ):
        light = bpy.data.lights.get(name)
        if light is not None:
            light.energy = strength
            light.use_shadow = props.cast_shadows


def initialize(scene):
    configure_render(scene)
    build_rig(scene)
