#!/usr/bin/env python3
"""Generate braced-subassembly CalculiX evidence decks without promoting signoff."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.hifi.frd_parser import parse_buckle_eigenvalues  # noqa: E402
from hpa_mdo.structure.calculix_beam_export import (  # noqa: E402
    BeamMaterial,
    build_dual_pipe_benchmark_spec,
    write_calculix_beam_inp,
)
from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase16_ccx_buckling_wire6_ramp import discover_ccx  # noqa: E402
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_current_candidate_model,
)
from scripts.phase30_full_wing_buckling_closure_inputs import (  # noqa: E402
    ACCEPTED_MODEL_SCOPES,
    build_full_wing_buckling_closure_check,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase41_braced_subassembly_fem_evidence"
DEFAULT_CLAIM_LOAD_FACTORS = (1.50, 1.75)
DEFAULT_BUCKLE_MODES = 5
REFERENCE_LOAD_REVIEW_MULTIPLIER_THRESHOLD = 50.0
MODEL_SCOPE = "braced_subassembly_eigen"
ENGINEERING_BOUNDARY = (
    "Generated dual-spar B32R braced-subassembly eigen decks are route evidence, "
    "not a full-wing pass claim. They still need solver success, mesh/refinement "
    "evidence, mode review, correlation, and separate rib/joint/hardware margins."
)


@dataclass(frozen=True)
class BracedSubassemblyFemEvidenceRow:
    case_id: str
    model_scope: str
    status: str
    claim_load_factor: float
    deck_path: str
    dat_path: str
    frd_path: str
    log_path: str
    ccx_path: str
    returncode: int | None
    first_eigen_multiplier: float | None
    inferred_first_buckling_load_factor: float | None
    eigenvalue_count: int
    reference_load_status: str
    joint_link_mode: str
    link_node_count: int
    wire_support_count: int
    includes_main_spar: bool
    includes_rear_spar: bool
    includes_finite_ribs: bool
    includes_wire_attach_load_path: bool
    includes_root_boundary: bool
    missing_components: str
    boundary_condition_status: str
    mesh_convergence_status: str
    solver_status: str
    mode_review_status: str
    phase30_closure_status: str
    engineering_note: str
    next_action: str


@dataclass(frozen=True)
class BracedSubassemblyFemEvidence:
    candidate_id: str
    overall_status: str
    case_count: int
    solver_ran_count: int
    mode_reviewed_count: int
    claim_load_factor_coverage: str
    engineering_boundary: str
    rows: tuple[BracedSubassemblyFemEvidenceRow, ...]


def write_braced_subassembly_fem_evidence_package(
    out_dir: Path,
    candidate_id: str,
    model: Any,
    *,
    claim_load_factors: tuple[float, ...] = DEFAULT_CLAIM_LOAD_FACTORS,
    run_solver: bool = True,
    solver_results: dict[str, dict[str, Any]] | None = None,
    n_buckle_modes: int = DEFAULT_BUCKLE_MODES,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_braced_subassembly_fem_evidence(
        candidate_id,
        model,
        out_dir=out_dir,
        claim_load_factors=claim_load_factors,
        run_solver=run_solver,
        solver_results=solver_results,
        n_buckle_modes=n_buckle_modes,
    )
    deck_paths = [Path(row.deck_path) for row in evidence.rows]
    report_paths = [
        _write_csv(out_dir / "braced_subassembly_fem_evidence.csv", evidence),
        _write_json(out_dir / "braced_subassembly_fem_evidence.json", evidence),
        _write_markdown(out_dir / "braced_subassembly_fem_evidence.md", evidence),
        _write_phase30_inputs_csv(
            out_dir / "phase30_closure_inputs_from_phase41.csv",
            evidence,
        ),
    ]
    return [*deck_paths, *report_paths]


def build_braced_subassembly_fem_evidence(
    candidate_id: str,
    model: Any,
    *,
    out_dir: Path,
    claim_load_factors: tuple[float, ...] = DEFAULT_CLAIM_LOAD_FACTORS,
    run_solver: bool = True,
    solver_results: dict[str, dict[str, Any]] | None = None,
    n_buckle_modes: int = DEFAULT_BUCKLE_MODES,
) -> BracedSubassemblyFemEvidence:
    rows = tuple(
        _build_case_row(
            candidate_id=candidate_id,
            model=model,
            out_dir=out_dir,
            claim_load_factor=float(claim_load_factor),
            run_solver=run_solver,
            solver_results=solver_results or {},
            n_buckle_modes=n_buckle_modes,
        )
        for claim_load_factor in claim_load_factors
    )
    solver_ran_count = sum(1 for row in rows if row.solver_status == "pass")
    mode_reviewed_count = sum(1 for row in rows if row.mode_review_status == "pass")
    return BracedSubassemblyFemEvidence(
        candidate_id=str(candidate_id),
        overall_status=_overall_status(rows),
        case_count=len(rows),
        solver_ran_count=solver_ran_count,
        mode_reviewed_count=mode_reviewed_count,
        claim_load_factor_coverage=";".join(
            f"{float(value):.2f}" for value in claim_load_factors
        ),
        engineering_boundary=ENGINEERING_BOUNDARY,
        rows=rows,
    )


def build_current_braced_subassembly_fem_evidence(
    *,
    out_dir: Path = DEFAULT_OUTPUT_DIR,
    run_solver: bool = False,
) -> BracedSubassemblyFemEvidence:
    return build_braced_subassembly_fem_evidence(
        CANDIDATE_ID,
        build_current_candidate_model(),
        out_dir=out_dir,
        run_solver=run_solver,
    )


def load_current_braced_subassembly_fem_evidence(
    *,
    out_dir: Path = DEFAULT_OUTPUT_DIR,
) -> BracedSubassemblyFemEvidence:
    evidence_path = out_dir / "braced_subassembly_fem_evidence.json"
    if evidence_path.exists():
        return read_braced_subassembly_fem_evidence_json(evidence_path)
    return build_current_braced_subassembly_fem_evidence(out_dir=out_dir, run_solver=False)


def read_braced_subassembly_fem_evidence_json(
    path: Path,
) -> BracedSubassemblyFemEvidence:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = tuple(BracedSubassemblyFemEvidenceRow(**row) for row in raw["rows"])
    return BracedSubassemblyFemEvidence(
        candidate_id=str(raw["candidate_id"]),
        overall_status=str(raw["overall_status"]),
        case_count=int(raw["case_count"]),
        solver_ran_count=int(raw["solver_ran_count"]),
        mode_reviewed_count=int(raw["mode_reviewed_count"]),
        claim_load_factor_coverage=str(raw["claim_load_factor_coverage"]),
        engineering_boundary=str(raw["engineering_boundary"]),
        rows=rows,
    )


def phase30_closure_inputs_from_evidence(
    evidence: BracedSubassemblyFemEvidence,
) -> list[dict[str, Any]]:
    return [_phase30_input_row(row) for row in evidence.rows]


def _build_case_row(
    *,
    candidate_id: str,
    model: Any,
    out_dir: Path,
    claim_load_factor: float,
    run_solver: bool,
    solver_results: dict[str, dict[str, Any]],
    n_buckle_modes: int,
) -> BracedSubassemblyFemEvidenceRow:
    case_id = f"braced_subassembly_{_load_factor_slug(claim_load_factor)}g_buckle"
    spec = _build_case_spec(case_id, model, claim_load_factor)
    deck = write_calculix_beam_inp(
        spec,
        out_dir / f"{case_id}.inp",
        analysis_kind="buckle",
        n_buckle_modes=n_buckle_modes,
    )
    solver_result = solver_results.get(case_id)
    if solver_result is None and run_solver:
        solver_result = run_ccx_buckle_case(deck.inp_path)
    row_data = _solver_row_data(
        claim_load_factor=claim_load_factor,
        deck_path=deck.inp_path,
        solver_result=solver_result,
    )
    row_without_status = {
        "case_id": case_id,
        "model_scope": MODEL_SCOPE,
        "status": row_data["status"],
        "claim_load_factor": claim_load_factor,
        "deck_path": str(deck.inp_path),
        "dat_path": row_data["dat_path"],
        "frd_path": row_data["frd_path"],
        "log_path": row_data["log_path"],
        "ccx_path": row_data["ccx_path"],
        "returncode": row_data["returncode"],
        "first_eigen_multiplier": row_data["first_eigen_multiplier"],
        "inferred_first_buckling_load_factor": row_data[
            "inferred_first_buckling_load_factor"
        ],
        "eigenvalue_count": row_data["eigenvalue_count"],
        "reference_load_status": row_data["reference_load_status"],
        "joint_link_mode": "offset_rigid",
        "link_node_count": len(spec.joint_node_indices),
        "wire_support_count": len(spec.wire_node_indices),
        "includes_main_spar": True,
        "includes_rear_spar": True,
        "includes_finite_ribs": bool(spec.joint_node_indices),
        "includes_wire_attach_load_path": bool(spec.wire_node_indices),
        "includes_root_boundary": True,
        "missing_components": "",
        "boundary_condition_status": "generated_unreviewed",
        "mesh_convergence_status": "single_mesh_not_converged",
        "solver_status": row_data["solver_status"],
        "mode_review_status": "unreviewed",
        "phase30_closure_status": "",
        "engineering_note": (
            "B32R dual-spar deck contains main/rear spars, offset-rigid rib links, "
            "root clamps, and idealized wire vertical supports. It is not rib shell, "
            "attach-ring, bonded insert, or full-aircraft signoff."
        )
        + _reference_load_note(row_data["reference_load_status"]),
        "next_action": (
            "Run/inspect the eigen solve, review the first mode, repeat with mesh/link "
            "sensitivity, and only then promote a qualified row into Phase30 closure inputs."
        ),
    }
    row_without_status["missing_components"] = _missing_components(row_without_status)
    row_without_status["phase30_closure_status"] = _phase30_closure_status(
        candidate_id,
        row_without_status,
    )
    return BracedSubassemblyFemEvidenceRow(**row_without_status)


def _build_case_spec(case_id: str, model: Any, claim_load_factor: float) -> Any:
    lift = np.asarray(model.lift_per_span_npm, dtype=float)
    torque = np.asarray(model.torque_per_span_nmpm, dtype=float)
    spacing = np.asarray(model.node_spacings_m, dtype=float)
    zeros = np.zeros_like(lift)
    return build_dual_pipe_benchmark_spec(
        name=case_id,
        y_nodes_m=np.asarray(model.y_nodes_m, dtype=float),
        main_x_m=np.asarray(model.nodes_main_m, dtype=float)[:, 0],
        rear_x_m=np.asarray(model.nodes_rear_m, dtype=float)[:, 0],
        main_z_m=np.asarray(model.nodes_main_m, dtype=float)[:, 2],
        rear_z_m=np.asarray(model.nodes_rear_m, dtype=float)[:, 2],
        main_outer_radius_m=np.asarray(model.main_r_seg_m, dtype=float),
        main_thickness_m=np.asarray(model.main_t_seg_m, dtype=float),
        rear_outer_radius_m=np.asarray(model.rear_r_seg_m, dtype=float),
        rear_thickness_m=np.asarray(model.rear_t_seg_m, dtype=float),
        material_main=_material_from_model(
            "MAIN_SPAR",
            young_pa=model.main_young_pa,
            shear_pa=model.main_shear_pa,
            density_kgpm3=model.main_density_kgpm3,
        ),
        material_rear=_material_from_model(
            "REAR_SPAR",
            young_pa=model.rear_young_pa,
            shear_pa=model.rear_shear_pa,
            density_kgpm3=model.rear_density_kgpm3,
        ),
        main_nodal_fz_n=lift * spacing * float(claim_load_factor),
        rear_nodal_fz_n=zeros,
        main_nodal_my_nm=torque * spacing * float(claim_load_factor),
        rear_nodal_my_nm=zeros,
        joint_node_indices=_braced_link_nodes(model),
        wire_node_indices=tuple(int(idx) for idx in model.wire_node_indices),
        joint_link_mode="offset_rigid",
    )


def _material_from_model(
    name: str,
    *,
    young_pa: Any,
    shear_pa: Any,
    density_kgpm3: Any,
) -> BeamMaterial:
    young = _mean_float(young_pa)
    shear = _mean_float(shear_pa)
    poisson = young / (2.0 * shear) - 1.0 if shear > 0.0 else 0.30
    if not np.isfinite(poisson) or poisson <= 0.0 or poisson >= 0.49:
        poisson = 0.30
    return BeamMaterial(
        name=name,
        young_pa=young,
        poisson_ratio=float(poisson),
        density_kgpm3=_mean_float(density_kgpm3),
    )


def _braced_link_nodes(model: Any) -> tuple[int, ...]:
    link_nodes = {
        int(idx)
        for idx in (
            *tuple(getattr(model, "joint_node_indices", ())),
            *tuple(getattr(model, "dense_link_node_indices", ())),
            *tuple(getattr(model, "wire_node_indices", ())),
        )
        if 0 < int(idx) < len(model.y_nodes_m) - 1
    }
    return tuple(sorted(link_nodes))


def run_ccx_buckle_case(
    deck_path: Path,
    *,
    ccx_path: str | None = None,
    timeout_s: int = 300,
) -> dict[str, Any]:
    resolved_ccx = ccx_path or discover_ccx()
    if resolved_ccx is None:
        return {
            "status": "SKIP",
            "returncode": None,
            "lambda_1": None,
            "eigenvalues": (),
            "dat_path": "",
            "frd_path": "",
            "log_path": "",
            "ccx_path": "",
            "message": "No local CalculiX executable was found.",
        }
    try:
        completed = subprocess.run(
            [resolved_ccx, deck_path.stem],
            cwd=deck_path.parent,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        returncode = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_path = deck_path.with_suffix(".log")
        log_path.write_text(str(exc), encoding="utf-8")
        return {
            "status": "FAIL",
            "returncode": None,
            "lambda_1": None,
            "eigenvalues": (),
            "dat_path": "",
            "frd_path": "",
            "log_path": str(log_path),
            "ccx_path": resolved_ccx,
            "message": f"CalculiX could not run: {exc}",
        }
    log_path = deck_path.with_suffix(".log")
    log_path.write_text(
        "\n".join(
            [
                "===== ccx stdout =====",
                stdout.rstrip(),
                "",
                "===== ccx stderr =====",
                stderr.rstrip(),
                "",
            ]
        ),
        encoding="utf-8",
    )
    dat_path = deck_path.with_suffix(".dat")
    frd_path = deck_path.with_suffix(".frd")
    eigenvalues = tuple(parse_buckle_eigenvalues(dat_path)) if dat_path.exists() else ()
    lambda_1 = float(eigenvalues[0]) if eigenvalues else None
    status = (
        "PASS_WITHOUT_REFERENCE"
        if returncode == 0 and lambda_1 is not None
        else "FAIL"
    )
    return {
        "status": status,
        "returncode": returncode,
        "lambda_1": lambda_1,
        "eigenvalues": eigenvalues,
        "dat_path": str(dat_path) if dat_path.exists() else "",
        "frd_path": str(frd_path) if frd_path.exists() else "",
        "log_path": str(log_path),
        "ccx_path": resolved_ccx,
        "message": (
            "CalculiX BUCKLE returned eigenvalues."
            if status == "PASS_WITHOUT_REFERENCE"
            else "CalculiX did not return a parseable eigen-buckling result."
        ),
    }


def _solver_row_data(
    *,
    claim_load_factor: float,
    deck_path: Path,
    solver_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if solver_result is None:
        return {
            "status": "deck_generated_solver_not_run",
            "solver_status": "not_run",
            "returncode": None,
            "first_eigen_multiplier": None,
            "inferred_first_buckling_load_factor": None,
            "eigenvalue_count": 0,
            "reference_load_status": "not_run",
            "dat_path": "",
            "frd_path": "",
            "log_path": "",
            "ccx_path": "",
        }
    eigenvalues = tuple(float(value) for value in solver_result.get("eigenvalues", ()))
    lambda_1 = _optional_float(solver_result.get("lambda_1"))
    if lambda_1 is None and eigenvalues:
        lambda_1 = float(eigenvalues[0])
    solver_status = (
        "pass"
        if str(solver_result.get("status", "")).startswith("PASS")
        and lambda_1 is not None
        else "fail"
    )
    reference_load_status = _reference_load_status(lambda_1)
    return {
        "status": _solver_status_label(
            solver_status=solver_status,
            reference_load_status=reference_load_status,
        ),
        "solver_status": solver_status,
        "returncode": (
            int(solver_result["returncode"])
            if solver_result.get("returncode") is not None
            else None
        ),
        "first_eigen_multiplier": lambda_1,
        "inferred_first_buckling_load_factor": (
            float(claim_load_factor) * lambda_1 if lambda_1 is not None else None
        ),
        "eigenvalue_count": len(eigenvalues),
        "reference_load_status": reference_load_status,
        "dat_path": str(solver_result.get("dat_path", "")),
        "frd_path": str(solver_result.get("frd_path", "")),
        "log_path": str(solver_result.get("log_path", "")),
        "ccx_path": str(solver_result.get("ccx_path", "")),
    }


def _phase30_closure_status(candidate_id: str, row: dict[str, Any]) -> str:
    check = build_full_wing_buckling_closure_check(
        candidate_id,
        closure_inputs=[_phase30_input_row(row)],
    )
    return str(check.rows[0].status)


def _phase30_input_row(row: BracedSubassemblyFemEvidenceRow | dict[str, Any]) -> dict[str, Any]:
    source = row["deck_path"] if isinstance(row, dict) else row.deck_path
    return {
        "case_id": _row_value(row, "case_id"),
        "model_scope": _row_value(row, "model_scope"),
        "accepted_model_scopes": ";".join(ACCEPTED_MODEL_SCOPES),
        "claim_load_factor": _row_value(row, "claim_load_factor"),
        "first_global_buckling_load_factor": _row_value(
            row,
            "inferred_first_buckling_load_factor",
        )
        or "",
        "includes_main_spar": _row_value(row, "includes_main_spar"),
        "includes_rear_spar": _row_value(row, "includes_rear_spar"),
        "includes_finite_ribs": _row_value(row, "includes_finite_ribs"),
        "includes_wire_attach_load_path": _row_value(
            row,
            "includes_wire_attach_load_path",
        ),
        "includes_root_boundary": _row_value(row, "includes_root_boundary"),
        "boundary_condition_status": _row_value(row, "boundary_condition_status"),
        "mesh_convergence_status": _row_value(row, "mesh_convergence_status"),
        "solver_status": _row_value(row, "solver_status"),
        "mode_review_status": _row_value(row, "mode_review_status"),
        "source": source,
        "notes": _row_value(row, "engineering_note"),
    }


def _missing_components(row: dict[str, Any]) -> str:
    components = (
        ("main_spar", "includes_main_spar"),
        ("rear_spar", "includes_rear_spar"),
        ("finite_ribs", "includes_finite_ribs"),
        ("wire_attach_load_path", "includes_wire_attach_load_path"),
        ("root_boundary", "includes_root_boundary"),
    )
    return ";".join(name for name, key in components if not bool(row[key]))


def _overall_status(rows: tuple[BracedSubassemblyFemEvidenceRow, ...]) -> str:
    if any(row.solver_status == "fail" for row in rows):
        return "braced_subassembly_solver_failed_not_signoff"
    if any(row.status == "solver_ran_reference_load_review_required" for row in rows):
        return "braced_subassembly_reference_load_review_required"
    if any(row.solver_status == "pass" for row in rows):
        return "braced_subassembly_solver_ran_mode_review_required"
    return "braced_subassembly_route_generated_not_signoff"


def _reference_load_status(lambda_1: float | None) -> str:
    if lambda_1 is None:
        return "not_available"
    if float(lambda_1) > REFERENCE_LOAD_REVIEW_MULTIPLIER_THRESHOLD:
        return "unphysical_or_load_sign_review_required"
    return "screening_range"


def _solver_status_label(*, solver_status: str, reference_load_status: str) -> str:
    if solver_status != "pass":
        return "solver_failed_not_signoff"
    if reference_load_status == "unphysical_or_load_sign_review_required":
        return "solver_ran_reference_load_review_required"
    return "solver_ran_mode_review_required"


def _reference_load_note(reference_load_status: str) -> str:
    if reference_load_status != "unphysical_or_load_sign_review_required":
        return ""
    return (
        " The very large eigen multiplier is a reference load/sign convention "
        "review trigger, not usable buckling margin."
    )


def _write_csv(path: Path, evidence: BracedSubassemblyFemEvidence) -> Path:
    fields = list(asdict(evidence.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in evidence.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, evidence: BracedSubassemblyFemEvidence) -> Path:
    path.write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_phase30_inputs_csv(
    path: Path,
    evidence: BracedSubassemblyFemEvidence,
) -> Path:
    fields = [
        "case_id",
        "model_scope",
        "accepted_model_scopes",
        "claim_load_factor",
        "first_global_buckling_load_factor",
        "includes_main_spar",
        "includes_rear_spar",
        "includes_finite_ribs",
        "includes_wire_attach_load_path",
        "includes_root_boundary",
        "boundary_condition_status",
        "mesh_convergence_status",
        "solver_status",
        "mode_review_status",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in evidence.rows:
            writer.writerow(_phase30_input_row(row))
    return path


def _write_markdown(path: Path, evidence: BracedSubassemblyFemEvidence) -> Path:
    lines = [
        "# Braced Subassembly FEM Evidence",
        "",
        f"Candidate: `{evidence.candidate_id}`",
        f"Overall status: `{evidence.overall_status}`",
        "",
        evidence.engineering_boundary,
        "",
        f"- cases: `{evidence.case_count}`",
        f"- solver ran: `{evidence.solver_ran_count}`",
        f"- mode reviewed: `{evidence.mode_reviewed_count}`",
        f"- claim load factor coverage: `{evidence.claim_load_factor_coverage}`",
        "",
        "| case | status | claim n | lambda 1 | inferred buckling n | solver | mode review | Phase30 status |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in evidence.rows:
        lines.append(
            f"| {row.case_id} | `{row.status}` | {_fmt(row.claim_load_factor)} | "
            f"{_fmt(row.first_eigen_multiplier)} | "
            f"{_fmt(row.inferred_first_buckling_load_factor)} | "
            f"{row.solver_status} | {row.mode_review_status} | "
            f"`{row.phase30_closure_status}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- The deck idealizes ribs as offset-rigid beam links; it is not rib shear/cap/bond validation.",
            "- The wire load path is an idealized vertical support at attach stations; it is not attach-ring or insert stress validation.",
            "- Boundary conditions, mesh/refinement, and the first buckling mode need engineering review before a global pass claim.",
            "- Positive eigenvalues here would rank a candidate global mode, not certify the real structure by themselves.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _row_value(row: BracedSubassemblyFemEvidenceRow | dict[str, Any], key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    return getattr(row, key)


def _load_factor_slug(value: float) -> str:
    return f"{float(value):.2f}".replace(".", "p")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _mean_float(value: Any) -> float:
    return float(np.asarray(value, dtype=float).reshape(-1).mean())


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-solver", action="store_true")
    args = parser.parse_args(argv)

    model = build_current_candidate_model()
    outputs = write_braced_subassembly_fem_evidence_package(
        args.output_dir,
        CANDIDATE_ID,
        model,
        run_solver=not args.skip_solver,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
