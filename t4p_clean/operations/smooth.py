"""Operator and helpers for smoothing mesh intersections."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator
from math import radians, degrees

from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..main import (
    SMOOTH_OPERATOR_IDNAME,
    _get_intersecting_face_indices,
    _play_happy_sound,
    _play_warning_sound,
    _select_intersecting_faces,
    _triangulate_bmesh,
)


def _grow_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_more()


def _shrink_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_less()


def _mesh_has_intersections(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh | None = None
) -> bool:
    """Return ``True`` when the provided mesh contains self-intersections."""

    def _bmesh_contains_self_intersections(
        eval_bm: bmesh.types.BMesh,
    ) -> bool:
        if not eval_bm.faces:
            return False

        faces = list(eval_bm.faces)
        if not faces:
            return False

        bmesh.ops.triangulate(eval_bm, faces=faces)
        eval_bm.faces.ensure_lookup_table()

        tree = BVHTree.FromBMesh(eval_bm)
        if tree is None:
            return False

        for index_a, index_b in tree.overlap(tree):
            if index_a == index_b or index_b < index_a:
                continue

            face_a = eval_bm.faces[index_a]
            face_b = eval_bm.faces[index_b]

            verts_a = {vert.index for vert in face_a.verts}
            verts_b = {vert.index for vert in face_b.verts}

            if verts_a & verts_b:
                continue

            return True

        return False

    if bm is not None:
        bm_copy = bm.copy()
        try:
            return _bmesh_contains_self_intersections(bm_copy)
        finally:
            bm_copy.free()

    new_bm = bmesh.new()
    try:
        new_bm.from_mesh(mesh)
        return _bmesh_contains_self_intersections(new_bm)
    finally:
        new_bm.free()

    return False


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
        return True
    bmesh.ops.connect_verts(bm, verts=[vert_a, vert_b])
    return True


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
    print(
        "[T4P][smooth] Iteration "
        f"{iteration}: sharp angle detected on face {face_index} "
        f"({degrees(smallest_angle):.2f}\N{DEGREE SIGN}); splitting edges "
        f"{[edge.index for edge in longest_edges]}"
    )
    midpoint_vertices = _subdivide_edges_and_collect_midpoints(bm, longest_edges)
    return _connect_midpoints_if_possible(bm, midpoint_vertices)


def _split_faces_once(
    bm: bmesh.types.BMesh,
    iteration: int,
    sharp_angle_threshold: float,
) -> bool:
    intersection_indices = _get_intersecting_face_indices(bm)
    print("Intersection indices", intersection_indices)
    if not intersection_indices:
        return False
    bm.edges.ensure_lookup_table()
    iteration_split = False
    for face_index, _ in _iter_valid_intersecting_faces(bm, intersection_indices):
        bm.faces.ensure_lookup_table()
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if not face.is_valid or len(face.edges) < 3:
            continue
        if _process_intersecting_face(bm, face_index, face, iteration, sharp_angle_threshold):
            iteration_split = True
    return iteration_split


def _split_elongated_intersecting_faces(
    mesh: bpy.types.Mesh,
    bm: bmesh.types.BMesh,
) -> bool:
    """Split intersecting faces when they contain sharp angles."""

    sharp_angle_threshold = radians(30.0)
    max_iterations = 10
    any_split_performed = False

    for iteration in range(1, max_iterations + 1):
        if not _split_faces_once(bm, iteration, sharp_angle_threshold):
            break
        any_split_performed = True

    if not any_split_performed:
        return False

    bm.normal_update()
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    return True


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

        try:
            bpy.ops.transform.shrink_fatten(value=distance_value, use_even_offset=True)
        except RuntimeError:
            _restore_saved_coords()
            return False

        try:
            bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=1)
        except RuntimeError:
            _restore_saved_coords()
            return False

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        remaining = _get_intersecting_face_indices(bm)
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


def _handle_remaining_intersections(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh
) -> bool:
    bpy.ops.mesh.select_mode(type="FACE")
    try:
        bpy.ops.mesh.reveal()
    except RuntimeError:
        pass

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    bm = bmesh.from_edit_mesh(mesh)

    face_count = _select_intersecting_faces(mesh, bm)
    if face_count == 0:
        return False

    bm = bmesh.from_edit_mesh(mesh)
    _grow_selection(1)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    try:
        bpy.ops.mesh.hide(unselected=True)
    except RuntimeError:
        pass

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    bm = bmesh.from_edit_mesh(mesh)
    islands = _get_selected_visible_face_islands(bm)
    if not islands:
        try:
            bpy.ops.mesh.reveal()
        except RuntimeError:
            pass
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return False

    bounding_boxes = [_calculate_faces_bounding_box(island) for island in islands]
    grouped_indices = _group_intersecting_bounding_boxes(bounding_boxes)

    solved_any = False
    for group in grouped_indices:
        group_faces = [face for idx in group for face in islands[idx]]
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for face in group_faces:
            if face.is_valid:
                face.select_set(True)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if _try_shrink_fatten(mesh, bm, group_faces):
            solved_any = True

        bm = bmesh.from_edit_mesh(mesh)

    try:
        bpy.ops.mesh.reveal()
    except RuntimeError:
        pass

    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    for face in bm.faces:
        face.select_set(False)
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    return solved_any


def _smooth_object_intersections(
    obj: bpy.types.Object, max_attempts: int
) -> int:
    """Run the intersection smoothing workflow on a mesh object.

    Returns the number of iterations that performed smoothing.
    """

    mesh = obj.data
    max_attempts = max(1, max_attempts)
    if mesh is None:
        return 0

    smoothed_attempts = 0
    subdivisions_done = 0
    max_subdivisions = 2

    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)

        if not _mesh_has_intersections(mesh, bm):
            return 0

        if _triangulate_bmesh(bm):
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            bm = bmesh.from_edit_mesh(mesh)

        while _split_elongated_intersecting_faces(mesh, bm):
            if _triangulate_bmesh(bm):
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            bm = bmesh.from_edit_mesh(mesh)

            if not _mesh_has_intersections(mesh, bm):
                return 0

        if not _mesh_has_intersections(mesh, bm):
            return 0

        bpy.ops.mesh.select_mode(type="FACE")

        for iteration in range(1, max_attempts + 1):
            face_count = _select_intersecting_faces(mesh, bm)
            if face_count == 0:
                break

            growth_steps = 2 + subdivisions_done
            _grow_selection(growth_steps)
            _shrink_selection(1)
            bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=iteration)
            smoothed_attempts += 1

            bmesh.update_edit_mesh(mesh)
            bm = bmesh.from_edit_mesh(mesh)

            if not _mesh_has_intersections(mesh, bm):
                return smoothed_attempts

            bpy.ops.mesh.select_mode(type="FACE")

        if _mesh_has_intersections(mesh, bm):
            if _handle_remaining_intersections(mesh, bm):
                bm = bmesh.from_edit_mesh(mesh)
                if not _mesh_has_intersections(mesh, bm):
                    return smoothed_attempts
            else:
                bm = bmesh.from_edit_mesh(mesh)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    if not _mesh_has_intersections(mesh):
        return smoothed_attempts

    return smoothed_attempts


def _smooth_object_intersections_in_edit_mode(
    obj: bpy.types.Object, max_attempts: int
) -> int:
    """Run the smoothing workflow while temporarily entering edit mode."""

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        return _smooth_object_intersections(obj, max_attempts)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


class T4P_OT_smooth_intersections(Operator):
    """Smooth intersecting faces across selected mesh objects."""

    bl_idname = SMOOTH_OPERATOR_IDNAME
    bl_label = "Smooth Intersections"
    bl_description = "Smooth intersecting faces for selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to smooth intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active
        initial_selection = list(context.selected_objects)

        bpy.ops.object.select_all(action="DESELECT")

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

            obj.select_set(True)
            context.view_layer.objects.active = obj

            try:
                attempts = _smooth_object_intersections_in_edit_mode(
                    obj, attempt_limit
                )
            except RuntimeError:
                attempts = 0
            finally:
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
            if _mesh_has_intersections(obj.data):
                remaining_intersections = True
                break

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


__all__ = ("T4P_OT_smooth_intersections",)
