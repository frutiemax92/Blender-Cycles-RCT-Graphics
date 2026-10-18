import os

import bpy

from . import render, scene_setup
from .core import export, jobs, postprocess


class RCT_OT_initialize(bpy.types.Operator):
    """Create the RCT camera/light rig and configure Cycles for sprite rendering"""

    bl_idname = "rct_graphics.initialize"
    bl_label = "Initialize / Repair Scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene_setup.initialize(context.scene)
        self.report({"INFO"}, "RCT rig created")
        return {"FINISHED"}


def postprocess_settings(props):
    return postprocess.Settings(
        alpha_threshold=props.alpha_threshold,
        dither_method=props.dither_method,
        dither_strength=props.dither_strength,
        background_blend=props.background_blend,
        outline_shades=props.outline_shades,
        outline_width=props.outline_width,
        outline_diagonal=props.outline_diagonal,
    )


def build_jobs(props):
    frames = jobs.animation_frames(
        props.animation_frames, props.animation_first_frame, props.animation_frame_step
    )
    if props.object_type == "SMALL":
        return jobs.small_scenery(props.small_anchor, frames, props.start_index)
    if props.object_type == "WALL":
        return jobs.wall(props.wall_double_sided, props.wall_sloped, props.start_index, frames[0])
    if props.object_type == "LARGE":
        return jobs.large_scenery(props.tiles_width, props.tiles_length, props.start_index, frames[0])
    raise ValueError("Unsupported object type " + props.object_type)


def footprint(props):
    if props.object_type == "LARGE":
        return props.tiles_width, props.tiles_length
    return 1, 1


def output_directory(props):
    if props.output_directory.startswith("//") and not bpy.data.filepath:
        raise ValueError("Save the .blend file first, or use an absolute output folder")
    return os.path.abspath(bpy.path.abspath(props.output_directory))


class RCT_OT_render(bpy.types.Operator):
    """Render all sprites of the object and write them with the images JSON"""

    bl_idname = "rct_graphics.render"
    bl_label = "Render Sprites"

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def execute(self, context):
        props = context.scene.rct_graphics
        try:
            directory = output_directory(props)
            job_list = build_jobs(props)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        window_manager = context.window_manager
        window_manager.progress_begin(0, 1)

        def progress(done, total):
            window_manager.progress_update(done / total)

        try:
            sprites = render.run_jobs(
                context, job_list, postprocess_settings(props), progress, footprint(props)
            )
        finally:
            window_manager.progress_end()

        export.write_sprites(directory, sprites)
        self.report({"INFO"}, "Rendered {} sprites to {}".format(len(sprites), directory))
        return {"FINISHED"}


classes = (RCT_OT_initialize, RCT_OT_render)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
