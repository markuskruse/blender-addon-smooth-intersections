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
)


def _deselect_edit_geometry() -> None:
    bpy.ops.mesh.select_all(action="DESELECT")


def _reveal_edit_geometry() -> None:
    bpy.ops.mesh.reveal(select=False)


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

        _deselect_edit_geometry()
        _reveal_edit_geometry()

        mesh = editable_object.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()

        face_indices = list(bmesh_get_intersecting_face_indices(bm))

        if not face_indices:
            bmesh.update_edit_mesh(mesh)
            self.report({"INFO"}, "No self-intersections detected.")
            return {"FINISHED"}

        selected = _select_faces_by_index(bm, face_indices)
        focus_location = _first_selected_face_center(bm)
        bmesh.update_edit_mesh(mesh)

        if focus_location is None:
            self.report(
                {"INFO"},
                f"Selected {selected} intersecting faces but could not find a face to focus on.",
            )
            return {"FINISHED"}

        if not _focus_view_on_location(context, focus_location):
            self.report(
                {"INFO"},
                "Selected intersecting faces but could not focus the 3D Viewport.",
            )
            return {"FINISHED"}

        self.report(
            {"INFO"},
            f"Focused on the first of {selected} intersecting faces.",
        )
        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_select_intersections", "T4P_OT_focus_intersections")
