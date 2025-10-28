"""Operator that selects non-manifold geometry in Edit mode."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import SELECT_NON_MANIFOLD_OPERATOR_IDNAME, select_non_manifold_verts


def _deselect_edit_geometry() -> None:
    bpy.ops.mesh.select_all(action="DESELECT")


def _reveal_selected_elements(bm: bmesh.types.BMesh) -> tuple[int, int, int]:
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    selected_vertices = 0
    selected_edges = 0
    selected_faces = 0

    for vert in bm.verts:
        if vert.select:
            vert.hide_set(False)
            selected_vertices += 1

    for edge in bm.edges:
        if edge.select:
            edge.hide_set(False)
            selected_edges += 1

    for face in bm.faces:
        if face.select:
            face.hide_set(False)
            selected_faces += 1

    return selected_vertices, selected_edges, selected_faces


class T4P_OT_select_non_manifold(Operator):
    """Select all non-manifold geometry in the active mesh."""

    bl_idname = SELECT_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Select Non Manifold"
    bl_description = "Select edges and vertices that are not manifold"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "EDIT_MESH":
            self.report({"ERROR"}, "Switch to Edit mode to select non-manifold geometry.")
            return {"CANCELLED"}

        editable_object = context.edit_object
        if (
            editable_object is None
            or editable_object.type != "MESH"
            or editable_object.data is None
        ):
            self.report({"INFO"}, "No editable mesh object selected.")
            return {"CANCELLED"}

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)

        _deselect_edit_geometry()
        select_non_manifold_verts(
            use_wire=True,
            use_boundary=True,
            use_multi_face=True,
            use_non_contiguous=True,
            use_verts=True,
        )

        selected_vertices, selected_edges, selected_faces = _reveal_selected_elements(bm)

        if not any((selected_vertices, selected_edges, selected_faces)):
            bmesh.update_edit_mesh(mesh)
            self.report({"INFO"}, "All visible geometry is manifold.")
            return {"FINISHED"}

        bmesh.update_edit_mesh(mesh)

        parts = []
        if selected_vertices:
            parts.append(f"{selected_vertices} vertices")
        if selected_edges:
            parts.append(f"{selected_edges} edges")
        if selected_faces:
            parts.append(f"{selected_faces} faces")
        summary = ", ".join(parts)

        self.report({"INFO"}, f"Selected non-manifold geometry: {summary}.")
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_non_manifold",)
