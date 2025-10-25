"""User interface panel for the T4P clean add-on."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from .main import (
    BATCH_DECIMATE_OPERATOR_IDNAME,
    CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_OPERATOR_IDNAME,
    SMOOTH_OPERATOR_IDNAME,
    TRIANGULATE_OPERATOR_IDNAME,
)


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

        ratio_row = controls_col.row(align=True)
        if scene is not None and hasattr(scene, "t4p_batch_decimate_ratio"):
            ratio_col = ratio_row.row(align=True)
            ratio_col.prop(scene, "t4p_batch_decimate_ratio", text="", slider=False)
        else:
            ratio_col = ratio_row.row(align=True)
            ratio_col.label(text="Ratio: 0.50")

        button_col = ratio_row.row(align=True)
        button_col.enabled = is_object_mode and has_selection
        button_col.operator(
            BATCH_DECIMATE_OPERATOR_IDNAME,
            icon="MOD_DECIM",
            text="Batch decimate",
        )

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


__all__ = ("T4P_PT_main_panel",)
