"""Operator that triangulates selected mesh objects."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import TRIANGULATE_OPERATOR_IDNAME, _triangulate_bmesh
from .modal_utils import ModalTimerMixin


class T4P_OT_triangulate_selected(ModalTimerMixin, Operator):
    """Triangulate all selected mesh objects."""

    bl_idname = TRIANGULATE_OPERATOR_IDNAME
    bl_label = "Triangulate Selected Meshes"
    bl_description = "Triangulate meshes for all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self) -> None:
        self._objects_to_process: list[bpy.types.Object] = []
        self._current_index = 0
        self._initial_active: bpy.types.Object | None = None
        self._triangulated_count = 0
        self._mesh_candidates = 0

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return self._begin(context)

    def execute(self, context: bpy.types.Context):
        return self._begin(context)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        if self._current_index >= len(self._objects_to_process):
            return self._finish_modal(context, cancelled=False)

        obj = self._objects_to_process[self._current_index]
        self._process_object(context, obj)
        self._current_index += 1
        self._update_modal_progress(self._current_index)
        return {"RUNNING_MODAL"}

    def _begin(self, context: bpy.types.Context):
        self._reset_state()
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to triangulate meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        self._objects_to_process = selected_objects
        self._initial_active = context.view_layer.objects.active
        return self._start_modal(context, len(selected_objects))

    def _reset_state(self) -> None:
        self._objects_to_process = []
        self._current_index = 0
        self._initial_active = None
        self._triangulated_count = 0
        self._mesh_candidates = 0

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        if obj.type != "MESH" or obj.data is None:
            return

        scene = context.scene
        if scene is not None and scene.objects.get(obj.name) is None:
            return

        mesh = obj.data
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            num_faces = len(bm.faces)
            _triangulate_bmesh(bm)
            bm.to_mesh(mesh)
            mesh.update()

            self._mesh_candidates += 1
            if len(bm.faces) > num_faces:
                self._triangulated_count += 1
        finally:
            bm.free()

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)

        if (
            self._initial_active
            and context.scene.objects.get(self._initial_active.name) is not None
        ):
            context.view_layer.objects.active = self._initial_active

        if cancelled:
            self.report(
                {"WARNING"},
                "Triangulation cancelled before all objects were processed.",
            )
            return {"CANCELLED"}

        if self._mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif self._triangulated_count == 0:
            self.report({"INFO"}, "Selected meshes have no faces to triangulate.")
        else:
            self.report(
                {"INFO"},
                f"Triangulated: {self._triangulated_count}",
            )

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_triangulate_selected",)
