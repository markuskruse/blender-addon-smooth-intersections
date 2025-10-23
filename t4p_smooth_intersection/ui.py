"""User interface elements for the T4P Smooth Intersection add-on."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from .ops import SMOOTH_OPERATOR_IDNAME, TRIANGULATE_OPERATOR_IDNAME


class T4P_PT_main_panel(Panel):
    """Panel that hosts the placeholder button in the Item tab."""

    bl_idname = "T4P_PT_main_panel"
    bl_label = "T4P Smooth Intersection"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            SMOOTH_OPERATOR_IDNAME,
            icon="MOD_BOOLEAN",
            text="Smooth int",
        )
        layout.operator(
            TRIANGULATE_OPERATOR_IDNAME,
            icon="MOD_TRIANGULATE",
            text="Triangulate all",
        )


classes = (T4P_PT_main_panel,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


__all__ = ("register", "unregister", "T4P_PT_main_panel")
