"""Entry point for the T4P Smooth Intersection add-on."""

from __future__ import annotations

from .gui import T4P_PT_main_panel
from .main import (
    CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_NON_MANIFOLD_OPERATOR_IDNAME,
    FILTER_OPERATOR_IDNAME,
    SMOOTH_OPERATOR_IDNAME,
    TRIANGULATE_OPERATOR_IDNAME,
    bl_info,
    register,
    unregister,
)
from .operations import (
    T4P_OT_clean_non_manifold,
    T4P_OT_filter_intersections,
    T4P_OT_filter_non_manifold,
    T4P_OT_smooth_intersections,
    T4P_OT_triangulate_selected,
)

__all__ = (
    "register",
    "unregister",
    "bl_info",
    "SMOOTH_OPERATOR_IDNAME",
    "FILTER_OPERATOR_IDNAME",
    "FILTER_NON_MANIFOLD_OPERATOR_IDNAME",
    "CLEAN_NON_MANIFOLD_OPERATOR_IDNAME",
    "TRIANGULATE_OPERATOR_IDNAME",
    "T4P_OT_smooth_intersections",
    "T4P_OT_filter_intersections",
    "T4P_OT_filter_non_manifold",
    "T4P_OT_clean_non_manifold",
    "T4P_OT_triangulate_selected",
    "T4P_PT_main_panel",
)


if __name__ == "__main__":
    register()
