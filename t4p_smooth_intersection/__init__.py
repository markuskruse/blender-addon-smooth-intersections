"""Single-file entry point for the T4P Smooth Intersection add-on."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.props import IntProperty
from bpy.types import Operator, Panel
from mathutils import Vector
from mathutils.bvhtree import BVHTree

bl_info = {
    "name": "T4P Smooth Intersection",
    "author": "T4P",
    "version": (0, 0, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > 3D Print",
    "description": "Smooth intersecting faces on mesh objects from the 3D Print tab.",
    "warning": "",
    "category": "3D View",
}

SMOOTH_OPERATOR_IDNAME = "t4p_smooth_intersection.smooth_intersections"
FILTER_OPERATOR_IDNAME = "t4p_smooth_intersection.filter_intersections"
FILTER_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.filter_non_manifold"
)
CLEAN_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.clean_non_manifold"
)
TRIANGULATE_OPERATOR_IDNAME = "t4p_smooth_intersection.triangulate_selected"


def _get_intersecting_face_indices(bm: bmesh.types.BMesh) -> set[int]:
    if not bm.faces:
        return set()

    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    if tree is None:
        return set()

    intersection_indices: set[int] = set()
    for index_a, index_b in tree.overlap(tree):
        if index_a == index_b or index_b < index_a:
            continue
        face_a = bm.faces[index_a]
        face_b = bm.faces[index_b]

        verts_a = {vert.index for vert in face_a.verts}
        verts_b = {vert.index for vert in face_b.verts}
        if verts_a & verts_b:
            continue

        intersection_indices.add(index_a)
        intersection_indices.add(index_b)

    return intersection_indices


def _select_intersecting_faces(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh
) -> int:
    """Select intersecting faces of ``bm`` in edit mode.

    Returns the number of faces that were selected.
    """

    intersection_indices = _get_intersecting_face_indices(bm)

    for face in bm.faces:
        face.select_set(face.index in intersection_indices)

    bmesh.update_edit_mesh(mesh)
    return len(intersection_indices)


def _select_intersecting_faces_on_mesh(mesh: bpy.types.Mesh) -> int:
    """Select intersecting faces of ``mesh`` while in object mode."""

    polygons = mesh.polygons
    if polygons:
        polygons.foreach_set("select", [False] * len(polygons))

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        intersection_indices = _get_intersecting_face_indices(bm)
    finally:
        bm.free()

    intersection_lookup = intersection_indices
    for polygon in mesh.polygons:
        polygon.select = polygon.index in intersection_lookup

    mesh.update()
    return len(intersection_indices)


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


def _triangulate_edit_bmesh(bm: bmesh.types.BMesh) -> bool:
    bm.faces.ensure_lookup_table()
    faces = [face for face in bm.faces if face.is_valid]
    if not faces:
        return False

    bmesh.ops.triangulate(bm, faces=faces)
    return True


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
) -> bool:
    islands = _get_mesh_vertex_islands(bm)
    if not islands:
        return False

    max_size = max(len(island) for island in islands)
    verts_to_delete: set[bmesh.types.BMVert] = set()
    for island in islands:
        if len(island) < min_vertices and len(island) < max_size:
            verts_to_delete.update(island)

    if not verts_to_delete:
        return False

    bmesh.ops.delete(bm, geom=list(verts_to_delete), context="VERTS")
    return True


def delete_interior_faces() -> bool:
    """Delete interior faces in edit mode.

    Returns ``True`` if any interior faces were removed.
    """

    edit_object = bpy.context.edit_object
    mesh = None
    if edit_object is not None and edit_object.type == "MESH":
        mesh = edit_object.data

    try:
        bpy.ops.mesh.select_all(action="DESELECT")
    except RuntimeError:
        return False

    try:
        bpy.ops.mesh.select_interior_faces()
    except RuntimeError:
        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass
        return False

    selected_faces: int | None = None
    if mesh is not None:
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        selected_faces = sum(
            1 for face in bm.faces if face.is_valid and face.select
        )

        if selected_faces == 0:
            try:
                bpy.ops.mesh.select_all(action="SELECT")
            except RuntimeError:
                pass
            return False

    try:
        delete_result = bpy.ops.mesh.delete(type="FACE")
    except RuntimeError:
        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass
        return False

    try:
        bpy.ops.mesh.select_all(action="SELECT")
    except RuntimeError:
        pass

    if "FINISHED" not in delete_result:
        return False

    if selected_faces is not None:
        return selected_faces > 0

    return True


def _fill_and_triangulate_holes(bm: bmesh.types.BMesh) -> bool:
    bm.edges.ensure_lookup_table()
    boundary_edges = [edge for edge in bm.edges if edge.is_valid and edge.is_boundary]
    if not boundary_edges:
        return False

    result = bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
    new_faces = [face for face in result.get("faces", []) if face.is_valid]
    if not new_faces:
        return False

    bmesh.ops.triangulate(bm, faces=new_faces)
    return True


def _dissolve_degenerate_and_triangulate(
    bm: bmesh.types.BMesh, threshold: float
) -> bool:
    bm.edges.ensure_lookup_table()
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

    triangulated = _triangulate_edit_bmesh(bm)
    return changed or triangulated


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
            bpy.ops.mesh.vertices_smooth(factor=0.5,repeat=iteration)
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


class T4P_OT_filter_intersections(Operator):
    """Keep selected only the mesh objects that have intersections."""

    bl_idname = FILTER_OPERATOR_IDNAME
    bl_label = "Filter Intersections"
    bl_description = "Deselect selected objects without self-intersections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to filter intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        objects_with_intersections: list[bpy.types.Object] = []

        for obj in selected_objects:
            has_intersections = False
            if obj.type == "MESH" and obj.data is not None:
                try:
                    face_count = _select_intersecting_faces_on_mesh(obj.data)
                except RuntimeError:
                    face_count = 0
                has_intersections = face_count > 0

            obj.select_set(has_intersections)

            if has_intersections:
                objects_with_intersections.append(obj)

        new_active = None
        if initial_active and initial_active in objects_with_intersections:
            new_active = initial_active
        elif objects_with_intersections:
            new_active = objects_with_intersections[0]

        context.view_layer.objects.active = new_active

        if not objects_with_intersections:
            self.report({"INFO"}, "No self-intersections detected on selected objects.")
        else:
            self.report(
                {"INFO"},
                "Objects with self-intersections: {}".format(
                    ", ".join(obj.name for obj in objects_with_intersections)
                ),
            )

        return {"FINISHED"}


class T4P_OT_filter_non_manifold(Operator):
    """Deselect mesh objects that contain non-manifold geometry."""

    bl_idname = FILTER_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Filter Non Manifold"
    bl_description = "Deselect selected mesh objects with non-manifold geometry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to filter non-manifold meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        scene = context.scene
        non_manifold_list: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if scene is not None and scene.objects.get(obj.name) is None:
                continue

            mesh_candidates += 1

            context.view_layer.objects.active = obj
            obj.select_set(True)

            has_non_manifold = False
            try:
                bpy.ops.object.mode_set(mode="EDIT")
                bm = bmesh.from_edit_mesh(obj.data)
                bm.edges.ensure_lookup_table()
                has_non_manifold = any(not edge.is_manifold for edge in bm.edges)
            except RuntimeError:
                has_non_manifold = False
            finally:
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except RuntimeError:
                    pass

            obj.select_set(False)
            if has_non_manifold:
                non_manifold_list.append(obj)

        for obj in non_manifold_list:
            obj.select_set(True)

        remaining_selected = [obj for obj in context.selected_objects if obj.select_get()]

        if (
            initial_active
            and scene is not None
            and scene.objects.get(initial_active.name) is not None
            and initial_active in remaining_selected
        ):
            context.view_layer.objects.active = initial_active
        elif remaining_selected:
            context.view_layer.objects.active = remaining_selected[0]
        else:
            context.view_layer.objects.active = None

        if mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not non_manifold_list:
            self.report({"INFO"}, "All checked mesh objects are manifold.")
        else:
            self.report(
                {"INFO"},
                "Deselected non-manifold meshes: {}".format(
                    ", ".join(obj.name for obj in non_manifold_list)
                ),
            )

        return {"FINISHED"}


def _triangulate_mesh(mesh: bpy.types.Mesh) -> bool:
    """Triangulate the provided mesh in-place.

    Returns ``True`` when triangulation was attempted on at least one face.
    """

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        if not bm.faces:
            return False

        faces = list(bm.faces)
        if not faces:
            return False

        bmesh.ops.triangulate(bm, faces=faces)
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()

    return True


def _clean_object_non_manifold(obj: bpy.types.Object) -> bool:
    mesh = obj.data
    if mesh is None:
        return False

    try:
        bpy.ops.object.mode_set(mode="EDIT")
    except RuntimeError:
        return False

    changed = False

    try:
        try:
            bpy.ops.mesh.select_mode(type="VERT")
        except RuntimeError:
            pass

        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass

        bm = bmesh.from_edit_mesh(mesh)

        if _triangulate_edit_bmesh(bm):
            changed = True

        if _delete_small_vertex_islands(bm, min_vertices=100):
            changed = True

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if delete_interior_faces():
            changed = True

        try:
            delete_loose_result = bpy.ops.mesh.delete_loose()
        except RuntimeError:
            delete_loose_result = set()
        else:
            if "FINISHED" in delete_loose_result:
                changed = True

        bm = bmesh.from_edit_mesh(mesh)

        if _fill_and_triangulate_holes(bm):
            changed = True

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        bm = bmesh.from_edit_mesh(mesh)

        if _dissolve_degenerate_and_triangulate(bm, threshold=0.01):
            changed = True

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass

    return changed


class T4P_OT_clean_non_manifold(Operator):
    """Clean up non-manifold geometry across selected mesh objects."""

    bl_idname = CLEAN_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Clean Non-manifold"
    bl_description = "Remove small islands, loose elements, and holes on selected meshes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to clean non-manifold meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        scene = context.scene
        cleaned_objects: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if scene is not None and scene.objects.get(obj.name) is None:
                continue

            mesh_candidates += 1

            context.view_layer.objects.active = obj
            obj.select_set(True)

            try:
                changed = _clean_object_non_manifold(obj)
            except RuntimeError:
                changed = False

            if changed:
                cleaned_objects.append(obj)

        if initial_active and (
            scene is None
            or scene.objects.get(initial_active.name) is not None
        ):
            context.view_layer.objects.active = initial_active
        elif initial_active is None:
            context.view_layer.objects.active = None
        elif cleaned_objects:
            context.view_layer.objects.active = cleaned_objects[0]
        else:
            context.view_layer.objects.active = None

        if mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif cleaned_objects:
            self.report(
                {"INFO"},
                "Cleaned non-manifold geometry on: {}".format(
                    ", ".join(obj.name for obj in cleaned_objects)
                ),
            )
        else:
            self.report({"INFO"}, "No changes made to selected meshes.")

        return {"FINISHED"}


class T4P_OT_triangulate_selected(Operator):
    """Triangulate all selected mesh objects."""

    bl_idname = TRIANGULATE_OPERATOR_IDNAME
    bl_label = "Triangulate Selected Meshes"
    bl_description = "Triangulate meshes for all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to triangulate meshes.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        triangulated_objects = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            mesh_candidates += 1
            try:
                changed = _triangulate_mesh(obj.data)
            except RuntimeError:
                changed = False

            if changed:
                triangulated_objects.append(obj.name)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
        elif mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not triangulated_objects:
            self.report({"INFO"}, "Selected meshes have no faces to triangulate.")
        else:
            self.report(
                {"INFO"},
                "Triangulated: {}".format(
                    ", ".join(triangulated_objects)
                ),
            )

        return {"FINISHED"}


class T4P_PT_main_panel(Panel):
    """Panel that hosts the controls in the 3D Print tab."""

    bl_idname = "T4P_PT_main_panel"
    bl_label = "T4P Cleaning"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "3D Print"

    def draw(self, context):
        layout = self.layout

        props_col = layout.column()
        scene = context.scene
        if scene is not None and hasattr(scene, "t4p_smooth_intersection_attempts"):
            props_col.prop(
                scene,
                "t4p_smooth_intersection_attempts",
                text="Smoothing attempts",
            )
        else:
            props_col.label(text="Smoothing attempts: 5")

        is_object_mode = context.mode == "OBJECT"
        has_selection = bool(getattr(context, "selected_objects", []))

        controls_col = layout.column(align=True)
        button_configs = (
            (SMOOTH_OPERATOR_IDNAME, "MOD_DASH", "Fix intersections"),
            (FILTER_OPERATOR_IDNAME, "FILTER", "Filter intersections"),
            (FILTER_NON_MANIFOLD_OPERATOR_IDNAME, "FILTER", "Filter non-manifold"),
            (CLEAN_NON_MANIFOLD_OPERATOR_IDNAME, "BRUSH_DATA", "Clean non-manifold"),
            (TRIANGULATE_OPERATOR_IDNAME, "MOD_TRIANGULATE", "Triangulate all"),
        )

        for operator_id, icon, label in button_configs:
            row = controls_col.row(align=True)
            row.enabled = is_object_mode and has_selection
            row.operator(operator_id, icon=icon, text=label)


classes = (
    T4P_OT_smooth_intersections,
    T4P_OT_filter_intersections,
    T4P_OT_filter_non_manifold,
    T4P_OT_clean_non_manifold,
    T4P_OT_triangulate_selected,
    T4P_PT_main_panel,
)


def register() -> None:
    bpy.types.Scene.t4p_smooth_intersection_attempts = IntProperty(
        name="Smooth Attempts",
        description=(
            "Maximum number of smoothing iterations to run when removing"
            " mesh self-intersections"
        ),
        default=5,
        min=1,
    )
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "t4p_smooth_intersection_attempts"):
        del bpy.types.Scene.t4p_smooth_intersection_attempts


__all__ = (
    "register",
    "unregister",
    "bl_info",
    "SMOOTH_OPERATOR_IDNAME",
    "FILTER_OPERATOR_IDNAME",
    "FILTER_NON_MANIFOLD_OPERATOR_IDNAME",
    "CLEAN_NON_MANIFOLD_OPERATOR_IDNAME",
    "TRIANGULATE_OPERATOR_IDNAME",
    "T4P_OT_smooth_intersections",
    "T4P_OT_filter_intersections",
    "T4P_OT_filter_non_manifold",
    "T4P_OT_clean_non_manifold",
    "T4P_OT_triangulate_selected",
    "T4P_PT_main_panel",
)


if __name__ == "__main__":
    register()
