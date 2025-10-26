"""Operator and helpers for cleaning non-manifold geometry."""

from __future__ import annotations

import bmesh
import bpy
from bpy.types import Operator

from ..main import (
    CLEAN_NON_MANIFOLD_OPERATOR_IDNAME,
    _play_happy_sound,
    _triangulate_bmesh,
)


def _get_mesh_vertex_islands(
    bm: bmesh.types.BMesh,
) -> list[list[bmesh.types.BMVert]]:
    bm.verts.ensure_lookup_table()
    visited: set[int] = set()
    islands: list[list[bmesh.types.BMVert]] = []

    for vert in bm.verts:
        if not vert.is_valid:
            continue
        if vert.index in visited:
            continue

        stack = [vert]
        island: list[bmesh.types.BMVert] = []
        while stack:
            current = stack.pop()
            if not current.is_valid:
                continue

            index = current.index
            if index in visited:
                continue

            visited.add(index)
            island.append(current)

            for edge in current.link_edges:
                if not edge.is_valid:
                    continue
                for linked_vert in edge.verts:
                    if linked_vert.is_valid and linked_vert.index not in visited:
                        stack.append(linked_vert)

        if island:
            islands.append(island)

    return islands


def _delete_small_vertex_islands(
    bm: bmesh.types.BMesh, min_vertices: int
) -> bool:
    islands = _get_mesh_vertex_islands(bm)
    if not islands:
        return False

    max_size = max(len(island) for island in islands)
    verts_to_delete: set[bmesh.types.BMVert] = set()
    for island in islands:
        if len(island) < min_vertices and len(island) < max_size:
            verts_to_delete.update(island)

    if not verts_to_delete:
        return False

    bmesh.ops.delete(bm, geom=list(verts_to_delete), context="VERTS")
    return True


def delete_interior_faces() -> bool:
    """Delete interior faces in edit mode.

    Returns ``True`` if any interior faces were removed.
    """

    edit_object = bpy.context.edit_object
    mesh = None
    if edit_object is not None and edit_object.type == "MESH":
        mesh = edit_object.data

    try:
        bpy.ops.mesh.select_all(action="DESELECT")
    except RuntimeError:
        return False

    try:
        bpy.ops.mesh.select_interior_faces()
    except RuntimeError:
        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass
        return False

    selected_faces: int | None = None
    if mesh is not None:
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        selected_faces = sum(
            1 for face in bm.faces if face.is_valid and face.select
        )

        if selected_faces == 0:
            try:
                bpy.ops.mesh.select_all(action="SELECT")
            except RuntimeError:
                pass
            return False

    try:
        delete_result = bpy.ops.mesh.delete(type="FACE")
    except RuntimeError:
        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass
        return False

    try:
        bpy.ops.mesh.select_all(action="SELECT")
    except RuntimeError:
        pass

    if "FINISHED" not in delete_result:
        return False

    if selected_faces is not None:
        return selected_faces > 0

    return True


def _fill_and_triangulate_holes(bm: bmesh.types.BMesh) -> bool:
    bm.edges.ensure_lookup_table()
    boundary_edges = [edge for edge in bm.edges if edge.is_valid and edge.is_boundary]
    if not boundary_edges:
        return False

    result = bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
    new_faces = [face for face in result.get("faces", []) if face.is_valid]
    if not new_faces:
        return False

    bmesh.ops.triangulate(bm, faces=new_faces)
    return True


def _dissolve_degenerate_and_triangulate(
    bm: bmesh.types.BMesh, threshold: float
) -> bool:
    bm.edges.ensure_lookup_table()
    edges = [edge for edge in bm.edges if edge.is_valid]
    if not edges:
        return False

    dissolve_result = bmesh.ops.dissolve_degenerate(
        bm, edges=edges, dist=threshold
    )
    # ``bmesh.ops.dissolve_degenerate`` may return ``None`` in some edge cases.
    result_get = getattr(dissolve_result, "get", None)
    if result_get is None:
        changed = False
    else:
        changed = bool(
            result_get("region_edges")
            or result_get("region_faces")
            or result_get("region_verts")
        )

    triangulated = _triangulate_bmesh(bm)
    return changed or triangulated


def _clean_object_non_manifold(obj: bpy.types.Object) -> bool:
    mesh = obj.data
    if mesh is None:
        return False

    try:
        bpy.ops.object.mode_set(mode="EDIT")
    except RuntimeError:
        return False

    changed = False

    try:
        try:
            bpy.ops.mesh.select_mode(type="VERT")
        except RuntimeError:
            pass

        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except RuntimeError:
            pass

        bm = bmesh.from_edit_mesh(mesh)

        if _triangulate_bmesh(bm):
            changed = True

        if _delete_small_vertex_islands(bm, min_vertices=100):
            changed = True

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        if delete_interior_faces():
            changed = True

        try:
            delete_loose_result = bpy.ops.mesh.delete_loose()
        except RuntimeError:
            delete_loose_result = set()
        else:
            if "FINISHED" in delete_loose_result:
                changed = True

        bm = bmesh.from_edit_mesh(mesh)

        if _fill_and_triangulate_holes(bm):
            changed = True

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        bm = bmesh.from_edit_mesh(mesh)

        if _dissolve_degenerate_and_triangulate(bm, threshold=0.01):
            changed = True
    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass

    return changed


class T4P_OT_clean_non_manifold(Operator):
    """Clean up non-manifold geometry across selected mesh objects."""

    bl_idname = CLEAN_NON_MANIFOLD_OPERATOR_IDNAME
    bl_label = "Clean Non-manifold"
    bl_description = "Remove small islands, loose elements, and holes on selected meshes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to clean non-manifold meshes.")
            return {"CANCELLED"}

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        initial_active = context.view_layer.objects.active
        scene = context.scene
        cleaned_objects: list[bpy.types.Object] = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if scene is not None and scene.objects.get(obj.name) is None:
                continue

            mesh_candidates += 1

            context.view_layer.objects.active = obj
            obj.select_set(True)

            try:
                changed = _clean_object_non_manifold(obj)
            except RuntimeError:
                changed = False

            if changed:
                cleaned_objects.append(obj)

        if initial_active and (
            scene is None
            or scene.objects.get(initial_active.name) is not None
        ):
            context.view_layer.objects.active = initial_active
        elif initial_active is None:
            context.view_layer.objects.active = None
        elif cleaned_objects:
            context.view_layer.objects.active = cleaned_objects[0]
        else:
            context.view_layer.objects.active = None

        if mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif cleaned_objects:
            self.report(
                {"INFO"},
                "Cleaned non-manifold geometry on: {}".format(
                    ", ".join(obj.name for obj in cleaned_objects)
                ),
            )
        else:
            self.report({"INFO"}, "No changes made to selected meshes.")

        _play_happy_sound(context)

        return {"FINISHED"}


__all__ = ("T4P_OT_clean_non_manifold",)
