"""Operator that triangulates selected mesh objects."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import TRIANGULATE_OPERATOR_IDNAME, _triangulate_bmesh


class T4P_OT_triangulate_selected(Operator):
    """Triangulate all selected mesh objects."""

    bl_idname = TRIANGULATE_OPERATOR_IDNAME
    bl_label = "Triangulate Selected Meshes"
    bl_description = "Triangulate meshes for all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to triangulate meshes.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        triangulated_objects = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            mesh = obj.data
            mesh_candidates += 1
            changed = False
            try:
                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh)
                    if _triangulate_bmesh(bm):
                        bm.to_mesh(mesh)
                        mesh.update()
                        changed = True
                finally:
                    bm.free()
            except RuntimeError:
                changed = False

            if changed:
                triangulated_objects.append(obj.name)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
        elif mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not triangulated_objects:
            self.report({"INFO"}, "Selected meshes have no faces to triangulate.")
        else:
            self.report(
                {"INFO"},
                "Triangulated: {}".format(
                    ", ".join(triangulated_objects)
                ),
            )

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_triangulate_selected",)
