from __future__ import annotations

import os

import aud
import bpy

_AUDIO_DEVICE: aud.Device | None
_AUDIO_DEVICE = None
_AUDIO_DEVICE_UNAVAILABLE = False
_PLAYBACK_HANDLES: list[aud.Handle] = [] if aud is not None else []
_ADDON_DIR = os.path.dirname(__file__)
_HAPPY_SOUND_PATH = os.path.join(_ADDON_DIR, "chime.wav")
_WARNING_SOUND_PATH = os.path.join(_ADDON_DIR, "warning.wav")


def _play_sound(
    context: bpy.types.Context | None,
    sound_path: str,
    *,
    volume: float = 1.0,
    pitch: float = 1.0,
) -> None:
    """Play a sound file through Blender's shared audio device."""

    device = _get_audio_device(context)
    if device is None:
        return

    if not os.path.isfile(sound_path):
        _report_audio_issue(
            context, f"Audio file missing: '{os.path.basename(sound_path)}'"
        )
        return

    _cleanup_finished_playback()

    try:
        sound = aud.Sound(sound_path)  # type: ignore[attr-defined]
        if pitch != 1.0:
            sound = sound.pitch(pitch)
        device.volume = volume
        handle = device.play(sound)
        if handle is not None:
            if hasattr(handle, "volume"):
                try:
                    handle.volume = volume  # type: ignore[assignment]
                except Exception:  # pragma: no cover - depends on runtime environment.
                    pass
            _PLAYBACK_HANDLES.append(handle)
    except Exception as exc:  # pragma: no cover - depends on runtime environment.
        _report_audio_issue(context, f"Failed to play sound '{sound_path}': {exc}")


def _report_audio_issue(context: bpy.types.Context | None, message: str) -> None:
    """Report an audio related issue to the system console."""

    print(f"[T4P][audio] {message}")


def _get_audio_device(context: bpy.types.Context | None = None) -> aud.Device | None:
    """Return a shared audio device when available."""

    global _AUDIO_DEVICE, _AUDIO_DEVICE_UNAVAILABLE

    if bpy.app.background:
        return None
    if _AUDIO_DEVICE_UNAVAILABLE:
        return None
    if aud is None:
        if not _AUDIO_DEVICE_UNAVAILABLE:
            details = (
                f"Failed to import Blender's audio module: {_AUDIO_IMPORT_ERROR}"
                if _AUDIO_IMPORT_ERROR is not None
                else "The 'aud' module is not available; sound notifications are disabled."
            )
            _report_audio_issue(context, details)
        _AUDIO_DEVICE_UNAVAILABLE = True
        return None

    if _AUDIO_DEVICE is None:
        try:
            _AUDIO_DEVICE = aud.Device()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - Blender specific failure path.
            _report_audio_issue(context, f"Unable to create audio device: {exc}")
            _AUDIO_DEVICE = None
            _AUDIO_DEVICE_UNAVAILABLE = True

    return _AUDIO_DEVICE


def _cleanup_finished_playback() -> None:
    """Drop finished audio handles so playback continues on Linux."""

    global _PLAYBACK_HANDLES

    if aud is None or not _PLAYBACK_HANDLES:
        _PLAYBACK_HANDLES = []
        return

    playing_status = getattr(aud, "AUD_STATUS_PLAYING", None)
    paused_status = getattr(aud, "AUD_STATUS_PAUSED", None)

    active_handles: list[aud.Handle] = []
    for handle in _PLAYBACK_HANDLES:
        status = getattr(handle, "status", None)
        if status in (playing_status, paused_status):
            active_handles.append(handle)

    _PLAYBACK_HANDLES = active_handles


def _play_happy_sound(context: bpy.types.Context | None = None) -> None:
    """Play the confirmation chime when operations succeed."""

    _play_sound(context, _HAPPY_SOUND_PATH)


def _play_warning_sound(context: bpy.types.Context | None = None) -> None:
    """Play a warning chime when issues are detected."""

    _play_sound(context, _WARNING_SOUND_PATH)


def _disable_profiling_for_audio() -> None:
    """Prevent profiling decorators from wrapping audio helper functions."""

    for function in (
            _report_audio_issue,
            _get_audio_device,
            _cleanup_finished_playback,
            _play_sound,
            _play_happy_sound,
            _play_warning_sound,
    ):
        setattr(function, "_t4p_profile_wrapped", True)
