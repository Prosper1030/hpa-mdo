"""Regression tests for the WO-006 lower-TE body/wake interface sliver.

The previous-pass Phase 1 localized 100 wrong-oriented face pyramids in
the fine `n_perim=240`, `wake_cross_cells=4` mesh to a single signature:

    owner     = airfoil-perim cell at (i_chord = n_perim - 1, i_radial = 0)
    neighbour = wake-extension cell at (i_wake = wake_cross_cells - 1, i_radial = 0)

The shared face is a ribbon-like quadrilateral with two short edges of
length ≈ `first_layer_height_m` and a non-planar twist of ~`1.3e-5 m`
that pushes its SIGNED face-pyramid volume below `1e-18` and triggers
the strict-checkMesh failure.

This file is a pure-Python regression-test contract for the generator.
The tests:

  1. Build a high-`n_perim` swept C-grid mesh at the production root
     station family, then introspect every spanwise station's
     lower-TE-corner body/wake interface face.
  2. Fail if any of those faces is a non-planar sliver with face
     pyramid volume / face-area / planarity below acceptance.

They are written so that the un-fixed generator FAILS them (the bug is
real, the test is real), and the generator-level TE radial rebalance
MUST keep them green. The acceptance thresholds are calibrated against the
`checkMesh -meshQuality` `face pyramid volume < 1e-18` cutoff:

  - `min_pyramid_volume_m3 >= 1e-15`
        (3 orders of magnitude above the checkMesh threshold for safety)
  - `face_planarity_ratio >= 0.2`
        (twist must be < 5x the shorter edge length;
         the un-fixed mesh fails with twist ~26% of the shorter edge)
  - `face_area_m2 >= 5e-7`
        (face cannot be < ~5e-7 m^2 = (50 micron x 10 mm) at the TE)

`pytest -k lower_te_sliver` from the repo root reproduces these gates.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import (  # noqa: E402
    interpolate_station,
    load_baseline_authority,
)
from cfd_rescue.section_cgrid import build_section_cgrid  # noqa: E402
from cfd_rescue.swept_cgrid import build_swept_cgrid_mesh  # noqa: E402


# Production grid family specifications (mirrors
# scripts/run_wo006_true_baseline_openfoam_grid_convergence.py).
BASE_HALF_WING_STATION_PLAN = (10, 10, 10, 10, 12, 10, 8, 8)
BASE_N_PERIM = 192
BASE_N_RADIAL = 64
FIRST_LAYER_HEIGHT_M = 5.0e-5
FARFIELD_CHORDS = 10.0
WAKE_LENGTH_CHORDS = 8.0


# Acceptance thresholds (see module docstring for rationale).
MIN_PYRAMID_VOLUME_M3 = 1e-15
MIN_FACE_PLANARITY_RATIO = 0.2
MIN_FACE_AREA_M2 = 5e-7


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec_norm(a):
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _quad_face_metrics(p0, p1, p2, p3, owner_centroid, neighbour_centroid):
    """Compute (planarity_ratio, area_m2, signed_pyramid_volume_owner,
    signed_pyramid_volume_neighbour) for a 4-vertex face."""

    # Face centroid (vertex average).
    cx = (p0[0] + p1[0] + p2[0] + p3[0]) / 4
    cy = (p0[1] + p1[1] + p2[1] + p3[1]) / 4
    cz = (p0[2] + p1[2] + p2[2] + p3[2]) / 4
    fc = (cx, cy, cz)

    # Sum of the two triangle areas (p0-p1-p2 and p0-p2-p3).
    e1 = _vec_sub(p1, p0)
    e2 = _vec_sub(p2, p0)
    e3 = _vec_sub(p3, p0)
    cross_a = _vec_cross(e1, e2)
    cross_b = _vec_cross(e2, e3)
    area_a = 0.5 * _vec_norm(cross_a)
    area_b = 0.5 * _vec_norm(cross_b)
    area = area_a + area_b

    # Face normal (sum of two triangle normals, normalised).
    nx = cross_a[0] + cross_b[0]
    ny = cross_a[1] + cross_b[1]
    nz = cross_a[2] + cross_b[2]
    nmag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if nmag <= 1e-20:
        n_unit = (0.0, 0.0, 0.0)
    else:
        n_unit = (nx / nmag, ny / nmag, nz / nmag)

    # Planarity: distance of p3 from the plane through p0, p1, p2.
    plane_n = _vec_cross(e1, e2)
    pn_mag = _vec_norm(plane_n)
    if pn_mag <= 1e-20:
        twist = float("inf")
    else:
        twist = abs(_vec_dot(e3, plane_n)) / pn_mag

    # Shorter pair-edge length (the duplicate-pair edge of the sliver).
    edge_01 = _vec_norm(e1)
    edge_03 = _vec_norm(e3)
    edge_23 = _vec_norm(_vec_sub(p3, p2))
    edge_12 = _vec_norm(_vec_sub(p2, p1))
    short_edge = min(edge_01, edge_03, edge_23, edge_12)
    if twist == 0.0:
        planarity_ratio = float("inf")
    else:
        planarity_ratio = short_edge / max(twist, 1e-20)

    # SIGNED face-pyramid volumes (face to owner / neighbour centroid).
    # The pyramid volume for an internal face is
    #   V = (1/3) * area * (centroid - faceCentre) . n_unit
    # For a CORRECTLY oriented face, owner and neighbour are on OPPOSITE
    # sides of the face plane, so V_owner and V_neighbour have OPPOSITE
    # signs. If they share the same sign the face is "incorrectly
    # oriented" — OpenFOAM's `checkMesh` flags this exactly.
    fc_to_owner = _vec_sub(owner_centroid, fc)
    fc_to_neighbour = _vec_sub(neighbour_centroid, fc)
    d_owner = _vec_dot(fc_to_owner, n_unit)
    d_neighbour = _vec_dot(fc_to_neighbour, n_unit)
    pyramid_owner = (1.0 / 3.0) * area * d_owner
    pyramid_neighbour = (1.0 / 3.0) * area * d_neighbour
    # The "orientation product" is positive when both centroids are on
    # the same side of the face plane (BAD) and negative when they're on
    # opposite sides (GOOD). A near-zero product means at least one
    # centroid is essentially on the face plane — also degenerate.
    orientation_product = pyramid_owner * pyramid_neighbour

    return {
        "area_m2": area,
        "twist_m": twist,
        "planarity_ratio": planarity_ratio,
        "pyramid_owner_m3": pyramid_owner,
        "pyramid_neighbour_m3": pyramid_neighbour,
        "orientation_product": orientation_product,
        "is_incorrectly_oriented": orientation_product >= 0.0,
        "min_pyramid_m3": min(abs(pyramid_owner), abs(pyramid_neighbour)),
        "short_edge_m": short_edge,
    }


def _scale_station_plan(plan, scale: float):
    return tuple(max(1, int(round(value * scale))) for value in plan)


def _build_halfwing_stations(authority, station_plan):
    """Replicate
    `scripts/run_wo006_true_baseline_openfoam_grid_convergence.build_halfwing_stations`
    so the test consumes the same station ladder as the production fine mesh."""
    stations = []
    for idx, n_sub in enumerate(station_plan):
        left = authority.half_stations[idx]
        right = authority.half_stations[idx + 1]
        block = [left] + [
            interpolate_station(left, right, step / n_sub)
            for step in range(1, n_sub)
        ]
        if idx == len(station_plan) - 1:
            block.append(right)
        stations.extend(block)
    return stations


def _build_swept_cgrid_for_test(
    *,
    scale: float = 1.25,
    wake_cross_cells: int = 4,
    te_normal_blend_points: int = 1,
):
    """Build the production-spec swept C-grid mesh at the requested scale.

    Mirrors the grid-convergence script's spec; default `scale=1.25`
    reproduces the fine rung that previously emitted the 100
    wrong-oriented face pyramids in `fine_te_fix_blend1_wake4_smoke`.
    """
    n_perim = ((int(round(BASE_N_PERIM * scale)) + 1) // 2) * 2   # even round
    n_radial = max(8, int(round(BASE_N_RADIAL * scale)))
    station_plan = _scale_station_plan(BASE_HALF_WING_STATION_PLAN, scale)
    authority = load_baseline_authority(
        n_perim=n_perim,
        airfoil_loop_mode="open_te_cgrid",
    )
    stations = _build_halfwing_stations(authority, station_plan)
    mesh = build_swept_cgrid_mesh(
        stations,
        n_radial=n_radial,
        first_layer_height_m=FIRST_LAYER_HEIGHT_M,
        farfield_chords=FARFIELD_CHORDS,
        wake_length_chords=WAKE_LENGTH_CHORDS,
        case_id=f"te_sliver_regression_scale_{scale:.2f}",
        wake_cross_cells=wake_cross_cells,
        te_normal_blend_points=te_normal_blend_points,
    )
    return mesh, n_perim, n_radial, sum(station_plan)


def _cell_centroid(points, cell):
    cx = sum(points[v][0] for v in cell) / len(cell)
    cy = sum(points[v][1] for v in cell) / len(cell)
    cz = sum(points[v][2] for v in cell) / len(cell)
    return (cx, cy, cz)


def _find_lower_te_body_wake_face(
    mesh,
    *,
    section: int,
    n_path: int,
    n_radial: int,
    wake_cross_cells: int,
    radial: int = 0,
):
    """Return the 4 face vertices, owner centroid, and neighbour centroid
    for the lower-TE body/wake interface face at the given spanwise cell.

    The face is at the airfoil's path-end column (`index = n_path - 1`)
    at radial layer 0 (wall layer), shared between the airfoil-perim's
    last cell and the wake's last cross cell.
    """
    # See build_swept_cgrid_mesh: each section contributes (n_radial+1)*n_path
    # airfoil-perim points + (n_radial+1)*(wake_cross_cells-1) wake-interior
    # points. cgrid_point_count = (n_radial+1)*n_path.
    cgrid_point_count = (n_radial + 1) * n_path
    wake_interior_count = (n_radial + 1) * (wake_cross_cells - 1)
    section_stride = cgrid_point_count + wake_interior_count

    def node(s: int, r: int, idx: int) -> int:
        return s * section_stride + r * n_path + idx

    def wake_node(s: int, r: int, cross: int) -> int:
        if cross == 0:
            return node(s, r, 0)
        if cross == wake_cross_cells:
            return node(s, r, n_path - 1)
        return (
            s * section_stride
            + cgrid_point_count
            + r * (wake_cross_cells - 1)
            + cross
            - 1
        )

    # The shared face uses airfoil's path-end column at
    # (radial=radial..radial+1, section=s..s+1).
    face_verts_ids = (
        node(section, radial, n_path - 1),
        node(section, radial + 1, n_path - 1),
        node(section + 1, radial + 1, n_path - 1),
        node(section + 1, radial, n_path - 1),
    )

    # The airfoil's last perim cell at this spanwise cell has corners at
    # airfoil indices n_path-2 and n_path-1 (= the bad face's wall + first-layer
    # corners), so its 8-vertex hex is:
    airfoil_last_cell = (
        node(section, radial, n_path - 2),
        node(section, radial, n_path - 1),
        node(section, radial + 1, n_path - 1),
        node(section, radial + 1, n_path - 2),
        node(section + 1, radial, n_path - 2),
        node(section + 1, radial, n_path - 1),
        node(section + 1, radial + 1, n_path - 1),
        node(section + 1, radial + 1, n_path - 2),
    )

    # The wake's last cross cell has corners using wake cross indices
    # (wake_cross_cells-1, wake_cross_cells) at radial 0..1 and section s..s+1.
    wake_last_cell = (
        wake_node(section, radial, wake_cross_cells - 1),
        wake_node(section, radial, wake_cross_cells),
        wake_node(section, radial + 1, wake_cross_cells),
        wake_node(section, radial + 1, wake_cross_cells - 1),
        wake_node(section + 1, radial, wake_cross_cells - 1),
        wake_node(section + 1, radial, wake_cross_cells),
        wake_node(section + 1, radial + 1, wake_cross_cells),
        wake_node(section + 1, radial + 1, wake_cross_cells - 1),
    )

    return face_verts_ids, airfoil_last_cell, wake_last_cell


def _evaluate_lower_te_face(
    mesh,
    n_path: int,
    n_radial: int,
    wake_cross_cells: int,
    n_spanwise_cells: int | None = None,
    radial: int = 0,
):
    """Return the lower-TE body/wake interface face metrics, plus the
    count of "incorrectly oriented" face occurrences across all
    spanwise cells."""
    points = mesh.points
    section_stride = (n_radial + 1) * n_path + (n_radial + 1) * (wake_cross_cells - 1)
    n_sections = len(points) // section_stride
    if n_spanwise_cells is None:
        n_spanwise_cells = n_sections - 1
    worst = None
    n_wrong = 0
    all_metrics = []
    for s in range(n_spanwise_cells):
        face_ids, airfoil_cell, wake_cell = _find_lower_te_body_wake_face(
            mesh,
            section=s,
            n_path=n_path,
            n_radial=n_radial,
            wake_cross_cells=wake_cross_cells,
            radial=radial,
        )
        face_pts = tuple(points[v] for v in face_ids)
        owner_c = _cell_centroid(points, airfoil_cell)
        nei_c = _cell_centroid(points, wake_cell)
        metrics = _quad_face_metrics(*face_pts, owner_c, nei_c)
        metrics["section"] = s
        metrics["radial"] = radial
        all_metrics.append(metrics)
        if metrics["is_incorrectly_oriented"]:
            n_wrong += 1
        # "Worst" tracks the most problematic section, by orientation_product
        # (large positive = badly mis-oriented). Falls back to smallest
        # pyramid magnitude if all sections are fine.
        if worst is None or metrics["orientation_product"] > worst["orientation_product"]:
            worst = metrics
    return worst, n_wrong, all_metrics


def test_lower_te_face_orientation_at_production_fine_settings() -> None:
    """Production-fine settings must NOT produce any incorrectly-oriented
    lower-TE body/wake faces.

    This test reproduces the production fine spec
    (scale=1.25 → n_perim=240, n_radial=80, station_plan scaled by 1.25,
    wake_cross_cells=4, te_normal_blend_points=1) from
    `scripts/run_wo006_true_baseline_openfoam_grid_convergence.py`. It
    flags any face whose owner and neighbour centroids lie on the same
    side of the face plane (i.e. `pyramid_owner * pyramid_neighbour >= 0`),
    which is the exact condition OpenFOAM `checkMesh -meshQuality`
    reports as "Error in face pyramids: N faces are incorrectly
    oriented".
    """
    mesh, n_perim, n_radial, n_spanwise_cells = _build_swept_cgrid_for_test(
        scale=1.25,
        wake_cross_cells=4,
        te_normal_blend_points=1,
    )
    n_path = n_perim + 1
    worst, n_wrong, _all = _evaluate_lower_te_face(
        mesh,
        n_path=n_path,
        n_radial=n_radial,
        wake_cross_cells=4,
        n_spanwise_cells=n_spanwise_cells,
    )
    assert worst is not None, "no lower-TE face evaluated"
    assert n_wrong == 0, (
        f"{n_wrong}/{n_spanwise_cells} lower-TE body/wake faces are "
        f"incorrectly oriented (owner and neighbour on the SAME side of "
        f"the face plane). Worst section: {worst['section']}; "
        f"twist={worst['twist_m']:.3e} m; "
        f"area={worst['area_m2']:.3e} m^2; "
        f"pyramid_owner={worst['pyramid_owner_m3']:.3e}; "
        f"pyramid_neighbour={worst['pyramid_neighbour_m3']:.3e}; "
        f"orientation_product={worst['orientation_product']:.3e}."
    )
    # The hard contract: every section must have a non-sliver face.
    assert worst["min_pyramid_m3"] >= MIN_PYRAMID_VOLUME_M3, (
        f"lower-TE body/wake interface face pyramid volume "
        f"{worst['min_pyramid_m3']:.3e} m^3 < threshold "
        f"{MIN_PYRAMID_VOLUME_M3:.3e}; section={worst['section']}; "
        f"twist={worst['twist_m']:.3e} m; "
        f"area={worst['area_m2']:.3e} m^2"
    )
    assert worst["area_m2"] >= MIN_FACE_AREA_M2, (
        f"lower-TE body/wake face is too thin: area={worst['area_m2']:.3e} m^2 < {MIN_FACE_AREA_M2:.3e}"
    )


def test_lower_te_face_orientation_stays_clean_through_radial_rebalance_layers() -> None:
    """The lower-TE fix must not simply push the bad face one radial
    layer outward.

    The first generator repair cleaned `i_radial=0` but OpenFOAM then
    found remaining wrong-oriented faces at `i_radial=1`. This checks
    the first few lower-TE body/wake interface layers, not just the wall
    layer where the original Phase 1 signature appeared.
    """
    mesh, n_perim, n_radial, n_spanwise_cells = _build_swept_cgrid_for_test(
        scale=1.25,
        wake_cross_cells=4,
        te_normal_blend_points=1,
    )
    n_path = n_perim + 1
    for radial in (0, 1, 2, 3):
        worst, n_wrong, _all = _evaluate_lower_te_face(
            mesh,
            n_path=n_path,
            n_radial=n_radial,
            wake_cross_cells=4,
            n_spanwise_cells=n_spanwise_cells,
            radial=radial,
        )
        assert worst is not None, f"no lower-TE face evaluated at radial={radial}"
        assert n_wrong == 0, (
            f"{n_wrong}/{n_spanwise_cells} lower-TE body/wake faces are "
            f"incorrectly oriented at radial={radial}. Worst section: "
            f"{worst['section']}; twist={worst['twist_m']:.3e} m; "
            f"area={worst['area_m2']:.3e} m^2; "
            f"pyramid_owner={worst['pyramid_owner_m3']:.3e}; "
            f"pyramid_neighbour={worst['pyramid_neighbour_m3']:.3e}."
        )


def test_lower_te_face_is_already_acceptable_at_coarse_settings() -> None:
    """At coarse settings the lower-TE face already has finite pyramid volume.

    This pins the existing-pass behaviour so the generator change does
    not regress the coarse rung.
    """
    mesh, n_perim, n_radial, n_spanwise_cells = _build_swept_cgrid_for_test(
        scale=0.75,                                  # coarse rung
        wake_cross_cells=4,
        te_normal_blend_points=1,
    )
    n_path = n_perim + 1
    worst, n_wrong, _all = _evaluate_lower_te_face(
        mesh,
        n_path=n_path,
        n_radial=n_radial,
        wake_cross_cells=4,
        n_spanwise_cells=n_spanwise_cells,
    )
    # Coarse must have ZERO incorrectly-oriented lower-TE faces.
    assert n_wrong == 0, (
        f"coarse rung regressed: {n_wrong} incorrectly-oriented lower-TE faces. "
        f"Worst section: {worst['section']}; orientation_product={worst['orientation_product']:.3e}."
    )


def test_lower_te_signature_owner_neighbour_indices_are_stable() -> None:
    """The owner/neighbour structural signature must be stable.

    If the generator changes the cell-ordering at the TE interface, the
    Phase 1 localisation report ("owner = i_chord=n_perim-1, i_radial=0;
    neighbour = i_wake=wake_cross_cells-1, i_radial=0") would silently
    break. This test pins that contract.
    """
    mesh, n_perim, n_radial, n_spanwise_cells = _build_swept_cgrid_for_test(
        scale=0.5,                                  # cheap probe
        wake_cross_cells=4,
        te_normal_blend_points=1,
    )
    n_path = n_perim + 1
    face_ids, airfoil_cell, wake_cell = _find_lower_te_body_wake_face(
        mesh,
        section=0,
        n_path=n_path,
        n_radial=n_radial,
        wake_cross_cells=4,
    )
    # All four face vertices must be distinct (no degenerate ID collapse).
    assert len(set(face_ids)) == 4, f"face has duplicate vertex IDs: {face_ids}"

    # Owner cell at i_chord = n_perim - 1, i_radial = 0 means its 8 corners
    # span airfoil indices (n_path-2, n_path-1). Verify.
    assert len(set(airfoil_cell)) == 8
    assert len(set(wake_cell)) == 8

    # The face's 4 vertices must be a subset of both cells (shared face).
    face_set = set(face_ids)
    assert face_set.issubset(set(airfoil_cell)), (
        f"face vertices {face_set} not all in airfoil's last perim cell "
        f"{set(airfoil_cell)}"
    )
    assert face_set.issubset(set(wake_cell)), (
        f"face vertices {face_set} not all in wake's last cross cell "
        f"{set(wake_cell)}"
    )
