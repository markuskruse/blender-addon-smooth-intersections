"""Core utilities and registration for the T4P clean add-on."""

from __future__ import annotations

import sys
import time
from functools import wraps
from pathlib import Path

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


_CHIME_FILENAME = "chime.wav"
_WARNING_FILENAME = "warning.wav"
_SOUND_FILEPATH_CACHE: dict[str, str] = {}
_AUD_DEVICE = None
_AUD_MODULE = None
_AUD_IMPORT_FAILED = False
_AUD_HANDLES: list[object] = []


def _resolve_sound_filepath(filename: str, cache_key: str) -> str | None:
    cached = _SOUND_FILEPATH_CACHE.get(cache_key)
    if cached is not None:
        return cached or None

    candidate = Path(__file__).resolve().parent / filename
    resolved = str(candidate) if candidate.exists() else ""
    _SOUND_FILEPATH_CACHE[cache_key] = resolved
    return resolved or None


def _get_chime_filepath() -> str | None:
    return _resolve_sound_filepath(_CHIME_FILENAME, "chime")


def _get_warning_filepath() -> str | None:
    return _resolve_sound_filepath(_WARNING_FILENAME, "warning")


def _get_sound_operator():
    return getattr(getattr(bpy.ops, "wm", None), "sound_play", None)


def _iter_sound_operator_overrides(context: bpy.types.Context | None):
    override: dict[str, object] = {}
    if context is not None:
        window = getattr(context, "window", None)
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if window is not None and area is not None and region is not None:
            override = {"window": window, "area": area, "region": region}

    if override:
        yield override
    yield {}


def _try_play_sound(context: bpy.types.Context | None, **kwargs) -> bool:
    sound_operator = _get_sound_operator()
    if sound_operator is None:
        return False

    for override in _iter_sound_operator_overrides(context):
        try:
            if override:
                sound_operator(override, **kwargs)
            else:
                sound_operator(**kwargs)
            return True
        except TypeError:
            continue
        except Exception:
            continue

    return False


def _play_sound(sound_id: str, context: bpy.types.Context | None = None) -> None:
    """Play a short notification sound, falling back to a terminal bell."""

    if _try_play_sound(context, sound_id=sound_id):
        return

    if _try_play_sound(context):
        return

    sys.stdout.write("\a")
    sys.stdout.flush()


def _cleanup_aud_handles(aud_module) -> None:
    if not _AUD_HANDLES:
        return

    invalid_status = getattr(aud_module, "AUD_STATUS_INVALID", None)
    stopped_status = getattr(aud_module, "AUD_STATUS_STOPPED", None)
    active_handles: list[object] = []
    for handle in _AUD_HANDLES:
        status = getattr(handle, "status", None)
        if status is None:
            active_handles.append(handle)
            continue

        if status in (invalid_status, stopped_status):
            continue

        active_handles.append(handle)

    _AUD_HANDLES[:] = active_handles


def _play_sound_with_aud(filepath: str) -> bool:
    global _AUD_DEVICE, _AUD_MODULE, _AUD_IMPORT_FAILED

    if not filepath or _AUD_IMPORT_FAILED:
        return False

    if _AUD_MODULE is None:
        try:
            import aud as aud_module  # type: ignore[import-not-found]
        except Exception:
            _AUD_IMPORT_FAILED = True
            return False
        _AUD_MODULE = aud_module

    aud_module = _AUD_MODULE
    if aud_module is None:
        return False

    if _AUD_DEVICE is None:
        try:
            _AUD_DEVICE = aud_module.Device()
        except Exception:
            return False

    try:
        factory = aud_module.Factory(filepath)
        handle = _AUD_DEVICE.play(factory) if _AUD_DEVICE is not None else None
    except Exception:
        return False

    if handle is not None:
        _cleanup_aud_handles(aud_module)
        _AUD_HANDLES.append(handle)

    return True


def _ensure_sound_id(filepath: str) -> str | None:
    try:
        sound = bpy.data.sounds.load(filepath, check_existing=True)
    except RuntimeError:
        sound = bpy.data.sounds.get(Path(filepath).name)
    except Exception:
        sound = None

    if sound is None:
        sound = bpy.data.sounds.get(Path(filepath).name)

    name = getattr(sound, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _play_file_sound(filepath: str | None, context: bpy.types.Context | None = None) -> bool:
    if not filepath:
        return False

    if _try_play_sound(context, filepath=filepath):
        return True

    sound_id = _ensure_sound_id(filepath)
    if sound_id and _try_play_sound(context, sound_id=sound_id):
        return True

    if _play_sound_with_aud(filepath):
        return True

    return False


def _play_chime_sound(context: bpy.types.Context | None = None) -> bool:
    return _play_file_sound(_get_chime_filepath(), context)


def _play_completion_sound(context: bpy.types.Context | None = None) -> None:
    if _play_chime_sound(context):
        return

    _play_sound("INFO", context)


def _play_happy_sound(context: bpy.types.Context | None = None) -> None:
    _play_completion_sound(context)


def _play_warning_sound(context: bpy.types.Context | None = None) -> None:
    if _play_file_sound(_get_warning_filepath(), context):
        return

    _play_sound("WARNING", context)


def _ensure_operation_is_timed(operator_cls: type[bpy.types.Operator]) -> None:
    """Wrap ``execute`` so the runtime is measured for all operator classes."""

    if not issubclass(operator_cls, bpy.types.Operator):
        return

    original_execute = getattr(operator_cls, "execute", None)
    if original_execute is None or getattr(original_execute, "_t4p_is_timed", False):
        return

    @wraps(original_execute)
    def timed_execute(self, context):  # type: ignore[override]
        start_time = time.perf_counter()
        try:
            return original_execute(self, context)
        finally:
            elapsed = time.perf_counter() - start_time
            operator_cls.t4p_last_execution_seconds = elapsed
            if elapsed >= 10.0 and not getattr(
                operator_cls, "t4p_disable_long_running_sound", False
            ):
                _play_completion_sound(context)

    timed_execute._t4p_is_timed = True  # type: ignore[attr-defined]
    setattr(operator_cls, "execute", timed_execute)


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

    operator_classes = [
        T4P_OT_smooth_intersections,
        T4P_OT_filter_intersections,
        T4P_OT_filter_non_manifold,
        T4P_OT_clean_non_manifold,
        T4P_OT_triangulate_selected,
    ]

    for operator_cls in operator_classes:
        _ensure_operation_is_timed(operator_cls)

    return (*operator_classes, T4P_PT_main_panel)


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
