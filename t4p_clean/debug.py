"""Debug utilities for the T4P clean add-on."""
from __future__ import annotations

import time
from functools import wraps
from types import FunctionType
from typing import Any, Callable, TypeVar, cast

try:
    import bpy  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - Blender injects bpy at runtime.
    bpy = None  # type: ignore[assignment]

if bpy is not None:
    _BPY_TYPES = getattr(bpy, "types", None)
else:  # pragma: no cover - executed when Blender is unavailable.
    _BPY_TYPES = None

_PROFILED_CLASS_EXCLUSIONS: tuple[type, ...]
if _BPY_TYPES is None:
    _PROFILED_CLASS_EXCLUSIONS = ()
else:  # pragma: no cover - depends on Blender runtime types.
    exclusions: list[type] = []
    for attr_name in (
        "Operator",
        "Panel",
        "Menu",
        "PropertyGroup",
        "AddonPreferences",
    ):
        base_type = getattr(_BPY_TYPES, attr_name, None)
        if isinstance(base_type, type):
            exclusions.append(base_type)
    _PROFILED_CLASS_EXCLUSIONS = tuple(exclusions)


def _is_excluded_class(cls: type) -> bool:
    """Return ``True`` when ``cls`` should not have its methods wrapped."""

    for base_type in _PROFILED_CLASS_EXCLUSIONS:
        try:
            if issubclass(cls, base_type):
                return True
        except TypeError:
            continue

    return False

DEBUG_PREFERENCE_ATTR = "enable_debug_output"
_DEBUG_PREFIX = "[T4P][debug]"
_FuncT = TypeVar("_FuncT", bound=Callable[..., Any])


def _get_addon_preferences() -> Any:
    """Return the add-on preferences instance when available."""

    if bpy is None:
        return None

    context = getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None) if context is not None else None
    addons = getattr(preferences, "addons", None) if preferences is not None else None
    if addons is None:
        return None

    addon_key = __package__ if isinstance(__package__, str) else None
    if not addon_key:
        return None

    addon = addons.get(addon_key)
    if addon is None:
        return None

    return getattr(addon, "preferences", None)


def is_debug_output_enabled() -> bool:
    """Return ``True`` when debug output is enabled in the add-on preferences."""

    preferences = _get_addon_preferences()
    if preferences is None:
        return False

    return bool(getattr(preferences, DEBUG_PREFERENCE_ATTR, False))


def profiled(function: _FuncT) -> _FuncT:
    """Wrap ``function`` to log its execution time when debugging is enabled."""

    if getattr(function, "_t4p_profile_wrapped", False):
        return function

    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any):
        if not is_debug_output_enabled():
            return function(*args, **kwargs)

        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            duration_ms_rounded = int(duration_ms + 0.5)
            identifier = f"{function.__module__}.{getattr(function, '__qualname__', function.__name__)}"
            print(f"{_DEBUG_PREFIX} {identifier} took {duration_ms_rounded} ms")

    setattr(wrapper, "_t4p_profile_wrapped", True)
    return cast(_FuncT, wrapper)


def profile_module(namespace: dict[str, Any]) -> None:
    """Profile all functions defined in the given module namespace."""

    module_name = namespace.get("__name__")
    if not isinstance(module_name, str):
        return

    for name, value in list(namespace.items()):
        if isinstance(value, FunctionType) and getattr(value, "__module__", None) == module_name:
            if getattr(value, "_t4p_profile_wrapped", False):
                continue
            namespace[name] = profiled(value)
            continue

        if isinstance(value, type) and getattr(value, "__module__", None) == module_name:
            if _is_excluded_class(value):
                continue
            for attr_name, attr_value in list(vars(value).items()):
                if not isinstance(attr_value, FunctionType):
                    continue
                if getattr(attr_value, "__module__", None) != module_name:
                    continue
                if getattr(attr_value, "_t4p_profile_wrapped", False):
                    continue
                setattr(value, attr_name, profiled(attr_value))


__all__ = ("DEBUG_PREFERENCE_ATTR", "is_debug_output_enabled", "profiled", "profile_module")
