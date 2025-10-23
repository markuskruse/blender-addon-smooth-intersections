"""Operator definitions for the T4P Smooth Intersection add-on."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator
from mathutils.bvhtree import BVHTree

OPERATOR_IDNAME = "t4p_smooth_intersection.smooth_intersections"


def _mode_from_context(mode: str) -> str:
    """Convert a context mode string to a value accepted by ``mode_set``."""

    if mode == "OBJECT":
        return "OBJECT"
    if mode.startswith("EDIT_"):
        return "EDIT"
    if mode == "POSE":
        return "POSE"
    if mode == "SCULPT":
        return "SCULPT"
    if mode == "PAINT_WEIGHT":
        return "WEIGHT_PAINT"
    if mode == "PAINT_VERTEX":
        return "VERTEX_PAINT"
    if mode == "PAINT_TEXTURE":
        return "TEXTURE_PAINT"
    if mode == "PARTICLE":
        return "PARTICLE_EDIT"
    if mode == "PAINT_GPENCIL":
        return "PAINT_GPENCIL"
    if mode == "SCULPT_GPENCIL":
        return "SCULPT_GPENCIL"
    if mode == "EDIT_GPENCIL":
        return "EDIT_GPENCIL"
    if mode == "WEIGHT_GPENCIL":
        return "WEIGHT_GPENCIL"
    if mode == "VERTEX_GPENCIL":
        return "VERTEX_GPENCIL"
    return "OBJECT"


def _select_intersecting_faces(mesh: bpy.types.Mesh) -> int:
    """Select intersecting faces of the mesh in edit mode.

    Returns the number of faces that were selected.
    """

    bm = bmesh.from_edit_mesh(mesh)
    if not bm.faces:
        return 0

    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    if tree is None:
        return 0

    intersection_indices = set()
    for index_a, index_b in tree.overlap(tree):
        if index_a == index_b or index_b < index_a:
            continue
        face_a = bm.faces[index_a]
        face_b = bm.faces[index_b]

        verts_a = {vert.index for vert in face_a.verts}
        verts_b = {vert.index for vert in face_b.verts}
        if verts_a & verts_b:
            continue

        intersection_indices.add(index_a)
        intersection_indices.add(index_b)

    for face in bm.faces:
        face.select_set(face.index in intersection_indices)

    bmesh.update_edit_mesh(mesh)
    return len(intersection_indices)


def _grow_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_more()


def _shrink_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_less()


def _process_object(obj: bpy.types.Object) -> int:
    """Run the smoothing workflow on a single mesh object.

    Returns the number of attempts that performed smoothing.
    """

    mesh = obj.data
    smoothed_attempts = 0

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")

    bm = bmesh.from_edit_mesh(mesh)
    if bm.faces:
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.update_edit_mesh(mesh)

    try:
        for _ in range(3):
            face_count = _select_intersecting_faces(mesh)
            if face_count == 0:
                break

            _grow_selection(2)
            _shrink_selection(1)
            bpy.ops.mesh.vertices_smooth(repeat=1)
            smoothed_attempts += 1
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return smoothed_attempts


class T4P_OT_smooth_intersections(Operator):
    """Smooth intersecting faces across all mesh objects."""

    bl_idname = OPERATOR_IDNAME
    bl_label = "Smooth Intersections"
    bl_description = "Smooth intersecting faces for every mesh object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        initial_mode = context.mode
        initial_active = context.view_layer.objects.active
        initial_selection = list(context.selected_objects)

        if initial_mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                pass

        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Unable to switch to Object mode for smoothing.")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")

        smoothed_objects: List[str] = []

        for obj in context.scene.objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if context.view_layer.objects.get(obj.name) is None:
                continue

            obj.select_set(True)
            context.view_layer.objects.active = obj

            try:
                attempts = _process_object(obj)
            except RuntimeError:
                attempts = 0
            finally:
                obj.select_set(False)

            if attempts:
                smoothed_objects.append(obj.name)

        bpy.ops.object.select_all(action="DESELECT")

        for obj in initial_selection:
            if context.scene.objects.get(obj.name) is not None:
                obj.select_set(True)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        target_mode = _mode_from_context(initial_mode)
        if target_mode != "OBJECT" and initial_active:
            try:
                bpy.ops.object.mode_set(mode=target_mode)
            except RuntimeError:
                pass

        if not smoothed_objects:
            self.report({"INFO"}, "No intersecting faces were found.")
        else:
            self.report(
                {"INFO"},
                "Smoothed intersections on: {}".format(
                    ", ".join(smoothed_objects)
                ),
            )

        return {"FINISHED"}


classes = (T4P_OT_smooth_intersections,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


__all__ = ("register", "unregister", "OPERATOR_IDNAME", "T4P_OT_smooth_intersections")
