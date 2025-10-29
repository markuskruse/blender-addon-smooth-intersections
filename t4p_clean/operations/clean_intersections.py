"""Operator and helpers for smoothing mesh intersections."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator

from mathutils import Vector

from ..audio import _play_happy_sound, _play_warning_sound
from ..debug import profile_module
from ..main import (
    SMOOTH_OPERATOR_IDNAME,
    _triangulate_bmesh,
    bmesh_get_intersecting_face_indices,
    get_bmesh,
    mesh_checksum_fast,
    select_faces,
)
from ..split_long import split_intersections
from .modal_utils import ModalTimerMixin


def _grow_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_more()


def _shrink_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_less()


def _calculate_faces_bounding_box(
    faces: list[bmesh.types.BMFace],
) -> tuple[Vector, Vector]:
    coords = [
        vert.co
        for face in faces
        if face.is_valid
        for vert in face.verts
    ]
    if not coords:
        origin = Vector((0.0, 0.0, 0.0))
        return origin.copy(), origin.copy()

    xs = [co.x for co in coords]
    ys = [co.y for co in coords]
    zs = [co.z for co in coords]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def _bounding_boxes_intersect(
    box_a: tuple[Vector, Vector], box_b: tuple[Vector, Vector]
) -> bool:
    min_a, max_a = box_a
    min_b, max_b = box_b
    return (
        max_a.x >= min_b.x
        and max_b.x >= min_a.x
        and max_a.y >= min_b.y
        and max_b.y >= min_a.y
        and max_a.z >= min_b.z
        and max_b.z >= min_a.z
    )


def _group_intersecting_bounding_boxes(
    boxes: list[tuple[Vector, Vector]]
) -> list[list[int]]:
    adjacency: list[set[int]] = [set() for _ in boxes]
    for idx_a in range(len(boxes)):
        for idx_b in range(idx_a + 1, len(boxes)):
            if _bounding_boxes_intersect(boxes[idx_a], boxes[idx_b]):
                adjacency[idx_a].add(idx_b)
                adjacency[idx_b].add(idx_a)

    visited: set[int] = set()
    groups: list[list[int]] = []
    for start in range(len(boxes)):
        if start in visited:
            continue

        stack = [start]
        group: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            group.append(current)
            stack.extend(adjacency[current])

        groups.append(group)

    return groups


def _get_selected_visible_face_islands(
    bm: bmesh.types.BMesh,
) -> list[list[bmesh.types.BMFace]]:
    bm.faces.ensure_lookup_table()
    visited: set[int] = set()
    islands: list[list[bmesh.types.BMFace]] = []

    for face in bm.faces:
        if not face.is_valid or not face.select or face.hide:
            continue
        if face.index in visited:
            continue

        stack = [face]
        island: list[bmesh.types.BMFace] = []
        while stack:
            current = stack.pop()
            if current.index in visited or not current.is_valid:
                continue

            visited.add(current.index)
            island.append(current)

            for edge in current.edges:
                for linked_face in edge.link_faces:
                    if (
                        linked_face.is_valid
                        and linked_face.select
                        and not linked_face.hide
                        and linked_face.index not in visited
                    ):
                        stack.append(linked_face)

        if island:
            islands.append(island)

    return islands


def _try_shrink_fatten(
    mesh: bpy.types.Mesh,
    bm: bmesh.types.BMesh,
    faces: list[bmesh.types.BMFace],
) -> bool:
    if not faces:
        return False

    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    group_face_indices = {face.index for face in faces if face.is_valid}
    if not group_face_indices:
        return False

    min_corner, max_corner = _calculate_faces_bounding_box(faces)
    extents = max_corner - min_corner
    max_length = max(extents.x, extents.y, extents.z)
    if max_length <= 0.0:
        return False

    relevant_vertices = {
        vert
        for face in faces
        if face.is_valid
        for vert in face.verts
        if vert.is_valid
    }
    if not relevant_vertices:
        return False

    def _attempt(distance_value: float) -> bool:
        saved_coords = {vert: vert.co.copy() for vert in relevant_vertices}

        def _restore_saved_coords() -> None:
            for vert, coord in saved_coords.items():
                vert.co = coord
            bm.normal_update()
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        bpy.ops.transform.shrink_fatten(value=distance_value, use_even_offset=True)
        bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=2)

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        remaining = bmesh_get_intersecting_face_indices(bm)
        if not (remaining & group_face_indices):
            return True

        _restore_saved_coords()
        return False

    for scale in (0.1, 0.2):
        distance = max_length * scale
        if abs(distance) <= 1e-6:
            continue

        if _attempt(distance):
            return True

        if _attempt(-distance):
            return True

    return False


def _test_shrink_fatten(
    obj, mesh: bpy.types.Mesh, bm: bmesh.types.BMesh
) -> bool:
    bpy.ops.mesh.select_mode(type="FACE")

    face_indices = bmesh_get_intersecting_face_indices(bm)
    select_faces(face_indices, obj)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    _grow_selection(1)
    get_bmesh(mesh)

    bpy.ops.mesh.hide(unselected=True)

    bm = bmesh.from_edit_mesh(mesh)
    islands = _get_selected_visible_face_islands(bm)
    if not islands:
        return False

    bounding_boxes = [_calculate_faces_bounding_box(island) for island in islands]
    grouped_indices = _group_intersecting_bounding_boxes(bounding_boxes)

    solved_any = False
    for group in grouped_indices:
        group_faces = [face for idx in group for face in islands[idx]]
        bpy.ops.mesh.select_all(action='DESELECT')
        for face in group_faces:
            if face.is_valid:
                face.select_set(True)
        bm = get_bmesh(mesh)

        if _try_shrink_fatten(mesh, bm, group_faces):
            solved_any = True

    bpy.ops.mesh.reveal()
    bpy.ops.mesh.select_all(action='DESELECT')

    return solved_any


def _clean_mesh_intersections_wrapper(obj: bpy.types.Object, max_attempts: int) -> tuple[bool, bool]:
    checksum_before = mesh_checksum_fast(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    clean = _clean_mesh_intersections(obj, max_attempts)
    bpy.ops.object.mode_set(mode="OBJECT")
    checksum_after = mesh_checksum_fast(obj)
    changed = checksum_before != checksum_after
    return changed, clean


def _clean_mesh_intersections(
    obj: bpy.types.Object, max_attempts: int
) -> bool:
    """Run the intersection smoothing workflow on a mesh object.

    returns if the mesh still contains intersections.
    """

    bpy.ops.mesh.reveal(select=False)

    mesh = obj.data
    max_attempts = max(1, max_attempts)
    if mesh is None:
        return True

    bm = get_bmesh(mesh)
    _triangulate_bmesh(bm)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)

    for iteration in range(1, max_attempts + 1):
        bpy.ops.mesh.select_mode(type="FACE")
        bm = get_bmesh(mesh)
        face_indices = list(bmesh_get_intersecting_face_indices(bm))
        print("num face indices", len(face_indices))
        if len(face_indices) == 0:
            return True

        select_faces(face_indices, mesh, bm)
        bpy.ops.mesh.select_more()
        bpy.ops.mesh.select_more()
        bpy.ops.mesh.select_less()
        bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=2)

    bm = get_bmesh(mesh)
    face_indices = bmesh_get_intersecting_face_indices(bm)
    return len(face_indices) == 0


class T4P_OT_smooth_intersections(ModalTimerMixin, Operator):
    """Smooth intersecting faces across selected mesh objects."""

    bl_idname = SMOOTH_OPERATOR_IDNAME
    bl_label = "Clean Intersections"
    bl_description = "Clean intersecting faces for selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self) -> None:
        self._objects_to_process: List[bpy.types.Object] = []
        self._current_index = 0
        self._initial_active: bpy.types.Object | None = None
        self._initial_selection: list[bpy.types.Object] = []
        self._smoothed_objects: list[str] = []
        self._attempt_limit = 1
        self._scene: bpy.types.Scene | None = None

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
            self.report({"ERROR"}, "Switch to Object mode to clean intersections.")
            return {"CANCELLED"}

        self._initial_active = context.view_layer.objects.active
        self._initial_selection = list(context.selected_objects)
        if not self._initial_selection:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        self._scene = context.scene
        self._attempt_limit = self._resolve_attempt_limit()
        self._objects_to_process = self._collect_candidates(context)

        bpy.ops.object.select_all(action="DESELECT")

        if not self._objects_to_process:
            return self._finish_modal(context, cancelled=False)

        return self._start_modal(context, len(self._objects_to_process))

    def _reset_state(self) -> None:
        self._objects_to_process = []
        self._current_index = 0
        self._initial_active = None
        self._initial_selection = []
        self._smoothed_objects = []
        self._attempt_limit = 1
        self._scene = None

    def _resolve_attempt_limit(self) -> int:
        scene = self._scene
        attempt_limit = 5
        if scene is not None:
            try:
                attempt_limit = int(getattr(scene, "t4p_smooth_intersection_attempts", 5))
            except (TypeError, ValueError):
                attempt_limit = 5
        return max(1, attempt_limit)

    def _collect_candidates(self, context: bpy.types.Context) -> list[bpy.types.Object]:
        view_layer_objects = getattr(context.view_layer, "objects", None)
        candidates: list[bpy.types.Object] = []
        for obj in self._initial_selection:
            if obj.type != "MESH" or obj.data is None:
                continue
            if view_layer_objects is not None and view_layer_objects.get(obj.name) is None:
                continue
            candidates.append(obj)
        return candidates

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        if self._scene is not None and self._scene.objects.get(obj.name) is None:
            return

        context.view_layer.objects.active = obj
        obj.select_set(True)
        attempts = _clean_mesh_intersections_wrapper(obj, self._attempt_limit)
        obj.select_set(False)

        if attempts:
            self._smoothed_objects.append(obj.name)

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)

        self._restore_initial_selection(context)

        if cancelled:
            self.report(
                {"WARNING"},
                "Intersection cleaning cancelled before completion.",
            )
            _play_warning_sound(context)
            return {"CANCELLED"}

        remaining_intersections = self._has_remaining_intersections()

        if remaining_intersections:
            _play_warning_sound(context)
        else:
            _play_happy_sound(context)

        if not self._smoothed_objects:
            self.report({"INFO"}, "No intersecting faces were found.")
        else:
            object_list = ", ".join(self._smoothed_objects)
            self.report({"INFO"}, f"Smoothed intersections on: {object_list}")

        return {"FINISHED"}

    def _restore_initial_selection(self, context: bpy.types.Context) -> None:
        bpy.ops.object.select_all(action="DESELECT")

        scene = context.scene
        for obj in self._initial_selection:
            if scene is not None and scene.objects.get(obj.name) is None:
                continue
            obj.select_set(True)

        if (
            self._initial_active
            and scene is not None
            and scene.objects.get(self._initial_active.name) is not None
        ):
            context.view_layer.objects.active = self._initial_active
        else:
            context.view_layer.objects.active = None

    def _has_remaining_intersections(self) -> bool:
        scene = self._scene
        for obj in self._initial_selection:
            if obj.type != "MESH" or obj.data is None:
                continue
            if scene is not None and scene.objects.get(obj.name) is None:
                continue

            bm_for_check = None
            try:
                bm_for_check = bmesh.new()
                bm_for_check.from_mesh(obj.data)
                if bmesh_get_intersecting_face_indices(bm_for_check):
                    return True
            except RuntimeError:
                continue
            finally:
                if bm_for_check is not None:
                    bm_for_check.free()

        return False


profile_module(globals())


__all__ = ("T4P_OT_smooth_intersections",)
