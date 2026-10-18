import os
import shutil

import bpy

from . import preferences, render, scene_setup
from .properties import flag_property, selected_ramps
from .core import alignment, export, jobs, objectjson, postprocess


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
        ramps=selected_ramps(props),
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
        return jobs.small_scenery(props.small_shape, frames, props.start_index)
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


def render_sprites(context):
    """Render every sprite and write them with images.json; returns a status message."""
    props = context.scene.rct_graphics
    directory = output_directory(props)
    job_list = build_jobs(props)

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
    message = "Rendered {} sprites to {}".format(len(sprites), directory)
    if props.check_after_render:
        from . import alignment_tools

        lines, path = alignment_tools.run_check(context)
        alignment_tools.store_report(context.scene, lines)
        if path is not None:
            alignment_tools.show_preview(context, path)
        problems = sum(1 for line in lines if line.startswith("FIX"))
        if problems:
            message += "; {} alignment problem(s), see the RCT panel".format(problems)
    return message


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
            if props.build_parkobj:
                check_object_id(props)
            message = render_sprites(context)
            if props.build_parkobj:
                message += "; " + export_parkobj(context)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}


def object_info(context, directory):
    props = context.scene.rct_graphics
    info = objectjson.ObjectInfo(
        props.object_id,
        props.object_name,
        [a.strip() for a in props.object_authors.split(",")],
        props.object_type,
    )
    info.price = props.price
    info.removal_price = props.removal_price
    info.scenery_group = props.scenery_group
    info.shape = props.small_shape
    info.frames = props.animation_frames if props.object_type == "SMALL" else 1
    info.animation_delay = props.animation_delay
    info.footprint = footprint(props)
    info.wall_double_sided = props.wall_double_sided
    info.wall_sloped = props.wall_sloped
    info.flags = {
        key: getattr(props, flag_property(props.object_type, key))
        for key, _, _, _ in objectjson.OBJECT_FLAGS[props.object_type]
    }
    info.remaps = objectjson.used_remaps(directory)
    points = render.scene_bounds_points(context.scene, context.view_layer)
    if len(points):
        info.clearance = alignment.clearance_from_height(points[:, 2].max())
    return info


def check_object_id(props):
    if not props.object_id.strip():
        raise ValueError("Set an object ID first")


def export_parkobj(context):
    """Write object.json and the .parkobj; returns a status message."""
    props = context.scene.rct_graphics
    check_object_id(props)
    directory = output_directory(props)
    if not os.path.exists(os.path.join(directory, export.IMAGES_JSON)):
        raise ValueError("Render the sprites first")
    path = objectjson.write_parkobj(directory, object_info(context, directory))
    message = "wrote " + os.path.basename(path)
    if props.copy_to_openrct2:
        target = preferences.openrct2_object_directory(context)
        if target is None:
            raise ValueError("Set the OpenRCT2 folder in the add-on preferences")
        os.makedirs(target, exist_ok=True)
        shutil.copy2(path, os.path.join(target, os.path.basename(path)))
        message += " and copied it to " + target
    return message


class RCT_OT_export_parkobj(bpy.types.Operator):
    """Render the sprites, write object.json (keeping manual edits) and pack them into a .parkobj"""

    bl_idname = "rct_graphics.export_parkobj"
    bl_label = "Build .parkobj"

    @classmethod
    def poll(cls, context):
        return scene_setup.get_rig(context.scene)[0] is not None

    def execute(self, context):
        try:
            check_object_id(context.scene.rct_graphics)
            message = render_sprites(context) + "; " + export_parkobj(context)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}


classes = (RCT_OT_initialize, RCT_OT_render, RCT_OT_export_parkobj)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
