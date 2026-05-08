#!/usr/bin/env python3
"""Candidate-specific CalculiX shell buckling and tip-limit review.

This route intentionally keeps the design fixed.  It turns the selected
candidate main-spar tube geometry and reference 2G load path into a structured
S4 shell eigen-buckling deck, then packages the result with a tip-deflection
limit sensitivity review.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    SELECTED_RUN,
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase17_candidate_shell_buckling_tip_review"
CCX_CANDIDATES = (
    Path("/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23"),
    Path("/opt/homebrew/bin/ccx"),
    Path("/usr/local/bin/ccx"),
)


@dataclass(frozen=True)
class CandidateStation:
    node: int
    y_m: float
    main_x_m: float
    main_z_m: float
    main_outer_radius_m: float
    main_wall_thickness_m: float
    main_fz_n: float
    is_wire_attach: bool


@dataclass(frozen=True)
class ShellBucklingRow:
    mesh_id: str
    n_span: int
    n_circumference: int
    node_count: int
    element_count: int
    reference_load_factor: float
    reference_load_main_fz_n: float
    reference_wire_fx_n: float
    reference_wire_fy_n: float
    reference_wire_fz_n: float
    static_root_rf_x_n: float | None
    static_root_rf_y_n: float | None
    static_root_rf_z_n: float | None
    first_positive_buckle_factor: float | None
    shell_buckle_load_factor: float | None
    utilization_at_3g: float | None
    utilization_at_4g: float | None
    runtime_s: float
    ccx_returncode: int | None
    status: str
    deck_path: str
    dat_path: str
    log_path: str
    note: str


@dataclass(frozen=True)
class LocalWallCouponRow:
    mesh_id: str
    length_m: float
    outer_radius_m: float
    wall_thickness_m: float
    d_over_t: float
    n_span: int
    n_circumference: int
    element_count: int
    reference_load_factor: float
    reference_compressive_stress_mpa: float
    reference_axial_force_n: float
    first_positive_buckle_factor: float | None
    shell_critical_stress_mpa: float | None
    shell_buckle_load_factor: float | None
    classical_knockdown_sigma_cr_mpa: float | None
    classical_knockdown_buckle_load_factor: float | None
    internal_estimate_buckle_load_factor: float | None
    utilization_at_3g: float | None
    runtime_s: float
    ccx_returncode: int | None
    status: str
    deck_path: str
    dat_path: str
    log_path: str
    note: str


@dataclass(frozen=True)
class TipLimitReviewRow:
    raw_tip_limit_m: float
    effective_tip_limit_m: float
    limit_to_halfspan_ratio: float
    deflection_limit_load_factor: float
    active_first_limiter_with_6kn_wire: str
    engineering_use: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_candidate_stations(path: Path = SELECTED_RUN / "jig_shape_spar_data.csv") -> list[CandidateStation]:
    rows = []
    for row in _read_csv_rows(path):
        rows.append(
            CandidateStation(
                node=int(row["Node"]),
                y_m=float(row["Y_Position_m"]),
                main_x_m=float(row["Main_X_m"]),
                main_z_m=float(row["Main_Z_m"]),
                main_outer_radius_m=float(row["Main_Outer_Radius_m"]),
                main_wall_thickness_m=float(row["Main_Wall_Thickness_m"]),
                main_fz_n=float(row["Main_FZ_N"]),
                is_wire_attach=bool(int(row["Is_Wire_Attach"])),
            )
        )
    if len(rows) < 2:
        raise ValueError(f"Need at least two spar stations in {path}.")
    return rows


def _interp_station_values(stations: list[CandidateStation], y_values: np.ndarray) -> dict[str, np.ndarray]:
    y_src = np.asarray([s.y_m for s in stations], dtype=float)
    return {
        "x": np.interp(y_values, y_src, [s.main_x_m for s in stations]),
        "z": np.interp(y_values, y_src, [s.main_z_m for s in stations]),
        "outer_r": np.interp(y_values, y_src, [s.main_outer_radius_m for s in stations]),
        "t": np.interp(y_values, y_src, [s.main_wall_thickness_m for s in stations]),
    }


def build_candidate_shell_mesh(
    stations: list[CandidateStation],
    *,
    n_span: int,
    n_circumference: int,
) -> tuple[np.ndarray, list[tuple[int, tuple[int, int, int, int]]], np.ndarray, np.ndarray]:
    """Build a structured S4 midsurface shell along the candidate jig centerline."""

    if n_span < 2:
        raise ValueError("n_span must be >= 2.")
    if n_circumference < 12:
        raise ValueError("n_circumference must be >= 12.")

    span_m = float(stations[-1].y_m)
    y_values = np.linspace(0.0, span_m, n_span + 1)
    interp = _interp_station_values(stations, y_values)
    mid_r = interp["outer_r"] - 0.5 * interp["t"]
    if np.any(mid_r <= 0.0):
        raise ValueError("All shell midsurface radii must be positive.")

    nodes: list[tuple[float, float, float, float]] = []
    node_ids: dict[tuple[int, int], int] = {}
    node_id = 1
    for i_span, y_m in enumerate(y_values):
        for i_circ in range(n_circumference):
            theta = 2.0 * math.pi * i_circ / n_circumference
            x_m = float(interp["x"][i_span] + mid_r[i_span] * math.cos(theta))
            z_m = float(interp["z"][i_span] + mid_r[i_span] * math.sin(theta))
            node_ids[(i_span, i_circ)] = node_id
            nodes.append((float(node_id), x_m, float(y_m), z_m))
            node_id += 1

    elements: list[tuple[int, tuple[int, int, int, int]]] = []
    element_id = 1
    for i_span in range(n_span):
        for i_circ in range(n_circumference):
            j_next = (i_circ + 1) % n_circumference
            elements.append(
                (
                    element_id,
                    (
                        node_ids[(i_span, i_circ)],
                        node_ids[(i_span + 1, i_circ)],
                        node_ids[(i_span + 1, j_next)],
                        node_ids[(i_span, j_next)],
                    ),
                )
            )
            element_id += 1

    return np.asarray(nodes, dtype=float), elements, interp["t"], y_values


def _format_int_chunks(values: Iterable[int], *, per_line: int = 16) -> list[str]:
    items = [int(value) for value in values]
    return [
        ", ".join(str(value) for value in items[index : index + per_line])
        for index in range(0, len(items), per_line)
    ]


def _clean_log_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def _nearest_ring_index(y_values: np.ndarray, y_m: float) -> int:
    return int(np.argmin(np.abs(y_values - float(y_m))))


def _ring_node_ids(ring_index: int, n_circumference: int) -> list[int]:
    first = ring_index * n_circumference + 1
    return list(range(first, first + n_circumference))


def _add_ring_load(
    loads: dict[tuple[int, int], float],
    *,
    ring_index: int,
    n_circumference: int,
    dof: int,
    value_n: float,
) -> None:
    if abs(value_n) <= 0.0:
        return
    per_node = float(value_n) / float(n_circumference)
    for node_id in _ring_node_ids(ring_index, n_circumference):
        key = (node_id, int(dof))
        loads[key] = loads.get(key, 0.0) + per_node


def wire_force_vector_n(rigging: dict[str, object]) -> tuple[float, float, float]:
    """Return the force applied by the wire to the wing attach point."""

    attach = np.asarray(rigging["attach_point_loaded_m"], dtype=float)
    anchor = np.asarray(rigging["anchor_point_m"], dtype=float)
    tension = float(rigging["tension_force_n"])
    vector = anchor - attach
    length = float(np.linalg.norm(vector))
    if length <= 0.0:
        raise ValueError("Wire attach and anchor points coincide.")
    force = tension * vector / length
    return float(force[0]), float(force[1]), float(force[2])


def build_reference_loads(
    stations: list[CandidateStation],
    y_values: np.ndarray,
    *,
    n_circumference: int,
    include_wire: bool = True,
) -> tuple[list[tuple[int, int, float]], dict[str, float]]:
    loads: dict[tuple[int, int], float] = {}
    for station in stations:
        ring_index = _nearest_ring_index(y_values, station.y_m)
        _add_ring_load(
            loads,
            ring_index=ring_index,
            n_circumference=n_circumference,
            dof=3,
            value_n=station.main_fz_n,
        )

    wire_fx = wire_fy = wire_fz = 0.0
    if include_wire:
        rigging = json.loads((SELECTED_RUN / "lift_wire_rigging.json").read_text(encoding="utf-8"))[
            "wire_rigging"
        ][0]
        wire_fx, wire_fy, wire_fz = wire_force_vector_n(rigging)
        attach_y = float(rigging["attach_y_m"])
        ring_index = _nearest_ring_index(y_values, attach_y)
        _add_ring_load(
            loads,
            ring_index=ring_index,
            n_circumference=n_circumference,
            dof=1,
            value_n=wire_fx,
        )
        _add_ring_load(
            loads,
            ring_index=ring_index,
            n_circumference=n_circumference,
            dof=2,
            value_n=wire_fy,
        )
        _add_ring_load(
            loads,
            ring_index=ring_index,
            n_circumference=n_circumference,
            dof=3,
            value_n=wire_fz,
        )

    return (
        [(node_id, dof, value) for (node_id, dof), value in sorted(loads.items()) if abs(value) > 1.0e-12],
        {
            "main_fz_n": float(sum(station.main_fz_n for station in stations)),
            "wire_fx_n": wire_fx,
            "wire_fy_n": wire_fy,
            "wire_fz_n": wire_fz,
        },
    )


def write_shell_buckle_inp(
    path: Path,
    *,
    nodes: np.ndarray,
    elements: list[tuple[int, tuple[int, int, int, int]]],
    thickness_by_ring_m: np.ndarray,
    material_name: str,
    young_pa: float,
    poisson_ratio: float,
    density_kgpm3: float,
    n_span: int,
    n_circumference: int,
    loads: list[tuple[int, int, float]],
    n_modes: int = 10,
) -> Path:
    lines = [
        "*HEADING",
        "Phase 17 candidate-specific main-spar S4 shell buckling deck",
        "*NODE",
    ]
    for node_id, x_m, y_m, z_m in nodes:
        lines.append(f"{int(node_id)}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}")

    lines.append("*ELEMENT, TYPE=S4")
    for element_id, node_ids in elements:
        lines.append(f"{element_id}, " + ", ".join(str(node_id) for node_id in node_ids))

    lines.extend(
        [
            f"*MATERIAL, NAME={material_name}",
            "*ELASTIC",
            f"{young_pa:.9g}, {poisson_ratio:.9g}",
            "*DENSITY",
            f"{density_kgpm3:.9g}",
        ]
    )

    for i_span in range(n_span):
        element_ids = range(i_span * n_circumference + 1, (i_span + 1) * n_circumference + 1)
        thickness = 0.5 * (float(thickness_by_ring_m[i_span]) + float(thickness_by_ring_m[i_span + 1]))
        elset = f"AXIAL_BAND_{i_span:03d}"
        lines.append(f"*ELSET, ELSET={elset}")
        lines.extend(_format_int_chunks(element_ids))
        lines.append(f"*SHELL SECTION, ELSET={elset}, MATERIAL={material_name}")
        lines.append(f"{thickness:.9g}")

    root_nodes = _ring_node_ids(0, n_circumference)
    lines.append("*NSET, NSET=ROOT")
    lines.extend(_format_int_chunks(root_nodes))
    lines.append("*BOUNDARY")
    for node_id in root_nodes:
        for dof in range(1, 7):
            lines.append(f"{node_id}, {dof}, {dof}, 0.0")

    lines.extend(
        [
            "*STEP, NAME=reference_static_2g",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_id, dof, value in loads:
        lines.append(f"{node_id}, {dof}, {value:.9g}")
    lines.extend(
        [
            "*NODE PRINT, NSET=ROOT, TOTALS=ONLY",
            "RF",
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "*STEP, NAME=buckle_from_reference_2g",
            "*BUCKLE",
            str(int(n_modes)),
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def find_ccx() -> Path:
    for candidate in CCX_CANDIDATES:
        if candidate.exists():
            return candidate
    discovered = shutil.which("ccx")
    if discovered:
        return Path(discovered)
    raise FileNotFoundError("CalculiX ccx executable not found.")


def parse_buckling_factors(dat_text: str) -> list[float]:
    factors: list[float] = []
    in_table = False
    for line in dat_text.splitlines():
        if "B U C K L I N G" in line and "F A C T O R" in line:
            in_table = True
            continue
        if not in_table:
            continue
        match = re.match(r"\s*\d+\s+([-+0-9.Ee]+)\s*$", line)
        if match:
            factors.append(float(match.group(1).replace("D", "E")))
    return factors


def parse_root_reaction(dat_text: str) -> tuple[float, float, float] | None:
    pattern = re.compile(
        r"total force \(fx,fy,fz\) for set ROOT.*?\n\s*"
        r"([-+0-9.EeD]+)\s+([-+0-9.EeD]+)\s+([-+0-9.EeD]+)",
        re.DOTALL,
    )
    match = pattern.search(dat_text)
    if not match:
        return None
    return tuple(float(group.replace("D", "E")) for group in match.groups())  # type: ignore[return-value]


def _tube_area_m2(outer_radius_m: float, wall_thickness_m: float) -> float:
    inner_radius = float(outer_radius_m) - float(wall_thickness_m)
    if inner_radius <= 0.0:
        raise ValueError("Tube inner radius must be positive.")
    return math.pi * (float(outer_radius_m) ** 2 - inner_radius**2)


def worst_main_tube_station(stations: list[CandidateStation]) -> CandidateStation:
    return max(stations, key=lambda station: 2.0 * station.main_outer_radius_m / station.main_wall_thickness_m)


def build_constant_tube_shell_mesh(
    *,
    outer_radius_m: float,
    wall_thickness_m: float,
    length_m: float,
    n_span: int,
    n_circumference: int,
) -> tuple[np.ndarray, list[tuple[int, tuple[int, int, int, int]]]]:
    if n_span < 2:
        raise ValueError("n_span must be >= 2.")
    if n_circumference < 12:
        raise ValueError("n_circumference must be >= 12.")
    mid_radius = float(outer_radius_m) - 0.5 * float(wall_thickness_m)
    if mid_radius <= 0.0:
        raise ValueError("Shell midsurface radius must be positive.")

    nodes: list[tuple[float, float, float, float]] = []
    node_ids: dict[tuple[int, int], int] = {}
    node_id = 1
    for i_span in range(n_span + 1):
        y_m = float(length_m) * i_span / float(n_span)
        for i_circ in range(n_circumference):
            theta = 2.0 * math.pi * i_circ / n_circumference
            node_ids[(i_span, i_circ)] = node_id
            nodes.append((float(node_id), mid_radius * math.cos(theta), y_m, mid_radius * math.sin(theta)))
            node_id += 1

    elements: list[tuple[int, tuple[int, int, int, int]]] = []
    element_id = 1
    for i_span in range(n_span):
        for i_circ in range(n_circumference):
            j_next = (i_circ + 1) % n_circumference
            elements.append(
                (
                    element_id,
                    (
                        node_ids[(i_span, i_circ)],
                        node_ids[(i_span + 1, i_circ)],
                        node_ids[(i_span + 1, j_next)],
                        node_ids[(i_span, j_next)],
                    ),
                )
            )
            element_id += 1
    return np.asarray(nodes, dtype=float), elements


def write_local_wall_coupon_buckle_inp(
    path: Path,
    *,
    nodes: np.ndarray,
    elements: list[tuple[int, tuple[int, int, int, int]]],
    material_name: str,
    young_pa: float,
    poisson_ratio: float,
    density_kgpm3: float,
    wall_thickness_m: float,
    n_circumference: int,
    axial_force_n: float,
    n_modes: int = 10,
) -> Path:
    root_nodes = _ring_node_ids(0, n_circumference)
    tip_ring_index = int(max(nodes[:, 2]) / max(nodes[:, 2].max(), 1.0e-12) * (len(nodes) / n_circumference - 1))
    tip_nodes = _ring_node_ids(tip_ring_index, n_circumference)

    lines = [
        "*HEADING",
        "Phase 17 candidate local-wall shell coupon buckling deck",
        "*NODE",
    ]
    for node_id, x_m, y_m, z_m in nodes:
        lines.append(f"{int(node_id)}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}")
    lines.append("*ELEMENT, TYPE=S4")
    for element_id, node_ids in elements:
        lines.append(f"{element_id}, " + ", ".join(str(node_id) for node_id in node_ids))
    lines.append("*ELSET, ELSET=EALL")
    lines.extend(_format_int_chunks([element_id for element_id, _ in elements]))
    lines.extend(
        [
            f"*MATERIAL, NAME={material_name}",
            "*ELASTIC",
            f"{young_pa:.9g}, {poisson_ratio:.9g}",
            "*DENSITY",
            f"{density_kgpm3:.9g}",
            f"*SHELL SECTION, ELSET=EALL, MATERIAL={material_name}",
            f"{wall_thickness_m:.9g}",
            "*NSET, NSET=ROOT",
            *_format_int_chunks(root_nodes),
            "*NSET, NSET=TIP",
            *_format_int_chunks(tip_nodes),
            "*BOUNDARY",
        ]
    )
    for node_id in root_nodes:
        for dof in range(1, 7):
            lines.append(f"{node_id}, {dof}, {dof}, 0.0")
    # Keep the loaded end ring centered so the eigenvalue targets local tube-wall
    # shell buckling instead of a free-end rigid swing.  Axial DOF 2 remains free.
    for node_id in tip_nodes:
        lines.append(f"{node_id}, 1, 1, 0.0")
        lines.append(f"{node_id}, 3, 3, 0.0")
    lines.extend(
        [
            "*STEP, NAME=reference_axial_compression",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    per_node = -abs(float(axial_force_n)) / float(n_circumference)
    for node_id in tip_nodes:
        lines.append(f"{node_id}, 2, {per_node:.9g}")
    lines.extend(
        [
            "*NODE PRINT, NSET=ROOT, TOTALS=ONLY",
            "RF",
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "*STEP, NAME=local_wall_buckle",
            "*BUCKLE",
            str(int(n_modes)),
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_local_wall_coupon_case(
    *,
    out_dir: Path,
    mesh_id: str,
    length_m: float,
    n_span: int,
    n_circumference: int,
    reference_load_factor: float,
) -> LocalWallCouponRow:
    reference = load_current_candidate_reference()
    stations = load_candidate_stations()
    cfg = load_config(
        json.loads((SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json").read_text())[
            "config"
        ]
    )
    material = MaterialDB().get(cfg.main_spar.material)
    worst = worst_main_tube_station(stations)
    outer_radius = float(worst.main_outer_radius_m)
    wall = float(worst.main_wall_thickness_m)
    d_over_t = 2.0 * outer_radius / wall
    stress_util_ref = max(0.0, 1.0 + float(reference.failure_index))
    reference_stress_pa = stress_util_ref * float(reference.tube_allowable_stress_pa)
    axial_force = reference_stress_pa * _tube_area_m2(outer_radius, wall)

    nodes, elements = build_constant_tube_shell_mesh(
        outer_radius_m=outer_radius,
        wall_thickness_m=wall,
        length_m=length_m,
        n_span=n_span,
        n_circumference=n_circumference,
    )
    case_dir = out_dir / "_ccx_local_wall_coupon" / mesh_id
    deck = write_local_wall_coupon_buckle_inp(
        case_dir / f"candidate_local_wall_coupon_{mesh_id}.inp",
        nodes=nodes,
        elements=elements,
        material_name="CANDIDATE_CFRP_HM_ISO",
        young_pa=float(material.E),
        poisson_ratio=float(material.poisson_ratio),
        density_kgpm3=float(material.density),
        wall_thickness_m=wall,
        n_circumference=n_circumference,
        axial_force_n=axial_force,
    )

    ccx = find_ccx()
    start = time.perf_counter()
    result = subprocess.run(
        [str(ccx), deck.stem],
        cwd=case_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1200,
        check=False,
    )
    runtime_s = time.perf_counter() - start
    log_path = case_dir / f"{deck.stem}.log"
    log_path.write_text(
        "\n".join(
            [
                f"ccx={ccx}",
                f"returncode={result.returncode}",
                "===== stdout =====",
                _clean_log_text(result.stdout),
                "===== stderr =====",
                _clean_log_text(result.stderr),
            ]
        ),
        encoding="utf-8",
    )
    dat_path = case_dir / f"{deck.stem}.dat"
    dat_text = dat_path.read_text(encoding="utf-8", errors="ignore") if dat_path.exists() else ""
    factors = parse_buckling_factors(dat_text)
    positive = [factor for factor in factors if factor > 0.0]
    first_factor = min(positive) if positive else None
    critical_stress_mpa = None if first_factor is None else first_factor * reference_stress_pa / 1.0e6
    shell_buckle_n = None if first_factor is None else float(reference_load_factor) * first_factor
    utilization_at_3g = None if shell_buckle_n is None else 3.0 / shell_buckle_n

    classical_factor = (
        None
        if reference.min_classical_sigma_cr_mpa is None or reference_stress_pa <= 0.0
        else (float(reference.min_classical_sigma_cr_mpa) * 1.0e6) / reference_stress_pa
    )
    classical_buckle_n = (
        None if classical_factor is None else float(reference_load_factor) * float(classical_factor)
    )
    internal_buckle_n = float(reference.reference_load_factor) / max(
        1.0 + float(reference.buckling_index),
        1.0e-12,
    )

    numerically_plausible = True
    if first_factor is not None and classical_factor is not None:
        ratio = first_factor / max(classical_factor, 1.0e-12)
        numerically_plausible = 0.05 <= ratio <= 20.0

    if result.returncode != 0:
        status = "FAIL"
        note = "CalculiX returned non-zero status."
    elif first_factor is None:
        status = "FAIL"
        note = "CalculiX completed but no positive local-wall buckling factor was parsed."
    elif not numerically_plausible:
        status = "UNTRUSTED_NUMERICAL"
        note = (
            "CalculiX shell eigenvalue is not credible for local-wall buckling: "
            "it is far outside the knockdown/classical critical-stress scale."
        )
    elif shell_buckle_n >= 6.0:
        status = "PASS_DIRECTIONAL"
        note = "Stress-calibrated shell coupon is above the 3G to 4G exploration range."
    elif shell_buckle_n >= 3.0:
        status = "WARN_DIRECTIONAL"
        note = "Stress-calibrated shell coupon is above 3G but not comfortable."
    else:
        status = "FAIL_DIRECTIONAL"
        note = "Stress-calibrated shell coupon buckles below 3G."

    return LocalWallCouponRow(
        mesh_id=mesh_id,
        length_m=float(length_m),
        outer_radius_m=outer_radius,
        wall_thickness_m=wall,
        d_over_t=d_over_t,
        n_span=n_span,
        n_circumference=n_circumference,
        element_count=len(elements),
        reference_load_factor=float(reference_load_factor),
        reference_compressive_stress_mpa=reference_stress_pa / 1.0e6,
        reference_axial_force_n=axial_force,
        first_positive_buckle_factor=first_factor,
        shell_critical_stress_mpa=critical_stress_mpa,
        shell_buckle_load_factor=shell_buckle_n,
        classical_knockdown_sigma_cr_mpa=reference.min_classical_sigma_cr_mpa,
        classical_knockdown_buckle_load_factor=classical_buckle_n,
        internal_estimate_buckle_load_factor=internal_buckle_n,
        utilization_at_3g=utilization_at_3g,
        runtime_s=runtime_s,
        ccx_returncode=result.returncode,
        status=status,
        deck_path=str(deck),
        dat_path=str(dat_path),
        log_path=str(log_path),
        note=note,
    )


def run_shell_buckling_case(
    *,
    out_dir: Path,
    mesh_id: str,
    n_span: int,
    n_circumference: int,
    reference_load_factor: float,
) -> ShellBucklingRow:
    stations = load_candidate_stations()
    cfg_path = Path(
        json.loads((SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json").read_text())[
            "config"
        ]
    )
    cfg = load_config(cfg_path)
    material = MaterialDB().get(cfg.main_spar.material)

    nodes, elements, thickness_by_ring, y_values = build_candidate_shell_mesh(
        stations,
        n_span=n_span,
        n_circumference=n_circumference,
    )
    loads, load_summary = build_reference_loads(stations, y_values, n_circumference=n_circumference)

    case_dir = out_dir / "_ccx_candidate_shell" / mesh_id
    deck = write_shell_buckle_inp(
        case_dir / f"candidate_main_spar_shell_buckle_{mesh_id}.inp",
        nodes=nodes,
        elements=elements,
        thickness_by_ring_m=thickness_by_ring,
        material_name="CANDIDATE_CFRP_HM_ISO",
        young_pa=float(material.E),
        poisson_ratio=float(material.poisson_ratio),
        density_kgpm3=float(material.density),
        n_span=n_span,
        n_circumference=n_circumference,
        loads=loads,
    )

    ccx = find_ccx()
    start = time.perf_counter()
    result = subprocess.run(
        [str(ccx), deck.stem],
        cwd=case_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1200,
        check=False,
    )
    runtime_s = time.perf_counter() - start
    log_path = case_dir / f"{deck.stem}.log"
    log_path.write_text(
        "\n".join(
            [
                f"ccx={ccx}",
                f"returncode={result.returncode}",
                "===== stdout =====",
                _clean_log_text(result.stdout),
                "===== stderr =====",
                _clean_log_text(result.stderr),
            ]
        ),
        encoding="utf-8",
    )

    dat_path = case_dir / f"{deck.stem}.dat"
    dat_text = dat_path.read_text(encoding="utf-8", errors="ignore") if dat_path.exists() else ""
    factors = parse_buckling_factors(dat_text)
    positive = [factor for factor in factors if factor > 0.0]
    first_factor = min(positive) if positive else None
    shell_buckle_n = None if first_factor is None else float(reference_load_factor) * first_factor
    root = parse_root_reaction(dat_text)
    reference = load_current_candidate_reference()
    internal_buckle_n = float(reference.reference_load_factor) / max(
        1.0 + float(reference.buckling_index),
        1.0e-12,
    )

    if result.returncode != 0:
        status = "FAIL"
        note = "CalculiX returned non-zero status."
    elif first_factor is None:
        status = "FAIL"
        note = "CalculiX completed but no positive buckling factor was parsed."
    elif shell_buckle_n is not None and shell_buckle_n > 100.0 * internal_buckle_n:
        status = "UNTRUSTED_FOR_LOCAL_WALL"
        note = (
            "CalculiX ran, but the full main-spar-only shell eigenvalue is far above "
            "the internal/local-wall scale because the simplified wire-supported load path "
            "does not reproduce the candidate compressive stress state."
        )
    elif shell_buckle_n >= 6.0:
        status = "PASS_DIRECTIONAL"
        note = "Candidate main-spar shell eigen-buckling is comfortably above the 3G to 4G exploration range."
    elif shell_buckle_n >= 3.0:
        status = "WARN_DIRECTIONAL"
        note = "Candidate shell buckling is above 3G but not comfortable for relaxed-limit exploration."
    else:
        status = "FAIL_DIRECTIONAL"
        note = "Candidate shell eigen-buckling is below 3G for this simplified tube model."

    return ShellBucklingRow(
        mesh_id=mesh_id,
        n_span=n_span,
        n_circumference=n_circumference,
        node_count=int(nodes.shape[0]),
        element_count=len(elements),
        reference_load_factor=float(reference_load_factor),
        reference_load_main_fz_n=float(load_summary["main_fz_n"]),
        reference_wire_fx_n=float(load_summary["wire_fx_n"]),
        reference_wire_fy_n=float(load_summary["wire_fy_n"]),
        reference_wire_fz_n=float(load_summary["wire_fz_n"]),
        static_root_rf_x_n=None if root is None else root[0],
        static_root_rf_y_n=None if root is None else root[1],
        static_root_rf_z_n=None if root is None else root[2],
        first_positive_buckle_factor=first_factor,
        shell_buckle_load_factor=shell_buckle_n,
        utilization_at_3g=None if shell_buckle_n is None else 3.0 / shell_buckle_n,
        utilization_at_4g=None if shell_buckle_n is None else 4.0 / shell_buckle_n,
        runtime_s=runtime_s,
        ccx_returncode=result.returncode,
        status=status,
        deck_path=str(deck),
        dat_path=str(dat_path),
        log_path=str(log_path),
        note=note,
    )


def build_tip_limit_review() -> list[TipLimitReviewRow]:
    reference = load_current_candidate_reference()
    cfg = load_config(
        json.loads((SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json").read_text())[
            "config"
        ]
    )
    halfspan = 0.5 * float(cfg.wing.span)
    wire6_limit_n = 3.9681422529259827
    rows: list[TipLimitReviewRow] = []
    for raw_limit in (2.50, 2.75, 3.00, 3.25):
        effective = raw_limit * 1.02
        n_defl = (
            float(reference.reference_load_factor)
            * effective
            / float(reference.tip_deflection_m)
        )
        first_limiter = "tip_deflection" if n_defl < wire6_limit_n else "wire_6kn"
        if raw_limit <= 2.50:
            use = "current conservative submission/design gate"
        elif raw_limit <= 3.00:
            use = "reasonable exploration gate only if loaded-shape/aeroelastic checks are rerun"
        else:
            use = "not recommended without a new aeroelastic/large-deflection validation basis"
        rows.append(
            TipLimitReviewRow(
                raw_tip_limit_m=raw_limit,
                effective_tip_limit_m=effective,
                limit_to_halfspan_ratio=effective / halfspan,
                deflection_limit_load_factor=n_defl,
                active_first_limiter_with_6kn_wire=first_limiter,
                engineering_use=use,
            )
        )
    return rows


def _write_csv(path: Path, rows: list[object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows to write for {path}.")
    payload = [asdict(row) for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(payload)
    return path


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.{digits}f}"


def write_reports(
    out_dir: Path,
    shell_rows: list[ShellBucklingRow],
    coupon_rows: list[LocalWallCouponRow],
    tip_rows: list[TipLimitReviewRow],
) -> list[Path]:
    best = min(
        (row for row in shell_rows if row.shell_buckle_load_factor is not None),
        key=lambda row: float(row.shell_buckle_load_factor),
        default=None,
    )
    reference = load_current_candidate_reference()

    shell_report = out_dir / "candidate_shell_buckling_report.md"
    shell_lines = [
        "# Candidate-Specific Shell Buckling FEM",
        "",
        "## Scope",
        "",
        "- Candidate: `current_avl_compromise_conservative_closed` / conservative closed run.",
        "- FEM route: Mac-local CalculiX S4 shell eigen-buckling, main spar only.",
        "- Geometry: current candidate jig main-spar centerline, outer radius, and wall thickness.",
        "- Load: current 2G main-spar nodal vertical loads plus the current wire force vector at the wire attach ring.",
        "- Material: `carbon_fiber_hm` as the current isotropic effective tube material.",
        "",
        "## Results",
        "",
        "| mesh | elements | first lambda | shell buckling n | util at 3G | util at 4G | status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in shell_rows:
        shell_lines.append(
            "| "
            f"{row.mesh_id} | {row.element_count} | {_fmt(row.first_positive_buckle_factor)} | "
            f"{_fmt(row.shell_buckle_load_factor)} | {_fmt(row.utilization_at_3g)} | "
            f"{_fmt(row.utilization_at_4g)} | {row.status} |"
        )
    shell_lines.extend(
        [
            "",
            "## Stress-Calibrated Local Wall Coupon",
            "",
            "| mesh | D/t | reference stress MPa | raw CCX lambda | raw CCX n | classical n | internal n | status |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in coupon_rows:
        shell_lines.append(
            "| "
            f"{row.mesh_id} | {row.d_over_t:.1f} | {row.reference_compressive_stress_mpa:.1f} | "
            f"{_fmt(row.first_positive_buckle_factor)} | {_fmt(row.shell_buckle_load_factor)} | "
            f"{_fmt(row.classical_knockdown_buckle_load_factor)} | "
            f"{_fmt(row.internal_estimate_buckle_load_factor)} | {row.status} |"
        )
    coupon_best = min(
        (row for row in coupon_rows if row.shell_buckle_load_factor is not None),
        key=lambda row: float(row.shell_buckle_load_factor),
        default=None,
    )
    shell_lines.extend(
        [
            "",
            "## Engineering Read",
            "",
        ]
    )
    if best is None and coupon_best is None:
        shell_lines.append("- CalculiX did not produce a usable positive buckling factor; this remains unresolved.")
    else:
        if best is not None:
            shell_lines.extend(
                [
                    f"- Full main-spar shell deck lowest parsed factor: `lambda = {_fmt(best.first_positive_buckle_factor, 4)}` on `{best.mesh_id}`, or `n = {_fmt(best.shell_buckle_load_factor, 3)}G` from the 2G preload.",
                    "- Engineering caution: this full-deck value is very high because the current wire load largely cancels net root vertical load in the simplified main-tube-only model; it is marked untrusted for local-wall buckling.",
                ]
            )
        if coupon_best is not None:
            shell_lines.extend(
                [
                    f"- Stress-calibrated local-wall coupon lowest parsed factor: `lambda = {_fmt(coupon_best.first_positive_buckle_factor, 4)}` on `{coupon_best.mesh_id}`.",
                    f"- That raw CCX value implies an impossible critical stress of `{_fmt(coupon_best.shell_critical_stress_mpa, 1)} MPa` versus the current knockdown/classical check of `{_fmt(coupon_best.classical_knockdown_sigma_cr_mpa, 1)} MPa`.",
                    "- Therefore the S4 shell eigenvalue is not accepted as local-wall truth in this run.",
                    f"- Current usable buckling screen remains the internal estimate: local-wall buckling utilization reaches 1.0 at about `n = {_fmt(coupon_best.internal_estimate_buckle_load_factor, 3)}G`.",
                    f"- A simpler knockdown/classical stress ratio gives `n = {_fmt(coupon_best.classical_knockdown_buckle_load_factor, 3)}G`, which is less conservative than the internal estimate.",
                    "- Engineering conclusion: buckling is not the blocker through 3G, but candidate-specific CCX shell eigen-buckling is still numerically unresolved rather than validated.",
                ]
            )
    shell_lines.extend(
        [
            "",
            "## Limits Of This FEM",
            "",
            "- This is candidate-specific for the main CFRP tube wall, but it is not a detailed root fitting, rib, bonded insert, lug, or wire-attach finite-element model.",
            "- The shell tube uses a smeared ring load at the wire attach station. That is appropriate for tube-wall screening, but it intentionally avoids claiming local lug bearing strength.",
            "- The local-wall coupon is stress-calibrated to the internal 2G compressive stress; it intentionally checks tube-wall stability rather than the full wing load path.",
            "- The material is still the current effective isotropic CFRP tube material; final composite local buckling should eventually use laminate ABD/orthotropic shell properties and knockdowns.",
            "- The run should therefore be called `candidate-specific CCX shell attempted, but local-wall eigenvalue unresolved`; the classical/internal estimate is still the accepted screening value.",
            "",
            f"- Reference 2G equivalent tip deflection used by the load-factor model: `{reference.tip_deflection_m:.6f} m`.",
            f"- Current effective tip deflection gate: `{reference.tip_deflection_limit_m:.6f} m`.",
        ]
    )
    shell_report.write_text("\n".join(shell_lines) + "\n", encoding="utf-8")

    tip_report = out_dir / "tip_deflection_limit_engineering_review.md"
    tip_lines = [
        "# Tip Deflection Limit Engineering Review",
        "",
        "## What The Limit Means",
        "",
        "- The current `max_tip_deflection_m = 2.5 m` is a design-validity gate, not a material rupture limit.",
        "- The feasibility code applies a 2% tolerance, so the effective current gate is `2.55 m`.",
        "- Crossing this gate means the fixed-load, fixed-aero-ranking, small/linear-deflection assumptions are becoming questionable; it does not mean the carbon tube snaps at that instant.",
        "",
        "## Sensitivity",
        "",
        "| raw limit m | effective limit m | effective / halfspan | deflection-limit n | first limiter with 6kN wire | engineering use |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for row in tip_rows:
        tip_lines.append(
            "| "
            f"{row.raw_tip_limit_m:.2f} | {row.effective_tip_limit_m:.2f} | "
            f"{row.limit_to_halfspan_ratio:.3f} | {row.deflection_limit_load_factor:.3f} | "
            f"{row.active_first_limiter_with_6kn_wire} | {row.engineering_use} |"
        )
    tip_lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "- The current 2.5 m raw limit is conservative but defensible: effective deflection is about 14.9% of halfspan, already large enough that aeroelastic/load-path assumptions deserve respect.",
            "- A modest relaxation to 2.75 m raw looks reasonable for engineering exploration using the current internal/classical buckling screen, because it keeps the deflection gate below the 6 kN wire failure estimate.",
            "- A 3.0 m raw limit can be used as a temporary exploration ceiling if the purpose is to see what happens after the current blocker, but it should trigger a loaded-shape AVL/aeroelastic recheck before being used as a submission number.",
            "- I would not relax beyond 3.0 m raw without a new validation basis. At that point the structural tube may still have stress/buckling margin, but the aircraft-level shape and joint load transfer are the real question.",
        ]
    )
    tip_report.write_text("\n".join(tip_lines) + "\n", encoding="utf-8")
    return [shell_report, tip_report]


def run_phase17(out_dir: Path = DEFAULT_OUTPUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = load_current_candidate_reference()
    mesh_specs = [
        ("coarse", 60, 48),
        ("medium", 96, 64),
    ]
    shell_rows = [
        run_shell_buckling_case(
            out_dir=out_dir,
            mesh_id=mesh_id,
            n_span=n_span,
            n_circumference=n_circ,
            reference_load_factor=reference.reference_load_factor,
        )
        for mesh_id, n_span, n_circ in mesh_specs
    ]
    coupon_specs = [
        ("coupon_coarse", 1.5, 96, 64),
        ("coupon_medium", 1.5, 160, 96),
    ]
    coupon_rows = [
        run_local_wall_coupon_case(
            out_dir=out_dir,
            mesh_id=mesh_id,
            length_m=length_m,
            n_span=n_span,
            n_circumference=n_circ,
            reference_load_factor=reference.reference_load_factor,
        )
        for mesh_id, length_m, n_span, n_circ in coupon_specs
    ]
    tip_rows = build_tip_limit_review()
    outputs = [
        _write_csv(out_dir / "candidate_shell_buckling_fem.csv", shell_rows),
        _write_csv(out_dir / "local_wall_shell_coupon_buckling.csv", coupon_rows),
        _write_csv(out_dir / "tip_deflection_limit_sensitivity.csv", tip_rows),
        *write_reports(out_dir, shell_rows, coupon_rows, tip_rows),
    ]
    return outputs


def main() -> None:
    outputs = run_phase17()
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
