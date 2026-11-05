"""L1 triangle intersection, winding and volume validity regressions."""

import itertools

import numpy as np
import pytest

from src.evaluator.l1_mesh import (
    GEOMETRY_POLICY,
    improper_intersection,
    intersection_audit,
    solid_validity,
    triangle_intersection,
    triangulated_volume,
    validate_geometry_policy,
    triangle_area,
)


def test_thin_export_triangle_uses_double_precision_without_relaxing_threshold():
    points = np.asarray([[.01880771853029728,-.014056750573217869,0],
                         [.018777651712298393,-.014132833108305931,0],
                         [.018771639093756676,-.014148049987852573,0]], dtype=np.float32)
    assert triangle_area(points) == pytest.approx(3.3943334254438184e-14, rel=1e-12)
    assert triangle_area([[0,0,0],[1,1,1],[2,2,2]]) == 0
    assert triangle_area([[0,0,0],[1e-10,0,0],[0,1e-10,0]]) < GEOMETRY_POLICY['degenerate_area_m2']


@pytest.mark.parametrize(
    "other,hit",
    [
        ([[0.25, 0.25, -1], [0.25, 0.25, 1], [0.75, 0.25, 0]], True),
        ([[2, 2, -1], [2, 2, 1], [3, 2, 0]], False),
        ([[0.2, 0.2, 0], [0.4, 0.2, 0], [0.2, 0.4, 0]], True),
        ([[2, 0, 0], [3, 0, 0], [2, 1, 0]], False),
        ([[0, 0, 0.01], [1, 0, 0.01], [0, 1, 0.01]], False),
        ([[1, 0, 0], [2, 0, 0], [1, 1, 0]], True),
    ],
)
def test_triangle_intersections_include_coplanar_cases(other, hit):
    first = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    second = np.array(other, dtype=float)
    for order in itertools.permutations(range(3)):
        assert bool(triangle_intersection(first, second[list(order)], 1e-9)) is hit
        assert bool(triangle_intersection(second[list(order)], first, 1e-9)) is hit


@pytest.mark.parametrize(
    "extra,right,hit",
    [
        ([[1, 1, 0]], [1, 3, 2], False),  # shared diagonal, ordinary square
        ([[0.2, 0.2, 0]], [0, 1, 3], True),  # folded coplanar neighboring faces
        ([[0, 0, 1]], [0, 1, 3], False),  # shared edge, different planes
        (
            [[1, 1, -1], [1, 1, 1]],
            [0, 3, 4],
            True,
        ),  # share vertex but cross away from it
        ([[-1, -1, 0], [-1, 0, 0]], [0, 3, 4], False),  # only shared vertex
        ([], [0, 2, 1], True),  # reversed duplicate
    ],
)
def test_topological_adjacency_does_not_hide_real_overlap(extra, right, hit):
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], *extra], dtype=float)
    for scale in (0.001, 1, 100):
        for translation in (np.zeros(3), np.array([12, -8, 5])):
            v = vertices * scale + translation
            assert (
                improper_intersection(v, np.array([0, 1, 2]), np.array(right), 1e-9)
                is hit
            )


def test_pair_budget_is_unmeasured_not_zero_intersections():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    t = [[0, 1, 2], [0, 1, 3], [0, 2, 3]]
    result = intersection_audit(v, t, [(0, 1), (0, 2), (1, 2)], 1e-9, 1)
    assert result["status"] == "not_measurable"
    assert result["intersecting_pairs"] is None


def valid_facts():
    return {
        "closed": True,
        "components": 1,
        "inconsistent_edges": 0,
        "nonmanifold_vertices": 0,
        "degenerate_faces": 0,
        "loose_vertices": 0,
        "loose_edges": 0,
        "signed_volume_integral_m3": 0.001,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("closed", False),
        ("components", 2),
        ("inconsistent_edges", 1),
        ("nonmanifold_vertices", 1),
        ("degenerate_faces", 1),
        ("loose_vertices", 1),
        ("loose_edges", 1),
        ("signed_volume_integral_m3", -0.001),
    ],
)
def test_closed_mesh_integral_is_not_automatically_valid_volume(field, value):
    facts = valid_facts()
    facts[field] = value
    result = solid_validity(facts, {"status": "ok", "intersecting_pairs": 0})
    assert not result["volume_reliable"] and result["solid_volume_m3"] is None


def test_self_intersection_or_unmeasured_intersection_rejects_volume():
    for intersection in (
        {"status": "ok", "intersecting_pairs": 1},
        {"status": "not_measurable"},
    ):
        result = solid_validity(valid_facts(), intersection)
        assert not result["valid_solid"] and result["solid_volume_m3"] is None
    assert (
        solid_validity(valid_facts(), {"status": "ok", "intersecting_pairs": 0})[
            "solid_volume_m3"
        ]
        == 0.001
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {**GEOMETRY_POLICY, "weld_m": 0.0003},
        {**GEOMETRY_POLICY, "max_triangles": 200000.0},
    ],
)
def test_geometry_precision_is_frozen(value):
    with pytest.raises(ValueError):
        validate_geometry_policy(value)


def test_signed_triangle_volume_is_translation_invariant():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    triangles = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    for offset in (np.zeros(3), np.array([1000, -234, 981])):
        assert triangulated_volume(vertices + offset, triangles) == pytest.approx(1 / 6)
        assert triangulated_volume(
            vertices + offset, triangles[:, ::-1]
        ) == pytest.approx(-1 / 6)
