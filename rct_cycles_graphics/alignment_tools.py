"""Blender operators for checking and fixing how objects line up in game."""

import os

import bpy
import numpy as np
from bpy.props import BoolProperty
from mathutils import Matrix

from . import render
from .core import alignment, export, png, projection

PREVIEW_FILE = "alignment_preview.png"
PREVIEW_IMAGE = "RCT Alignment Preview"


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
    for finding in alignment.geometry_report(low, high, props.object_type, size):
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
        for layout in alignment.arrangements(props.object_type, clearance, size, props.start_index)
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


def show_preview(context, path):
    image = bpy.data.images.get(PREVIEW_IMAGE)
    if image is None:
        image = bpy.data.images.load(path, check_existing=False)
        image.name = PREVIEW_IMAGE
    else:
        image.filepath = path
        image.reload()
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
                return


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


class RCT_OT_snap_to_grid(bpy.types.Operator):
    """Scale and move the selected objects (or all rendered objects) so their bounds fill the tile cell and a whole number of clearance units"""

    bl_idname = "rct_graphics.snap_to_grid"
    bl_label = "Snap to Grid"
    bl_options = {"REGISTER", "UNDO"}

    horizontal: BoolProperty(
        name="Tile Edges",
        description="Fit the footprint to the tile edges (the +X edge for walls)",
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
            low, high, props.object_type, footprint(props), self.horizontal, self.height
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


classes = (RCT_OT_check_alignment, RCT_OT_snap_to_grid)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
