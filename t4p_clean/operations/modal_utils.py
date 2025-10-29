"""Utilities for building modal operators that process selected objects."""

from __future__ import annotations

from contextlib import AbstractContextManager

import bpy

from ..main import update_window_manager_progress, window_manager_progress


class ModalTimerMixin:
    """Provide helpers for running long operations as modal timers."""

    _modal_timer: bpy.types.Timer | None = None
    _modal_progress_context: AbstractContextManager[
        bpy.types.WindowManager | None
    ] | None = None
    _modal_progress_manager: bpy.types.WindowManager | None = None

    def _start_modal(self, context: bpy.types.Context, total_items: int) -> set[str]:
        """Register the operator as a modal handler and start progress tracking."""

        window_manager = getattr(context, "window_manager", None)
        window = getattr(context, "window", None)
        if window_manager is not None and window is not None:
            self._modal_timer = window_manager.event_timer_add(0.0, window=window)
            window_manager.modal_handler_add(self)  # type: ignore[arg-type]

        self._modal_progress_context = window_manager_progress(context, total_items)
        self._modal_progress_manager = self._modal_progress_context.__enter__()

        return {"RUNNING_MODAL"}

    def _update_modal_progress(self, current_item: int) -> None:
        """Update the progress indicator when active."""

        update_window_manager_progress(self._modal_progress_manager, current_item)

    def _stop_modal(self, context: bpy.types.Context) -> None:
        """Tear down timers and progress tracking for the modal operator."""

        window_manager = getattr(context, "window_manager", None)
        if self._modal_timer is not None and window_manager is not None:
            window_manager.event_timer_remove(self._modal_timer)
        self._modal_timer = None

        if self._modal_progress_context is not None:
            self._modal_progress_context.__exit__(None, None, None)

        self._modal_progress_context = None
        self._modal_progress_manager = None


__all__ = ("ModalTimerMixin",)
