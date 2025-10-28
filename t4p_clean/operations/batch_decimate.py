"""Operator for batch decimating selected mesh objects."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound
from ..debug import profile_module
from ..main import BATCH_DECIMATE_OPERATOR_IDNAME


class T4P_OT_batch_decimate(Operator):
    """Apply a decimate modifier to all selected mesh objects."""

    bl_idname = BATCH_DECIMATE_OPERATOR_IDNAME
    bl_label = "Batch Decimate Selected Meshes"
    bl_description = "Apply the decimate modifier to all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to batch decimate objects.")
            return {"CANCELLED"}

        scene = context.scene
        ratio = float(getattr(scene, "t4p_batch_decimate_ratio", 0.5))
        if ratio <= 0.0 or ratio > 1.0:
            self.report({"ERROR"}, "Decimation ratio must be greater than 0 and at most 1.")
            return {"CANCELLED"}

        selected_objects = list(getattr(context, "selected_objects", []))
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            _play_happy_sound(context)
            return {"FINISHED"}

        mesh_objects = [
            obj for obj in selected_objects if obj.type == "MESH" and obj.data is not None
        ]
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            _play_happy_sound(context)
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        decimated_objects: list[str] = []

        for obj in mesh_objects:
            context.view_layer.objects.active = obj
            try:
                modifier = obj.modifiers.new(name="T4P_BatchDecimate", type="DECIMATE")
            except (RuntimeError, ValueError):
                continue

            modifier.show_viewport = False
            modifier.show_render = False
            if hasattr(modifier, "decimate_type"):
                modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio

            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except RuntimeError:
                if obj.modifiers.get(modifier.name) is not None:
                    obj.modifiers.remove(modifier)
                continue

            decimated_objects.append(obj.name)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        if decimated_objects:
            object_list = ", ".join(decimated_objects)
            self.report({"INFO"}, f"Decimated: {object_list}")
        else:
            self.report({"INFO"}, "Decimation modifiers could not be applied.")

        _play_happy_sound(context)
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_batch_decimate",)
