"""Operator that analyzes selected mesh objects for topology issues."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import (
    ANALYZE_OPERATOR_IDNAME,
    _triangulate_bmesh,
    bmesh_get_intersecting_face_indices,
    count_non_manifold_verts,
    get_bmesh,
)


def _triangulate_edit_mesh(mesh: bpy.types.Mesh) -> None:
    bm = get_bmesh(mesh)
    _triangulate_bmesh(bm)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)


def _count_non_manifold_vertices(mesh: bpy.types.Mesh) -> int:
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = get_bmesh(mesh)
    return int(count_non_manifold_verts(bm))


def _count_self_intersections(mesh: bpy.types.Mesh) -> int:
    bm = get_bmesh(mesh)
    return len(bmesh_get_intersecting_face_indices(bm))


class T4P_OT_analyze_selection(Operator):
    """Analyze selected mesh objects and store non-manifold and intersection counts."""

    bl_idname = ANALYZE_OPERATOR_IDNAME
    bl_label = "Analyze Selected Meshes"
    bl_description = (
        "Analyze selected mesh objects for non-manifold vertices and self-intersections"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to analyze objects.")
            return {"CANCELLED"}

        selected_objects = list(getattr(context, "selected_objects", []))
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        scene = context.scene
        mesh_objects = [
            obj
            for obj in selected_objects
            if obj.type == "MESH"
            and obj.data is not None
            and (scene is None or scene.objects.get(obj.name) is not None)
        ]
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            return {"FINISHED"}

        bpy.ops.object.select_all(action="DESELECT")

        initial_active = context.view_layer.objects.active
        analyses: list[tuple[str, int, int]] = []

        for obj in mesh_objects:
            context.view_layer.objects.active = obj
            obj.select_set(True)

            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except RuntimeError:
                obj.select_set(False)
                continue

            mesh = obj.data
            _triangulate_edit_mesh(mesh)
            non_manifold_count = _count_non_manifold_vertices(mesh)
            bpy.ops.mesh.select_all(action="DESELECT")
            intersection_count = _count_self_intersections(mesh)

            bpy.ops.object.mode_set(mode="OBJECT")
            obj.select_set(False)

            obj["t4p_non_manifold_count"] = int(non_manifold_count)
            obj["t4p_self_intersection_count"] = int(intersection_count)

            analyses.append((obj.name, non_manifold_count, intersection_count))

        if (
            initial_active
            and scene is not None
            and scene.objects.get(initial_active.name) is not None
        ):
            context.view_layer.objects.active = initial_active
        else:
            context.view_layer.objects.active = None

        if analyses:
            summary = "; ".join(
                f"{name}: non-manifold {non_manifold}, intersections {intersections}"
                for name, non_manifold, intersections in analyses
            )
            self.report({"INFO"}, f"Analyzed objects - {summary}")
        else:
            self.report({"INFO"}, "No mesh objects could be analyzed.")

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_analyze_selection",)
