"""Operator that filters selected objects by self-intersections."""

from __future__ import annotations

import array

import bmesh
import bpy
from bpy.types import Operator

import t4p_clean.main
from ..debug import profile_module
from ..main import (
    FILTER_OPERATOR_IDNAME,
    _play_happy_sound,
    _play_warning_sound,
    _get_bmesh
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
            face_indices = array.array("i", ())
            if obj.type == "MESH" and obj.data is not None:
                mesh_candidates += 1
                mesh = obj.data
                bm = _get_bmesh(mesh)

                face_indices = t4p_clean.main.bmesh_check_self_intersect_object(bm)

                if face_indices:
                    polygons = obj.data.polygons
                    if polygons:
                        selection = [False] * len(polygons)
                        for index in face_indices:
                            if 0 <= index < len(selection):
                                selection[index] = True
                        polygons.foreach_set("select", selection)
                        obj.data.update()

            has_intersections = bool(face_indices)
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
                self.report({"WARNING"}, "No mesh objects selected.")
            else:
                self.report({"INFO"}, "No self-intersections detected on selected objects.")
                _play_happy_sound(context)
        else:
            self.report({"INFO"}, "{} objects of {} with self-intersections.".format(len()))
            _play_warning_sound(context)

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_filter_intersections",)
