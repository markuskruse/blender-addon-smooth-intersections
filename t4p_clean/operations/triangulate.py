"""Operator that triangulates selected mesh objects."""

from __future__ import annotations

from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.types import Operator

from ..debug import profile_module
from ..main import TRIANGULATE_OPERATOR_IDNAME, _triangulate_bmesh
from .modal_utils import ModalTimerMixin


@dataclass
class _TriangulateState:
    """Mutable state tracked while triangulating meshes."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    initial_active: bpy.types.Object | None = None
    triangulated_count: int = 0
    mesh_candidates: int = 0


class T4P_OT_triangulate_selected(ModalTimerMixin, Operator):
    """Triangulate all selected mesh objects."""

    bl_idname = TRIANGULATE_OPERATOR_IDNAME
    bl_label = "Triangulate Selected Meshes"
    bl_description = "Triangulate meshes for all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self) -> None:
        object.__setattr__(self, "_triangulate_state", _TriangulateState())

    @property
    def _state(self) -> _TriangulateState:
        return object.__getattribute__(self, "_triangulate_state")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return self._begin(context)

    def execute(self, context: bpy.types.Context):
        return self._begin(context)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        state = self._state
        if state.current_index >= len(state.objects_to_process):
            return self._finish_modal(context, cancelled=False)

        obj = state.objects_to_process[state.current_index]
        self._process_object(context, obj)
        state.current_index += 1
        self._update_modal_progress(state.current_index)
        return {"RUNNING_MODAL"}

    def _begin(self, context: bpy.types.Context):
        self._reset_state()
        state = self._state
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to triangulate meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        state.objects_to_process = selected_objects
        state.initial_active = context.view_layer.objects.active
        return self._start_modal(context, len(selected_objects))

    def _reset_state(self) -> None:
        state = self._state
        state.objects_to_process.clear()
        state.current_index = 0
        state.initial_active = None
        state.triangulated_count = 0
        state.mesh_candidates = 0

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        state = self._state
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

            state.mesh_candidates += 1
            if len(bm.faces) > num_faces:
                state.triangulated_count += 1
        finally:
            bm.free()

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        if (
            state.initial_active
            and context.scene.objects.get(state.initial_active.name) is not None
        ):
            context.view_layer.objects.active = state.initial_active

        if cancelled:
            self.report(
                {"WARNING"},
                "Triangulation cancelled before all objects were processed.",
            )
            return {"CANCELLED"}

        if state.mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif state.triangulated_count == 0:
            self.report({"INFO"}, "Selected meshes have no faces to triangulate.")
        else:
            self.report(
                {"INFO"},
                f"Triangulated: {state.triangulated_count}",
            )

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_triangulate_selected",)
