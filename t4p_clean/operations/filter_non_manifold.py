"""Operator that filters non-manifold mesh objects from the selection."""

from __future__ import annotations

from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound, _play_warning_sound
from ..debug import profile_module
from ..main import (
    FILTER_NON_MANIFOLD_OPERATOR_IDNAME,
    count_non_manifold_verts,
    get_bmesh,
    get_cached_non_manifold_count,
    set_object_analysis_stats,
)
from .modal_utils import ModalTimerMixin


@dataclass
class _FilterNonManifoldState:
    """Mutable state tracked while filtering non-manifold meshes."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    initial_active: bpy.types.Object | None = None
    initial_selection: list[bpy.types.Object] = field(default_factory=list)
    non_manifold_objects: list[bpy.types.Object] = field(default_factory=list)
    mesh_candidates: int = 0
    scene: bpy.types.Scene | None = None


class T4P_OT_filter_non_manifold(ModalTimerMixin, Operator):
    """Deselect mesh objects that contain non-manifold geometry."""

    bl_idname = FILTER_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Filter Non Manifold"
    bl_description = "Deselect selected mesh objects with non-manifold geometry"
    bl_options = {"REGISTER", "UNDO"}
    t4p_disable_long_running_sound = True

    def __init__(self) -> None:
        object.__setattr__(self, "_filter_non_manifold_state", _FilterNonManifoldState())

    @property
    def _state(self) -> _FilterNonManifoldState:
        return object.__getattribute__(self, "_filter_non_manifold_state")

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
            self.report({"ERROR"}, "Switch to Object mode to filter non-manifold meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        state.initial_active = context.view_layer.objects.active
        state.initial_selection = selected_objects
        state.objects_to_process = selected_objects
        state.scene = context.scene

        bpy.ops.object.select_all(action="DESELECT")

        return self._start_modal(context, len(selected_objects))

    def _reset_state(self) -> None:
        state = self._state
        state.objects_to_process.clear()
        state.current_index = 0
        state.initial_active = None
        state.initial_selection.clear()
        state.non_manifold_objects.clear()
        state.mesh_candidates = 0
        state.scene = None

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        state = self._state
        if obj.type != "MESH" or obj.data is None:
            return

        if state.scene is not None and state.scene.objects.get(obj.name) is None:
            return

        state.mesh_candidates += 1
        cached_count = get_cached_non_manifold_count(obj)
        if cached_count is not None:
            if cached_count > 0:
                state.non_manifold_objects.append(obj)
            return

        context.view_layer.objects.active = obj
        obj.select_set(True)

        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except RuntimeError:
            obj.select_set(False)
            return

        bm = get_bmesh(obj.data)
        non_manifold_count = count_non_manifold_verts(bm)

        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)

        set_object_analysis_stats(obj, non_manifold_count=non_manifold_count)

        if non_manifold_count > 0:
            state.non_manifold_objects.append(obj)

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        if cancelled:
            self._restore_initial_selection(context)
            self.report(
                {"WARNING"},
                "Filtering non-manifold meshes cancelled before completion.",
            )
            _play_warning_sound(context)
            return {"CANCELLED"}

        for obj in state.non_manifold_objects:
            obj.select_set(True)

        remaining_selected = [obj for obj in state.non_manifold_objects if obj.select_get()]
        self._assign_new_active(context, remaining_selected)

        if state.mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not state.non_manifold_objects:
            self.report({"INFO"}, "All checked mesh objects are manifold.")
            _play_happy_sound(context)
        elif len(state.non_manifold_objects) == state.mesh_candidates:
            self.report({"WARNING"}, "All checked mesh objects are not manifold.")
            _play_warning_sound(context)
        else:
            self.report(
                {"WARNING"},
                f"Deselected non-manifold meshes, {len(state.non_manifold_objects)} remain.",
            )
            _play_warning_sound(context)

        return {"FINISHED"}

    def _restore_initial_selection(self, context: bpy.types.Context) -> None:
        bpy.ops.object.select_all(action="DESELECT")

        state = self._state

        for obj in state.initial_selection:
            if state.scene is not None and state.scene.objects.get(obj.name) is None:
                continue
            obj.select_set(True)

        if (
            state.initial_active
            and state.scene is not None
            and state.scene.objects.get(state.initial_active.name) is not None
        ):
            context.view_layer.objects.active = state.initial_active
        else:
            context.view_layer.objects.active = None

    def _assign_new_active(
        self, context: bpy.types.Context, remaining_selected: list[bpy.types.Object]
    ) -> None:
        state = self._state
        if (
            state.initial_active
            and state.scene is not None
            and state.scene.objects.get(state.initial_active.name) is not None
            and state.initial_active in remaining_selected
        ):
            context.view_layer.objects.active = state.initial_active
        elif remaining_selected:
            context.view_layer.objects.active = remaining_selected[0]
        else:
            context.view_layer.objects.active = None


profile_module(globals())


__all__ = ("T4P_OT_filter_non_manifold",)
