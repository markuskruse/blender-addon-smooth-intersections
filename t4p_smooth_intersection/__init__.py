"""Add-on entry point for the T4P Smooth Intersection add-on."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Iterable

from . import ops, ui

bl_info = {
    "name": "T4P Smooth Intersection",
    "author": "T4P",
    "version": (0, 0, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Item",
    "description": "Skeleton add-on with a placeholder button in the Item tab.",
    "warning": "",
    "category": "3D View",
}


_SUBMODULES: tuple[ModuleType, ...] = (
    ops,
    ui,
)


def _reload_modules(modules: Iterable[ModuleType]) -> None:
    for module in modules:
        importlib.reload(module)


def register() -> None:
    _reload_modules(_SUBMODULES)
    for module in _SUBMODULES:
        module.register()


def unregister() -> None:
    for module in reversed(_SUBMODULES):
        module.unregister()


__all__ = ("register", "unregister", "bl_info")


if __name__ == "__main__":
    register()
