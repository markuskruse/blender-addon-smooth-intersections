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
    set_object_analysis_stats,
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

    def __init__(self) -> None:
        self._objects_to_process: list[bpy.types.Object] = []
        self._current_index = 0
        self._initial_selection: list[bpy.types.Object] = []
        self._initial_active: bpy.types.Object | None = None
        self._scene: bpy.types.Scene | None = None
        self._analyses: list[tuple[str, int, int]] = []

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
            self.report({"ERROR"}, "Switch to Object mode to analyze objects.")
            return {"CANCELLED"}

        selected_objects = list(getattr(context, "selected_objects", []))
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        self._scene = context.scene
        mesh_objects = [
            obj
            for obj in selected_objects
            if obj.type == "MESH"
            and obj.data is not None
            and (self._scene is None or self._scene.objects.get(obj.name) is not None)
        ]
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            return {"FINISHED"}

        self._initial_selection = selected_objects
        self._initial_active = context.view_layer.objects.active
        self._objects_to_process = mesh_objects

        bpy.ops.object.select_all(action="DESELECT")

        return self._start_modal(context, len(mesh_objects))

    def _reset_state(self) -> None:
        self._objects_to_process = []
        self._current_index = 0
        self._initial_selection = []
        self._initial_active = None
        self._scene = None
        self._analyses = []

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        if self._scene is not None and self._scene.objects.get(obj.name) is None:
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

        self._analyses.append((obj.name, non_manifold_count, intersection_count))

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)

        _restore_object_selection(
            context,
            original_selection=self._initial_selection,
            initial_active=self._initial_active,
            scene=self._scene,
        )

        if cancelled:
            self.report(
                {"WARNING"},
                "Analysis cancelled before all objects were processed.",
            )
            return {"CANCELLED"}

        if self._analyses:
            summary = "; ".join(
                f"{name}: non-manifold {non_manifold}, intersections {intersections}"
                for name, non_manifold, intersections in self._analyses
            )
            self.report({"INFO"}, f"Analyzed objects - {summary}")
        else:
            self.report({"INFO"}, "No mesh objects could be analyzed.")

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_analyze_selection",)
