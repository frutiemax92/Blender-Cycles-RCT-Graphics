"""Drives Cycles to render the jobs and turns the results into sprites."""

import os
import shutil
import tempfile

import bpy
import numpy as np

from . import scene_setup
from .core import postprocess, projection

#: Name of the AOV written by recolourable materials (see materials.py).
REMAP_AOV = "rct_remap"

RENDERABLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}


class RenderResult:
    """Pixel data of one render, top row first."""

    def __init__(self, bounds, rgba, position=None, remap=None):
        self.bounds = bounds
        self.rgba = rgba
        self.position = position
        self.remap = remap


def renderable_objects(scene, view_layer):
    rig_names = scene_setup.rig_object_names()
    for obj in scene.objects:
        if obj.name in rig_names or obj.type not in RENDERABLE_TYPES:
            continue
        if obj.hide_render or not obj.visible_get(view_layer=view_layer):
            continue
        yield obj


def scene_bounds_points(scene, view_layer):
    """World-space bounding box corners of everything that renders."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in renderable_objects(scene, view_layer):
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for corner in evaluated.bound_box:
            points.append(tuple(matrix @ _vector(corner)))
    return np.array(points, dtype=np.float64).reshape(-1, 3)


def _vector(values):
    from mathutils import Vector

    return Vector(values)


class _SceneState:
    """Saves and restores the render settings the renderer touches."""

    def __init__(self, scene):
        self.scene = scene
        render = scene.render
        settings = render.image_settings
        self.values = {
            "filepath": render.filepath,
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "resolution_percentage": render.resolution_percentage,
            "file_format": settings.file_format,
            "color_depth": settings.color_depth,
            "color_mode": settings.color_mode,
            "exr_codec": settings.exr_codec,
            "frame": scene.frame_current,
        }
        self.media_type = getattr(settings, "media_type", None)

    def restore(self):
        scene = self.scene
        render = scene.render
        settings = render.image_settings
        if self.media_type is not None:
            settings.media_type = self.media_type
        for key in ("file_format", "color_depth", "color_mode", "exr_codec"):
            setattr(settings, key, self.values[key])
        for key in ("filepath", "resolution_x", "resolution_y", "resolution_percentage"):
            setattr(render, key, self.values[key])
        scene.frame_set(self.values["frame"])


def _configure_passes(scene, view_layer):
    view_layer.use_pass_combined = True
    view_layer.use_pass_position = True
    if REMAP_AOV not in view_layer.aovs:
        aov = view_layer.aovs.add()
        aov.name = REMAP_AOV
        aov.type = "VALUE"
    settings = scene.render.image_settings
    if hasattr(settings, "media_type"):
        settings.media_type = "MULTI_LAYER_IMAGE"
    settings.file_format = "OPEN_EXR_MULTILAYER"
    settings.color_depth = "32"
    settings.color_mode = "RGBA"
    settings.exr_codec = "ZIP"


def _read_exr(path):
    """Read every channel of a (possibly multi-part) EXR into {name: array}."""
    import OpenImageIO as oiio

    image = oiio.ImageInput.open(path)
    if image is None:
        raise RuntimeError("Could not read render output {}: {}".format(path, oiio.geterror()))
    channels = {}
    try:
        subimage = 0
        while image.seek_subimage(subimage, 0):
            spec = image.spec()
            pixels = image.read_image(subimage, 0, 0, spec.nchannels, "float")
            pixels = np.asarray(pixels, dtype=np.float32).reshape(spec.height, spec.width, spec.nchannels)
            for i, name in enumerate(spec.channelnames):
                channels[name] = pixels[..., i]
            subimage += 1
    finally:
        image.close()
    return channels


def _pass(channels, view_layer_name, pass_name, components):
    arrays = []
    for component in components:
        key = "{}.{}.{}".format(view_layer_name, pass_name, component)
        if key not in channels:
            # Single layer files have no view layer prefix.
            key = "{}.{}".format(pass_name, component)
        if key not in channels:
            return None
        arrays.append(channels[key])
    return np.stack(arrays, axis=-1)


class Renderer:
    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.view_layer = context.view_layer
        self.temp_dir = tempfile.mkdtemp(prefix="rct_render_")
        self._state = None

    def __enter__(self):
        self._state = _SceneState(self.scene)
        scene_setup.configure_render(self.scene)
        _configure_passes(self.scene, self.view_layer)
        return self

    def __exit__(self, *exc):
        self._state.restore()
        scene_setup.set_view(self.scene, 0, (-64, -96, 64, 32))
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        return False

    def render(self, view, frame):
        scene = self.scene
        scene.frame_set(frame)
        points = scene_bounds_points(scene, self.view_layer)
        if len(points) == 0:
            return None
        bounds = projection.screen_bounds(points, view)
        scene_setup.set_view(scene, view, bounds)

        path = os.path.join(self.temp_dir, "view{}_frame{}.exr".format(view, frame))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True, scene=scene.name, layer=self.view_layer.name)

        channels = _read_exr(path)
        name = self.view_layer.name
        rgba = _pass(channels, name, "Combined", "RGBA")
        if rgba is None:
            raise RuntimeError("The render has no Combined pass")
        position = _pass(channels, name, "Position", "XYZ")
        remap = _pass(channels, name, REMAP_AOV, "X")
        # EXR rows are stored top to bottom, which is screen order already.
        return RenderResult(
            bounds,
            rgba,
            position,
            None if remap is None else remap[..., 0],
        )


def run_jobs(context, jobs, settings, progress=None):
    """Render ``jobs`` and return ``{image_index: Sprite}``."""
    sprites = {}
    groups = {}
    for job in jobs:
        groups.setdefault(job.render_key, []).append(job)

    with Renderer(context) as renderer:
        for step, (key, group) in enumerate(sorted(groups.items())):
            view, frame, _variant = key
            result = renderer.render(view, frame)
            for job in group:
                sprites[job.index] = _make_sprite(result, job, settings)
            if progress is not None:
                progress(step + 1, len(groups))
    return sprites


def _make_sprite(result, job, settings):
    if result is None:
        return postprocess.Sprite(np.zeros((0, 0), dtype=np.uint8), 0, 0)
    remap = None
    if result.remap is not None:
        remap = postprocess.remap_classes(result.remap, result.rgba[..., 3])
    indices = postprocess.to_indices(result.rgba, settings, remap=remap)
    x0, y0 = result.bounds[0], result.bounds[1]
    return postprocess.make_sprite(indices, x0, y0, job.anchor())
