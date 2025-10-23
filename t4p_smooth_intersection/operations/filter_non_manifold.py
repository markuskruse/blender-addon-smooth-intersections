"""Operator that filters non-manifold mesh objects from the selection."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..main import FILTER_NON_MANIFOLD_OPERATOR_IDNAME


class T4P_OT_filter_non_manifold(Operator):
    """Deselect mesh objects that contain non-manifold geometry."""

    bl_idname = FILTER_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Filter Non Manifold"
    bl_description = "Deselect selected mesh objects with non-manifold geometry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to filter non-manifold meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        scene = context.scene
        non_manifold_list: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if scene is not None and scene.objects.get(obj.name) is None:
                continue

            mesh_candidates += 1

            context.view_layer.objects.active = obj
            obj.select_set(True)

            has_non_manifold = False
            try:
                bpy.ops.object.mode_set(mode="EDIT")
                bm = bmesh.from_edit_mesh(obj.data)
                bm.edges.ensure_lookup_table()
                has_non_manifold = any(not edge.is_manifold for edge in bm.edges)
            except RuntimeError:
                has_non_manifold = False
            finally:
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except RuntimeError:
                    pass

            obj.select_set(False)
            if has_non_manifold:
                non_manifold_list.append(obj)

        for obj in non_manifold_list:
            obj.select_set(True)

        remaining_selected = [obj for obj in context.selected_objects if obj.select_get()]

        if (
            initial_active
            and scene is not None
            and scene.objects.get(initial_active.name) is not None
            and initial_active in remaining_selected
        ):
            context.view_layer.objects.active = initial_active
        elif remaining_selected:
            context.view_layer.objects.active = remaining_selected[0]
        else:
            context.view_layer.objects.active = None

        if mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not non_manifold_list:
            self.report({"INFO"}, "All checked mesh objects are manifold.")
        else:
            self.report(
                {"INFO"},
                "Deselected non-manifold meshes: {}".format(
                    ", ".join(obj.name for obj in non_manifold_list)
                ),
            )

        return {"FINISHED"}


__all__ = ("T4P_OT_filter_non_manifold",)
