"""Operator that analyzes selected mesh objects for topology issues."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    set_object_analysis_stats,
)
from .modal_utils import ModalTimerMixin


@dataclass
class _AnalysisState:
    """Mutable state tracked while the analyze operator runs."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    initial_selection: list[bpy.types.Object] = field(default_factory=list)
    initial_active: bpy.types.Object | None = None
    scene: bpy.types.Scene | None = None
    analyses: list[tuple[str, int, int]] = field(default_factory=list)


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


def _object_is_available(
    obj: bpy.types.Object | None, scene: bpy.types.Scene | None
) -> bool:
    if obj is None:
        return False
    if scene is None:
        return True
    return scene.objects.get(obj.name) is not None


def _restore_object_selection(
    context: bpy.types.Context,
    original_selection: list[bpy.types.Object],
    initial_active: bpy.types.Object | None,
    scene: bpy.types.Scene | None,
) -> None:
    bpy.ops.object.select_all(action="DESELECT")

    for obj in original_selection:
        if not _object_is_available(obj, scene):
            continue
        obj.select_set(True)

    if _object_is_available(initial_active, scene):
        context.view_layer.objects.active = initial_active
    else:
        context.view_layer.objects.active = None


class T4P_OT_analyze_selection(ModalTimerMixin, Operator):
    """Analyze selected mesh objects and store non-manifold and intersection counts."""

    bl_idname = ANALYZE_OPERATOR_IDNAME
    bl_label = "Analyze Selected Meshes"
    bl_description = (
        "Analyze selected mesh objects for non-manifold vertices and self-intersections"
    )
    bl_options = {"REGISTER", "UNDO"}


    @property
    def _state(self) -> _AnalysisState:
        return object.__getattribute__(self, "_analysis_state")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return self._begin(context)

    def execute(self, context: bpy.types.Context):
        return self._begin(context)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        state = self._state
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        if state.current_index >= len(state.objects_to_process):
            return self._finish_modal(context, cancelled=False)

        obj = state.objects_to_process[state.current_index]
        self._process_object(context, obj)
        state.current_index += 1
        self._update_modal_progress(state.current_index)
        return {"RUNNING_MODAL"}

    def _begin(self, context: bpy.types.Context):
        self._analysis_state = _AnalysisState()
        self._reset_state()
        state = self._state
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to analyze objects.")
            return {"CANCELLED"}

        selected_objects = list(getattr(context, "selected_objects", []))
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        state.scene = context.scene
        mesh_objects = [
            obj
            for obj in selected_objects
            if obj.type == "MESH"
            and obj.data is not None
            and (state.scene is None or state.scene.objects.get(obj.name) is not None)
        ]
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            return {"FINISHED"}

        state.initial_selection = selected_objects
        state.initial_active = context.view_layer.objects.active
        state.objects_to_process = mesh_objects

        bpy.ops.object.select_all(action="DESELECT")

        return self._start_modal(context, len(mesh_objects))

    def _reset_state(self) -> None:
        state = self._state
        state.objects_to_process.clear()
        state.current_index = 0
        state.initial_selection.clear()
        state.initial_active = None
        state.scene = None
        state.analyses.clear()

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        state = self._state
        if state.scene is not None and state.scene.objects.get(obj.name) is None:
            return

        context.view_layer.objects.active = obj
        obj.select_set(True)

        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except RuntimeError:
            obj.select_set(False)
            return

        mesh = obj.data
        _triangulate_edit_mesh(mesh)
        non_manifold_count = _count_non_manifold_vertices(mesh)
        bpy.ops.mesh.select_all(action="DESELECT")
        intersection_count = _count_self_intersections(mesh)

        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)

        set_object_analysis_stats(
            obj,
            non_manifold_count=int(non_manifold_count),
            intersection_count=int(intersection_count),
        )

        state.analyses.append((obj.name, non_manifold_count, intersection_count))

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        _restore_object_selection(
            context,
            original_selection=state.initial_selection,
            initial_active=state.initial_active,
            scene=state.scene,
        )

        if cancelled:
            self.report(
                {"WARNING"},
                "Analysis cancelled before all objects were processed.",
            )
            return {"CANCELLED"}

        if state.analyses:
            summary = "; ".join(
                f"{name}: non-manifold {non_manifold}, intersections {intersections}"
                for name, non_manifold, intersections in state.analyses
            )
            self.report({"INFO"}, f"Analyzed objects - {summary}")
        else:
            self.report({"INFO"}, "No mesh objects could be analyzed.")

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_analyze_selection",)
