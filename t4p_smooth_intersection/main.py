"""Core utilities and registration for the T4P clean add-on."""
from __future__ import annotations

import os

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator
from mathutils.bvhtree import BVHTree

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

_AUDIO_DEVICE: aud.Device | None
_AUDIO_DEVICE = None
_AUDIO_DEVICE_UNAVAILABLE = False
_PLAYBACK_HANDLES: list[aud.Handle] = [] if aud is not None else []
_ADDON_DIR = os.path.dirname(__file__)
_HAPPY_SOUND_PATH = os.path.join(_ADDON_DIR, "chime.wav")
_WARNING_SOUND_PATH = os.path.join(_ADDON_DIR, "warning.wav")


def _report_audio_issue(context: bpy.types.Context | None, message: str) -> None:
    """Report an audio related issue to the system console."""

    print(f"[T4P][audio] {message}")


def _get_audio_device(context: bpy.types.Context | None = None) -> aud.Device | None:
    """Return a shared audio device when available."""

    global _AUDIO_DEVICE, _AUDIO_DEVICE_UNAVAILABLE

    if bpy.app.background:
        return None
    if _AUDIO_DEVICE_UNAVAILABLE:
        return None
    if aud is None:
        if not _AUDIO_DEVICE_UNAVAILABLE:
            details = (
                f"Failed to import Blender's audio module: {_AUDIO_IMPORT_ERROR}"
                if _AUDIO_IMPORT_ERROR is not None
                else "The 'aud' module is not available; sound notifications are disabled."
            )
            _report_audio_issue(context, details)
        _AUDIO_DEVICE_UNAVAILABLE = True
        return None

    if _AUDIO_DEVICE is None:
        try:
            _AUDIO_DEVICE = aud.Device()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - Blender specific failure path.
            _report_audio_issue(context, f"Unable to create audio device: {exc}")
            _AUDIO_DEVICE = None
            _AUDIO_DEVICE_UNAVAILABLE = True

    return _AUDIO_DEVICE


def _cleanup_finished_playback() -> None:
    """Drop finished audio handles so playback continues on Linux."""

    global _PLAYBACK_HANDLES

    if aud is None or not _PLAYBACK_HANDLES:
        _PLAYBACK_HANDLES = []
        return

    playing_status = getattr(aud, "AUD_STATUS_PLAYING", None)
    paused_status = getattr(aud, "AUD_STATUS_PAUSED", None)

    active_handles: list[aud.Handle] = []
    for handle in _PLAYBACK_HANDLES:
        status = getattr(handle, "status", None)
        if status in (playing_status, paused_status):
            active_handles.append(handle)

    _PLAYBACK_HANDLES = active_handles


def _play_sound(
    context: bpy.types.Context | None,
    sound_path: str,
    *,
    volume: float = 1.0,
    pitch: float = 1.0,
) -> None:
    """Play a sound file through Blender's shared audio device."""

    device = _get_audio_device(context)
    if device is None:
        return

    if not os.path.isfile(sound_path):
        _report_audio_issue(
            context, f"Audio file missing: '{os.path.basename(sound_path)}'"
        )
        return

    _cleanup_finished_playback()

    try:
        sound = aud.Sound(sound_path)  # type: ignore[attr-defined]
        if pitch != 1.0:
            sound = sound.pitch(pitch)
        device.volume = volume
        handle = device.play(sound)
        if handle is not None:
            if hasattr(handle, "volume"):
                try:
                    handle.volume = volume  # type: ignore[assignment]
                except Exception:  # pragma: no cover - depends on runtime environment.
                    pass
            _PLAYBACK_HANDLES.append(handle)
    except Exception as exc:  # pragma: no cover - depends on runtime environment.
        _report_audio_issue(context, f"Failed to play sound '{sound_path}': {exc}")


def _play_happy_sound(context: bpy.types.Context | None = None) -> None:
    """Play the confirmation chime when operations succeed."""

    _play_sound(context, _HAPPY_SOUND_PATH)


def _play_warning_sound(context: bpy.types.Context | None = None) -> None:
    """Play a warning chime when issues are detected."""

    _play_sound(context, _WARNING_SOUND_PATH)


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


def _iter_classes():
    from .operations.clean_non_manifold import T4P_OT_clean_non_manifold
    from .operations.filter_intersections import T4P_OT_filter_intersections
    from .operations.filter_non_manifold import T4P_OT_filter_non_manifold
    from .operations.smooth import T4P_OT_smooth_intersections
    from .operations.triangulate import T4P_OT_triangulate_selected
    from .gui import T4P_PT_main_panel

    operator_classes = [
        T4P_OT_batch_decimate,
        T4P_OT_smooth_intersections,
        T4P_OT_filter_intersections,
        T4P_OT_filter_non_manifold,
        T4P_OT_clean_non_manifold,
        T4P_OT_triangulate_selected,
    ]

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
    "_get_intersecting_face_indices",
    "_select_intersecting_faces",
    "_select_intersecting_faces_on_mesh",
    "_triangulate_edit_bmesh",
    "_triangulate_mesh",
    "T4P_OT_batch_decimate",
)
