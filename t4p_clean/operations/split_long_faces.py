"""Operator for splitting long faces in edit mode."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import SPLIT_LONG_FACES_OPERATOR_IDNAME, get_bmesh
from ..split_long import split_selection


class T4P_OT_split_long_faces(Operator):
    """Split long faces for the current edit-mode selection."""

    bl_idname = SPLIT_LONG_FACES_OPERATOR_IDNAME
    bl_label = "Split Long Faces"
    bl_description = "Split long faces for the currently selected faces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        if context.mode != "EDIT_MESH":
            self.report({"ERROR"}, "Switch to Edit mode to split long faces.")
            return {"CANCELLED"}

        edit_object = context.edit_object or context.active_object
        if edit_object is None or edit_object.type != "MESH" or edit_object.data is None:
            self.report({"ERROR"}, "No editable mesh object available.")
            return {"CANCELLED"}

        mesh = edit_object.data
        bm = get_bmesh(mesh)
        split_selection(bm)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        self.report({"INFO"}, "Split long faces on the selected geometry.")
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_split_long_faces",)
