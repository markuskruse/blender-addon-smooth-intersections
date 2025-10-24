"""Operator and helpers for smoothing mesh intersections."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..main import (
    SMOOTH_OPERATOR_IDNAME,
    _get_intersecting_face_indices,
    _play_happy_sound,
    _play_warning_sound,
    _select_intersecting_faces,
    _triangulate_mesh,
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

    distance = max_length * 0.1
    if abs(distance) <= 1e-6:
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
        try:
            bpy.ops.transform.shrink_fatten(value=distance_value, use_even_offset=True)
        except RuntimeError:
            for vert, coord in saved_coords.items():
                vert.co = coord
            bm.normal_update()
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            return False

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        remaining = _get_intersecting_face_indices(bm)
        if not (remaining & group_face_indices):
            return True

        for vert, coord in saved_coords.items():
            vert.co = coord
        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return False

    if _attempt(distance):
        return True

    return _attempt(-distance)


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

        bpy.ops.object.mode_set(mode="OBJECT")
        _triangulate_mesh(mesh)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)

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
