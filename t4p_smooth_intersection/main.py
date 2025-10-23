"""Core utilities and registration for the T4P Smooth Intersection add-on."""

from __future__ import annotations

import bmesh
import bpy
from bpy.props import IntProperty
from mathutils.bvhtree import BVHTree

SMOOTH_OPERATOR_IDNAME = "t4p_smooth_intersection.smooth_intersections"
FILTER_OPERATOR_IDNAME = "t4p_smooth_intersection.filter_intersections"
FILTER_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.filter_non_manifold"
)
CLEAN_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.clean_non_manifold"
)
TRIANGULATE_OPERATOR_IDNAME = "t4p_smooth_intersection.triangulate_selected"

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


def _triangulate_edit_bmesh(bm: bmesh.types.BMesh) -> bool:
    bm.faces.ensure_lookup_table()
    faces = [face for face in bm.faces if face.is_valid]
    if not faces:
        return False

    bmesh.ops.triangulate(bm, faces=faces)
    return True


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


def _iter_classes():
    from .operations.clean_non_manifold import T4P_OT_clean_non_manifold
    from .operations.filter_intersections import T4P_OT_filter_intersections
    from .operations.filter_non_manifold import T4P_OT_filter_non_manifold
    from .operations.smooth import T4P_OT_smooth_intersections
    from .operations.triangulate import T4P_OT_triangulate_selected
    from .gui import T4P_PT_main_panel

    return (
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
    for cls in _iter_classes():
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_iter_classes()):
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
    "_get_intersecting_face_indices",
    "_select_intersecting_faces",
    "_select_intersecting_faces_on_mesh",
    "_triangulate_edit_bmesh",
    "_triangulate_mesh",
)
