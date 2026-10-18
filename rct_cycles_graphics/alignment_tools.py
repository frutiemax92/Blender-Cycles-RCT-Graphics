"""Blender operators for checking and fixing how objects line up in game."""

import os
import struct

import bpy
import numpy as np
from bpy.props import BoolProperty, IntProperty
from mathutils import Matrix

from . import preferences, render
from .core import alignment, export, g1, png, projection, rct2dat, terrain

PREVIEW_FILE = "alignment_preview.png"
PREVIEW_IMAGE = "RCT Alignment Preview"
TERRAIN_FILE = "terrain_preview.png"
TERRAIN_IMAGE = "RCT Terrain Preview"


def model_bounds(context):
    points = render.scene_bounds_points(context.scene, context.view_layer)
    if len(points) == 0:
        return None
    return points.min(axis=0), points.max(axis=0)


def image_anchors(job_list):
    """Paint anchor of every image relative to the top corner of its own tile."""
    anchors = {}
    for job in job_list:
        ax, ay = job.anchor()
        tx, ty = projection.tile_top_vertex(job.tile_center[0], job.tile_center[1], job.view)
        anchors[job.index] = (ax - tx, ay - ty)
    return anchors


def run_check(context):
    """Geometry report plus, when sprites exist, the composited preview.

    Returns (report lines, preview path or None).
    """
    from .operators import build_jobs, footprint, output_directory

    props = context.scene.rct_graphics
    lines = []
    bounds = model_bounds(context)
    if bounds is None:
        return ["Nothing to check: no renderable objects"], None

    low, high = bounds
    size = footprint(props)
    for finding in alignment.geometry_report(low, high, props.object_type, size, props.small_shape):
        lines.append(("OK  " if finding.ok else "FIX ") + finding.message)

    directory = output_directory(props)
    if not os.path.exists(os.path.join(directory, export.IMAGES_JSON)):
        lines.append("Render the sprites to get a tiling preview")
        return lines, None

    sprites = export.load_sprites(directory)
    anchors = image_anchors(build_jobs(props))
    clearance = alignment.clearance_from_height(high[2])
    layouts = [
        layout
        for layout in alignment.arrangements(props.object_type, clearance, size, props.start_index, props.small_shape)
        if all(p.image in sprites for p in layout.placements)
    ]
    if not layouts:
        lines.append("The images in the output folder do not match the object type")
        return lines, None

    for layout in layouts:
        holes = alignment.pinholes(sprites, anchors, layout)
        if holes:
            lines.append("FIX {}: {} pixel holes between copies".format(layout.name, holes))
    sheet = alignment.preview_sheet(sprites, anchors, layouts)
    path = os.path.join(directory, PREVIEW_FILE)
    png.write_rgba(path, sheet)
    lines.append("Preview: {} ({} layouts, stacked {} z units)".format(PREVIEW_FILE, len(layouts), clearance))
    return lines, path


def show_preview(context, path, name=PREVIEW_IMAGE, open_window=False):
    """Load ``path`` as image ``name`` and show it in an Image Editor.

    open_window: without an Image Editor on screen, open one in a new window.
    """
    image = bpy.data.images.get(name)
    if image is None:
        image = bpy.data.images.load(path, check_existing=False)
        image.name = name
    else:
        image.filepath = path
        image.reload()
    if _show_in_image_editor(context, image) or not open_window or context.window is None:
        return
    try:
        # Opens the render view (a new window by default), an Image Editor.
        bpy.ops.render.view_show("INVOKE_DEFAULT")
    except RuntimeError:
        return
    _show_in_image_editor(context, image)


def _show_in_image_editor(context, image):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
                return True
    return False


def grass_tile(rct2):
    """The ground tile sprite and whether it is the game's own (from g1.dat)."""
    path = g1.find_g1(rct2)
    if path is not None:
        try:
            sprite = g1.read_sprite(path, g1.GRASS_GRID)
            return (sprite.indices, sprite.x, sprite.y), True
        except (OSError, ValueError, IndexError):
            pass
    return terrain.fallback_grass(), False


def preview_jobs(job_list):
    """The jobs to draw per view: the first frame, flat, per footprint tile."""
    chosen = {}
    for job in job_list:
        if job.variant is not None:
            continue
        key = (job.view, job.tile)
        if key not in chosen or job.index < chosen[key].index:
            chosen[key] = job
    views = []
    for view in range(4):
        group = [job for (v, _), job in sorted(chosen.items(), key=lambda item: item[1].index) if v == view]
        # Large scenery: the per-tile images, not the whole-object preview.
        if any(job.tile is not None for job in group):
            group = [job for job in group if job.tile is not None]
        views.append(group)
    return views


def comparison_names(props):
    """The vanilla trees picked to stand beside the object, in slot order."""
    return [name for name in (getattr(props, "compare_tree_{}".format(i)) for i in range(1, 5)) if name != "NONE"]


def load_vanilla(rct2, names):
    """Read the picked RCT2 objects; returns (objects, names not found)."""
    objdata = rct2dat.find_objdata(rct2)
    objects, missing = [], []
    for name in names:
        path = rct2dat.find_object(objdata, name)
        try:
            objects.append(rct2dat.read_small_scenery(path))
        except (OSError, TypeError, ValueError, IndexError, struct.error):
            missing.append(name)
    return objects, missing


def run_terrain_preview(context, margin=2, scale=2):
    """Composite the rendered sprites, and the vanilla trees picked to compare
    with, on grass in the four views.

    Returns (preview path, whether the game's grass was used, vanilla trees
    that could not be read).
    """
    from .operators import build_jobs, footprint, output_directory

    props = context.scene.rct_graphics
    directory = output_directory(props)
    if not os.path.exists(os.path.join(directory, export.IMAGES_JSON)):
        raise ValueError("Render the sprites first")
    sprites = export.load_sprites(directory)
    rct2 = preferences.rct2_directory(context)
    ground, from_game = grass_tile(rct2)
    vanilla, missing = load_vanilla(rct2, comparison_names(props))
    occupied = terrain.ground_tiles(footprint(props), margin=0)

    views = []
    drawn = 0
    for view, group in enumerate(preview_jobs(build_jobs(props))):
        placements = [(job.index, job.anchor(), job.tile_center) for job in group if job.index in sprites]
        drawn += len(placements)
        row = terrain.row_tiles(view, len(vanilla), occupied)
        for obj, centre in zip(vanilla, row):
            key = (obj.identifier, view)
            image = obj.images[view % len(obj.images)]
            sprites[key] = (image.indices, image.x, image.y)
            top = projection.tile_top_vertex(centre[0], centre[1], view)
            offset = projection.game_offset_to_screen(*rct2dat.paint_offset(obj.flags, view))
            placements.append((key, (top[0] + offset[0], top[1] + offset[1]), centre))
        tiles = terrain.tiles_around(occupied + row, margin)
        views.append(terrain.compose_view(view, ground, tiles, sprites, placements))
    if not drawn:
        raise ValueError("The images in the output folder do not match the object type")
    path = os.path.join(directory, TERRAIN_FILE)
    png.write_rgba(path, terrain.preview_sheet(views, scale=scale))
    return path, from_game, missing


def store_report(scene, lines):
    scene.rct_graphics.alignment_report = "\n".join(lines)


class RCT_OT_check_alignment(bpy.types.Operator):
    """Compare the model with the tile grid and composite the sprites the way the game repeats them"""

    bl_idname = "rct_graphics.check_alignment"
    bl_label = "Check Alignment"

    def execute(self, context):
        try:
            lines, path = run_check(context)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        store_report(context.scene, lines)
        if path is not None:
            show_preview(context, path)
        problems = [line for line in lines if line.startswith("FIX")]
        if problems:
            self.report({"WARNING"}, "{} alignment problem(s), see the RCT panel".format(len(problems)))
        else:
            self.report({"INFO"}, "Model aligned with the grid")
        return {"FINISHED"}


class RCT_OT_terrain_preview(bpy.types.Operator):
    """Show the rendered sprites on the game's grass with gridlines, in all four views"""

    bl_idname = "rct_graphics.terrain_preview"
    bl_label = "Preview on Grass"

    margin: IntProperty(
        name="Tiles Around",
        description="Rings of grass tiles drawn around the object's footprint",
        default=2,
        min=0,
        max=8,
    )
    scale: IntProperty(
        name="Zoom",
        description="Pixel size of the preview image (the game's zoom-in levels)",
        default=2,
        min=1,
        max=4,
    )

    def execute(self, context):
        try:
            path, from_game, missing = run_terrain_preview(context, self.margin, self.scale)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        show_preview(context, path, TERRAIN_IMAGE, open_window=True)
        problems = []
        if not from_game:
            problems.append("RCT2's g1.dat not found (see the add-on preferences): using a stand-in grass")
        if missing:
            problems.append("could not read {} from RCT2's ObjData".format(", ".join(missing)))
        if problems:
            self.report({"WARNING"}, "; ".join(problems))
        else:
            self.report({"INFO"}, "Terrain preview written to " + path)
        return {"FINISHED"}


class RCT_OT_snap_to_grid(bpy.types.Operator):
    """Scale and move the selected objects (or all rendered objects) so their bounds fill the tile cell and a whole number of clearance units"""

    bl_idname = "rct_graphics.snap_to_grid"
    bl_label = "Snap to Grid"
    bl_options = {"REGISTER", "UNDO"}

    horizontal: BoolProperty(
        name="Tile Edges",
        description="Fit the footprint to the tile edges (the +X edge for walls, the half grid for quarter tiles)",
        default=True,
    )
    height: BoolProperty(
        name="Clearance Height",
        description="Put the bottom on the ground and round the height to clearance units (8 z units)",
        default=True,
    )

    def execute(self, context):
        from .operators import footprint

        props = context.scene.rct_graphics
        objects = [o for o in context.selected_objects if o in set(render.renderable_objects(context.scene, context.view_layer))]
        if not objects:
            objects = list(render.renderable_objects(context.scene, context.view_layer))
        if not objects:
            self.report({"ERROR"}, "Nothing to snap")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        points = []
        for obj in objects:
            evaluated = obj.evaluated_get(depsgraph)
            points += [evaluated.matrix_world @ _vec(c) for c in evaluated.bound_box]
        points = np.array([tuple(p) for p in points])
        low, high = points.min(axis=0), points.max(axis=0)
        target_low, target_high = alignment.snap_box(
            low, high, props.object_type, footprint(props), self.horizontal, self.height, props.small_shape
        )

        transform = Matrix.Identity(4)
        for axis in range(3):
            size = high[axis] - low[axis]
            scale = (target_high[axis] - target_low[axis]) / size if size > 1e-9 else 1.0
            transform[axis][axis] = scale
            transform[axis][3] = target_low[axis] - low[axis] * scale

        moved = set(objects)
        for obj in objects:
            # Children follow their parent; only move the top-most selected objects.
            parent = obj.parent
            while parent is not None and parent not in moved:
                parent = parent.parent
            if parent is None:
                obj.matrix_world = transform @ obj.matrix_world
        context.view_layer.update()
        self.report({"INFO"}, "Snapped {} object(s)".format(len(objects)))
        return {"FINISHED"}


def _vec(values):
    from mathutils import Vector

    return Vector(values)


classes = (RCT_OT_check_alignment, RCT_OT_terrain_preview, RCT_OT_snap_to_grid)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
