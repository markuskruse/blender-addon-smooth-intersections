"""Utility helpers that mirror the native intersection library."""

from __future__ import annotations

import array
from collections.abc import MutableSequence

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

from .debug import profile_module


def bmesh_check_self_intersect_object(
    bm: bmesh.types.BMesh | None,
) -> MutableSequence[int]:
    """Return the indices of faces that overlap within ``bm``."""

    if bm is None or len(bm.faces) == 0:
        return array.array("i", ())

    bm_copy = bm.copy()
    try:
        bm_copy.faces.ensure_lookup_table()
        tree = BVHTree.FromBMesh(bm_copy, epsilon=0.00001)
        if tree is None:
            return array.array("i", ())

        overlap = tree.overlap(tree)
        if not overlap:
            return array.array("i", ())

        faces_error = {index for pair in overlap for index in pair}
        return array.array("i", faces_error)
    finally:
        bm_copy.free()


def mesh_has_self_intersections(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh | None = None
) -> bool:
    """Return ``True`` when the provided mesh contains self-intersections."""

    if bm is not None:
        return bool(bmesh_check_self_intersect_object(bm))

    new_bm = bmesh.new()
    try:
        new_bm.from_mesh(mesh)
        return bool(bmesh_check_self_intersect_object(new_bm))
    finally:
        new_bm.free()


profile_module(globals())


__all__ = (
    "bmesh_check_self_intersect_object",
    "mesh_has_self_intersections",
)
