#!/usr/bin/env python3
"""Audit rear-spar stiffness and torsion/twist evidence for the current candidate."""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    CANDIDATE_ID,
    SELECTED_RUN,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase20_rear_spar_torsion_audit"
NOMINAL_LOCAL_RIB_BAY_M = 0.30


@dataclass(frozen=True)
class RearSparTorsionEntry:
    key: str
    title: str
    status: str
    value: float | None
    evidence: str
    missing_evidence: str
    allowed_claim: str
    blocked_claim: str


@dataclass(frozen=True)
class RearSparTorsionAudit:
    candidate_id: str
    overall_status: str
    rear_bending_stiffness_fraction_min: float
    rear_bending_stiffness_fraction_mean: float
    rear_bending_stiffness_fraction_max: float
    rear_torsion_tube_stiffness_fraction_min: float
    rear_torsion_tube_stiffness_fraction_mean: float
    rear_torsion_tube_stiffness_fraction_max: float
    max_spar_pair_line_angle_delta_deg: float
    equivalent_twist_max_deg: float | None
    max_effective_bay_m: float
    nominal_rib_bay_m: float
    entries: tuple[RearSparTorsionEntry, ...]


def tube_i_m4(outer_radius_m: float, wall_thickness_m: float) -> float:
    """Second moment of area for a hollow circular tube."""

    outer = float(outer_radius_m)
    inner = max(outer - float(wall_thickness_m), 0.0)
    if outer <= 0.0 or inner >= outer:
        raise ValueError("Tube radius and wall thickness must define a positive hollow section.")
    return float(math.pi / 4.0 * (outer**4 - inner**4))


def tube_j_m4(outer_radius_m: float, wall_thickness_m: float) -> float:
    """Polar second moment of area for a hollow circular tube."""

    outer = float(outer_radius_m)
    inner = max(outer - float(wall_thickness_m), 0.0)
    if outer <= 0.0 or inner >= outer:
        raise ValueError("Tube radius and wall thickness must define a positive hollow section.")
    return float(math.pi / 2.0 * (outer**4 - inner**4))


def spar_pair_line_angle_delta_deg(
    jig_rows: list[dict[str, str]],
    loaded_rows: list[dict[str, str]],
) -> list[float]:
    if len(jig_rows) != len(loaded_rows):
        raise ValueError("jig_rows and loaded_rows must have the same node count.")
    if not jig_rows:
        raise ValueError("At least one spar row is required.")

    jig_angles = [_spar_pair_angle_deg(row) for row in jig_rows]
    loaded_angles = [_spar_pair_angle_deg(row) for row in loaded_rows]
    root_delta = loaded_angles[0] - jig_angles[0]
    return [
        float((loaded_angle - jig_angle) - root_delta)
        for jig_angle, loaded_angle in zip(jig_angles, loaded_angles, strict=True)
    ]


def build_rear_spar_torsion_audit(
    candidate_id: str,
    *,
    jig_rows: list[dict[str, str]],
    loaded_rows: list[dict[str, str]],
    young_pa: float,
    shear_pa: float,
    nominal_rib_bay_m: float = NOMINAL_LOCAL_RIB_BAY_M,
    rear_young_pa: float | None = None,
    rear_shear_pa: float | None = None,
    equivalent_twist_max_deg: float | None = None,
) -> RearSparTorsionAudit:
    if len(jig_rows) < 2:
        raise ValueError("At least two jig rows are required.")

    main_ei, rear_ei, main_gj, rear_gj = _section_stiffness_arrays(
        jig_rows,
        main_young_pa=float(young_pa),
        rear_young_pa=float(young_pa if rear_young_pa is None else rear_young_pa),
        main_shear_pa=float(shear_pa),
        rear_shear_pa=float(shear_pa if rear_shear_pa is None else rear_shear_pa),
    )
    rear_bending_fraction = _fraction(rear_ei, _elementwise_sum(main_ei, rear_ei))
    rear_torsion_fraction = _fraction(rear_gj, _elementwise_sum(main_gj, rear_gj))
    angle_delta = spar_pair_line_angle_delta_deg(jig_rows, loaded_rows)
    max_angle_delta = max(abs(value) for value in angle_delta)
    mandatory_y = _mandatory_bracing_stations_m(jig_rows)
    max_bay = _max_spacing(mandatory_y)
    bay_status = (
        "mandatory_station_bay_exceeds_nominal_rib_bay"
        if max_bay > float(nominal_rib_bay_m) + 1.0e-12
        else "mandatory_station_bay_at_or_below_nominal_rib_bay"
    )

    entries = (
        RearSparTorsionEntry(
            key="rear_spar_stiffness",
            title="Rear spar stiffness",
            status="section_stiffness_present_global_role_unproven",
            value=float(_mean(rear_bending_fraction)),
            evidence=(
                "rear spar section stiffness exists; rear EI fraction "
                f"min/mean/max = {_min(rear_bending_fraction):.4f}/"
                f"{_mean(rear_bending_fraction):.4f}/{_max(rear_bending_fraction):.4f}."
            ),
            missing_evidence=(
                "global deflection, lateral deformation, and load-sharing benefit versus a rear-spar-off "
                "or finite-rib model is not proven"
            ),
            allowed_claim="Rear-spar tube EI is quantified from the candidate geometry.",
            blocked_claim="Do not claim the rear spar has proven global bracing or anti-torsion effectiveness.",
        ),
        RearSparTorsionEntry(
            key="rear_spar_torsion_tube_stiffness",
            title="Rear spar tube torsion stiffness",
            status="tube_gj_present_torque_route_unproven",
            value=float(_mean(rear_torsion_fraction)),
            evidence=(
                "Rear tube GJ fraction min/mean/max = "
                f"{_min(rear_torsion_fraction):.4f}/{_mean(rear_torsion_fraction):.4f}/"
                f"{_max(rear_torsion_fraction):.4f}; production torque is still owned as main-beam My."
            ),
            missing_evidence=(
                "a main/rear torque-couple route, finite-rib torsional stiffness, and closed aeroelastic "
                "twist response are not proven"
            ),
            allowed_claim="Rear-spar tube GJ is quantified from the candidate geometry.",
            blocked_claim="Do not claim rear spar torsion stiffness is participating in a validated torque path.",
        ),
        RearSparTorsionEntry(
            key="torsion_twist_coupling",
            title="Torsion / twist coupling",
            status="geometry_angle_observed_aeroelastic_loop_unproven",
            value=float(max_angle_delta),
            evidence=(
                "Jig-to-loaded main/rear spar-pair line-angle delta reaches "
                f"{max_angle_delta:.3f} deg; this is not aero twist."
            ),
            missing_evidence=(
                "aeroelastic twist loop is not closed; load redistribution from twist is still not a signoff loop"
            ),
            allowed_claim="Current jig-to-loaded spar-pair geometry angle delta is measurable.",
            blocked_claim="Do not claim torsional stiffness or aeroelastic twist coupling passes.",
        ),
        RearSparTorsionEntry(
            key="rib_spacing_assumption",
            title="Rib spacing assumption",
            status=bay_status,
            value=float(max_bay),
            evidence=(
                f"Mandatory bracing stations give max bay {max_bay:.3f} m versus "
                f"the {float(nominal_rib_bay_m):.2f} m nominal rib-bay local buckling assumption."
            ),
            missing_evidence=(
                "rib structural stations, rib stiffness, and spar attachment load transfer are not proven"
            ),
            allowed_claim="Mandatory-station spacing can be compared with the local-buckling bay assumption.",
            blocked_claim="Do not use the 0.30 m rib-bay local wall result unless physical bracing supports it.",
        ),
    )

    return RearSparTorsionAudit(
        candidate_id=candidate_id,
        overall_status="rear_spar_and_torsion_not_signoff",
        rear_bending_stiffness_fraction_min=float(_min(rear_bending_fraction)),
        rear_bending_stiffness_fraction_mean=float(_mean(rear_bending_fraction)),
        rear_bending_stiffness_fraction_max=float(_max(rear_bending_fraction)),
        rear_torsion_tube_stiffness_fraction_min=float(_min(rear_torsion_fraction)),
        rear_torsion_tube_stiffness_fraction_mean=float(_mean(rear_torsion_fraction)),
        rear_torsion_tube_stiffness_fraction_max=float(_max(rear_torsion_fraction)),
        max_spar_pair_line_angle_delta_deg=float(max_angle_delta),
        equivalent_twist_max_deg=(
            None if equivalent_twist_max_deg is None else float(equivalent_twist_max_deg)
        ),
        max_effective_bay_m=float(max_bay),
        nominal_rib_bay_m=float(nominal_rib_bay_m),
        entries=entries,
    )


def write_rear_spar_torsion_audit_package(
    out_dir: Path,
    candidate_id: str,
    *,
    jig_rows: list[dict[str, str]],
    loaded_rows: list[dict[str, str]],
    young_pa: float,
    shear_pa: float,
    nominal_rib_bay_m: float = NOMINAL_LOCAL_RIB_BAY_M,
    rear_young_pa: float | None = None,
    rear_shear_pa: float | None = None,
    equivalent_twist_max_deg: float | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = build_rear_spar_torsion_audit(
        candidate_id,
        jig_rows=jig_rows,
        loaded_rows=loaded_rows,
        young_pa=young_pa,
        shear_pa=shear_pa,
        nominal_rib_bay_m=nominal_rib_bay_m,
        rear_young_pa=rear_young_pa,
        rear_shear_pa=rear_shear_pa,
        equivalent_twist_max_deg=equivalent_twist_max_deg,
    )
    outputs = [
        _write_csv(out_dir / "rear_spar_torsion_audit.csv", audit),
        _write_json(out_dir / "rear_spar_torsion_audit.json", audit),
        _write_markdown(out_dir / "rear_spar_torsion_audit.md", audit),
    ]
    return outputs


def load_current_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return (
        _read_csv_rows(SELECTED_RUN / "jig_shape_spar_data.csv"),
        _read_csv_rows(SELECTED_RUN / "loaded_shape_spar_data.csv"),
    )


def load_current_summary() -> dict[str, object]:
    return json.loads(
        (SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json").read_text(
            encoding="utf-8"
        )
    )


def load_current_material_stiffness() -> tuple[float, float, float, float]:
    summary = load_current_summary()
    cfg = load_config(summary["config"])
    materials = MaterialDB()
    main = materials.get(cfg.main_spar.material)
    rear = materials.get(cfg.rear_spar.material)
    return float(main.E), float(main.G), float(rear.E), float(rear.G)


def load_current_equivalent_twist_max_deg() -> float | None:
    summary = load_current_summary()
    iterations = summary.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return None
    selected = iterations[0].get("selected") if isinstance(iterations[0], dict) else None
    if not isinstance(selected, dict) or selected.get("equivalent_twist_max_deg") is None:
        return None
    return float(selected["equivalent_twist_max_deg"])


def _section_stiffness_arrays(
    rows: list[dict[str, str]],
    *,
    main_young_pa: float,
    rear_young_pa: float,
    main_shear_pa: float,
    rear_shear_pa: float,
) -> tuple[list[float], list[float], list[float], list[float]]:
    main_i = [
        tube_i_m4(float(row["Main_Outer_Radius_m"]), float(row["Main_Wall_Thickness_m"]))
        for row in rows
    ]
    rear_i = [
        tube_i_m4(float(row["Rear_Outer_Radius_m"]), float(row["Rear_Wall_Thickness_m"]))
        for row in rows
    ]
    main_j = [
        tube_j_m4(float(row["Main_Outer_Radius_m"]), float(row["Main_Wall_Thickness_m"]))
        for row in rows
    ]
    rear_j = [
        tube_j_m4(float(row["Rear_Outer_Radius_m"]), float(row["Rear_Wall_Thickness_m"]))
        for row in rows
    ]
    return (
        [float(main_young_pa) * value for value in main_i],
        [float(rear_young_pa) * value for value in rear_i],
        [float(main_shear_pa) * value for value in main_j],
        [float(rear_shear_pa) * value for value in rear_j],
    )


def _spar_pair_angle_deg(row: dict[str, str]) -> float:
    dx = float(row["Rear_X_m"]) - float(row["Main_X_m"])
    dz = float(row["Rear_Z_m"]) - float(row["Main_Z_m"])
    return float(math.degrees(math.atan2(dz, dx)))


def _mandatory_bracing_stations_m(rows: list[dict[str, str]]) -> tuple[float, ...]:
    stations = {float(rows[0]["Y_Position_m"]), float(rows[-1]["Y_Position_m"])}
    for row in rows:
        if int(float(row.get("Is_Joint", "0"))) or int(float(row.get("Is_Wire_Attach", "0"))):
            stations.add(float(row["Y_Position_m"]))
    return tuple(sorted(stations))


def _max_spacing(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    return max(values[idx + 1] - values[idx] for idx in range(len(values) - 1))


def _fraction(numerators: list[float], denominators: list[float]) -> list[float]:
    return [
        float(numerator) / max(float(denominator), 1.0e-30)
        for numerator, denominator in zip(numerators, denominators, strict=True)
    ]


def _elementwise_sum(left: list[float], right: list[float]) -> list[float]:
    return [
        float(left_value) + float(right_value)
        for left_value, right_value in zip(left, right, strict=True)
    ]


def _min(values: list[float]) -> float:
    return float(min(values))


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values))


def _max(values: list[float]) -> float:
    return float(max(values))


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, audit: RearSparTorsionAudit) -> Path:
    fields = [
        "key",
        "title",
        "status",
        "value",
        "evidence",
        "missing_evidence",
        "allowed_claim",
        "blocked_claim",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for entry in audit.entries:
            writer.writerow(asdict(entry))
    return path


def _write_json(path: Path, audit: RearSparTorsionAudit) -> Path:
    path.write_text(json.dumps(asdict(audit), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, audit: RearSparTorsionAudit) -> Path:
    lines = [
        "# Rear Spar Torsion Audit",
        "",
        f"Candidate: `{audit.candidate_id}`",
        f"Overall status: `{audit.overall_status}`",
        "",
        "## Engineering Boundary",
        "",
        "- This audit quantifies rear-spar tube EI/GJ and spar-pair geometry angle from existing artifacts.",
        "- It does not prove finite-rib bracing, aeroelastic twist coupling, or full-wing buckling.",
        "- Rear-spar and torsion claims remain blocked until a global bracing/joint FEM closes them.",
        "",
        "## Summary",
        "",
        "- rear EI fraction min/mean/max: "
        f"`{audit.rear_bending_stiffness_fraction_min:.4f}` / "
        f"`{audit.rear_bending_stiffness_fraction_mean:.4f}` / "
        f"`{audit.rear_bending_stiffness_fraction_max:.4f}`",
        "- rear tube GJ fraction min/mean/max: "
        f"`{audit.rear_torsion_tube_stiffness_fraction_min:.4f}` / "
        f"`{audit.rear_torsion_tube_stiffness_fraction_mean:.4f}` / "
        f"`{audit.rear_torsion_tube_stiffness_fraction_max:.4f}`",
        "- equivalent-beam twist estimate: "
        f"`{_fmt(audit.equivalent_twist_max_deg)} deg`",
        "- max jig-to-loaded spar-pair line-angle delta: "
        f"`{audit.max_spar_pair_line_angle_delta_deg:.3f} deg` (not aero twist)",
        f"- max effective mandatory-station bay: `{audit.max_effective_bay_m:.3f} m`",
        f"- nominal local-wall rib-bay assumption: `{audit.nominal_rib_bay_m:.2f} m`",
        "",
        "## Ledger",
        "",
        "| item | status | value | missing evidence |",
        "|---|---|---:|---|",
    ]
    for entry in audit.entries:
        lines.append(
            f"| {entry.title} | `{entry.status}` | {_fmt(entry.value)} | {entry.missing_evidence} |"
        )
    lines.extend(
        [
            "",
            "## Readout",
            "",
            "- rear spar: rear spar section stiffness exists, but global bracing contribution is not proven.",
            "- torsion: aeroelastic twist loop is not closed by this report; spar-pair line angle is not aero twist.",
            "- ribs: the 0.30 m nominal rib-bay local-wall assumption needs physical bracing evidence.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--nominal-rib-bay-m", type=float, default=NOMINAL_LOCAL_RIB_BAY_M)
    args = parser.parse_args(argv)

    jig_rows, loaded_rows = load_current_rows()
    main_e, main_g, rear_e, rear_g = load_current_material_stiffness()
    equivalent_twist_max_deg = load_current_equivalent_twist_max_deg()
    outputs = write_rear_spar_torsion_audit_package(
        args.output_dir,
        CANDIDATE_ID,
        jig_rows=jig_rows,
        loaded_rows=loaded_rows,
        young_pa=main_e,
        shear_pa=main_g,
        nominal_rib_bay_m=args.nominal_rib_bay_m,
        rear_young_pa=rear_e,
        rear_shear_pa=rear_g,
        equivalent_twist_max_deg=equivalent_twist_max_deg,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
