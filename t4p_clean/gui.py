"""User interface panel for the T4P clean add-on."""

from __future__ import annotations

from bpy.types import Panel

from .debug import profile_module
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

        scene = context.scene
        is_object_mode = context.mode == "OBJECT"
        has_selection = bool(getattr(context, "selected_objects", []))

        controls_col = layout.column(align=True)

        triangulate_row = controls_col.row(align=True)
        triangulate_row.enabled = is_object_mode and has_selection
        triangulate_row.operator(
            TRIANGULATE_OPERATOR_IDNAME,
            text="Triangulate all",
        )

        controls_col.label(text="Filters")
        filters_row = controls_col.row(align=True)
        filters_row.enabled = is_object_mode and has_selection
        filters_row.operator(
            FILTER_OPERATOR_IDNAME,
            text="Intersections",
        )
        filters_row.operator(
            FILTER_NON_MANIFOLD_OPERATOR_IDNAME,
            text="Non manifold",
        )

        controls_col.label(text="Cleanup")
        cleanup_col = controls_col.column(align=True)
        if scene is not None and hasattr(scene, "t4p_smooth_intersection_attempts"):
            cleanup_col.prop(
                scene,
                "t4p_smooth_intersection_attempts",
                text="Smoothing attempts",
            )
        else:
            cleanup_col.label(text="Smoothing attempts: 5")

        cleanup_row = cleanup_col.row(align=True)
        cleanup_row.enabled = is_object_mode and has_selection
        cleanup_row.operator(
            SMOOTH_OPERATOR_IDNAME,
            text="Intersections",
        )
        cleanup_row.operator(
            CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
            text="Non manifold",
        )

        controls_col.label(text="Decimate")
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
            text="Batch decimate",
        )


profile_module(globals())


__all__ = ("T4P_PT_main_panel",)
