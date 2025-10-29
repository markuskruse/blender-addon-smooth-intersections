"""Operator that filters selected objects by self-intersections."""

from __future__ import annotations

from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound, _play_warning_sound
from ..debug import profile_module
from ..main import (
    FILTER_OPERATOR_IDNAME,
    bmesh_get_intersecting_face_indices,
    get_cached_self_intersection_count,
    set_object_analysis_stats,
)
from .modal_utils import ModalTimerMixin


@dataclass
class _FilterIntersectionsState:
    """Mutable state tracked while filtering intersections."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    initial_active: bpy.types.Object | None = None
    initial_selection: list[bpy.types.Object] = field(default_factory=list)
    objects_with_intersections: list[bpy.types.Object] = field(default_factory=list)
    mesh_candidates: int = 0
    scene: bpy.types.Scene | None = None


class T4P_OT_filter_intersections(ModalTimerMixin, Operator):
    """Keep selected only the mesh objects that have intersections."""

    bl_idname = FILTER_OPERATOR_IDNAME
    bl_label = "Filter Intersections"
    bl_description = "Deselect selected objects without self-intersections"
    bl_options = {"REGISTER", "UNDO"}
    t4p_disable_long_running_sound = True

    def __init__(self) -> None:
        object.__setattr__(self, "_filter_intersections_state", _FilterIntersectionsState())

    @property
    def _state(self) -> _FilterIntersectionsState:
        return object.__getattribute__(self, "_filter_intersections_state")

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
            self.report({"ERROR"}, "Switch to Object mode to filter intersections.")
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
        state.objects_with_intersections.clear()
        state.mesh_candidates = 0
        state.scene = None

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        state = self._state
        if obj.type != "MESH" or obj.data is None:
            return

        if state.scene is not None and state.scene.objects.get(obj.name) is None:
            return

        state.mesh_candidates += 1
        cached_intersections = get_cached_self_intersection_count(obj)
        if cached_intersections is not None:
            if cached_intersections > 0:
                state.objects_with_intersections.append(obj)
            return

        context.view_layer.objects.active = obj
        obj.select_set(True)

        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except RuntimeError:
            obj.select_set(False)
            return

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        face_indices = bmesh_get_intersecting_face_indices(bm)
        intersection_count = len(face_indices)

        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)

        set_object_analysis_stats(obj, intersection_count=intersection_count)

        if face_indices:
            state.objects_with_intersections.append(obj)

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        if cancelled:
            self._restore_initial_selection(context)
            self.report(
                {"WARNING"},
                "Filtering intersections cancelled before completion.",
            )
            _play_warning_sound(context)
            return {"CANCELLED"}

        for obj in state.objects_with_intersections:
            obj.select_set(True)

        new_active = self._determine_new_active()
        context.view_layer.objects.active = new_active

        if not state.objects_with_intersections:
            if state.mesh_candidates == 0:
                self.report({"WARNING"}, "No mesh objects selected.")
            else:
                self.report({"INFO"}, "No self-intersections detected on selected objects.")
                _play_happy_sound(context)
        else:
            self.report(
                {"INFO"},
                f"{len(state.objects_with_intersections)} objects of {state.mesh_candidates} with self-intersections.",
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

    def _determine_new_active(self) -> bpy.types.Object | None:
        state = self._state
        if (
            state.initial_active
            and state.initial_active in state.objects_with_intersections
        ):
            return state.initial_active
        if state.objects_with_intersections:
            return state.objects_with_intersections[0]
        return None


profile_module(globals())


__all__ = ("T4P_OT_filter_intersections",)
