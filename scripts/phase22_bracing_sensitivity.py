#!/usr/bin/env python3
"""Run report-only rear-spar and rib-link bracing sensitivity variants."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from hpa_mdo.structure.dual_beam_mainline import (  # noqa: E402
    AnalysisModeName,
    DualBeamMainlineModel,
    LinkMode,
    TorqueInputDefinition,
    run_dual_beam_mainline_kernel,
)
from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    CANDIDATE_ID,
    SELECTED_RUN,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase22_bracing_sensitivity"
REAR_SOFT_SCALE = 0.05


@dataclass(frozen=True)
class BracingSensitivityRow:
    variant_id: str
    mode: str
    link_mode: str
    rear_stiffness_scale: float
    status: str
    tip_main_m: float
    tip_rear_m: float
    max_vertical_displacement_m: float
    max_spar_pair_line_angle_delta_deg: float
    link_force_max_n: float
    wire_tension_max_n: float
    tip_main_delta_vs_baseline_pct: float
    max_vertical_delta_vs_baseline_pct: float
    angle_delta_vs_baseline_deg: float


@dataclass(frozen=True)
class BracingSensitivityAudit:
    candidate_id: str
    overall_status: str
    baseline_variant_id: str
    rows: tuple[BracingSensitivityRow, ...]


def clone_with_rear_stiffness_scale(
    model: DualBeamMainlineModel,
    scale: float,
) -> DualBeamMainlineModel:
    if scale <= 0.0:
        raise ValueError("rear stiffness scale must be positive.")
    cloned = copy.deepcopy(model)
    cloned.rear_area_m2 = np.asarray(model.rear_area_m2, dtype=float).copy() * float(scale)
    cloned.rear_iy_m4 = np.asarray(model.rear_iy_m4, dtype=float).copy() * float(scale)
    cloned.rear_iz_m4 = np.asarray(model.rear_iz_m4, dtype=float).copy() * float(scale)
    cloned.rear_j_m4 = np.asarray(model.rear_j_m4, dtype=float).copy() * float(scale)
    cloned.rear_mass_per_length_kgpm = (
        np.asarray(model.rear_mass_per_length_kgpm, dtype=float).copy() * float(scale)
    )
    return cloned


def build_bracing_sensitivity_audit(
    candidate_id: str,
    model: DualBeamMainlineModel,
) -> BracingSensitivityAudit:
    variants = (
        (
            "baseline_joint_only",
            AnalysisModeName.DUAL_BEAM_PRODUCTION,
            LinkMode.JOINT_ONLY_OFFSET_RIGID,
            1.0,
            model,
        ),
        (
            "dense_rigid_links",
            AnalysisModeName.DUAL_BEAM_PRODUCTION,
            LinkMode.DENSE_OFFSET_RIGID,
            1.0,
            model,
        ),
        (
            "dense_finite_rib_surrogate",
            AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
            LinkMode.DENSE_FINITE_RIB,
            1.0,
            model,
        ),
        (
            "rear_stiffness_5pct",
            AnalysisModeName.DUAL_BEAM_PRODUCTION,
            LinkMode.JOINT_ONLY_OFFSET_RIGID,
            REAR_SOFT_SCALE,
            clone_with_rear_stiffness_scale(model, REAR_SOFT_SCALE),
        ),
    )

    raw_rows = [
        _run_variant(
            variant_id=variant_id,
            mode=mode,
            link_mode=link_mode,
            rear_stiffness_scale=rear_stiffness_scale,
            model=variant_model,
        )
        for variant_id, mode, link_mode, rear_stiffness_scale, variant_model in variants
    ]
    baseline = raw_rows[0]
    rows = tuple(_with_baseline_delta(row, baseline) for row in raw_rows)
    return BracingSensitivityAudit(
        candidate_id=candidate_id,
        overall_status="report_only_bracing_sensitivity_not_signoff",
        baseline_variant_id=baseline.variant_id,
        rows=rows,
    )


def write_bracing_sensitivity_package(
    out_dir: Path,
    candidate_id: str,
    model: DualBeamMainlineModel,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = build_bracing_sensitivity_audit(candidate_id, model)
    outputs = [
        _write_csv(out_dir / "bracing_sensitivity.csv", audit),
        _write_json(out_dir / "bracing_sensitivity.json", audit),
        _write_markdown(out_dir / "bracing_sensitivity.md", audit),
    ]
    return outputs


def build_current_candidate_model() -> DualBeamMainlineModel:
    rows = _read_csv_rows(SELECTED_RUN / "jig_shape_spar_data.csv")
    wire = json.loads((SELECTED_RUN / "lift_wire_rigging.json").read_text(encoding="utf-8"))[
        "wire_rigging"
    ]
    summary = json.loads(
        (SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json").read_text(
            encoding="utf-8"
        )
    )
    cfg = load_config(summary["config"])
    materials = MaterialDB()
    main_mat = materials.get(cfg.main_spar.material)
    rear_mat = materials.get(cfg.rear_spar.material)
    load_case = cfg.structural_load_cases()[0]
    safety_factor = float(cfg.safety.material_safety_factor)
    main_allowable = min(
        float(main_mat.tensile_strength),
        float(main_mat.compressive_strength or main_mat.tensile_strength),
    ) / safety_factor
    rear_allowable = min(
        float(rear_mat.tensile_strength),
        float(rear_mat.compressive_strength or rear_mat.tensile_strength),
    ) / safety_factor

    y_nodes = np.asarray([float(row["Y_Position_m"]) for row in rows], dtype=float)
    nodes_main = np.asarray(
        [[float(row["Main_X_m"]), float(row["Y_Position_m"]), float(row["Main_Z_m"])] for row in rows],
        dtype=float,
    )
    nodes_rear = np.asarray(
        [[float(row["Rear_X_m"]), float(row["Y_Position_m"]), float(row["Rear_Z_m"])] for row in rows],
        dtype=float,
    )
    element_lengths = np.linalg.norm(np.diff(nodes_main, axis=0), axis=1)
    node_spacings = _node_spacings(y_nodes)
    main_r_node = np.asarray([float(row["Main_Outer_Radius_m"]) for row in rows], dtype=float)
    rear_r_node = np.asarray([float(row["Rear_Outer_Radius_m"]) for row in rows], dtype=float)
    main_t_node = np.asarray([float(row["Main_Wall_Thickness_m"]) for row in rows], dtype=float)
    rear_t_node = np.asarray([float(row["Rear_Wall_Thickness_m"]) for row in rows], dtype=float)
    main_r = _element_mean(main_r_node)
    rear_r = _element_mean(rear_r_node)
    main_t = _element_mean(main_t_node)
    rear_t = _element_mean(rear_t_node)
    main_area, main_i, main_j = _tube_properties(main_r, main_t)
    rear_area, rear_i, rear_j = _tube_properties(rear_r, rear_t)
    wire_node_indices = tuple(int(row["attach_node_index"]) for row in wire)
    wire_anchor_points = np.asarray([row["anchor_point_m"] for row in wire], dtype=float)
    wire_unstretched = np.asarray([float(row.get("L_cut_m", row["L_flight_m"])) for row in wire], dtype=float)
    wire_reference = np.linalg.norm(nodes_main[list(wire_node_indices)] - wire_anchor_points, axis=1)
    wire_allowable = np.asarray([float(row["allowable_tension_n"]) for row in wire], dtype=float)
    wire_area = np.full(len(wire_node_indices), np.pi * (0.5 * 2.0e-3) ** 2, dtype=float)
    wire_young = np.full(len(wire_node_indices), 70.0e9, dtype=float)

    return DualBeamMainlineModel(
        y_nodes_m=y_nodes,
        node_spacings_m=node_spacings,
        element_lengths_m=element_lengths,
        main_t_seg_m=main_t,
        main_r_seg_m=main_r,
        rear_t_seg_m=rear_t,
        rear_r_seg_m=rear_r,
        nodes_main_m=nodes_main,
        nodes_rear_m=nodes_rear,
        spar_offset_vectors_m=nodes_rear - nodes_main,
        spar_separation_nodes_m=nodes_rear[:, 0] - nodes_main[:, 0],
        main_area_m2=main_area,
        main_iy_m4=main_i,
        main_iz_m4=main_i.copy(),
        main_j_m4=main_j,
        rear_area_m2=rear_area,
        rear_iy_m4=rear_i,
        rear_iz_m4=rear_i.copy(),
        rear_j_m4=rear_j,
        main_radius_elem_m=main_r,
        rear_radius_elem_m=rear_r,
        main_mass_per_length_kgpm=main_area * float(main_mat.density),
        rear_mass_per_length_kgpm=rear_area * float(rear_mat.density),
        main_young_pa=np.full_like(main_area, float(main_mat.E), dtype=float),
        main_shear_pa=np.full_like(main_area, float(main_mat.G), dtype=float),
        rear_young_pa=np.full_like(rear_area, float(rear_mat.E), dtype=float),
        rear_shear_pa=np.full_like(rear_area, float(rear_mat.G), dtype=float),
        main_density_kgpm3=np.full_like(main_area, float(main_mat.density), dtype=float),
        rear_density_kgpm3=np.full_like(rear_area, float(rear_mat.density), dtype=float),
        main_allowable_stress_pa=np.full_like(main_area, main_allowable, dtype=float),
        rear_allowable_stress_pa=np.full_like(rear_area, rear_allowable, dtype=float),
        lift_per_span_npm=np.asarray([float(row["Lift_Per_Span_N_m"]) for row in rows], dtype=float),
        torque_per_span_nmpm=np.asarray(
            [float(row["Torque_Per_Span_Nm_m"]) for row in rows],
            dtype=float,
        ),
        torque_input=TorqueInputDefinition(),
        gravity_scale=float(load_case.gravity_scale),
        max_tip_deflection_limit_m=load_case.max_tip_deflection_m,
        max_thickness_step_m=float(cfg.solver.max_thickness_step_m),
        max_thickness_to_radius_ratio=float(cfg.solver.max_thickness_to_radius_ratio),
        main_spar_dominance_margin_m=float(cfg.solver.main_spar_dominance_margin_m),
        rear_main_radius_ratio_min=float(cfg.solver.rear_main_radius_ratio_min),
        main_spar_ei_ratio=float(cfg.solver.main_spar_ei_ratio),
        rear_min_inner_radius_m=float(cfg.solver.rear_min_inner_radius_m),
        rear_inboard_span_m=float(cfg.solver.rear_inboard_span_m),
        rear_inboard_ei_to_main_ratio_max=float(cfg.solver.rear_inboard_ei_to_main_ratio_max),
        joint_node_indices=tuple(
            idx for idx, row in enumerate(rows) if int(float(row.get("Is_Joint", "0")))
        ),
        dense_link_node_indices=tuple(range(1, len(rows) - 1)),
        wire_node_indices=wire_node_indices,
        wire_attachment_angles_deg=tuple(_wire_angle_deg(nodes_main[idx], anchor) for idx, anchor in zip(wire_node_indices, wire_anchor_points, strict=True)),
        wire_anchor_points_m=wire_anchor_points,
        wire_area_m2=wire_area,
        wire_young_pa=wire_young,
        wire_allowable_tension_n=wire_allowable,
        wire_reference_lengths_m=wire_reference,
        wire_unstretched_lengths_m=wire_unstretched,
        joint_mass_half_kg=0.0,
        fitting_mass_half_kg=0.0,
        equivalent_analysis_success=True,
        equivalent_failure_index=-1.0,
        equivalent_buckling_index=-1.0,
        equivalent_tip_deflection_m=0.0,
        equivalent_tip_deflection_limit_m=load_case.max_tip_deflection_m,
        equivalent_twist_max_deg=0.0,
        equivalent_twist_limit_deg=cfg.wing.max_tip_twist_deg,
    )


def _run_variant(
    *,
    variant_id: str,
    mode: AnalysisModeName,
    link_mode: LinkMode,
    rear_stiffness_scale: float,
    model: DualBeamMainlineModel,
) -> BracingSensitivityRow:
    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=mode,
        link_mode=link_mode,
    )
    max_angle_delta = _max_spar_pair_line_angle_delta_deg(
        model,
        result.disp_main_m,
        result.disp_rear_m,
    )
    return BracingSensitivityRow(
        variant_id=variant_id,
        mode=mode.value,
        link_mode=link_mode.value,
        rear_stiffness_scale=float(rear_stiffness_scale),
        status="solved_report_only",
        tip_main_m=float(result.report.tip_deflection_main_m),
        tip_rear_m=float(result.report.tip_deflection_rear_m),
        max_vertical_displacement_m=float(result.report.max_vertical_displacement_m),
        max_spar_pair_line_angle_delta_deg=float(max_angle_delta),
        link_force_max_n=float(result.report.link_force_max_n),
        wire_tension_max_n=float(result.recovery.max_wire_tension_n),
        tip_main_delta_vs_baseline_pct=0.0,
        max_vertical_delta_vs_baseline_pct=0.0,
        angle_delta_vs_baseline_deg=0.0,
    )


def _with_baseline_delta(
    row: BracingSensitivityRow,
    baseline: BracingSensitivityRow,
) -> BracingSensitivityRow:
    return BracingSensitivityRow(
        **{
            **asdict(row),
            "tip_main_delta_vs_baseline_pct": _pct_delta(row.tip_main_m, baseline.tip_main_m),
            "max_vertical_delta_vs_baseline_pct": _pct_delta(
                row.max_vertical_displacement_m,
                baseline.max_vertical_displacement_m,
            ),
            "angle_delta_vs_baseline_deg": (
                row.max_spar_pair_line_angle_delta_deg
                - baseline.max_spar_pair_line_angle_delta_deg
            ),
        }
    )


def _max_spar_pair_line_angle_delta_deg(
    model: DualBeamMainlineModel,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
) -> float:
    jig_angles = [
        _spar_pair_angle_deg(main, rear)
        for main, rear in zip(model.nodes_main_m, model.nodes_rear_m, strict=True)
    ]
    loaded_main = np.asarray(model.nodes_main_m, dtype=float) + np.asarray(disp_main_m[:, :3], dtype=float)
    loaded_rear = np.asarray(model.nodes_rear_m, dtype=float) + np.asarray(disp_rear_m[:, :3], dtype=float)
    loaded_angles = [
        _spar_pair_angle_deg(main, rear)
        for main, rear in zip(loaded_main, loaded_rear, strict=True)
    ]
    root_delta = loaded_angles[0] - jig_angles[0]
    deltas = [
        float((loaded_angle - jig_angle) - root_delta)
        for jig_angle, loaded_angle in zip(jig_angles, loaded_angles, strict=True)
    ]
    return float(max(abs(value) for value in deltas))


def _spar_pair_angle_deg(main: np.ndarray, rear: np.ndarray) -> float:
    dx = float(rear[0] - main[0])
    dz = float(rear[2] - main[2])
    return float(math.degrees(math.atan2(dz, dx)))


def _node_spacings(y_nodes: np.ndarray) -> np.ndarray:
    spacings = np.zeros_like(y_nodes, dtype=float)
    dy = np.diff(y_nodes)
    spacings[0] = 0.5 * dy[0]
    spacings[-1] = 0.5 * dy[-1]
    if y_nodes.size > 2:
        spacings[1:-1] = 0.5 * (dy[:-1] + dy[1:])
    return spacings


def _element_mean(values: np.ndarray) -> np.ndarray:
    return 0.5 * (np.asarray(values[:-1], dtype=float) + np.asarray(values[1:], dtype=float))


def _tube_properties(radius_m: np.ndarray, wall_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    inner = np.maximum(np.asarray(radius_m, dtype=float) - np.asarray(wall_m, dtype=float), 0.0)
    area = math.pi * (radius_m**2 - inner**2)
    second_moment = math.pi / 4.0 * (radius_m**4 - inner**4)
    polar = math.pi / 2.0 * (radius_m**4 - inner**4)
    return area, second_moment, polar


def _wire_angle_deg(attach: np.ndarray, anchor: np.ndarray) -> float:
    axis = np.asarray(attach, dtype=float) - np.asarray(anchor, dtype=float)
    horizontal = math.hypot(float(axis[0]), float(axis[1]))
    return float(math.degrees(math.atan2(abs(float(axis[2])), max(horizontal, 1.0e-12))))


def _pct_delta(value: float, baseline: float) -> float:
    denom = max(abs(float(baseline)), 1.0e-12)
    return float((float(value) - float(baseline)) / denom * 100.0)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fmt(value: float) -> str:
    return f"{float(value):.4f}"


def _write_csv(path: Path, audit: BracingSensitivityAudit) -> Path:
    fields = list(asdict(audit.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in audit.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, audit: BracingSensitivityAudit) -> Path:
    path.write_text(json.dumps(asdict(audit), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, audit: BracingSensitivityAudit) -> Path:
    lines = [
        "# Bracing Sensitivity",
        "",
        f"Candidate: `{audit.candidate_id}`",
        f"Overall status: `{audit.overall_status}`",
        "",
        "This is a report-only sensitivity, not a full-wing FEM signoff.",
        "The current-candidate smoke rebuilds the beam-kernel model from exported rows; compare deltas only, not absolute signoff loads.",
        "",
        "## Variants",
        "",
        "| variant | mode | link mode | rear scale | tip main m | max vertical m | spar-pair angle deg | link force N | wire tension N | d tip % | d max vertical % | d angle deg |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in audit.rows:
        lines.append(
            f"| {row.variant_id} | `{row.mode}` | `{row.link_mode}` | {_fmt(row.rear_stiffness_scale)} | "
            f"{_fmt(row.tip_main_m)} | {_fmt(row.max_vertical_displacement_m)} | "
            f"{_fmt(row.max_spar_pair_line_angle_delta_deg)} | {_fmt(row.link_force_max_n)} | "
            f"{_fmt(row.wire_tension_max_n)} | {_fmt(row.tip_main_delta_vs_baseline_pct)} | "
            f"{_fmt(row.max_vertical_delta_vs_baseline_pct)} | {_fmt(row.angle_delta_vs_baseline_deg)} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- This compares existing beam/rib-link modeling choices only.",
            "- Dense finite rib remains a surrogate, not rib hardware allowables.",
            "- Rear-soft sensitivity indicates dependence on rear-spar section stiffness, not proof of local joints or full-wing buckling.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    model = build_current_candidate_model()
    outputs = write_bracing_sensitivity_package(args.output_dir, CANDIDATE_ID, model)
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
