"""Drives Cycles to render the jobs and turns the results into sprites."""

import os
import shutil
import tempfile

import bpy
import numpy as np

from . import scene_setup
from .core import jobs as jobs_core
from .core import postprocess, projection, tone

#: AOVs written by recolourable materials (see materials.py): one coverage
#: pass per remap, so pixels mixing two remaps are never averaged into a third.
REMAP_AOVS = {1: "rct_remap_1", 2: "rct_remap_2", 3: "rct_remap_3"}

#: Colour AOV holding each face's flat geometric normal (encoded 0.5 + 0.5 n),
#: which tells faces apart when resolving supersampled renders.
SURFACE_AOV = "rct_surface_normal"
SURFACE_NODE_NAME = "RCT Surface Normal AOV"

RENDERABLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}


class RenderResult:
    """Pixel data of one render, top row first."""

    def __init__(self, bounds, rgba, position=None, classes=None, opaque=None):
        self.bounds = bounds
        self.rgba = rgba
        self.position = position
        #: Remap number (0-3) per pixel.
        self.classes = classes
        #: Silhouette, or None to cut it with the alpha threshold.
        self.opaque = opaque


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


class _sheared:
    """Temporarily apply a world-space 4x4 matrix to every rendered object.

    Root objects are parented to a temporary empty with the matrix as parent
    inverse, which (unlike loc/rot/scale) can hold a shear.
    """

    def __init__(self, scene, view_layer, matrix):
        self.scene = scene
        self.view_layer = view_layer
        self.matrix = matrix
        self.saved = []
        self.empty = None

    def __enter__(self):
        from mathutils import Matrix

        self.empty = bpy.data.objects.new("RCT_TempShear", None)
        self.scene.collection.objects.link(self.empty)
        shear = Matrix(self.matrix)
        roots = {_root(obj) for obj in renderable_objects(self.scene, self.view_layer)}
        for obj in roots:
            self.saved.append((obj, obj.matrix_parent_inverse.copy()))
            obj.parent = self.empty
            obj.matrix_parent_inverse = shear
        bpy.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        for obj, parent_inverse in self.saved:
            obj.parent = None
            obj.matrix_parent_inverse = parent_inverse
        bpy.data.objects.remove(self.empty, do_unlink=True)
        bpy.context.view_layer.update()
        return False


class _surface_normals:
    """Temporarily make every rendered material write SURFACE_AOV.

    Unlike the Normal pass, the geometric normal ignores smooth shading, bump
    and normal maps, so it is constant over a face. Pixels of materials that
    cannot be edited (linked) fall back to the Normal pass.
    """

    def __init__(self, scene, view_layer):
        self.scene = scene
        self.view_layer = view_layer
        self.added = []

    def __enter__(self):
        materials = set()
        for obj in renderable_objects(self.scene, self.view_layer):
            for slot in getattr(obj, "material_slots", ()):
                if slot.material is not None:
                    materials.add(slot.material)
        for material in materials:
            tree = material.node_tree
            if tree is None or material.library is not None or SURFACE_NODE_NAME in tree.nodes:
                continue
            geometry = tree.nodes.new("ShaderNodeNewGeometry")
            encode = tree.nodes.new("ShaderNodeVectorMath")
            encode.operation = "MULTIPLY_ADD"
            encode.inputs[1].default_value = (0.5, 0.5, 0.5)
            encode.inputs[2].default_value = (0.5, 0.5, 0.5)
            aov = tree.nodes.new("ShaderNodeOutputAOV")
            aov.name = SURFACE_NODE_NAME
            aov.aov_name = SURFACE_AOV
            tree.links.new(geometry.outputs["True Normal"], encode.inputs[0])
            tree.links.new(encode.outputs["Vector"], aov.inputs["Color"])
            self.added.append((tree, (geometry, encode, aov)))
        return self

    def __exit__(self, *exc):
        for tree, nodes in self.added:
            for node in nodes:
                tree.nodes.remove(node)
        self.added = []
        return False


def _surface_normal(channels, view_layer_name, alpha):
    """World-space normal per pixel: the flat AOV, else the Normal pass."""
    normal = _pass(channels, view_layer_name, "Normal", "XYZ")
    encoded = _pass(channels, view_layer_name, SURFACE_AOV, "RGB")
    if encoded is None:
        return normal
    written = np.any(encoded != 0.0, axis=-1, keepdims=True)
    safe = np.where(alpha > 1e-6, alpha, 1.0)[..., None]
    flat = 2.0 * encoded / safe - 1.0
    if normal is None:
        return flat
    return np.where(written, flat, normal)


def _root(obj):
    while obj.parent is not None:
        obj = obj.parent
    return obj


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
    view_layer.use_pass_normal = True
    for name, kind in [(name, "VALUE") for name in REMAP_AOVS.values()] + [(SURFACE_AOV, "COLOR")]:
        if name not in view_layer.aovs:
            aov = view_layer.aovs.add()
            aov.name = name
            aov.type = kind
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
        self.factor = scene_setup.supersampling_factor(self.scene.rct_graphics)
        self._state = None
        self._normals = None

    def __enter__(self):
        self._state = _SceneState(self.scene)
        scene_setup.configure_render(self.scene)
        _configure_passes(self.scene, self.view_layer)
        if self.factor > 1:
            self._normals = _surface_normals(self.scene, self.view_layer).__enter__()
        return self

    def __exit__(self, *exc):
        if self._normals is not None:
            self._normals.__exit__(*exc)
        self._state.restore()
        scene_setup.set_view(self.scene, 0, (-64, -96, 64, 32))
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        return False

    def render(self, view, frame, variant=None):
        scene = self.scene
        scene.frame_set(frame)
        if variant in ("up", "down"):
            with _sheared(scene, self.view_layer, jobs_core.wall_slope_matrix(variant)):
                return self._render(view, frame, variant)
        return self._render(view, frame, variant)

    def _render(self, view, frame, variant):
        scene = self.scene
        points = scene_bounds_points(scene, self.view_layer)
        if len(points) == 0:
            return None
        bounds = projection.screen_bounds(points, view)
        scene_setup.set_view(scene, view, bounds)
        # Each pixel becomes factor x factor point-sampled sub-pixels.
        scene.render.resolution_x *= self.factor
        scene.render.resolution_y *= self.factor

        path = os.path.join(self.temp_dir, "view{}_frame{}_{}.exr".format(view, frame, variant))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True, scene=scene.name, layer=self.view_layer.name)

        channels = _read_exr(path)
        name = self.view_layer.name
        rgba = _pass(channels, name, "Combined", "RGBA")
        if rgba is None:
            raise RuntimeError("The render has no Combined pass")
        position = _pass(channels, name, "Position", "XYZ")
        coverages = [_pass(channels, name, aov, "X") for aov in REMAP_AOVS.values()]
        classes = None
        if all(c is not None for c in coverages):
            remap = np.stack([c[..., 0] for c in coverages], axis=-1)
            classes = postprocess.remap_classes(remap, rgba[..., 3])
        # EXR rows are stored top to bottom, which is screen order already.
        if self.factor == 1:
            return RenderResult(bounds, rgba, position, classes)
        normal = _surface_normal(channels, name, rgba[..., 3])
        if position is None or normal is None:
            raise RuntimeError("Supersampling needs the Position and Normal passes")
        if classes is None:
            classes = np.zeros(rgba.shape[:2], dtype=np.int32)
        rgba, position, classes, opaque = postprocess.resolve_supersampled(
            rgba, position, normal, classes, self.factor, scene.rct_graphics.alpha_threshold
        )
        return RenderResult(bounds, rgba, position, classes, opaque)


def run_jobs(context, jobs, settings, progress=None, footprint=(1, 1)):
    """Render ``jobs`` and return ``{image_index: Sprite}``.

    footprint: (width, length) in tiles, used to split jobs bound to a tile.
    """
    sprites = {}
    groups = {}
    for job in jobs:
        groups.setdefault(job.render_key, []).append(job)
    steps = 2 * len(groups)

    # Render everything first: matching tones needs every view at once, so
    # that all of them get the same correction.
    results = []
    with Renderer(context) as renderer:
        for step, (key, group) in enumerate(sorted(groups.items(), key=lambda item: _sort_key(item[0]))):
            view, frame, variant = key
            results.append((renderer.render(view, frame, variant), group))
            if progress is not None:
                progress(step + 1, steps)

    curve = _fit_tone(results, settings) if settings.tone_match else None
    for step, (result, group) in enumerate(results, start=len(groups)):
        if result is None:
            for job in group:
                sprites[job.index] = postprocess.Sprite(np.zeros((0, 0), dtype=np.uint8), 0, 0)
        else:
            _make_sprites(result, group, settings, footprint, sprites, curve)
        if progress is not None:
            progress(step + 1, steps)
    return sprites


def _fit_tone(results, settings):
    samples = [
        postprocess.prepare(result.rgba, settings, remap=result.classes, opaque=result.opaque)
        for result, _ in results
        if result is not None
    ]
    return tone.fit(samples, settings.tone_strength, settings.tone_saturation)


def _sort_key(render_key):
    view, frame, variant = render_key
    return (frame, "" if variant is None else str(variant), view)


def _make_sprites(result, group, settings, footprint, sprites, curve=None):
    # Quantize the whole render once, so dithering and outlines do not show
    # seams where large scenery is cut into tiles.
    indices = postprocess.to_indices(
        result.rgba, settings, remap=result.classes, opaque=result.opaque, tone=curve
    )
    tiles = None
    x0, y0 = result.bounds[0], result.bounds[1]
    for job in group:
        job_indices = indices
        if job.tile is not None:
            if tiles is None:
                if result.position is None:
                    raise RuntimeError("The render has no Position pass to split tiles with")
                tiles = jobs_core.tile_map(result.position, result.rgba[..., 3], *footprint)
            job_indices = np.where(tiles == job.tile, indices, 0).astype(np.uint8)
        sprites[job.index] = postprocess.make_sprite(job_indices, x0, y0, job.anchor())
