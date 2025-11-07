"""Operator that selects non-manifold geometry in Edit mode."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector

from ..debug import profile_module
from ..main import (
    FOCUS_NON_MANIFOLD_OPERATOR_IDNAME,
    SELECT_NON_MANIFOLD_OPERATOR_IDNAME,
    select_non_manifold_verts,
    select_faces,
    select_verts,
    get_bmesh,
    focus_view_on_selected_faces,
    get_selected_faces,
    get_selected_edges,
    get_selected_verts,
    set_object_analysis_stats,
)


def _select_faces_linked_to_selection(bm: bmesh.types.BMesh) -> int:
    bm.faces.ensure_lookup_table()
    visited: set[int] = set()

    for edge in bm.edges:
        if not edge.select:
            continue

        for face in edge.link_faces:
            if face.index in visited:
                continue
            face.select_set(True)
            face.hide_set(False)
            visited.add(face.index)

    for vert in bm.verts:
        if not vert.select:
            continue

        for face in vert.link_faces:
            if face.index in visited:
                continue
            face.select_set(True)
            face.hide_set(False)
            visited.add(face.index)

    return len(visited)


def _first_selected_face_center(bm: bmesh.types.BMesh) -> Vector | None:
    bm.faces.ensure_lookup_table()

    for face in bm.faces:
        if face.select:
            bm.faces.active = face
            return face.calc_center_median()

    return None


class T4P_OT_select_non_manifold(Operator):
    """Select all non-manifold geometry in the active mesh."""

    bl_idname = SELECT_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Select Non Manifold"
    bl_description = "Select edges and vertices that are not manifold"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        bpy.ops.mesh.select_all(action="DESELECT")
        select_non_manifold_verts(
            use_wire=True,
            use_boundary=True,
            use_multi_face=True,
            use_non_contiguous=True,
            use_verts=True,
        )

        editable_object = context.edit_object
        mesh = getattr(editable_object, "data", None)
        if mesh is not None:
            bm = get_bmesh(mesh)
            non_manifold_count = len(get_selected_verts(bm))
            set_object_analysis_stats(editable_object, non_manifold_count=non_manifold_count)
            bmesh.update_edit_mesh(mesh)

        return {"FINISHED"}


class T4P_OT_focus_non_manifold(Operator):
    """Select non-manifold geometry and focus the viewport on it."""

    bl_idname = FOCUS_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Focus on Non Manifold"
    bl_description = "Select non-manifold geometry and focus the viewport on the first face"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        editable_object = context.edit_object

        mesh = editable_object.data
        bpy.ops.mesh.reveal(select=False)
        bpy.ops.mesh.select_all(action="DESELECT")

        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        select_non_manifold_verts(
            use_wire=True,
            use_boundary=True,
            use_multi_face=True,
            use_non_contiguous=True,
            use_verts=True,
        )

        bm = get_bmesh(mesh)
        selected_faces = get_selected_faces(bm)
        selected_edges = get_selected_edges(bm)
        selected_verts = get_selected_verts(bm)
        non_manifold_count = len(selected_verts)
        set_object_analysis_stats(editable_object, non_manifold_count=non_manifold_count)
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = get_bmesh(mesh)
        if selected_faces:
            first_face = [selected_faces[0].index]
            select_faces(first_face, mesh, bm)
        elif selected_edges:
            first_face = [selected_edges[0].link_faces[0].index]
            select_faces(first_face, mesh, bm)
        elif selected_verts:
            if len(selected_verts[0].link_faces):
                first_face = [selected_verts[0].link_faces[0].index]
                select_faces(first_face, mesh, bm)
            else:
                vert_index = [selected_verts[0].index]
                select_verts(vert_index, mesh, bm)
        else:
            self.report({"INFO"}, "No non manifold geometry were found.")
            return {"CANCELLED"}

        bmesh.update_edit_mesh(mesh)

        focus_view_on_selected_faces(context)

        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        select_non_manifold_verts(
            use_wire=True,
            use_boundary=True,
            use_multi_face=True,
            use_non_contiguous=True,
            use_verts=True,
        )

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_non_manifold", "T4P_OT_focus_non_manifold")
