"""Single-file entry point for the T4P Smooth Intersection add-on."""

from __future__ import annotations

from typing import List

import bmesh
import bpy
from bpy.types import Operator, Panel
from mathutils.bvhtree import BVHTree

bl_info = {
    "name": "T4P Smooth Intersection",
    "author": "T4P",
    "version": (0, 0, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Item",
    "description": "Smooth intersecting faces on mesh objects from the Item tab.",
    "warning": "",
    "category": "3D View",
}

SMOOTH_OPERATOR_IDNAME = "t4p_smooth_intersection.smooth_intersections"
FILTER_OPERATOR_IDNAME = "t4p_smooth_intersection.filter_intersections"
TRIANGULATE_OPERATOR_IDNAME = "t4p_smooth_intersection.triangulate_selected"


def _select_intersecting_faces(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh
) -> int:
    """Select intersecting faces of ``bm`` in edit mode.

    Returns the number of faces that were selected.
    """

    if not bm.faces:
        return 0

    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    if tree is None:
        return 0

    intersection_indices = set()
    for index_a, index_b in tree.overlap(tree):
        if index_a == index_b or index_b < index_a:
            continue
        face_a = bm.faces[index_a]
        face_b = bm.faces[index_b]

        verts_a = {vert.index for vert in face_a.verts}
        verts_b = {vert.index for vert in face_b.verts}
        if verts_a & verts_b:
            continue

        intersection_indices.add(index_a)
        intersection_indices.add(index_b)

    for face in bm.faces:
        face.select_set(face.index in intersection_indices)

    bmesh.update_edit_mesh(mesh)
    return len(intersection_indices)


def _grow_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_more()


def _shrink_selection(times: int) -> None:
    for _ in range(times):
        bpy.ops.mesh.select_less()


def _mesh_has_intersections(
    mesh: bpy.types.Mesh, bm: bmesh.types.BMesh | None = None
) -> bool:
    """Return ``True`` when the provided mesh contains self-intersections."""

    def _bmesh_contains_self_intersections(
        eval_bm: bmesh.types.BMesh,
    ) -> bool:
        if not eval_bm.faces:
            return False

        faces = list(eval_bm.faces)
        if not faces:
            return False

        bmesh.ops.triangulate(eval_bm, faces=faces)
        eval_bm.faces.ensure_lookup_table()

        tree = BVHTree.FromBMesh(eval_bm)
        if tree is None:
            return False

        for index_a, index_b in tree.overlap(tree):
            if index_a == index_b or index_b < index_a:
                continue

            face_a = eval_bm.faces[index_a]
            face_b = eval_bm.faces[index_b]

            verts_a = {vert.index for vert in face_a.verts}
            verts_b = {vert.index for vert in face_b.verts}

            if verts_a & verts_b:
                continue

            return True

        return False

    if bm is not None:
        bm_copy = bm.copy()
        try:
            return _bmesh_contains_self_intersections(bm_copy)
        finally:
            bm_copy.free()

    new_bm = bmesh.new()
    try:
        new_bm.from_mesh(mesh)
        return _bmesh_contains_self_intersections(new_bm)
    finally:
        new_bm.free()

    return False


def _smooth_object_intersections(obj: bpy.types.Object) -> int:
    """Run the intersection smoothing workflow on a mesh object.

    Returns the number of iterations that performed smoothing.
    """

    mesh = obj.data
    if mesh is None:
        return 0

    smoothed_attempts = 0

    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)

        if not _mesh_has_intersections(mesh, bm):
            return 0

        bpy.ops.object.mode_set(mode="OBJECT")
        _triangulate_mesh(mesh)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)

        if not _mesh_has_intersections(mesh, bm):
            return 0

        bpy.ops.mesh.select_mode(type="FACE")

        for iteration in range(1, 4):
            face_count = _select_intersecting_faces(mesh, bm)
            if face_count == 0:
                break

            _grow_selection(2)
            _shrink_selection(1)
            bpy.ops.mesh.vertices_smooth(repeat=iteration)
            smoothed_attempts += 1

            bmesh.update_edit_mesh(mesh)
            bm = bmesh.from_edit_mesh(mesh)

            if not _mesh_has_intersections(mesh, bm):
                return smoothed_attempts

            bpy.ops.mesh.select_mode(type="FACE")
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    if not _mesh_has_intersections(mesh):
        return smoothed_attempts

    return smoothed_attempts


def _smooth_object_intersections_in_edit_mode(obj: bpy.types.Object) -> int:
    """Run the smoothing workflow while temporarily entering edit mode."""

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        return _smooth_object_intersections(obj)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


class T4P_OT_smooth_intersections(Operator):
    """Smooth intersecting faces across all mesh objects."""

    bl_idname = SMOOTH_OPERATOR_IDNAME
    bl_label = "Smooth Intersections"
    bl_description = "Smooth intersecting faces for every mesh object"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to smooth intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active
        initial_selection = list(context.selected_objects)

        bpy.ops.object.select_all(action="DESELECT")

        smoothed_objects: List[str] = []

        for obj in context.scene.objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            if context.view_layer.objects.get(obj.name) is None:
                continue

            obj.select_set(True)
            context.view_layer.objects.active = obj

            try:
                attempts = _smooth_object_intersections_in_edit_mode(obj)
            except RuntimeError:
                attempts = 0
            finally:
                obj.select_set(False)

            if attempts:
                smoothed_objects.append(obj.name)

        bpy.ops.object.select_all(action="DESELECT")

        for obj in initial_selection:
            if context.scene.objects.get(obj.name) is not None:
                obj.select_set(True)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active
        elif initial_active is None:
            context.view_layer.objects.active = None

        if not smoothed_objects:
            self.report({"INFO"}, "No intersecting faces were found.")
        else:
            self.report(
                {"INFO"},
                "Smoothed intersections on: {}".format(
                    ", ".join(smoothed_objects)
                ),
            )

        return {"FINISHED"}


class T4P_OT_filter_intersections(Operator):
    """Keep selected only the mesh objects that have intersections."""

    bl_idname = FILTER_OPERATOR_IDNAME
    bl_label = "Filter Intersections"
    bl_description = "Deselect selected objects without self-intersections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to filter intersections.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
            return {"FINISHED"}

        objects_with_intersections: list[bpy.types.Object] = []

        for obj in selected_objects:
            has_intersections = False
            if obj.type == "MESH" and obj.data is not None:
                try:
                    has_intersections = _mesh_has_intersections(obj.data)
                except RuntimeError:
                    has_intersections = False

            obj.select_set(has_intersections)

            if has_intersections:
                objects_with_intersections.append(obj)

        new_active = None
        if initial_active and initial_active in objects_with_intersections:
            new_active = initial_active
        elif objects_with_intersections:
            new_active = objects_with_intersections[0]

        context.view_layer.objects.active = new_active

        if not objects_with_intersections:
            self.report({"INFO"}, "No self-intersections detected on selected objects.")
        else:
            self.report(
                {"INFO"},
                "Objects with self-intersections: {}".format(
                    ", ".join(obj.name for obj in objects_with_intersections)
                ),
            )

        return {"FINISHED"}


def _triangulate_mesh(mesh: bpy.types.Mesh) -> bool:
    """Triangulate the provided mesh in-place.

    Returns ``True`` when triangulation was attempted on at least one face.
    """

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        if not bm.faces:
            return False

        faces = list(bm.faces)
        if not faces:
            return False

        bmesh.ops.triangulate(bm, faces=faces)
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()

    return True


class T4P_OT_triangulate_selected(Operator):
    """Triangulate all selected mesh objects."""

    bl_idname = TRIANGULATE_OPERATOR_IDNAME
    bl_label = "Triangulate Selected Meshes"
    bl_description = "Triangulate meshes for all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object mode to triangulate meshes.")
            return {"CANCELLED"}

        initial_active = context.view_layer.objects.active

        selected_objects = list(context.selected_objects)
        triangulated_objects = []
        mesh_candidates = 0

        for obj in selected_objects:
            if obj.type != "MESH" or obj.data is None:
                continue

            mesh_candidates += 1
            try:
                changed = _triangulate_mesh(obj.data)
            except RuntimeError:
                changed = False

            if changed:
                triangulated_objects.append(obj.name)

        if initial_active and context.scene.objects.get(initial_active.name) is not None:
            context.view_layer.objects.active = initial_active

        if not selected_objects:
            self.report({"INFO"}, "No objects selected.")
        elif mesh_candidates == 0:
            self.report({"INFO"}, "No mesh objects selected.")
        elif not triangulated_objects:
            self.report({"INFO"}, "Selected meshes have no faces to triangulate.")
        else:
            self.report(
                {"INFO"},
                "Triangulated: {}".format(
                    ", ".join(triangulated_objects)
                ),
            )

        return {"FINISHED"}


class T4P_PT_main_panel(Panel):
    """Panel that hosts the placeholder button in the Item tab."""

    bl_idname = "T4P_PT_main_panel"
    bl_label = "T4P Smooth Intersection"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"

    def draw(self, context):
        layout = self.layout

        col = layout.column()
        col.enabled = context.mode == "OBJECT" and bool(context.selected_objects)

        col.operator(
            SMOOTH_OPERATOR_IDNAME,
            icon="MOD_BOOLEAN",
            text="Smooth int",
        )
        col.operator(
            FILTER_OPERATOR_IDNAME,
            icon="FILTER",
            text="Filter intersections",
        )
        col.operator(
            TRIANGULATE_OPERATOR_IDNAME,
            icon="MOD_TRIANGULATE",
            text="Triangulate all",
        )


classes = (
    T4P_OT_smooth_intersections,
    T4P_OT_filter_intersections,
    T4P_OT_triangulate_selected,
    T4P_PT_main_panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


__all__ = (
    "register",
    "unregister",
    "bl_info",
    "SMOOTH_OPERATOR_IDNAME",
    "FILTER_OPERATOR_IDNAME",
    "TRIANGULATE_OPERATOR_IDNAME",
    "T4P_OT_smooth_intersections",
    "T4P_OT_filter_intersections",
    "T4P_OT_triangulate_selected",
    "T4P_PT_main_panel",
)


if __name__ == "__main__":
    register()
