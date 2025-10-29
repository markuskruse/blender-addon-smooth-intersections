"""Operator and helpers for cleaning non-manifold geometry."""

from __future__ import annotations

from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound, _play_warning_sound
from ..debug import profile_module
from ..main import (
    CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
    _triangulate_bmesh,
    count_non_manifold_verts,
    get_bmesh,
    mesh_checksum_fast,
    select_non_manifold_verts,
)
from .modal_utils import ModalTimerMixin


@dataclass
class _CleanNonManifoldState:
    """Mutable state tracked while cleaning non-manifold geometry."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    initial_active: bpy.types.Object | None = None
    initial_selection: list[bpy.types.Object] = field(default_factory=list)
    scene: bpy.types.Scene | None = None
    num_candidates: int = 0
    num_fine: int = 0
    num_failed: int = 0
    num_fixed: int = 0
    num_worse: int = 0


def _clean_object_non_manifold(
        obj: bpy.types.Object,
        merge_distance,
        delete_island_threshold) -> tuple[bool, bool, bool]:
    mesh = obj.data
    if mesh is None:
        return False, True

    checksum_before = mesh_checksum_fast(obj)
    # TODO should be changeable afterwards

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="VERT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.reveal()

    bm = get_bmesh(mesh)
    _triangulate_bmesh(bm)
    num_errors_before = count_non_manifold_verts(bm)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)

    bpy.ops.mesh.delete_loose()
    _delete_interior_faces()
    _fill_holes()

    bm = get_bmesh(mesh)
    _delete_small_vertex_islands(bm, min_vertices=delete_island_threshold)
    _dissolve_degenerate_and_triangulate(bm, threshold=merge_distance)
    bm.normal_update()
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)

    _remove_doubles(merge_distance)
    _make_manifold(mesh)
    _unify_normals()

    bm = get_bmesh(mesh)
    num_errors_after = count_non_manifold_verts(bm)
    clean = num_errors_after == 0
    worse = num_errors_after > num_errors_before

    bpy.ops.object.mode_set(mode="OBJECT")

    checksum_after = mesh_checksum_fast(obj)
    changed = checksum_after != checksum_before

    print("Stats: before", num_errors_before, "after", num_errors_after, "clean", clean, "changed", changed, "worse", worse)

    return changed, clean, worse


def _unify_normals():
    """have all normals face outwards"""
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent()


def _remove_doubles(merge_distance):
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=merge_distance)


def _make_manifold(mesh):
    bm = get_bmesh(mesh)
    fix_non_manifold = count_non_manifold_verts(bm) > 0
    num_faces = len(bm.faces)
    while fix_non_manifold:
        _try_fix_manifold()
        bm = get_bmesh(mesh)
        new_num_faces = len(bm.faces)
        if new_num_faces == num_faces:
            fix_non_manifold = False
        else:
            num_faces = new_num_faces


def _try_fix_manifold():
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.fill_holes(sides=0)
    select_non_manifold_verts(use_wire=True, use_verts=True)
    bpy.ops.mesh.delete(type="VERT")


def _fill_holes():
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.fill_holes(sides=0)


def _get_mesh_vertex_islands(
        bm: bmesh.types.BMesh,
) -> list[list[bmesh.types.BMVert]]:
    bm.verts.ensure_lookup_table()
    visited: set[int] = set()
    islands: list[list[bmesh.types.BMVert]] = []

    for vert in bm.verts:
        if not vert.is_valid:
            continue
        if vert.index in visited:
            continue

        stack = [vert]
        island: list[bmesh.types.BMVert] = []
        while stack:
            current = stack.pop()
            if not current.is_valid:
                continue

            index = current.index
            if index in visited:
                continue

            visited.add(index)
            island.append(current)

            for edge in current.link_edges:
                if not edge.is_valid:
                    continue
                for linked_vert in edge.verts:
                    if linked_vert.is_valid and linked_vert.index not in visited:
                        stack.append(linked_vert)

        if island:
            islands.append(island)

    return islands


def _delete_small_vertex_islands(
        bm: bmesh.types.BMesh, min_vertices: int
) -> None:
    islands = _get_mesh_vertex_islands(bm)
    if not islands:
        return

    max_size = max(len(island) for island in islands)
    verts_to_delete: set[bmesh.types.BMVert] = set()
    for island in islands:
        if len(island) < min_vertices and len(island) < max_size:
            verts_to_delete.update(island)

    if not verts_to_delete:
        return False

    bmesh.ops.delete(bm, geom=list(verts_to_delete), context="VERTS")
    return True


def _fill_non_manifold(sides: int):
    """fill in any remnant non-manifolds"""
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.fill_holes(sides=sides)


def _delete_interior_faces() -> None:
    """Delete interior faces in edit mode.
    """
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.mesh.select_interior_faces()
    bpy.ops.mesh.delete(type="FACE")


def _fill_and_triangulate_holes(bm: bmesh.types.BMesh) -> None:
    bm.edges.ensure_lookup_table()
    boundary_edges = [edge for edge in bm.edges if edge.is_valid and edge.is_boundary]
    if not boundary_edges:
        return

    result = bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
    new_faces = [face for face in result.get("faces", []) if face.is_valid]
    if not new_faces:
        return

    bmesh.ops.triangulate(bm, faces=new_faces)
    return


def _dissolve_degenerate_and_triangulate(
        bm: bmesh.types.BMesh, threshold: float
) -> bool:
    edges = [edge for edge in bm.edges if edge.is_valid]
    if not edges:
        return False

    dissolve_result = bmesh.ops.dissolve_degenerate(
        bm, edges=edges, dist=threshold
    )
    # ``bmesh.ops.dissolve_degenerate`` may return ``None`` in some edge cases.
    result_get = getattr(dissolve_result, "get", None)
    if result_get is None:
        changed = False
    else:
        changed = bool(
            result_get("region_edges")
            or result_get("region_faces")
            or result_get("region_verts")
        )

    triangulated = _triangulate_bmesh(bm)
    return changed or triangulated


def get_bmesh_islands(bm: bmesh.types.BMesh):
    """
    Return a list of face islands (each island = list of BMFace objects)
    for the given BMesh. Pure BMesh, no bpy.ops, no context.

    Two faces are considered connected if they share an edge.
    """
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    for f in bm.faces:
        f.tag = False  # unvisited

    islands = []
    for f in bm.faces:
        if f.tag:
            continue
        island = []
        q = deque([f])
        f.tag = True

        while q:
            cur = q.popleft()
            island.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if not nf.tag:
                        nf.tag = True
                        q.append(nf)

        islands.append(island)

    return islands


class T4P_OT_clean_non_manifold(ModalTimerMixin, Operator):
    """Clean up non-manifold geometry across selected mesh objects."""

    bl_idname = CLEAN_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Clean Non-manifold"
    bl_description = "Remove small islands, loose elements, and holes on selected meshes"
    bl_options = {"REGISTER", "UNDO"}


    @property
    def _state(self) -> _CleanNonManifoldState:
        return object.__getattribute__(self, "_clean_non_manifold_state")

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
        self._clean_non_manifold_state = _CleanNonManifoldState()
        self._reset_state()
        state = self._state
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to clean non-manifold meshes.")
            return {"CANCELLED"}

        state.initial_selection = list(context.selected_objects)
        if not state.initial_selection:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        state.initial_active = context.view_layer.objects.active
        state.scene = context.scene
        state.objects_to_process = [
            obj
            for obj in state.initial_selection
            if obj.type == "MESH"
            and obj.data is not None
            and (
                state.scene is None
                or state.scene.objects.get(obj.name) is not None
            )
        ]
        state.num_candidates = len(state.objects_to_process)

        bpy.ops.object.select_all(action="DESELECT")

        if not state.objects_to_process:
            return self._finish_modal(context, cancelled=False)

        return self._start_modal(context, state.num_candidates)

    def _reset_state(self) -> None:
        state = self._state
        state.objects_to_process.clear()
        state.current_index = 0
        state.initial_active = None
        state.initial_selection.clear()
        state.scene = None
        state.num_candidates = 0
        state.num_fine = 0
        state.num_failed = 0
        state.num_fixed = 0
        state.num_worse = 0

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        state = self._state
        if state.scene is not None and state.scene.objects.get(obj.name) is None:
            return

        context.view_layer.objects.active = obj
        obj.select_set(True)

        changed, clean, worse = _clean_object_non_manifold(obj, 0.001, 100)

        if clean and not changed:
            state.num_fine += 1
        elif clean and changed:
            state.num_fixed += 1
        elif not clean and changed:
            state.num_failed += 1
        if worse:
            state.num_worse += 1

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        if cancelled:
            self._restore_initial_selection(context)
            self.report(
                {"WARNING"},
                "Non-manifold cleaning cancelled before completion.",
            )
            _play_warning_sound(context)
            return {"CANCELLED"}

        self._restore_active_object(context)
        self._report_results(context)
        return {"FINISHED"}

    def _restore_initial_selection(self, context: bpy.types.Context) -> None:
        bpy.ops.object.select_all(action="DESELECT")
        state = self._state
        if not state.initial_selection:
            context.view_layer.objects.active = None
            return

        scene = state.scene
        for obj in state.initial_selection:
            if scene is not None and scene.objects.get(obj.name) is None:
                continue
            obj.select_set(True)

        self._restore_active_object(context)

    def _restore_active_object(self, context: bpy.types.Context) -> None:
        state = self._state
        scene = state.scene
        if (
            state.initial_active
            and (scene is None or scene.objects.get(state.initial_active.name) is not None)
        ):
            context.view_layer.objects.active = state.initial_active
        else:
            context.view_layer.objects.active = None

    def _report_results(self, context: bpy.types.Context) -> None:
        state = self._state
        if state.num_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif state.num_failed == 0 and state.num_fixed > 0 and state.num_worse == 0:
            self.report({"INFO"}, f"Fixed all on {state.num_fixed} objects")
        elif state.num_fixed > 0 or (state.num_failed > 0 and state.num_worse == 0):
            self.report(
                {"WARNING"},
                f"Cleaned {state.num_candidates} objects, {state.num_fixed} clean",
            )
        elif state.num_worse > 0:
            self.report(
                {"ERROR"},
                f"Cleaned {state.num_candidates} objects, but {state.num_worse} is worse",
            )

        if state.num_failed > 0 or state.num_worse > 0:
            _play_warning_sound(context)
        else:
            _play_happy_sound(context)


profile_module(globals())

__all__ = ("T4P_OT_clean_non_manifold",)
