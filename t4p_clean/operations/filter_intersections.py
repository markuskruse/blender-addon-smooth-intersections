"""Operator that filters selected objects by self-intersections."""

from __future__ import annotations

import array

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import (
    FILTER_OPERATOR_IDNAME,
    bmesh_get_intersecting_face_indices,
    select_faces
)
from ..audio import _play_happy_sound, _play_warning_sound


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

        bpy.ops.object.select_all(action='DESELECT')

        objects_with_intersections: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            face_indices = array.array("i", ())
            if obj.type == "MESH" and obj.data is not None:
                mesh_candidates += 1
                context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.mode_set(mode="EDIT")
                bm = bmesh.from_edit_mesh(obj.data)
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()

                face_indices = bmesh_get_intersecting_face_indices(bm)
                bpy.ops.object.mode_set(mode="OBJECT")
                obj.select_set(False)

            if bool(face_indices):
                objects_with_intersections.append(obj)

        for obj in objects_with_intersections:
            obj.select_set(True)

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
            self.report({"INFO"}, "{} objects of {} with self-intersections.".format(len(objects_with_intersections), mesh_candidates))
            _play_warning_sound(context)

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_filter_intersections",)
