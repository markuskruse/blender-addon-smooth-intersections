from __future__ import annotations

from math import radians

import bmesh

from main import bmesh_get_intersecting_face_indices


def split_intersections(bm: bmesh.types.BMesh) -> bool:

    sharp_angle_threshold = radians(15.0)

    face_indices = bmesh_get_intersecting_face_indices(bm)
    face_indices = _collect_face_indices_with_neighbors(
        bm, list(face_indices)
    )
    iteration_split = False
    for face_index in face_indices:
        bm.faces.ensure_lookup_table()
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if not face.is_valid or len(face.edges) < 3:
            continue
        if _split_face(bm, face, sharp_angle_threshold):
            iteration_split = True
    bm.normal_update()

    return iteration_split


def split_selection(bm: bmesh.types.BMesh):
    sharp_angle_threshold = radians(15.0)

    bm.faces.ensure_lookup_table()
    selected_visible_faces = [f for f in bm.faces if f.select and not f.hide]
    for face in selected_visible_faces:
        _split_face(bm, face, sharp_angle_threshold)
    bm.normal_update()


def _collect_face_indices_with_neighbors(
    bm: bmesh.types.BMesh, intersection_indices: list[int]
) -> list[int]:
    bm.faces.ensure_lookup_table()
    faces_to_visit: list[int] = []
    seen: set[int] = set()

    for face_index, face in _iter_valid_intersecting_faces(bm, intersection_indices):
        if face_index in seen:
            continue
        seen.add(face_index)
        faces_to_visit.append(face_index)

        for edge in list(face.edges):
            if not edge.is_valid:
                continue
            for neighbor in edge.link_faces:
                if not neighbor.is_valid or len(neighbor.edges) < 3:
                    continue
                neighbor_index = neighbor.index
                if neighbor_index in seen:
                    continue
                seen.add(neighbor_index)
                faces_to_visit.append(neighbor_index)

    return faces_to_visit


def _split_face(
    bm: bmesh.types.BMesh,
    face: bmesh.types.BMFace,
    sharp_angle_threshold: float,
) -> bool:
    if not face.is_valid or not face.loops:
        return False
    smallest_angle = _find_smallest_face_angle(face)
    if smallest_angle >= sharp_angle_threshold:
        return False
    longest_edges = _collect_longest_edges(face)
    if len(longest_edges) < 2:
        return False
    midpoint_vertices = _subdivide_edges_and_collect_midpoints(bm, longest_edges)
    return _connect_midpoints_if_possible(bm, midpoint_vertices)


def _iter_valid_intersecting_faces(
    bm: bmesh.types.BMesh, intersection_indices: list[int]
) -> list[tuple[int, bmesh.types.BMFace]]:
    bm.faces.ensure_lookup_table()
    valid: list[tuple[int, bmesh.types.BMFace]] = []
    for face_index in intersection_indices:
        if face_index >= len(bm.faces):
            continue
        face = bm.faces[face_index]
        if not face.is_valid or len(face.edges) < 3:
            continue
        valid.append((face_index, face))
    return valid


def _find_smallest_face_angle(face: bmesh.types.BMFace) -> float:
    smallest_angle = float("inf")
    for loop in face.loops:
        prev_vector = loop.link_loop_prev.vert.co - loop.vert.co
        next_vector = loop.link_loop_next.vert.co - loop.vert.co
        if prev_vector.length <= 1e-6 or next_vector.length <= 1e-6:
            continue
        angle = prev_vector.angle(next_vector)
        if angle < smallest_angle:
            smallest_angle = angle
    return smallest_angle


def _collect_longest_edges(
    face: bmesh.types.BMFace,
) -> list[bmesh.types.BMEdge]:
    edge_lengths: list[tuple[float, bmesh.types.BMEdge]] = []
    for edge in face.edges:
        if not edge.is_valid:
            continue
        length = edge.calc_length()
        if length <= 1e-6:
            continue
        edge_lengths.append((length, edge))
    if len(edge_lengths) < 2:
        return []
    edge_lengths.sort(key=lambda item: item[0], reverse=True)
    return [edge for _, edge in edge_lengths[:2] if edge.is_valid]


def _subdivide_edges_and_collect_midpoints(
    bm: bmesh.types.BMesh, edges: list[bmesh.types.BMEdge]
) -> list[bmesh.types.BMVert]:
    midpoint_vertices: list[bmesh.types.BMVert] = []
    for edge in edges:
        if not edge.is_valid:
            continue
        result = bmesh.ops.subdivide_edges(
            bm,
            edges=[edge],
            cuts=1,
            use_grid_fill=False,
            smooth=0.0,
        )
        new_vertex = next(
            (
                geom
                for geom in result.get("geom_split", [])
                if isinstance(geom, bmesh.types.BMVert) and geom.is_valid
            ),
            None,
        )
        if new_vertex is not None and new_vertex.is_valid:
            midpoint_vertices.append(new_vertex)
    return [vert for vert in midpoint_vertices if vert.is_valid]


def _connect_midpoints_if_possible(
    bm: bmesh.types.BMesh,
    midpoint_vertices: list[bmesh.types.BMVert],
) -> bool:
    if len(midpoint_vertices) < 2:
        return False
    vert_a, vert_b = midpoint_vertices[:2]
    if vert_a == vert_b:
        return False
    if not vert_a.is_valid or not vert_b.is_valid:
        return False
    shared_faces = set(vert_a.link_faces) & set(vert_b.link_faces)
    if not shared_faces:
        return False
    has_existing_edge = any(
        edge for edge in vert_a.link_edges if edge.is_valid and vert_b in edge.verts
    )
    if has_existing_edge:
        return False

    result = bmesh.ops.connect_verts(bm, verts=[vert_a, vert_b])
    new_edges = [
        edge
        for edge in result.get("edges", [])
        if isinstance(edge, bmesh.types.BMEdge) and edge.is_valid
    ]
    return bool(new_edges)
