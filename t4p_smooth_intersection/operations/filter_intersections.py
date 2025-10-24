"""Operator that filters selected objects by self-intersections."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ..main import (
    FILTER_OPERATOR_IDNAME,
    _play_happy_sound,
    _play_warning_sound,
    _select_intersecting_faces_on_mesh,
)


class T4P_OT_filter_intersections(Operator):
    """Keep selected only the mesh objects that have intersections."""

    bl_idname = FILTER_OPERATOR_IDNAME
    bl_label = "Filter Intersections"
    bl_description = "Deselect selected objects without self-intersections"
    bl_options = {"REGISTER", "UNDO"}
    t4p_disable_long_running_sound = True

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to filter intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        objects_with_intersections: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            has_intersections = False
            if obj.type == "MESH" and obj.data is not None:
                mesh_candidates += 1
                try:
                    face_count = _select_intersecting_faces_on_mesh(obj.data)
                except RuntimeError:
                    face_count = 0
                has_intersections = face_count > 0

            obj.select_set(has_intersections)

            if has_intersections:
                objects_with_intersections.append(obj)

        new_active = None
        if initial_active and initial_active in objects_with_intersections:
            new_active = initial_active
        elif objects_with_intersections:
            new_active = objects_with_intersections[0]

        context.view_layer.objects.active = new_active

        if not objects_with_intersections:
            if mesh_candidates == 0:
                self.report({"INFO"}, "No mesh objects selected.")
            else:
                self.report(
                    {"INFO"}, "No self-intersections detected on selected objects."
                )
                _play_happy_sound(context)
        else:
            self.report(
                {"INFO"},
                "Objects with self-intersections: {}".format(
                    ", ".join(obj.name for obj in objects_with_intersections)
                ),
            )
            _play_warning_sound(context)

        return {"FINISHED"}


__all__ = ("T4P_OT_filter_intersections",)
