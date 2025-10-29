"""Operator for batch decimating selected mesh objects."""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy
from bpy.types import Operator

from ..audio import _play_happy_sound
from ..debug import profile_module
from ..main import BATCH_DECIMATE_OPERATOR_IDNAME
from .modal_utils import ModalTimerMixin


@dataclass
class _BatchDecimateState:
    """Mutable state tracked while the decimate operator runs."""

    objects_to_process: list[bpy.types.Object] = field(default_factory=list)
    current_index: int = 0
    decimated_objects: list[str] = field(default_factory=list)
    initial_active: bpy.types.Object | None = None
    ratio: float = 0.5


class T4P_OT_batch_decimate(ModalTimerMixin, Operator):
    """Apply a decimate modifier to all selected mesh objects."""

    bl_idname = BATCH_DECIMATE_OPERATOR_IDNAME
    bl_label = "Batch Decimate Selected Meshes"
    bl_description = "Apply the decimate modifier to all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self) -> None:
        object.__setattr__(self, "_batch_decimate_state", _BatchDecimateState())

    @property
    def _state(self) -> _BatchDecimateState:
        return object.__getattribute__(self, "_batch_decimate_state")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return self._begin(context)

    def execute(self, context: bpy.types.Context):
        return self._begin(context)

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)

        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        state = self._state
        if state.current_index >= len(state.objects_to_process):
            return self._finish_modal(context, cancelled=False)

        obj = state.objects_to_process[state.current_index]
        self._process_object(context, obj)
        state.current_index += 1
        self._update_modal_progress(state.current_index)
        return {"RUNNING_MODAL"}

    def _begin(self, context: bpy.types.Context):
        self._reset_state()
        state = self._state
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

        state.ratio = ratio
        state.objects_to_process = mesh_objects
        state.initial_active = context.view_layer.objects.active
        return self._start_modal(context, len(mesh_objects))

    def _reset_state(self) -> None:
        state = self._state
        state.objects_to_process.clear()
        state.current_index = 0
        state.decimated_objects.clear()
        state.initial_active = None
        state.ratio = 0.5

    def _collect_mesh_objects(self, context: bpy.types.Context) -> list[bpy.types.Object]:
        selected_objects = list(getattr(context, "selected_objects", []))
        return [
            obj
            for obj in selected_objects
            if obj.type == "MESH" and obj.data is not None
        ]

    def _process_object(self, context: bpy.types.Context, obj: bpy.types.Object) -> None:
        scene = context.scene
        state = self._state
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
        modifier.ratio = state.ratio

        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except RuntimeError:
            existing = obj.modifiers.get(modifier.name)
            if existing is not None:
                obj.modifiers.remove(existing)
            return

        state.decimated_objects.append(obj.name)

    def _finish_modal(self, context: bpy.types.Context, *, cancelled: bool) -> set[str]:
        self._stop_modal(context)
        state = self._state

        if (
            state.initial_active
            and context.scene.objects.get(state.initial_active.name) is not None
        ):
            context.view_layer.objects.active = state.initial_active

        if cancelled:
            processed = len(state.decimated_objects)
            total = len(state.objects_to_process)
            self.report(
                {"WARNING"},
                f"Batch decimation cancelled after {processed} of {total} objects.",
            )
        elif state.decimated_objects:
            object_list = ", ".join(state.decimated_objects)
            self.report({"INFO"}, f"Decimated: {object_list}")
        else:
            self.report({"INFO"}, "Decimation modifiers could not be applied.")

        _play_happy_sound(context)
        return {"CANCELLED" if cancelled else "FINISHED"}


profile_module(globals())


__all__ = ("T4P_OT_batch_decimate",)
