"""Core utilities and registration for the T4P clean add-on."""
from __future__ import annotations

import array
import hashlib
import time
from contextlib import contextmanager
from typing import MutableSequence

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
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

ANALYZE_OPERATOR_IDNAME = "t4p_smooth_intersection.analyze_selection"
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


_CHECKSUM_CACHE_VALUE_KEY = "t4p_mesh_checksum_cache_value"
_CHECKSUM_CACHE_TIME_KEY = "t4p_mesh_checksum_cache_time"
_CHECKSUM_CACHE_DURATION_SECONDS = 5 * 60


@contextmanager
def window_manager_progress(
    context: bpy.types.Context | None, total_items: int
):
    """Provide a context manager for reporting progress to the window manager."""

    if context is None or total_items <= 0:
        yield None
        return

    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        yield None
        return

    window_manager.progress_begin(0, total_items)
    try:
        yield window_manager
    finally:
        window_manager.progress_end()


def update_window_manager_progress(
    window_manager: bpy.types.WindowManager | None, current_item: int
) -> None:
    """Update the active progress indicator when possible."""

    if window_manager is None:
        return

    window_manager.progress_update(current_item)


def start_ui_modal_progress(
    window_manager: bpy.types.WindowManager | None, *, label: str, total_items: int
) -> None:
    """Initialize the custom UI progress indicator in the sidebar."""

    if window_manager is None or not hasattr(window_manager, "t4p_modal_progress_total"):
        return

    total = max(int(total_items), 0)

    window_manager.t4p_modal_progress_label = label
    window_manager.t4p_modal_progress_total = total
    window_manager.t4p_modal_progress_current = 0
    window_manager.t4p_modal_progress_is_running = total > 0


def update_ui_modal_progress(
    window_manager: bpy.types.WindowManager | None, current_item: int
) -> None:
    """Update the sidebar progress indicator when a modal operator advances."""

    if window_manager is None or not hasattr(window_manager, "t4p_modal_progress_total"):
        return

    total = max(int(window_manager.t4p_modal_progress_total), 0)
    clamped_current = max(0, min(int(current_item), total if total > 0 else int(current_item)))
    window_manager.t4p_modal_progress_current = clamped_current


def finish_ui_modal_progress(window_manager: bpy.types.WindowManager | None) -> None:
    """Clear the sidebar progress indicator once the modal operator stops."""

    if window_manager is None or not hasattr(window_manager, "t4p_modal_progress_total"):
        return

    window_manager.t4p_modal_progress_current = window_manager.t4p_modal_progress_total
    window_manager.t4p_modal_progress_is_running = False


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


def _clear_cached_mesh_checksum(obj: bpy.types.Object | None) -> None:
    """Remove cached checksum data stored on ``obj``."""

    if obj is None:
        return

    if not hasattr(obj, "keys"):
        return

    for key in (_CHECKSUM_CACHE_VALUE_KEY, _CHECKSUM_CACHE_TIME_KEY):
        try:
            if key in obj:
                del obj[key]
        except Exception:
            continue


def _set_cached_mesh_checksum(obj: bpy.types.Object | None, checksum: int) -> None:
    """Store the checksum value and timestamp on ``obj``."""

    if obj is None:
        return

    if not hasattr(obj, "keys"):
        return

    try:
        obj[_CHECKSUM_CACHE_VALUE_KEY] = int(checksum)
        obj[_CHECKSUM_CACHE_TIME_KEY] = float(time.time())
    except Exception:
        _clear_cached_mesh_checksum(obj)


def _get_cached_mesh_checksum(obj: bpy.types.Object | None) -> int | None:
    """Return the cached checksum when it is still valid."""

    if obj is None or obj.type != "MESH":
        return None

    if not hasattr(obj, "get"):
        return None

    cached_value = obj.get(_CHECKSUM_CACHE_VALUE_KEY)
    cached_time = obj.get(_CHECKSUM_CACHE_TIME_KEY)

    if cached_value is None or cached_time is None:
        return None

    try:
        cached_timestamp = float(cached_time)
    except (TypeError, ValueError):
        _clear_cached_mesh_checksum(obj)
        return None

    if time.time() - cached_timestamp > _CHECKSUM_CACHE_DURATION_SECONDS:
        _clear_cached_mesh_checksum(obj)
        return None

    try:
        return int(cached_value)
    except (TypeError, ValueError):
        _clear_cached_mesh_checksum(obj)
        return None


def calculate_object_mesh_checksum(obj: bpy.types.Object | None) -> int | None:
    """Return a checksum for the mesh data on ``obj`` if possible."""

    cached_checksum = _get_cached_mesh_checksum(obj)
    if cached_checksum is not None:
        return cached_checksum

    if obj is None or obj.type != "MESH":
        _clear_cached_mesh_checksum(obj)
        return None

    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "vertices") or not hasattr(mesh, "polygons"):
        _clear_cached_mesh_checksum(obj)
        return None

    checksum = mesh_checksum_fast(obj)
    _set_cached_mesh_checksum(obj, checksum)
    return checksum


def set_object_analysis_stats(
    obj: bpy.types.Object | None,
    *,
    non_manifold_count: int | None = None,
    intersection_count: int | None = None,
) -> None:
    """Store the latest analysis counts on ``obj`` when available."""

    if obj is None:
        return

    should_update_non_manifold = non_manifold_count is not None
    should_update_intersections = intersection_count is not None
    checksum: int | None = None

    if should_update_non_manifold or should_update_intersections:
        checksum = calculate_object_mesh_checksum(obj)

    if should_update_non_manifold:
        obj["t4p_non_manifold_count"] = int(non_manifold_count)
        obj["t4p_non_manifold_checksum"] = checksum if checksum is not None else "0"

    if should_update_intersections:
        obj["t4p_self_intersection_count"] = int(intersection_count)
        obj["t4p_self_intersection_checksum"] = checksum if checksum is not None else "0"


def _get_validated_object_stat(
    obj: bpy.types.Object | None,
    count_key: str,
    checksum_key: str,
) -> int | None:
    """Return the stored analysis value when the mesh checksum is current."""

    if obj is None:
        return None

    stored_count = obj.get(count_key)
    stored_checksum = obj.get(checksum_key)
    if stored_count is None or stored_checksum in (None, "0"):
        return None

    current_checksum = calculate_object_mesh_checksum(obj)
    if current_checksum is None or current_checksum != stored_checksum:
        return None

    try:
        return int(stored_count)
    except (TypeError, ValueError):
        return None


def get_cached_non_manifold_count(obj: bpy.types.Object | None) -> int | None:
    """Return the cached non-manifold vertex count when available."""

    return _get_validated_object_stat(
        obj,
        "t4p_non_manifold_count",
        "t4p_non_manifold_checksum",
    )


def get_cached_self_intersection_count(obj: bpy.types.Object | None) -> int | None:
    """Return the cached self-intersection count when available."""

    return _get_validated_object_stat(
        obj,
        "t4p_self_intersection_count",
        "t4p_self_intersection_checksum",
    )


def get_bmesh(mesh):
    """get an updated bmesh from mesh and make all indexes"""
    bm = bmesh.from_edit_mesh(mesh)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    return bm


def mesh_checksum_fast(obj, decimals=3):
    """Stable, fast checksum of vertex positions (rounded) + polygon topology.
       Object Mode only (uses Mesh data directly).
    """
    me = obj.data

    # --- vertex coords (fast path) ---
    n = len(me.vertices) * 3
    coords = [0.0] * n
    me.vertices.foreach_get("co", coords)

    q = 10 ** decimals  # rounding factor
    # quantize to integers (rounding) to keep it stable and compact
    coords_q = array.array('i', (int(round(c * q)) for c in coords))

    # --- polygon topology (vertex indices with separators) ---
    poly_idx = array.array('i')
    for p in me.polygons:
        poly_idx.extend(p.vertices)  # indices
        poly_idx.append(-1)          # separator

    # --- hash (blake2b is fast and stable) ---
    h = hashlib.blake2b(digest_size=16)
    h.update(coords_q.tobytes())
    h.update(poly_idx.tobytes())
    return h.hexdigest()


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
    from .operations.analyze import T4P_OT_analyze_selection
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
        T4P_OT_analyze_selection,
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
    bpy.types.WindowManager.t4p_modal_progress_is_running = BoolProperty(
        name="T4P Modal Progress Active",
        default=False,
        options={"HIDDEN"},
    )
    bpy.types.WindowManager.t4p_modal_progress_current = IntProperty(
        name="T4P Modal Progress Current",
        default=0,
        min=0,
        options={"HIDDEN"},
    )
    bpy.types.WindowManager.t4p_modal_progress_total = IntProperty(
        name="T4P Modal Progress Total",
        default=0,
        min=0,
        options={"HIDDEN"},
    )
    bpy.types.WindowManager.t4p_modal_progress_label = StringProperty(
        name="T4P Modal Progress Label",
        default="",
        options={"HIDDEN"},
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
    if hasattr(bpy.types.WindowManager, "t4p_modal_progress_is_running"):
        del bpy.types.WindowManager.t4p_modal_progress_is_running
    if hasattr(bpy.types.WindowManager, "t4p_modal_progress_current"):
        del bpy.types.WindowManager.t4p_modal_progress_current
    if hasattr(bpy.types.WindowManager, "t4p_modal_progress_total"):
        del bpy.types.WindowManager.t4p_modal_progress_total
    if hasattr(bpy.types.WindowManager, "t4p_modal_progress_label"):
        del bpy.types.WindowManager.t4p_modal_progress_label


profile_module(globals())


__all__ = (
    "register",
    "unregister",
    "ANALYZE_OPERATOR_IDNAME",
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
    "start_ui_modal_progress",
    "update_ui_modal_progress",
    "finish_ui_modal_progress",
    "_triangulate_bmesh",
    "T4PAddonPreferences",
    "set_object_analysis_stats",
)
