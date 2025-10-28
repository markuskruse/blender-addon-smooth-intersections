"""Operator that selects faces with self-intersections in Edit mode."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector

from ..debug import profile_module
from ..main import (
    FOCUS_INTERSECTIONS_OPERATOR_IDNAME,
    SELECT_INTERSECTIONS_OPERATOR_IDNAME,
    bmesh_get_intersecting_face_indices,
    focus_view_on_selected_faces,
    select_faces,
    set_object_analysis_stats,
)



def _select_faces_by_index(bm: bmesh.types.BMesh, indices: list[int]) -> int:
    bm.faces.ensure_lookup_table()
    selected = 0

    for index in indices:
        if index < 0 or index >= len(bm.faces):
            continue

        face = bm.faces[index]
        face.hide_set(False)
        face.select_set(True)
        selected += 1

    return selected


class T4P_OT_select_intersections(Operator):
    """Select all faces that are part of self-intersections."""

    bl_idname = SELECT_INTERSECTIONS_OPERATOR_IDNAME
    bl_label = "Select Intersections"
    bl_description = "Select faces that are part of self-intersections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        editable_object = context.edit_object

        bpy.ops.mesh.reveal(select=False)
        bpy.ops.mesh.select_all(action="DESELECT")

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        face_indices = list(bmesh_get_intersecting_face_indices(bm))
        intersection_count = len(face_indices)
        set_object_analysis_stats(editable_object, intersection_count=intersection_count)

        if not face_indices:
            bmesh.update_edit_mesh(mesh)
            self.report({"INFO"}, "No self-intersections detected.")
            return {"FINISHED"}

        selected = _select_faces_by_index(bm, face_indices)
        bmesh.update_edit_mesh(mesh)

        self.report({"INFO"}, f"Selected {selected} intersecting faces.")
        return {"FINISHED"}


class T4P_OT_focus_intersections(Operator):
    """Select intersecting faces and focus the viewport on the first one."""

    bl_idname = FOCUS_INTERSECTIONS_OPERATOR_IDNAME
    bl_label = "Focus on Intersections"
    bl_description = "Select intersecting faces and focus the viewport on the first one"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "EDIT_MESH":
            self.report({"ERROR"}, "Switch to Edit mode to focus on intersections.")
            return {"CANCELLED"}

        editable_object = context.edit_object
        if (
            editable_object is None
            or editable_object.type != "MESH"
            or editable_object.data is None
        ):
            self.report({"INFO"}, "No editable mesh object selected.")
            return {"CANCELLED"}

        bpy.ops.mesh.reveal(select=False)
        bpy.ops.mesh.select_all(action="DESELECT")

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        face_indices = list(bmesh_get_intersecting_face_indices(bm))
        intersection_count = len(face_indices)
        set_object_analysis_stats(editable_object, intersection_count=intersection_count)

        if not face_indices:
            self.report({"INFO"}, "No intersecting faces detected.")
            return {"CANCELLED"}
        first_face = [face_indices[0]]
        select_faces(first_face, mesh, bm)

        focus_view_on_selected_faces(context)

        select_faces(face_indices, mesh, bm)
        bmesh.update_edit_mesh(mesh)

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_intersections", "T4P_OT_focus_intersections")
