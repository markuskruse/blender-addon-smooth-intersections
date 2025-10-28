"""Core utilities and registration for the T4P clean add-on."""
from __future__ import annotations

import array
import os
from typing import MutableSequence

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import Operator
from mathutils.bvhtree import BVHTree

from .debug import DEBUG_PREFERENCE_ATTR, profile_module
from .audio import _play_happy_sound, \
    _disable_profiling_for_audio

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
FILTER_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.filter_non_manifold"
)
CLEAN_NON_MANIFOLD_OPERATOR_IDNAME = (
    "t4p_smooth_intersection.clean_non_manifold"
)
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


def select_faces(face_indices: MutableSequence[int], obj):
    if face_indices:
        polygons = obj.data.polygons
        if polygons:
            selection = [False] * len(polygons)
            for index in face_indices:
                if 0 <= index < len(selection):
                    selection[index] = True
            polygons.foreach_set("select", selection)
            obj.data.update()


class T4P_OT_batch_decimate(Operator):
    """Apply a decimate modifier to all selected mesh objects."""

    bl_idname = BATCH_DECIMATE_OPERATOR_IDNAME
    bl_label = "Batch Decimate Selected Meshes"
    bl_description = "Apply the decimate modifier to all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to batch decimate objects.")
            return {"CANCELLED"}

        scene = context.scene
        ratio = float(getattr(scene, "t4p_batch_decimate_ratio", 0.5))
        if ratio <= 0.0 or ratio > 1.0:
            self.report({"ERROR"}, "Decimation ratio must be greater than 0 and at most 1.")
            return {"CANCELLED"}

        selected_objects = list(getattr(context, "selected_objects", []))
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            _play_happy_sound(context)
            return {"FINISHED"}

        mesh_objects = [
            obj for obj in selected_objects if obj.type == "MESH" and obj.data is not None
        ]
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            _play_happy_sound(context)
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        decimated_objects: list[str] = []

        for obj in mesh_objects:
            context.view_layer.objects.active = obj
            try:
                modifier = obj.modifiers.new(name="T4P_BatchDecimate", type="DECIMATE")
            except (RuntimeError, ValueError):
                continue

            modifier.show_viewport = False
            modifier.show_render = False
            if hasattr(modifier, "decimate_type"):
                modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio

            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except RuntimeError:
                if obj.modifiers.get(modifier.name) is not None:
                    obj.modifiers.remove(modifier)
                continue

            decimated_objects.append(obj.name)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        if decimated_objects:
            object_list = ", ".join(decimated_objects)
            self.report({"INFO"}, f"Decimated: {object_list}")
        else:
            self.report({"INFO"}, "Decimation modifiers could not be applied.")

        _play_happy_sound(context)
        return {"FINISHED"}


_disable_profiling_for_audio()


def _iter_classes():
    from .operations.clean_non_manifold import T4P_OT_clean_non_manifold
    from .operations.filter_intersections import T4P_OT_filter_intersections
    from .operations.filter_non_manifold import T4P_OT_filter_non_manifold
    from .operations.clean_intersections import T4P_OT_smooth_intersections
    from .operations.triangulate import T4P_OT_triangulate_selected
    from .operations.split_long_faces import T4P_OT_split_long_faces
    from .gui import T4P_PT_main_panel

    operator_classes = [
        T4P_OT_batch_decimate,
        T4P_OT_smooth_intersections,
        T4P_OT_filter_intersections,
        T4P_OT_filter_non_manifold,
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
    "bl_info",
    "BATCH_DECIMATE_OPERATOR_IDNAME",
    "SMOOTH_OPERATOR_IDNAME",
    "FILTER_OPERATOR_IDNAME",
    "FILTER_NON_MANIFOLD_OPERATOR_IDNAME",
    "CLEAN_NON_MANIFOLD_OPERATOR_IDNAME",
    "TRIANGULATE_OPERATOR_IDNAME",
    "SPLIT_LONG_FACES_OPERATOR_IDNAME",
    "_triangulate_bmesh",
    "T4P_OT_batch_decimate",
    "T4PAddonPreferences",
)
