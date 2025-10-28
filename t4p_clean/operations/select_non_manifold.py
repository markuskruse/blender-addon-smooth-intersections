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
)


def _deselect_edit_geometry() -> None:
    bpy.ops.mesh.select_all(action="DESELECT")


def _reveal_edit_geometry() -> None:
    bpy.ops.mesh.reveal(select=False)


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


def _focus_view_on_location(context: bpy.types.Context, location: Vector | None) -> bool:
    if location is None or context.screen is None:
        return False

    view_area = next((area for area in context.screen.areas if area.type == "VIEW_3D"), None)
    if view_area is None:
        return False

    region = next((region for region in view_area.regions if region.type == "WINDOW"), None)
    if region is None:
        return False

    space = view_area.spaces.active
    region_3d = getattr(space, "region_3d", None)
    if region_3d is None:
        return False

    region_3d.view_location = location

    override = context.copy()
    override["area"] = view_area
    override["region"] = region
    override["space_data"] = space

    try:
        bpy.ops.view3d.view_selected(override, use_all_regions=False)
    except RuntimeError:
        return False

    return True


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


class T4P_OT_focus_non_manifold(Operator):
    """Select non-manifold geometry and focus the viewport on it."""

    bl_idname = FOCUS_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Focus on Non Manifold"
    bl_description = "Select non-manifold geometry and focus the viewport on the first face"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "EDIT_MESH":
            self.report({"ERROR"}, "Switch to Edit mode to focus on non-manifold geometry.")
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
        _reveal_edit_geometry()

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)

        select_non_manifold_verts(
            use_wire=True,
            use_boundary=True,
            use_multi_face=True,
            use_non_contiguous=True,
            use_verts=True,
        )

        selected_vertices, selected_edges, selected_faces = _reveal_selected_elements(bm)
        additional_faces = _select_faces_linked_to_selection(bm)
        focus_location = _first_selected_face_center(bm)
        bmesh.update_edit_mesh(mesh)

        if not any((selected_vertices, selected_edges, selected_faces, additional_faces)):
            self.report({"INFO"}, "All visible geometry is manifold.")
            return {"FINISHED"}

        if focus_location is None:
            self.report(
                {"INFO"},
                "Selected non-manifold geometry but could not find a face to focus on.",
            )
            return {"FINISHED"}

        if not _focus_view_on_location(context, focus_location):
            self.report(
                {"INFO"},
                "Selected non-manifold geometry but could not focus the 3D Viewport.",
            )
            return {"FINISHED"}

        total_faces = selected_faces + additional_faces
        parts = []
        if selected_vertices:
            parts.append(f"{selected_vertices} vertices")
        if selected_edges:
            parts.append(f"{selected_edges} edges")
        if total_faces:
            parts.append(f"{total_faces} faces")
        summary = ", ".join(parts)

        self.report(
            {"INFO"},
            f"Focused on non-manifold geometry: {summary}.",
        )
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_non_manifold", "T4P_OT_focus_non_manifold")
