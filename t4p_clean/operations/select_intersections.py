"""Operator that selects faces with self-intersections in Edit mode."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import (
    SELECT_INTERSECTIONS_OPERATOR_IDNAME,
    bmesh_get_intersecting_face_indices,
)


def _deselect_edit_geometry() -> None:
    bpy.ops.mesh.select_all(action="DESELECT")


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
        if context.mode != "EDIT_MESH":
            self.report({"ERROR"}, "Switch to Edit mode to select intersections.")
            return {"CANCELLED"}

        editable_object = context.edit_object
        if (
            editable_object is None
            or editable_object.type != "MESH"
            or editable_object.data is None
        ):
            self.report({"INFO"}, "No editable mesh object selected.")
            return {"CANCELLED"}

        _deselect_edit_geometry()

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        face_indices = list(bmesh_get_intersecting_face_indices(bm))

        if not face_indices:
            bmesh.update_edit_mesh(mesh)
            self.report({"INFO"}, "No self-intersections detected.")
            return {"FINISHED"}

        selected = _select_faces_by_index(bm, face_indices)
        bmesh.update_edit_mesh(mesh)

        self.report({"INFO"}, f"Selected {selected} intersecting faces.")
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_intersections",)
