"""Operator and helpers for smoothing mesh intersections."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator
from math import radians, degrees

from mathutils import Vector

from ..debug import profile_module
from ..main import (
    SMOOTH_OPERATOR_IDNAME,
    _triangulate_bmesh,
    bmesh_get_intersecting_face_indices,
    mesh_checksum_fast,
    select_faces,
    get_bmesh,
)
from ..audio import _play_happy_sound, _play_warning_sound


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


def _iter_valid_intersecting_faces(
    bm: bmesh.types.BMesh, intersection_indices: list[int]
) -> list[tuple[int, bmesh.types.BMFace]]:
    bm.faces.ensure_lookup_table()
    valid: list[tuple[int, bmesh.types.BMFace]] = []
    for face_index in intersection_indices:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if not face.is_valid or len(face.edges) < 3:
            continue
        valid.append((face_index, face))
    return valid


def _collect_longest_edges(
    face: bmesh.types.BMFace,
) -> list[bmesh.types.BMEdge]:
    edge_lengths: list[tuple[float, bmesh.types.BMEdge]] = []
    for edge in face.edges:
        if not edge.is_valid:
            continue
        length = edge.calc_length()
        if length <= 1e-6:
            continue
        edge_lengths.append((length, edge))
    if len(edge_lengths) < 2:
        return []
    edge_lengths.sort(key=lambda item: item[0], reverse=True)
    return [edge for _, edge in edge_lengths[:2] if edge.is_valid]


def _find_smallest_face_angle(face: bmesh.types.BMFace) -> float:
    smallest_angle = float("inf")
    for loop in face.loops:
        prev_vector = loop.link_loop_prev.vert.co - loop.vert.co
        next_vector = loop.link_loop_next.vert.co - loop.vert.co
        if prev_vector.length <= 1e-6 or next_vector.length <= 1e-6:
            continue
        angle = prev_vector.angle(next_vector)
        if angle < smallest_angle:
            smallest_angle = angle
    return smallest_angle


def _subdivide_edges_and_collect_midpoints(
    bm: bmesh.types.BMesh, edges: list[bmesh.types.BMEdge]
) -> list[bmesh.types.BMVert]:
    midpoint_vertices: list[bmesh.types.BMVert] = []
    for edge in edges:
        if not edge.is_valid:
            continue
        result = bmesh.ops.subdivide_edges(
            bm,
            edges=[edge],
            cuts=1,
            use_grid_fill=False,
            smooth=0.0,
        )
        new_vertex = next(
            (
                geom
                for geom in result.get("geom_split", [])
                if isinstance(geom, bmesh.types.BMVert) and geom.is_valid
            ),
            None,
        )
        if new_vertex is not None and new_vertex.is_valid:
            midpoint_vertices.append(new_vertex)
    return [vert for vert in midpoint_vertices if vert.is_valid]


def _connect_midpoints_if_possible(
    bm: bmesh.types.BMesh,
    midpoint_vertices: list[bmesh.types.BMVert],
) -> bool:
    if len(midpoint_vertices) < 2:
        return False
    vert_a, vert_b = midpoint_vertices[:2]
    if vert_a == vert_b:
        return False
    if not vert_a.is_valid or not vert_b.is_valid:
        return False
    shared_faces = set(vert_a.link_faces) & set(vert_b.link_faces)
    if not shared_faces:
        return False
    has_existing_edge = any(
        edge for edge in vert_a.link_edges if edge.is_valid and vert_b in edge.verts
    )
    if has_existing_edge:
        return False

    result = bmesh.ops.connect_verts(bm, verts=[vert_a, vert_b])
    new_edges = [
        edge
        for edge in result.get("edges", [])
        if isinstance(edge, bmesh.types.BMEdge) and edge.is_valid
    ]
    return bool(new_edges)


def _process_intersecting_face(
    bm: bmesh.types.BMesh,
    face_index: int,
    face: bmesh.types.BMFace,
    iteration: int,
    sharp_angle_threshold: float,
) -> bool:
    if not face.is_valid or not face.loops:
        return False
    smallest_angle = _find_smallest_face_angle(face)
    if smallest_angle >= sharp_angle_threshold:
        return False
    longest_edges = _collect_longest_edges(face)
    if len(longest_edges) < 2:
        return False
    midpoint_vertices = _subdivide_edges_and_collect_midpoints(bm, longest_edges)
    return _connect_midpoints_if_possible(bm, midpoint_vertices)


def _collect_face_indices_with_neighbors(
    bm: bmesh.types.BMesh, intersection_indices: list[int]
) -> list[int]:
    bm.faces.ensure_lookup_table()
    faces_to_visit: list[int] = []
    seen: set[int] = set()

    for face_index, face in _iter_valid_intersecting_faces(bm, intersection_indices):
        if face_index in seen:
            continue
        seen.add(face_index)
        faces_to_visit.append(face_index)

        for edge in list(face.edges):
            if not edge.is_valid:
                continue
            for neighbor in edge.link_faces:
                if not neighbor.is_valid or len(neighbor.edges) < 3:
                    continue
                neighbor_index = neighbor.index
                if neighbor_index in seen:
                    continue
                seen.add(neighbor_index)
                faces_to_visit.append(neighbor_index)

    return faces_to_visit


def _split_faces_once(
    bm: bmesh.types.BMesh,
    iteration: int
) -> bool:

    sharp_angle_threshold = radians(15.0)

    face_indices = bmesh_get_intersecting_face_indices(bm)
    face_indices = _collect_face_indices_with_neighbors(
        bm, list(face_indices)
    )
    iteration_split = False
    for face_index in face_indices:
        bm.faces.ensure_lookup_table()
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if not face.is_valid or len(face.edges) < 3:
            continue
        if _process_intersecting_face(bm, face_index, face, iteration, sharp_angle_threshold):
            iteration_split = True
    bm.normal_update()

    return iteration_split


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

    smoothed_attempts = 0

    bm = get_bmesh(mesh)
    _triangulate_bmesh(bm)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=True)

    split = True
    splits = 0
    while split:
        face_indices = bmesh_get_intersecting_face_indices(bm)
        if not face_indices:
            return True

        changed = _split_faces_once(bm, 1)
        if changed:
            _triangulate_bmesh(bm)
            face_indices = bmesh_get_intersecting_face_indices(bm)
            if not face_indices:
                return True
        else:
            split = False
        splits += 1
        if splits >= 3:
            split = False

    for iteration in range(1, max_attempts + 1):
        bpy.ops.mesh.select_mode(type="FACE")
        bm = get_bmesh(mesh)
        face_indices = bmesh_get_intersecting_face_indices(bm)
        if len(face_indices) == 0:
            return True

        select_faces(face_indices, obj)
        if iteration > 2:
            _grow_selection(3)
        else:
            _grow_selection(2)
        _shrink_selection(1)
        if iteration > 2:
            bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=3)
        else:
            bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=2)

    bm = get_bmesh(mesh)
    face_indices = bmesh_get_intersecting_face_indices(bm)
    if len(face_indices) == 0:
        return True

    #_test_shrink_fatten(obj, mesh, bm)

    bm = get_bmesh(mesh)
    face_indices = bmesh_get_intersecting_face_indices(bm)
    return len(face_indices) == 0


class T4P_OT_smooth_intersections(Operator):
    """Smooth intersecting faces across selected mesh objects."""

    bl_idname = SMOOTH_OPERATOR_IDNAME
    bl_label = "Clean Intersections"
    bl_description = "Clean intersecting faces for selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to clean intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active
        initial_selection = list(context.selected_objects)

        smoothed_objects: List[str] = []
        scene = context.scene
        attempt_limit = 5
        if scene is not None:
            try:
                attempt_limit = int(getattr(scene, "t4p_smooth_intersection_attempts", 5))
            except (TypeError, ValueError):
                attempt_limit = 5
            attempt_limit = max(1, attempt_limit)

        for obj in initial_selection:
            if obj.type != "MESH" or obj.data is None:
                continue

            if context.view_layer.objects.get(obj.name) is None:
                continue

            context.view_layer.objects.active = obj
            obj.select_set(True)
            attempts = _clean_mesh_intersections_wrapper(obj, attempt_limit)
            obj.select_set(False)

            if attempts:
                smoothed_objects.append(obj.name)

        bpy.ops.object.select_all(action="DESELECT")

        for obj in initial_selection:
            if context.scene.objects.get(obj.name) is not None:
                obj.select_set(True)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active
        elif initial_active is None:
            context.view_layer.objects.active = None

        remaining_intersections = False
        scene_for_check = context.scene
        for obj in initial_selection:
            if obj.type != "MESH" or obj.data is None:
                continue
            if scene_for_check is not None and scene_for_check.objects.get(obj.name) is None:
                continue

            bm_for_check = None
            try:
                bm_for_check = bmesh.new()
                bm_for_check.from_mesh(obj.data)
                if bmesh_get_intersecting_face_indices(bm_for_check):
                    remaining_intersections = True
                    break
            except RuntimeError:
                continue
            finally:
                if bm_for_check is not None:
                    bm_for_check.free()

        if remaining_intersections:
            _play_warning_sound(context)
        else:
            _play_happy_sound(context)

        if not smoothed_objects:
            self.report({"INFO"}, "No intersecting faces were found.")
        else:
            self.report(
                {"INFO"},
                "Smoothed intersections on: {}".format(
                    ", ".join(smoothed_objects)
                ),
            )

        return {"FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_smooth_intersections",)
