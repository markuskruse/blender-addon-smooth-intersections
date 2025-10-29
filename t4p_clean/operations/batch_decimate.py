"""Operator for batch decimating selected mesh objects."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound
from ..debug import profile_module
from ..main import BATCH_DECIMATE_OPERATOR_IDNAME
from .modal_utils import ModalTimerMixin


class T4P_OT_batch_decimate(ModalTimerMixin, Operator):
    """Apply a decimate modifier to all selected mesh objects."""

    bl_idname = BATCH_DECIMATE_OPERATOR_IDNAME
    bl_label = "Batch Decimate Selected Meshes"
    bl_description = "Apply the decimate modifier to all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self) -> None:
        self._objects_to_process: list[bpy.types.Object] = []
        self._current_index = 0
        self._decimated_objects: list[str] = []
        self._initial_active: bpy.types.Object | None = None
        self._ratio: float = 0.5

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return self._begin(context)

    def execute(self, context: bpy.types.Context):
        return self._begin(context)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        if self._current_index >= len(self._objects_to_process):
            return self._finish_modal(context, cancelled=False)

        obj = self._objects_to_process[self._current_index]
        self._process_object(context, obj)
        self._current_index += 1
        self._update_modal_progress(self._current_index)
        return {"RUNNING_MODAL"}

    def _begin(self, context: bpy.types.Context):
        self._reset_state()
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to batch decimate objects.")
            return {"CANCELLED"}

        scene = context.scene
        ratio = float(getattr(scene, "t4p_batch_decimate_ratio", 0.5))
        if ratio <= 0.0 or ratio > 1.0:
            self.report({"ERROR"}, "Decimation ratio must be greater than 0 and at most 1.")
            return {"CANCELLED"}

        mesh_objects = self._collect_mesh_objects(context)
        if not mesh_objects:
            self.report({"INFO"}, "No mesh objects selected.")
            _play_happy_sound(context)
            return {"FINISHED"}

        self._ratio = ratio
        self._objects_to_process = mesh_objects
        self._initial_active = context.view_layer.objects.active
        return self._start_modal(context, len(mesh_objects))

    def _reset_state(self) -> None:
        self._objects_to_process = []
        self._current_index = 0
        self._decimated_objects = []
        self._initial_active = None
        self._ratio = 0.5

    def _collect_mesh_objects(self, context: bpy.types.Context) -> list[bpy.types.Object]:
        selected_objects = list(getattr(context, "selected_objects", []))
        return [
            obj
            for obj in selected_objects
            if obj.type == "MESH" and obj.data is not None
        ]

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        scene = context.scene
        if scene is not None and scene.objects.get(obj.name) is None:
            return

        context.view_layer.objects.active = obj
        try:
            modifier = obj.modifiers.new(name="T4P_BatchDecimate", type="DECIMATE")
        except (RuntimeError, ValueError):
            return

        modifier.show_viewport = False
        modifier.show_render = False
        if hasattr(modifier, "decimate_type"):
            modifier.decimate_type = "COLLAPSE"
        modifier.ratio = self._ratio

        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except RuntimeError:
            existing = obj.modifiers.get(modifier.name)
            if existing is not None:
                obj.modifiers.remove(existing)
            return

        self._decimated_objects.append(obj.name)

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)

        if (
            self._initial_active
            and context.scene.objects.get(self._initial_active.name) is not None
        ):
            context.view_layer.objects.active = self._initial_active

        if cancelled:
            processed = len(self._decimated_objects)
            total = len(self._objects_to_process)
            self.report(
                {"WARNING"},
                f"Batch decimation cancelled after {processed} of {total} objects.",
            )
        elif self._decimated_objects:
            object_list = ", ".join(self._decimated_objects)
            self.report({"INFO"}, f"Decimated: {object_list}")
        else:
            self.report({"INFO"}, "Decimation modifiers could not be applied.")

        _play_happy_sound(context)
        return {"CANCELLED" if cancelled else "FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_batch_decimate",)
