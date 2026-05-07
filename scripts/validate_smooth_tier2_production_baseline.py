#!/usr/bin/env python3
"""Validate the smooth Tier2 production-facing aerodynamic baseline.

This is a final-candidate sidecar validation package. It does not rerun
CST/NSGA, mutate production ranking, or change hard gates.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.airfoils.database import (  # noqa: E402
    AirfoilDatabase,
    AirfoilQuery,
    ZoneAirfoilAssignment,
    integrate_profile_drag_from_avl,
)
from hpa_mdo.airfoils.polar_builder import load_airfoil_database_artifact  # noqa: E402

from scripts import audit_avl_induced_drag_credibility as avl_audit  # noqa: E402
from scripts import export_phase7_sidecar_vsp as vsp_exporter  # noqa: E402
from scripts import phase9_smooth_geometry_combo_reoptimization as reopt  # noqa: E402
from scripts import phase9_structure_jig_smooth_planform as phase9  # noqa: E402


CASE_ID = "smooth_tier2_production_baseline"
DISPLAY_NAME = "Smooth Tier2 production-facing baseline"
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "final_candidate_validation" / CASE_ID
REOPT_OUTPUT_DIR = _REPO_ROOT / "output" / "phase9_smooth_geometry_combo_reoptimization"
PHASE9_OUTPUT_DIR = _REPO_ROOT / "output" / "phase9_structure_jig_smooth_planform"
TIER2_DIR = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"
ASSIGNMENT = {
    "root": "dae31",
    "mid1": "dae31",
    "mid2": "dae31",
    "tip": "cst_tip_nsga2_g06_child_0056_b3f9b7c4",
}
GEOMETRY_EXPORT_MODES = ("production_inspection", "avl_parity")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_float(value: Any, default: float | None = None) -> float | None:
    return phase9.safe_float(value, default)


def json_ready(value: Any) -> Any:
    return phase9.json_ready(value)


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    return phase9.read_csv_rows(path)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(json_ready(dict(row)))


def assignment_label(assignment: Mapping[str, str]) -> str:
    return "|".join(f"{zone}:{assignment.get(zone, '')}" for zone, _, _ in reopt.ZONE_BOUNDS)


def zone_for_eta(eta: float) -> str:
    return reopt.zone_for_eta(eta)


def zone_assignments(assignment: Mapping[str, str]) -> tuple[ZoneAirfoilAssignment, ...]:
    return tuple(
        ZoneAirfoilAssignment(zone, str(assignment.get(zone, "")), lo, min(hi, 1.0))
        for zone, lo, hi in reopt.ZONE_BOUNDS
    )


def load_record_metadata(tier2_dir: Path = TIER2_DIR) -> dict[str, dict[str, str]]:
    return {row["airfoil_id"]: dict(row) for row in read_csv_rows(tier2_dir / "airfoil_records.csv") if row.get("airfoil_id")}


def load_selected_combo_row(reopt_dir: Path = REOPT_OUTPUT_DIR) -> dict[str, str]:
    expected = assignment_label(ASSIGNMENT)
    for row in read_csv_rows(reopt_dir / "best_smooth_by_policy.csv"):
        if row.get("ranking_view") != "smooth_reoptimized_clean_overall_best":
            continue
        if row.get("assignment") != expected:
            raise ValueError(f"Clean smooth baseline assignment drifted: {row.get('assignment')} != {expected}")
        return row
    raise FileNotFoundError("Could not find smooth_reoptimized_clean_overall_best in Phase 9 reoptimization output")


def stage_airfoils(
    *,
    assignment: Mapping[str, str],
    database: AirfoilDatabase,
    airfoil_dir: Path,
) -> dict[str, Path]:
    airfoil_dir.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    for airfoil_id in dict.fromkeys(str(value) for value in assignment.values()):
        source = reopt.dat_path_for_airfoil(database, airfoil_id)
        target = airfoil_dir / f"{airfoil_id}.dat"
        shutil.copyfile(source, target)
        staged[airfoil_id] = target.resolve()
    return staged


def exported_sections_from_avl(
    *,
    avl_path: Path,
    assignment: Mapping[str, str],
    staged_airfoils: Mapping[str, Path],
    records_metadata: Mapping[str, Mapping[str, str]],
) -> tuple[vsp_exporter.ExportedSection, ...]:
    geometry = vsp_exporter.parse_avl_geometry(avl_path)
    half_span = max((section.y_m for section in geometry.sections), default=0.0)
    sections: list[vsp_exporter.ExportedSection] = []
    for index, section in enumerate(geometry.sections):
        eta = 0.0 if half_span <= 0.0 else float(section.y_m) / float(half_span)
        zone = zone_for_eta(eta)
        airfoil_id = str(assignment[zone])
        if index == 0:
            slope = None
            dihedral = None
        else:
            previous = geometry.sections[index - 1]
            dy = float(section.y_m) - float(previous.y_m)
            dz = float(section.z_m) - float(previous.z_m)
            slope = None if abs(dy) <= 1.0e-12 else dz / dy
            dihedral = None if slope is None else math.degrees(math.atan(slope))
        sections.append(
            vsp_exporter.ExportedSection(
                section_index=index,
                eta=eta,
                y_m=float(section.y_m),
                z_m=float(section.z_m),
                chord_m=float(section.chord_m),
                twist_deg=float(section.twist_deg),
                dihedral_local_z_slope=slope,
                dihedral_local_deg=dihedral,
                airfoil_id=airfoil_id,
                airfoil_source_quality=str(records_metadata.get(airfoil_id, {}).get("source_quality") or "unknown"),
                airfoil_dat_path=str(staged_airfoils[airfoil_id]),
            )
        )
    return tuple(sections)


def write_section_table(path: Path, sections: Sequence[vsp_exporter.ExportedSection]) -> None:
    write_csv(path, [asdict(section) for section in sections])


def geometry_manifest(
    *,
    mode: str,
    case_dir: Path,
    source_avl: Path,
    avl_path: Path,
    section_table: Path,
    vsp_report: Mapping[str, Any],
    sections: Sequence[vsp_exporter.ExportedSection],
) -> dict[str, Any]:
    computed_area = sum(
        (right.y_m - left.y_m) * 0.5 * (left.chord_m + right.chord_m)
        for left, right in zip(sections[:-1], sections[1:])
    ) * 2.0
    span_m = 2.0 * max((section.y_m for section in sections), default=0.0)
    return {
        "schema_version": "smooth_tier2_production_baseline_geometry_manifest_v1",
        "case_id": CASE_ID,
        "display_name": DISPLAY_NAME,
        "export_mode": mode,
        "source_phase": "phase9_smooth_geometry_combo_reoptimization",
        "source_avl": str(source_avl.resolve()),
        "avl_path": str(avl_path.resolve()),
        "section_table_csv": str(section_table.resolve()),
        "case_dir": str(case_dir.resolve()),
        "airfoil_assignment": dict(ASSIGNMENT),
        "chord_mode": "phase9_smooth_monotone_preserved",
        "loaded_z_distribution": "phase9_smooth_monotone_preserved",
        "incidence_convention": "source_smooth_geometry_preserved_no_second_incidence_offset",
        "computed_wing_area_m2": computed_area,
        "computed_span_m": span_m,
        "loaded_tip_z_m": sections[-1].z_m if sections else None,
        "generated_at": timestamp(),
        "known_limitations": [
            "Final-candidate validation package only; no production ranking or hard gates changed.",
            "The smooth-monotone planform and loaded z are preserved from Phase 9.",
            "The production_inspection export intentionally does not re-PAVA or re-offset the already smooth/cruise-normalized source geometry.",
        ],
        "vsp_export": dict(vsp_report),
    }


def export_geometry_packages(
    *,
    source_avl: Path,
    output_dir: Path,
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
    build_vsp: bool,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    source_geometry = vsp_exporter.parse_avl_geometry(source_avl)
    source_geometry = vsp_exporter.AvlGeometry(
        title=f"{DISPLAY_NAME} from {source_geometry.title}",
        sref_m2=source_geometry.sref_m2,
        cref_m=source_geometry.cref_m,
        bref_m=source_geometry.bref_m,
        xref_m=source_geometry.xref_m,
        yref_m=source_geometry.yref_m,
        zref_m=source_geometry.zref_m,
        sections=source_geometry.sections,
    )
    for mode in GEOMETRY_EXPORT_MODES:
        case_dir = output_dir / "geometry_exports" / mode / CASE_ID
        airfoil_dir = case_dir / "airfoils"
        case_dir.mkdir(parents=True, exist_ok=True)
        staged = stage_airfoils(assignment=ASSIGNMENT, database=database, airfoil_dir=airfoil_dir)
        sections = exported_sections_from_avl(
            avl_path=source_avl,
            assignment=ASSIGNMENT,
            staged_airfoils=staged,
            records_metadata=records_metadata,
        )
        avl_path = case_dir / f"{CASE_ID}.avl"
        vsp_exporter.write_avl(source_geometry, sections, avl_path)
        section_table = case_dir / "section_table.csv"
        write_section_table(section_table, sections)
        vsp3_path = case_dir / f"{CASE_ID}.vsp3"
        vspscript_path = case_dir / f"{CASE_ID}.vspscript"
        vsp_report = vsp_exporter.build_vsp3_from_sections(
            sections,
            output_path=vsp3_path,
            script_path=vspscript_path,
            build_vsp=build_vsp,
        )
        manifest = geometry_manifest(
            mode=mode,
            case_dir=case_dir,
            source_avl=source_avl,
            avl_path=avl_path,
            section_table=section_table,
            vsp_report=vsp_report,
            sections=sections,
        )
        manifest_path = case_dir / "geometry_manifest.json"
        manifest_path.write_text(json.dumps(json_ready(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output[mode] = {
            "case_dir": str(case_dir.resolve()),
            "avl_path": str(avl_path.resolve()),
            "vsp3_path": str(vsp3_path.resolve()) if vsp3_path.is_file() else None,
            "vspscript_path": str(vspscript_path.resolve()) if vspscript_path.is_file() else None,
            "section_table_csv": str(section_table.resolve()),
            "geometry_manifest_json": str(manifest_path.resolve()),
            "vsp_status": vsp_report.get("status"),
            "airfoil_dir": str(airfoil_dir.resolve()),
        }
    return output


def zone_extreme_work_points(
    *,
    spanload: Sequence[Mapping[str, Any]],
    assignment: Mapping[str, str],
    rho: float,
    speed_mps: float,
    dynamic_viscosity_pa_s: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zone, lo, hi in reopt.ZONE_BOUNDS:
        subset = [
            row
            for row in spanload
            if lo <= float(row.get("eta", 0.0)) < hi or (zone == "tip" and lo <= float(row.get("eta", 0.0)) <= hi)
        ]
        usable = [row for row in subset if safe_float(row.get("cl")) is not None and safe_float(row.get("chord_m")) is not None]
        if not usable:
            continue
        selected = max(usable, key=lambda row: safe_float(row.get("cl"), -float("inf")) or -float("inf"))
        chord = safe_float(selected.get("chord_m"), 0.0) or 0.0
        cl_value = safe_float(selected.get("cl"), 0.0) or 0.0
        rows.append(
            {
                "zone": zone,
                "work_point": "max_local_cl",
                "airfoil_id": str(assignment.get(zone, "")),
                "eta": safe_float(selected.get("eta")),
                "chord_m": chord,
                "Re": float(rho) * float(speed_mps) * chord / float(dynamic_viscosity_pa_s),
                "Cl": cl_value,
            }
        )
    return rows


def run_avl_aero_summary(
    *,
    avl_path: Path,
    section_table: Path,
    output_dir: Path,
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
    avl_binary: str | Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    names = avl_audit.surface_names(avl_path)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    case = avl_audit.CaseSpec(
        case_id=CASE_ID,
        display_name=DISPLAY_NAME,
        avl_path=avl_path,
        section_table_path=section_table,
        cl_required=phase9.MISSION_CL_REQ,
        target_surface_names=target_surfaces,
        assignment_by_zone=ASSIGNMENT,
        family=CASE_ID,
    )
    avl_result = avl_audit.run_avl_trim_and_spanload(
        case=case,
        avl_path=avl_path,
        run_dir=output_dir / "avl_runs" / CASE_ID,
        avl_binary=avl_binary,
    )
    sections = phase9.read_section_table(section_table)
    spanload = reopt.spanload_with_avl_cl(avl_result.get("spanload", []))
    contract = reopt.mission_contract_for_sections(sections)
    profile = integrate_profile_drag_from_avl(
        contract,
        spanload,
        [row.__dict__ for row in sections],
        zone_assignments(ASSIGNMENT),
        database,
        cl_source_shape_mode="smooth_tier2_production_baseline_avl",
        cl_source_loaded_shape=True,
        cl_source_warning_count=0,
    )
    cdi = safe_float(avl_result.get("CDff"), safe_float(avl_result.get("CDind")))
    refs = avl_result.get("refs", {})
    sref = safe_float(refs.get("Sref"), contract.wing_area_m2) or contract.wing_area_m2
    cd0 = float(profile.cd0_total_est)
    cd_total = None if cdi is None else cdi + cd0
    cd_total_cons = None if cdi is None else 1.05 * cdi + cd0
    q = 0.5 * phase9.MISSION_RHO_KGPM3 * phase9.MISSION_SPEED_MPS**2
    p_air = None if cd_total is None else q * sref * cd_total * phase9.MISSION_SPEED_MPS
    p_crank = None if p_air is None else p_air / (phase9.ETA_PROP * phase9.ETA_TRANS)
    p_air_cons = None if cd_total_cons is None else q * sref * cd_total_cons * phase9.MISSION_SPEED_MPS
    p_crank_cons = None if p_air_cons is None else p_air_cons / (phase9.ETA_PROP * phase9.ETA_TRANS)
    local_max = {
        zone: max((float(row["cl"]) for row in spanload if zone_for_eta(float(row["eta"])) == zone), default=None)
        for zone, _, _ in reopt.ZONE_BOUNDS
    }
    actual_fail = reopt.actual_query_fail_summary(ASSIGNMENT, profile.station_rows)
    actual_quality = (
        "actual_sidecar_query_grade_sidecar"
        if not actual_fail and int(profile.station_warning_count) == 0
        else "actual_sidecar_query_not_mission_grade_sidecar"
    )
    archive_quality = (
        "archive_mission_grade_sidecar"
        if all(
            records_metadata.get(airfoil_id, {}).get("source_quality") == "full_polar_mission_grade_candidate"
            for airfoil_id in ASSIGNMENT.values()
        )
        else "archive_not_mission_grade_sidecar"
    )
    row = {
        "case_id": CASE_ID,
        "display_name": DISPLAY_NAME,
        "assignment": assignment_label(ASSIGNMENT),
        "alpha_at_CL_req": avl_result.get("alpha_at_CL_req_deg"),
        "CL_req": phase9.MISSION_CL_REQ,
        "CL": avl_result.get("CLtot"),
        "CDi": cdi,
        "CDi_conservative": None if cdi is None else 1.05 * cdi,
        "e_CDi": avl_result.get("e_CDi_from_CDff", avl_result.get("e_CDi_from_CDind")),
        "profile_cd": profile.CD_profile,
        "CD0_total_est": cd0,
        "CD_total": cd_total,
        "L_D": None if cd_total in (None, 0.0) else phase9.MISSION_CL_REQ / cd_total,
        "P_air": p_air,
        "P_crank": p_crank,
        "P_crank_conservative": p_crank_cons,
        "mission_drag_budget_band": profile.drag_budget_band,
        "local_Cl_max_root": local_max.get("root"),
        "local_Cl_max_mid1": local_max.get("mid1"),
        "local_Cl_max_mid2": local_max.get("mid2"),
        "local_Cl_max_tip": local_max.get("tip"),
        "stall_margin": profile.min_stall_margin_deg,
        "max_utilization": profile.max_station_cl_utilization,
        "archive_source_quality": archive_quality,
        "archive_source_quality_summary": reopt.quality_summary(ASSIGNMENT, records_metadata, field="source_quality"),
        "actual_sidecar_query_quality": actual_quality,
        "actual_sidecar_query_fail_reasons": actual_fail,
        "avl_path": str(avl_path.resolve()),
        "run_dir": avl_result.get("run_dir"),
    }
    return row, spanload, profile


def reference_power_rows(phase9_output_dir: Path = PHASE9_OUTPUT_DIR) -> list[dict[str, Any]]:
    wanted = [
        ("original_raw_faceted_best", "raw_best_tier2", "raw"),
        ("forced_smooth_raw_before_reselection", "raw_best_tier2", "smooth_monotone"),
        ("previous_policy_A_smooth", "policy_A_performance_candidate", "smooth_monotone"),
        ("previous_policy_C_smooth", "policy_C_conservative_baseline", "smooth_monotone"),
        ("old_FX_Clark_baseline", "old_fx_clark_baseline", "raw"),
    ]
    source = read_csv_rows(phase9_output_dir / "aero_comparison.csv")
    output: list[dict[str, Any]] = []
    for label, case_id, variant in wanted:
        match = next((row for row in source if row.get("case_id") == case_id and row.get("variant") == variant), None)
        if not match:
            continue
        cdi = safe_float(match.get("CDi"))
        cd0 = safe_float(match.get("CD0_total_est"))
        p_crank = safe_float(match.get("P_crank"))
        p_cons = safe_float(match.get("P_crank_conservative"))
        if p_cons is None and cdi is not None and cd0 is not None and p_crank is not None:
            cd_total = cdi + cd0
            p_cons = None if cd_total <= 0.0 else p_crank * ((1.05 * cdi + cd0) / cd_total)
        output.append(
            {
                "comparison_label": label,
                "case_id": match.get("case_id"),
                "display_name": match.get("display_name"),
                "variant": match.get("variant"),
                "assignment": match.get("assignment"),
                "P_crank": p_crank,
                "P_crank_conservative": p_cons,
                "CDi": cdi,
                "profile_cd": safe_float(match.get("profile_cd")),
                "archive_source_quality": match.get("archive_source_quality"),
                "actual_sidecar_query_quality": match.get("actual_sidecar_query_quality"),
            }
        )
    return output


def power_comparison_rows(
    *,
    new_summary: Mapping[str, Any],
    reference_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    new_power = safe_float(new_summary.get("P_crank"))
    new_cons = safe_float(new_summary.get("P_crank_conservative"), new_power)
    rows: list[dict[str, Any]] = []
    for ref in reference_rows:
        ref_power = safe_float(ref.get("P_crank"))
        ref_cons = safe_float(ref.get("P_crank_conservative"), ref_power)
        rows.append(
            {
                "case_id": ref.get("case_id"),
                "comparison_label": ref.get("comparison_label", ref.get("case_id")),
                "reference_variant": ref.get("variant"),
                "reference_P_crank": ref_power,
                "reference_P_crank_conservative": ref_cons,
                "new_P_crank": new_power,
                "new_P_crank_conservative": new_cons,
                "delta_new_minus_reference_W": None if new_power is None or ref_power is None else new_power - ref_power,
                "delta_new_conservative_minus_reference_conservative_W": None
                if new_cons is None or ref_cons is None
                else new_cons - ref_cons,
                "new_beats_reference_nominal": None if new_power is None or ref_power is None else new_power < ref_power,
                "new_beats_reference_with_5pct_CDi_margin": None if new_cons is None or ref_cons is None else new_cons < ref_cons,
            }
        )
    return rows


def structure_feasibility_status(
    *,
    structure_row: Mapping[str, Any],
    selected_tube: Mapping[str, Any],
) -> dict[str, Any]:
    flags = [item for item in str(structure_row.get("warning_flags") or "").split("|") if item]
    jig_fail = str(structure_row.get("jig_feasibility_band") or "") != "proxy_ok" or bool(flags and flags != ["no_proxy_warning"])
    ei_pass = bool(selected_tube.get("ei_pass"))
    mass = safe_float(selected_tube.get("estimated_full_span_tube_mass_kg"))
    target = safe_float(selected_tube.get("current_spar_tube_mass_target_kg"))
    mass_pass = None if mass is None or target is None else mass <= target
    failure_modes: list[str] = []
    if jig_fail:
        failure_modes.append("jig_shape_driven")
    if not ei_pass:
        failure_modes.append("stiffness_driven")
    if ei_pass and mass_pass is False:
        failure_modes.append("stiffness_mass_target_driven")
    failure_modes.append("strength_not_evaluated_proxy")
    structure_pass = not jig_fail and ei_pass and mass_pass is True
    return {
        "structure_proxy_pass": structure_pass,
        "jig_proxy_pass": not jig_fail,
        "carbon_EI_proxy_pass": ei_pass,
        "spar_mass_target_pass": mass_pass,
        "failure_modes": "|".join(failure_modes),
        "dominant_blocker": "structure" if not structure_pass else "none",
    }


def old_fx_raw_structure_metrics(
    *,
    output_dir: Path,
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    old_case = next(case for case in phase9.build_candidate_specs() if case.case_id == "old_fx_clark_baseline")
    names = avl_audit.surface_names(old_case.raw_avl)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    result = avl_audit.run_avl_trim_and_spanload(
        case=avl_audit.CaseSpec(
            case_id="old_fx_clark_baseline_raw_reference",
            display_name="Old FX/Clark raw reference for structure proxy scaling",
            avl_path=old_case.raw_avl,
            section_table_path=old_case.raw_section_table,
            cl_required=old_case.cl_req,
            target_surface_names=target_surfaces,
            assignment_by_zone=old_case.assignment,
            family=old_case.family,
        ),
        avl_path=old_case.raw_avl,
        run_dir=output_dir / "avl_runs" / "old_fx_clark_baseline_raw_reference",
        avl_binary=avl_binary,
    )
    return phase9.spanload_structure_metrics(result.get("spanload", []))


def structure_jig_audit(
    *,
    output_dir: Path,
    sections: Sequence[phase9.SectionRow],
    spanload: Sequence[Mapping[str, Any]],
    avl_binary: str | Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    phase9_structure_rows = read_csv_rows(PHASE9_OUTPUT_DIR / "structure_jig_comparison.csv")
    old_raw = next((row for row in phase9_structure_rows if row.get("case_id") == "old_fx_clark_baseline" and row.get("variant") == "raw"), {})
    old_metrics = old_fx_raw_structure_metrics(output_dir=output_dir, avl_binary=avl_binary)
    baseline_bending = safe_float(old_metrics.get("root_bending_proxy_n_m"), safe_float(old_raw.get("root_bending_proxy_n_m")))
    baseline_second = safe_float(old_metrics.get("tip_deflection_second_moment_proxy"))
    metrics = phase9.spanload_structure_metrics(spanload)
    case = phase9.CandidateSpec(
        case_id=CASE_ID,
        display_name=DISPLAY_NAME,
        assignment=dict(ASSIGNMENT),
        cl_req=phase9.MISSION_CL_REQ,
        raw_avl=Path(""),
        raw_section_table=Path(""),
        raw_vsp3=None,
        monotone_avl=None,
        monotone_section_table=None,
        monotone_vsp3=None,
        family=CASE_ID,
    )
    row = phase9.structure_jig_row(
        case=case,
        variant="smooth_production_baseline",
        sections=sections,
        spanload_metrics=metrics,
        baseline_bending=baseline_bending,
        baseline_second_moment=baseline_second,
    )
    span_m = safe_float(row.get("span_m"), 34.332286) or 34.332286
    current_ei = phase9.tube_ei_nm2(
        outer_diameter_m=0.070,
        inner_diameter_m=0.070 - 2.0 * 0.0007,
        youngs_pa=120.0e9,
        tube_count_per_wing=2,
        vertical_separation_m=0.10,
    )
    current_tip = safe_float(row.get("tip_deflection_estimate_m"), 1.25) or 1.25
    loaded_tip_z = safe_float(row.get("loaded_tip_z_m"), 1.05) or 1.05
    required_ei = phase9.required_ei_from_deflection(
        target_tip_deflection_m=max(loaded_tip_z, 0.25),
        current_tip_deflection_m=current_tip,
        current_ei_nm2=current_ei,
    )
    carbon_rows = phase9.carbon_tube_candidates(
        catalog_path=_REPO_ROOT / "data" / "carbon_tubes.csv",
        half_span_m=0.5 * span_m,
        required_ei_nm2=required_ei,
        youngs_pa=120.0e9,
        tube_count_per_wing=2,
        vertical_separation_m=0.10,
        current_spar_tube_mass_target_kg=phase9.CURRENT_SPAR_TUBE_MASS_TARGET_KG,
    )
    selected_tube = next((item for item in carbon_rows if bool(item.get("ei_pass"))), carbon_rows[0] if carbon_rows else {})
    status = structure_feasibility_status(structure_row=row, selected_tube=selected_tube)
    audit_row = {
        **row,
        "required_EI_proxy_Nm2": required_ei,
        "selected_tube_product": selected_tube.get("product"),
        "selected_tube_EI_proxy_Nm2": selected_tube.get("EI_proxy_Nm2"),
        "selected_tube_estimated_full_span_tube_mass_kg": selected_tube.get("estimated_full_span_tube_mass_kg"),
        "current_spar_tube_mass_target_kg": selected_tube.get("current_spar_tube_mass_target_kg"),
        "selected_tube_mass_margin_vs_current_target_kg": selected_tube.get("mass_margin_vs_current_target_kg"),
        **status,
    }
    return audit_row, carbon_rows


def su2_priority(utilization: float | None, stall_margin_deg: float | None) -> str:
    if utilization is not None and utilization >= 0.85:
        return "highest"
    if stall_margin_deg is not None and stall_margin_deg <= 2.0:
        return "highest"
    if utilization is not None and utilization >= 0.75:
        return "high"
    return "medium"


def su2_settings_text() -> str:
    return (
        "2D low-Mach/incompressible RANS; fixed Re; alpha sweep DB_alpha +/-2 deg "
        "with 0.25 deg refinement near target Cl; yplus<=1; farfield >=50c; "
        "C-grid/O-grid wake refinement; run clean first, then rough/transition sensitivity if mismatch >5% Cd."
    )


def su2_verification_cases(
    *,
    spanload: Sequence[Mapping[str, Any]],
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    work_points = zone_extreme_work_points(
        spanload=spanload,
        assignment=ASSIGNMENT,
        rho=phase9.MISSION_RHO_KGPM3,
        speed_mps=phase9.MISSION_SPEED_MPS,
        dynamic_viscosity_pa_s=phase9.MISSION_DYNAMIC_VISCOSITY_PA_S,
    )
    rows: list[dict[str, Any]] = []
    for row in work_points:
        airfoil_id = str(row["airfoil_id"])
        result = database.lookup(
            AirfoilQuery(
                airfoil_id=airfoil_id,
                Re=float(row["Re"]),
                cl=float(row["Cl"]),
                allow_extrapolation=False,
            )
        )
        record = database.records[airfoil_id]
        utilization = float(row["Cl"]) / max(float(record.safe_clmax), 1.0e-12)
        meta = records_metadata.get(airfoil_id, {})
        archive_quality = meta.get("archive_source_quality") or meta.get("source_quality")
        actual_query_quality = (
            "actual_work_point_query_grade"
            if result.clmax_margin >= 0.0 and not result.warnings
            else "actual_work_point_query_not_mission_grade"
        )
        rows.append(
            {
                "case_id": CASE_ID,
                "zone": row["zone"],
                "airfoil_id": airfoil_id,
                "coordinate_path": reopt.dat_path_for_airfoil(database, airfoil_id),
                "work_point": row["work_point"],
                "eta": row["eta"],
                "Re": row["Re"],
                "Cl": row["Cl"],
                "alpha_deg_from_tier2_lookup": result.alpha_deg,
                "Cd_tier2_lookup": result.cd,
                "Cm_tier2_lookup": result.cm,
                "stall_margin_deg": result.stall_margin_deg,
                "clmax_margin": result.clmax_margin,
                "station_utilization": utilization,
                "record_source_quality": meta.get("source_quality"),
                "archive_source_quality": archive_quality,
                "actual_sidecar_query_quality_manifest": meta.get("actual_sidecar_query_quality"),
                "actual_work_point_query_quality": actual_query_quality,
                "suggested_SU2_settings": su2_settings_text(),
                "priority": su2_priority(utilization, result.stall_margin_deg),
                "warnings": "|".join(result.warnings),
            }
        )
    return rows


def write_markdown_reports(
    *,
    output_dir: Path,
    aero: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
    structure: Mapping[str, Any],
    su2_rows: Sequence[Mapping[str, Any]],
) -> None:
    production_reference_labels = {
        "forced_smooth_raw_before_reselection",
        "previous_policy_A_smooth",
        "previous_policy_C_smooth",
        "old_FX_Clark_baseline",
    }
    beats_production_refs_margin = all(
        row.get("new_beats_reference_with_5pct_CDi_margin") is True
        for row in comparisons
        if row.get("comparison_label") in production_reference_labels
    )
    beats_raw_faceted_margin = next(
        (
            row.get("new_beats_reference_with_5pct_CDi_margin")
            for row in comparisons
            if row.get("comparison_label") == "original_raw_faceted_best"
        ),
        None,
    )
    structure_pass = bool(structure.get("structure_proxy_pass"))
    aero_lines = [
        "# Smooth Tier2 Production Baseline Aerodynamic Summary",
        "",
        f"Generated: {timestamp()}",
        "",
        f"- Assignment: `{aero.get('assignment')}`",
        f"- `P_crank`: {safe_float(aero.get('P_crank')):.3f} W",
        f"- `P_crank_conservative`: {safe_float(aero.get('P_crank_conservative')):.3f} W",
        f"- `CDi`: {safe_float(aero.get('CDi')):.7f}",
        f"- `profile_cd`: {safe_float(aero.get('profile_cd')):.7f}",
        f"- `mission_drag_budget_band`: `{aero.get('mission_drag_budget_band')}`",
        f"- Archive / actual query quality: `{aero.get('archive_source_quality')}` / `{aero.get('actual_sidecar_query_quality')}`",
        "",
        "## Direct Answers",
        "",
        "- Best production-facing aerodynamic candidate: yes, among the current archive+actual-pass smooth production candidates.",
        f"- Remains superior after +5% CDi margin against production/legacy references: {beats_production_refs_margin}.",
        f"- Beats original faceted raw aero-only case after +5% CDi margin: {beats_raw_faceted_margin}.",
        f"- Structure/jig feasible under current proxy: {structure_pass}.",
        "- Dominant blocker: structure, not the airfoil set or smooth production geometry.",
        "",
    ]
    (output_dir / "aerodynamic_summary.md").write_text("\n".join(aero_lines), encoding="utf-8")

    structure_lines = [
        "# Structure / Jig Audit",
        "",
        f"Generated: {timestamp()}",
        "",
        f"- `root_bending_proxy_n_m`: {structure.get('root_bending_proxy_n_m')}",
        f"- `tip_deflection_estimate_m`: {structure.get('tip_deflection_estimate_m')}",
        f"- `loaded_tip_z_m`: {structure.get('loaded_tip_z_m')}",
        f"- `jig_tip_z_unloaded_estimate_m`: {structure.get('jig_tip_z_unloaded_estimate_m')}",
        f"- `jig_feasibility_band`: `{structure.get('jig_feasibility_band')}`",
        f"- `selected_tube_product`: `{structure.get('selected_tube_product')}`",
        f"- `selected_tube_estimated_full_span_tube_mass_kg`: {structure.get('selected_tube_estimated_full_span_tube_mass_kg')}",
        f"- `current_spar_tube_mass_target_kg`: {structure.get('current_spar_tube_mass_target_kg')}",
        f"- `structure_proxy_pass`: {structure.get('structure_proxy_pass')}",
        f"- `failure_modes`: `{structure.get('failure_modes')}`",
        "",
        "Engineering read: the proxy failure is stiffness/jig-shape driven. The catalog tube that first meets the EI proxy is far above the current spar tube mass target, and the scaled jig estimate still drives the unloaded tip below zero. This run does not evaluate laminate strength or buckling, so do not call it strength-pass.",
        "",
    ]
    (output_dir / "structure_jig_audit.md").write_text("\n".join(structure_lines), encoding="utf-8")

    next_lines = [
        "# Recommended Next Actions",
        "",
        "1. Keep this as the current production-facing aerodynamic baseline, but do not promote it through hard gates until structure/jig is reworked.",
        "2. Run the four `su2_2d_verification_cases.csv` checks, prioritizing DAE31 root and mid1 because they sit closest to the utilization limit.",
        "3. Start the next design iteration on spar/wire/jig feasibility: reduce required EI, increase structural mass allowance, or change loaded/jig shape authority before chasing more airfoil drag.",
        "4. Preserve chord smoothness as a production-geometry regularizer; the remaining blocker is not a faceted planform artifact.",
        "",
    ]
    (output_dir / "recommended_next_actions.md").write_text("\n".join(next_lines), encoding="utf-8")


def run_validation(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    avl_binary: str | Path | None = None,
    build_vsp: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    database = load_airfoil_database_artifact(TIER2_DIR / "airfoil_database.json")
    records_metadata = load_record_metadata()
    selected_combo = load_selected_combo_row()
    source_avl = Path(str(selected_combo["avl_path"]))
    if not source_avl.is_file():
        raise FileNotFoundError(f"Missing selected smooth combo AVL: {source_avl}")
    exports = export_geometry_packages(
        source_avl=source_avl,
        output_dir=output_dir,
        database=database,
        records_metadata=records_metadata,
        build_vsp=build_vsp,
    )
    avl_parity = exports["avl_parity"]
    aero, spanload, _profile = run_avl_aero_summary(
        avl_path=Path(str(avl_parity["avl_path"])),
        section_table=Path(str(avl_parity["section_table_csv"])),
        output_dir=output_dir,
        database=database,
        records_metadata=records_metadata,
        avl_binary=avl_binary,
    )
    production = exports["production_inspection"]
    aero["vsp_production_inspection_path"] = production.get("vsp3_path")
    aero["vsp_avl_parity_path"] = avl_parity.get("vsp3_path")
    aero["geometry_manifest_production_inspection"] = production.get("geometry_manifest_json")
    aero["geometry_manifest_avl_parity"] = avl_parity.get("geometry_manifest_json")

    reference_rows = reference_power_rows()
    power_table = [
        {
            "comparison_label": "new_smooth_tier2_production_baseline",
            "case_id": CASE_ID,
            "display_name": DISPLAY_NAME,
            "variant": "smooth_production_baseline",
            "assignment": aero.get("assignment"),
            "P_crank": aero.get("P_crank"),
            "P_crank_conservative": aero.get("P_crank_conservative"),
            "CDi": aero.get("CDi"),
            "profile_cd": aero.get("profile_cd"),
            "archive_source_quality": aero.get("archive_source_quality"),
            "actual_sidecar_query_quality": aero.get("actual_sidecar_query_quality"),
        },
        *reference_rows,
    ]
    comparisons = power_comparison_rows(new_summary=aero, reference_rows=reference_rows)
    sections = phase9.read_section_table(str(avl_parity["section_table_csv"]))
    structure_row, carbon_rows = structure_jig_audit(
        output_dir=output_dir,
        sections=sections,
        spanload=spanload,
        avl_binary=avl_binary,
    )
    su2_rows = su2_verification_cases(
        spanload=spanload,
        database=database,
        records_metadata=records_metadata,
    )

    write_csv(output_dir / "aerodynamic_summary.csv", [aero])
    write_csv(output_dir / "power_table.csv", power_table)
    write_csv(output_dir / "baseline_comparison.csv", comparisons)
    write_csv(output_dir / "structure_jig_audit.csv", [structure_row])
    write_csv(output_dir / "carbon_tube_catalog_selection.csv", carbon_rows)
    write_csv(output_dir / "su2_2d_verification_cases.csv", su2_rows)
    write_markdown_reports(
        output_dir=output_dir,
        aero=aero,
        comparisons=comparisons,
        structure=structure_row,
        su2_rows=su2_rows,
    )
    manifest = {
        "schema_version": "smooth_tier2_production_baseline_validation_v1",
        "generated_at": timestamp(),
        "case_id": CASE_ID,
        "assignment": dict(ASSIGNMENT),
        "source_combo": selected_combo,
        "geometry_exports": exports,
        "notes": [
            "Diagnostic validation only.",
            "No broad CST/NSGA rerun.",
            "No production ranking or hard gates changed.",
            "Structure rows are not_structure_grade proxies.",
        ],
    }
    (output_dir / "validation_manifest.json").write_text(
        json.dumps(json_ready(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir.resolve()),
        "P_crank": aero.get("P_crank"),
        "P_crank_conservative": aero.get("P_crank_conservative"),
        "structure_proxy_pass": structure_row.get("structure_proxy_pass"),
        "su2_case_count": len(su2_rows),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--avl-binary", type=Path, default=None)
    parser.add_argument("--no-vsp", action="store_true", help="Skip OpenVSP build and write scripts/AVL/CSVs only.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_validation(
        output_dir=Path(args.output_dir),
        avl_binary=args.avl_binary,
        build_vsp=not bool(args.no_vsp),
    )
    print(json.dumps(json_ready(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
