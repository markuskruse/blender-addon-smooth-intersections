"""User interface panel for the T4P clean add-on."""

from __future__ import annotations

from bpy.types import Panel


def _get_active_object_analysis_stats(context) -> tuple[str, str, bool]:
    """Return analysis stats for the active object, if present."""

    active_object = getattr(context, "active_object", None)
    if active_object is None:
        return "0", "0", False

    non_manifold_value = active_object.get("t4p_non_manifold_count")
    intersection_value = active_object.get("t4p_self_intersection_count")
    non_manifold_checksum = active_object.get("t4p_non_manifold_checksum")
    intersection_checksum = active_object.get("t4p_self_intersection_checksum")

    has_non_manifold = non_manifold_value is not None
    has_intersections = intersection_value is not None
    has_stats = bool(has_non_manifold and has_intersections)

    non_manifold_count = int(non_manifold_value) if has_non_manifold else 0
    intersection_count = int(intersection_value) if has_intersections else 0

    current_checksum = calculate_object_mesh_checksum(active_object)

    def _format_stat(count: int, stored_checksum) -> str:
        text = str(count)
        if (
            stored_checksum is not None
            and current_checksum is not None
            and int(stored_checksum) != int(current_checksum)
        ):
            text = f"{text}??"
        return text

    non_manifold_display = _format_stat(non_manifold_count, non_manifold_checksum)
    intersection_display = _format_stat(intersection_count, intersection_checksum)

    return non_manifold_display, intersection_display, has_stats


def _draw_analysis_stat(layout, label_text: str, value: str) -> None:
    """Draw a row showing a single analysis value."""

    row = layout.row(align=True)
    row.label(text=label_text)
    value_row = row.row(align=True)
    value_row.alignment = "RIGHT"
    value_row.label(text=value)

from .debug import profile_module
from .main import (
    ANALYZE_OPERATOR_IDNAME,
    BATCH_DECIMATE_OPERATOR_IDNAME,
    calculate_object_mesh_checksum,
    CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_OPERATOR_IDNAME,
    FOCUS_INTERSECTIONS_OPERATOR_IDNAME,
    FOCUS_NON_MANIFOLD_OPERATOR_IDNAME,
    SELECT_INTERSECTIONS_OPERATOR_IDNAME,
    SELECT_NON_MANIFOLD_OPERATOR_IDNAME,
    SMOOTH_OPERATOR_IDNAME,
    SPLIT_LONG_FACES_OPERATOR_IDNAME,
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

        analyze_row = controls_col.row(align=True)
        analyze_row.enabled = is_object_mode and has_selection
        analyze_row.operator(
            ANALYZE_OPERATOR_IDNAME,
            text="Analyze",
        )

        non_manifold_count, intersection_count, has_stats = (
            _get_active_object_analysis_stats(context)
        )
        stats_col = controls_col.column(align=True)
        stats_col.use_property_split = True
        stats_col.use_property_decorate = False
        stats_col.enabled = has_stats
        _draw_analysis_stat(stats_col, "Non-manifold vertices", non_manifold_count)
        _draw_analysis_stat(stats_col, "Self-intersections", intersection_count)

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

        select_row = controls_col.row(align=True)
        select_row.enabled = context.mode == "EDIT_MESH"
        select_row.operator(
            SELECT_INTERSECTIONS_OPERATOR_IDNAME,
            text="Select intersections",
        )
        select_row.operator(
            SELECT_NON_MANIFOLD_OPERATOR_IDNAME,
            text="Select non manifold",
        )

        focus_row = controls_col.row(align=True)
        focus_row.enabled = context.mode == "EDIT_MESH"
        focus_row.operator(
            FOCUS_INTERSECTIONS_OPERATOR_IDNAME,
            text="Focus on intersection",
        )
        focus_row.operator(
            FOCUS_NON_MANIFOLD_OPERATOR_IDNAME,
            text="Focus on non manifold",
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

        split_row = cleanup_col.row()
        split_row.enabled = context.mode == "EDIT_MESH"
        split_row.operator(
            SPLIT_LONG_FACES_OPERATOR_IDNAME,
            text="Split long faces",
        )

        controls_col.label(text="Decimate")
        decimate_col = controls_col.column(align=True)

        ratio_row = decimate_col.row(align=True)
        if scene is not None and hasattr(scene, "t4p_batch_decimate_ratio"):
            ratio_input = ratio_row.row(align=True)
            ratio_input.prop(scene, "t4p_batch_decimate_ratio", text="", slider=False)
        else:
            ratio_input = ratio_row.row(align=True)
            ratio_input.label(text="Ratio: 0.50")

        button_row = ratio_row.row(align=True)
        button_row.enabled = is_object_mode and has_selection
        button_row.operator(
            BATCH_DECIMATE_OPERATOR_IDNAME,
            text="Batch decimate",
        )


profile_module(globals())


__all__ = ("T4P_PT_main_panel",)
