"""Core utilities and registration for the T4P clean add-on."""
from __future__ import annotations

import array
import os
from typing import MutableSequence

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from mathutils.bvhtree import BVHTree

from .debug import DEBUG_PREFERENCE_ATTR, profile_module
from .audio import _disable_profiling_for_audio

try:
    import aud  # type: ignore[attr-defined]
except Exception as exc:  # pragma: no cover - Blender provides ``aud``.
    aud = None  # type: ignore[assignment]
    _AUDIO_IMPORT_ERROR = exc
else:
    _AUDIO_IMPORT_ERROR = None

BATCH_DECIMATE_OPERATOR_IDNAME = "t4p_smooth_intersection.batch_decimate"
SMOOTH_OPERATOR_IDNAME = "t4p_smooth_intersection.smooth_intersections"
FILTER_OPERATOR_IDNAME = "t4p_smooth_intersection.filter_intersections"
FILTER_NON_MANIFOLD_OPERATOR_IDNAME = "t4p_smooth_intersection.filter_non_manifold"
CLEAN_NON_MANIFOLD_OPERATOR_IDNAME = "t4p_smooth_intersection.clean_non_manifold"
SELECT_INTERSECTIONS_OPERATOR_IDNAME = "t4p_smooth_intersection.select_intersections"
SELECT_NON_MANIFOLD_OPERATOR_IDNAME = "t4p_smooth_intersection.select_non_manifold"
FOCUS_INTERSECTIONS_OPERATOR_IDNAME = "t4p_smooth_intersection.focus_intersections"
FOCUS_NON_MANIFOLD_OPERATOR_IDNAME = "t4p_smooth_intersection.focus_non_manifold"
TRIANGULATE_OPERATOR_IDNAME = "t4p_smooth_intersection.triangulate_selected"
SPLIT_LONG_FACES_OPERATOR_IDNAME = "t4p_smooth_intersection.split_long_faces"


class T4PAddonPreferences(bpy.types.AddonPreferences):
    """Add-on preferences exposed in the Blender add-on settings."""

    bl_idname = __package__ or __name__

    enable_debug_output: BoolProperty(
        name="Enable debug output",
        description="Log profiling information when running add-on functions",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:  # pragma: no cover - UI code
        layout = self.layout
        layout.prop(self, DEBUG_PREFERENCE_ATTR, text="Enable debug output")


def _triangulate_bmesh(bm: bmesh.types.BMesh) -> None:
    faces = [face for face in bm.faces]
    bmesh.ops.triangulate(bm, faces=faces)


def select_non_manifold_verts(
        use_wire=False,
        use_boundary=False,
        use_multi_face=False,
        use_non_contiguous=False,
        use_verts=False,
):
    """select non-manifold vertices"""
    bpy.ops.mesh.select_non_manifold(
        extend=False,
        use_wire=use_wire,
        use_boundary=use_boundary,
        use_multi_face=use_multi_face,
        use_non_contiguous=use_non_contiguous,
        use_verts=use_verts,
    )


def count_non_manifold_verts(bm):
    """return a set of coordinates of non-manifold vertices"""
    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
    select_non_manifold_verts(use_wire=True, use_boundary=True, use_verts=True, use_multi_face=True)
    return sum((1 for v in bm.verts if v.select))


def get_bmesh(mesh):
    """get an updated bmesh from mesh and make all indexes"""
    bm = bmesh.from_edit_mesh(mesh)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    return bm


def mesh_checksum_fast(obj):
    m = obj.data
    return hash((
        tuple(round(c, 6) for v in m.vertices for c in v.co),
        tuple(tuple(p.vertices) for p in m.polygons)
    ))


def bmesh_get_intersecting_face_indices(
    bm: bmesh.types.BMesh | None,
) -> MutableSequence[int]:
    """Return the indices of faces that overlap within ``bm``."""

    if bm is None or len(bm.faces) == 0:
        return array.array("i", ())

    bm = bm.copy()
    tree = BVHTree.FromBMesh(bm, epsilon=0.00001)
    if tree is None:
        return array.array("i", ())

    overlap = tree.overlap(tree)
    if not overlap:
        return array.array("i", ())

    faces_error = {index for pair in overlap for index in pair}
    bm.free()
    return array.array("i", faces_error)


def select_faces(face_indices: MutableSequence[int], mesh, bm):
    bm.faces.ensure_lookup_table()

    for i in face_indices:
        if 0 <= i < len(bm.faces):
            bm.faces[i].select_set(True)

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def get_selected_faces(bm: bmesh.types.BMesh):
    """Return a list of all selected faces in the BMesh."""
    return [f for f in bm.faces if f.select]


def get_selected_edges(bm: bmesh.types.BMesh):
    """Return a list of all selected edges in the BMesh."""
    return [e for e in bm.edges if e.select]


def get_selected_verts(bm: bmesh.types.BMesh):
    """Return a list of all selected vertices in the BMesh."""
    return [v for v in bm.verts if v.select]


def focus_view_on_selected_faces(context):
    """Focus the 3D Viewport on the currently selected faces."""

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            space = next((s for s in area.spaces if s.type == 'VIEW_3D'), None)
            if space is None:
                continue

            with context.temp_override(area=area, region=region, space_data=space):
                bpy.ops.view3d.view_selected(use_all_regions=False)
            return True

    return False


_disable_profiling_for_audio()


def _iter_classes():
    from .operations.batch_decimate import T4P_OT_batch_decimate
    from .operations.clean_non_manifold import T4P_OT_clean_non_manifold
    from .operations.filter_intersections import T4P_OT_filter_intersections
    from .operations.filter_non_manifold import T4P_OT_filter_non_manifold
    from .operations.clean_intersections import T4P_OT_smooth_intersections
    from .operations.select_intersections import (
        T4P_OT_focus_intersections,
        T4P_OT_select_intersections,
    )
    from .operations.select_non_manifold import (
        T4P_OT_focus_non_manifold,
        T4P_OT_select_non_manifold,
    )
    from .operations.triangulate import T4P_OT_triangulate_selected
    from .operations.split_long_faces import T4P_OT_split_long_faces
    from .gui import T4P_PT_main_panel

    operator_classes = [
        T4P_OT_batch_decimate,
        T4P_OT_smooth_intersections,
        T4P_OT_filter_intersections,
        T4P_OT_filter_non_manifold,
        T4P_OT_select_intersections,
        T4P_OT_select_non_manifold,
        T4P_OT_focus_intersections,
        T4P_OT_focus_non_manifold,
        T4P_OT_clean_non_manifold,
        T4P_OT_triangulate_selected,
        T4P_OT_split_long_faces,
    ]

    return (T4PAddonPreferences, *operator_classes, T4P_PT_main_panel)


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
    bpy.types.Scene.t4p_batch_decimate_ratio = FloatProperty(
        name="Batch Decimate Ratio",
        description=(
            "Ratio used for decimating each selected mesh; valid values are greater"
            " than 0 and at most 1"
        ),
        default=0.5,
        min=0.0,
        max=1.0,
        precision=3,
    )
    for cls in _iter_classes():
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_iter_classes()):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "t4p_smooth_intersection_attempts"):
        del bpy.types.Scene.t4p_smooth_intersection_attempts
    if hasattr(bpy.types.Scene, "t4p_batch_decimate_ratio"):
        del bpy.types.Scene.t4p_batch_decimate_ratio


profile_module(globals())


__all__ = (
    "register",
    "unregister",
    "BATCH_DECIMATE_OPERATOR_IDNAME",
    "SMOOTH_OPERATOR_IDNAME",
    "FILTER_OPERATOR_IDNAME",
    "FILTER_NON_MANIFOLD_OPERATOR_IDNAME",
    "SELECT_INTERSECTIONS_OPERATOR_IDNAME",
    "SELECT_NON_MANIFOLD_OPERATOR_IDNAME",
    "FOCUS_INTERSECTIONS_OPERATOR_IDNAME",
    "FOCUS_NON_MANIFOLD_OPERATOR_IDNAME",
    "CLEAN_NON_MANIFOLD_OPERATOR_IDNAME",
    "TRIANGULATE_OPERATOR_IDNAME",
    "SPLIT_LONG_FACES_OPERATOR_IDNAME",
    "_triangulate_bmesh",
    "T4PAddonPreferences",
)
