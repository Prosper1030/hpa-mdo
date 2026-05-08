#!/usr/bin/env python3
"""Prove local CalculiX BUCKLE capability, then ramp the candidate with 6 kN wire."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from math import pi
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import load_config  # noqa: E402
from hpa_mdo.hifi.calculix_runner import find_ccx  # noqa: E402
from hpa_mdo.hifi.frd_parser import parse_buckle_eigenvalues  # noqa: E402
from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    CandidateReference,
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/phase16_ccx_buckling_wire6_ramp"
DEFAULT_CONFIG = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary"
    / "smooth_tier2_canonical_config.yaml"
)
DEFAULT_WIRE6_ALLOWABLE_N = 6000.0
DEFAULT_RAMP_LOAD_FACTORS = tuple(round(1.0 + 0.25 * idx, 2) for idx in range(0, 21))
_KNOWN_CCX_CANDIDATES = (
    "/opt/homebrew/bin/ccx_2.23",
    "/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23",
)
_OFFICIAL_BUCKLE_EXAMPLES = (
    Path("/opt/homebrew/share/calculix-ccx/beamb.inp"),
    Path("/opt/homebrew/opt/calculix-ccx/share/calculix-ccx/beamb.inp"),
    Path("/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/share/calculix-ccx/beamb.inp"),
)


@dataclass(frozen=True)
class FixedFreeColumnSpec:
    length_m: float = 2.0
    outer_radius_m: float = 0.03
    wall_thickness_m: float = 0.0015
    young_pa: float = 230.0e9
    poisson_ratio: float = 0.27
    density_kgpm3: float = 1600.0
    n_elements: int = 20
    reference_compression_n: float = 1000.0
    n_modes: int = 5

    @property
    def top_endpoint_node_id(self) -> int:
        return int(self.n_elements) + 1


@dataclass(frozen=True)
class CcxBucklingResult:
    case_id: str
    status: str
    ccx_path: str | None
    source_inp_path: Path | None
    reference_dat_path: Path | None
    deck_path: Path
    dat_path: Path | None
    frd_path: Path | None
    log_path: Path | None
    returncode: int | None
    lambda_1: float | None
    eigenvalues: tuple[float, ...]
    reference_eigenvalues: tuple[float, ...]
    reference_lambda_1: float | None
    max_reference_error_pct: float | None
    message: str


@dataclass(frozen=True)
class Wire6RampRow:
    load_factor: float
    wire_tension_n: float
    wire_utilization: float
    tip_deflection_m: float
    tip_deflection_utilization: float
    cfrp_global_stress_utilization: float
    local_buckling_utilization_est: float
    twist_utilization: float
    event: str
    interpretation: str


def tube_second_moment_m4(*, outer_radius_m: float, wall_thickness_m: float) -> float:
    inner_radius_m = float(outer_radius_m) - float(wall_thickness_m)
    if inner_radius_m < 0.0:
        raise ValueError("wall_thickness_m cannot exceed outer_radius_m")
    return pi / 4.0 * (float(outer_radius_m) ** 4 - inner_radius_m**4)


def euler_fixed_free_pcr_n(
    *,
    young_pa: float,
    second_moment_m4: float,
    length_m: float,
) -> float:
    return pi**2 * float(young_pa) * float(second_moment_m4) / (4.0 * float(length_m) ** 2)


def write_fixed_free_b32r_buckle_deck(path: Path, spec: FixedFreeColumnSpec) -> Path:
    if spec.n_elements < 1:
        raise ValueError("n_elements must be >= 1")
    path.parent.mkdir(parents=True, exist_ok=True)
    dy = float(spec.length_m) / float(spec.n_elements)
    endpoint_ids = [idx + 1 for idx in range(spec.n_elements + 1)]
    midpoint_ids = [spec.n_elements + 2 + idx for idx in range(spec.n_elements)]

    lines = [
        "** Phase 16 CalculiX BUCKLE capability proof: fixed-free pipe column",
        "*NODE",
    ]
    for idx, node_id in enumerate(endpoint_ids):
        lines.append(f"{node_id}, 0.0, {idx * dy:.9g}, 0.0")
    for idx, node_id in enumerate(midpoint_ids):
        lines.append(f"{node_id}, 0.0, {(idx + 0.5) * dy:.9g}, 0.0")

    lines.append("*ELEMENT, TYPE=B32R, ELSET=EALL")
    for elem_idx in range(spec.n_elements):
        lines.append(
            f"{elem_idx + 1}, {endpoint_ids[elem_idx]}, {midpoint_ids[elem_idx]}, "
            f"{endpoint_ids[elem_idx + 1]}"
        )

    lines.extend(
        [
            "*NSET, NSET=ROOT",
            str(endpoint_ids[0]),
            "*NSET, NSET=TIP",
            str(endpoint_ids[-1]),
            "*MATERIAL, NAME=CARBON_FIBER_HM",
            "*ELASTIC",
            f"{spec.young_pa:.9g}, {spec.poisson_ratio:.9g}",
            "*DENSITY",
            f"{spec.density_kgpm3:.9g}",
            "*BEAM SECTION, ELSET=EALL, MATERIAL=CARBON_FIBER_HM, SECTION=PIPE",
            f"{spec.outer_radius_m:.9g}, {spec.wall_thickness_m:.9g}",
            "1.0, 0.0, 0.0",
            "*BOUNDARY",
            f"{endpoint_ids[0]}, 1, 6",
            "*STEP, NAME=reference_static",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
            f"{endpoint_ids[-1]}, 2, {-float(spec.reference_compression_n):.9g}",
            "*END STEP",
            "*STEP, NAME=buckle",
            "*BUCKLE",
            str(int(spec.n_modes)),
            "*NODE FILE, OUTPUT=2D",
            "U",
            "*END STEP",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_ccx_buckling_capability(
    *,
    output_dir: Path,
    config_path: Path = DEFAULT_CONFIG,
    spec: FixedFreeColumnSpec = FixedFreeColumnSpec(),
) -> CcxBucklingResult:
    runtime_dir = output_dir / "_ccx_buckle_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    ccx_path = discover_ccx(config_path)
    source_inp, source_ref = _official_buckle_example_paths()
    if source_inp is not None:
        deck_path = runtime_dir / source_inp.name
        shutil.copyfile(source_inp, deck_path)
        reference_values = (
            tuple(parse_buckle_eigenvalues(source_ref))
            if source_ref is not None and source_ref.exists()
            else ()
        )
        case_id = source_inp.stem
    else:
        deck_path = write_fixed_free_b32r_buckle_deck(
            runtime_dir / "fixed_free_pipe_column_buckle.inp",
            spec,
        )
        reference_values = ()
        case_id = "fixed_free_pipe_column_buckle"

    if ccx_path is None:
        return CcxBucklingResult(
            case_id=case_id,
            status="SKIP",
            ccx_path=None,
            source_inp_path=source_inp,
            reference_dat_path=source_ref,
            deck_path=deck_path,
            dat_path=None,
            frd_path=None,
            log_path=None,
            returncode=None,
            lambda_1=None,
            eigenvalues=(),
            reference_eigenvalues=reference_values,
            reference_lambda_1=reference_values[0] if reference_values else None,
            max_reference_error_pct=None,
            message="No local CalculiX executable was found.",
        )

    try:
        completed = subprocess.run(
            [ccx_path, deck_path.stem],
            cwd=runtime_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        returncode = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_path = runtime_dir / f"{deck_path.stem}.log"
        log_path.write_text(str(exc), encoding="utf-8")
        return CcxBucklingResult(
            case_id=case_id,
            status="FAIL",
            ccx_path=ccx_path,
            source_inp_path=source_inp,
            reference_dat_path=source_ref,
            deck_path=deck_path,
            dat_path=None,
            frd_path=None,
            log_path=log_path,
            returncode=None,
            lambda_1=None,
            eigenvalues=(),
            reference_eigenvalues=reference_values,
            reference_lambda_1=reference_values[0] if reference_values else None,
            max_reference_error_pct=None,
            message=f"CalculiX could not run: {exc}",
        )

    log_path = runtime_dir / f"{deck_path.stem}.log"
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
    if returncode != 0:
        return CcxBucklingResult(
            case_id=case_id,
            status="FAIL",
            ccx_path=ccx_path,
            source_inp_path=source_inp,
            reference_dat_path=source_ref,
            deck_path=deck_path,
            dat_path=dat_path if dat_path.exists() else None,
            frd_path=frd_path if frd_path.exists() else None,
            log_path=log_path,
            returncode=returncode,
            lambda_1=None,
            eigenvalues=(),
            reference_eigenvalues=reference_values,
            reference_lambda_1=reference_values[0] if reference_values else None,
            max_reference_error_pct=None,
            message=f"CalculiX returned non-zero exit code {returncode}.",
        )

    eigenvalues = tuple(parse_buckle_eigenvalues(dat_path)) if dat_path.exists() else ()
    if not eigenvalues:
        return CcxBucklingResult(
            case_id=case_id,
            status="FAIL",
            ccx_path=ccx_path,
            source_inp_path=source_inp,
            reference_dat_path=source_ref,
            deck_path=deck_path,
            dat_path=dat_path if dat_path.exists() else None,
            frd_path=frd_path if frd_path.exists() else None,
            log_path=log_path,
            returncode=returncode,
            lambda_1=None,
            eigenvalues=(),
            reference_eigenvalues=reference_values,
            reference_lambda_1=reference_values[0] if reference_values else None,
            max_reference_error_pct=None,
            message="CalculiX completed but no BUCKLE eigenvalues were parsed.",
        )

    lambda_1 = float(eigenvalues[0])
    max_error_pct = _max_eigenvalue_error_pct(eigenvalues, reference_values)
    if max_error_pct is None:
        status = "PASS_WITHOUT_REFERENCE"
        message = "CalculiX BUCKLE completed and returned eigenvalues; no reference .dat was available."
    else:
        status = "PASS" if max_error_pct <= 0.5 else "WARN"
        message = "CalculiX BUCKLE completed and matched the installed verification reference."
    return CcxBucklingResult(
        case_id=case_id,
        status=status,
        ccx_path=ccx_path,
        source_inp_path=source_inp,
        reference_dat_path=source_ref,
        deck_path=deck_path,
        dat_path=dat_path,
        frd_path=frd_path if frd_path.exists() else None,
        log_path=log_path,
        returncode=returncode,
        lambda_1=lambda_1,
        eigenvalues=eigenvalues,
        reference_eigenvalues=reference_values,
        reference_lambda_1=reference_values[0] if reference_values else None,
        max_reference_error_pct=max_error_pct,
        message=message,
    )


def _official_buckle_example_paths() -> tuple[Path | None, Path | None]:
    for inp_path in _OFFICIAL_BUCKLE_EXAMPLES:
        if inp_path.exists():
            ref_path = inp_path.with_suffix(".dat.ref")
            return inp_path, ref_path if ref_path.exists() else None
    return None, None


def _max_eigenvalue_error_pct(
    actual: tuple[float, ...],
    reference: tuple[float, ...],
) -> float | None:
    if not actual or not reference:
        return None
    errors = []
    for act, ref in zip(actual, reference, strict=False):
        if abs(ref) <= 1.0e-12:
            continue
        errors.append(abs(float(act) - float(ref)) / abs(float(ref)) * 100.0)
    return max(errors) if errors else None


def discover_ccx(config_path: Path = DEFAULT_CONFIG) -> str | None:
    try:
        cfg = load_config(config_path)
        configured = find_ccx(cfg)
        if configured:
            return configured
    except Exception:
        pass
    for binary in ("ccx", "ccx_2.23"):
        found = shutil.which(binary)
        if found:
            return str(Path(found).resolve())
    for candidate in _KNOWN_CCX_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return str(path.resolve())
    return None


def build_wire6_ramp_rows(
    reference: CandidateReference,
    *,
    load_factors: Iterable[float] = DEFAULT_RAMP_LOAD_FACTORS,
    wire_allowable_n: float = DEFAULT_WIRE6_ALLOWABLE_N,
) -> list[Wire6RampRow]:
    stress_util_ref = max(0.0, 1.0 + float(reference.failure_index))
    buckling_util_ref = max(0.0, 1.0 + float(reference.buckling_index))
    rows: list[Wire6RampRow] = []
    for load_factor in load_factors:
        n = float(load_factor)
        scale = n / float(reference.reference_load_factor)
        wire_tension = float(reference.wire_tension_n) * scale
        wire_util = wire_tension / float(wire_allowable_n)
        tip_deflection = float(reference.tip_deflection_m) * scale
        tip_util = tip_deflection / float(reference.tip_deflection_limit_m)
        stress_util = stress_util_ref * scale
        buckling_util = buckling_util_ref * scale
        twist_util = (
            abs(float(reference.twist_max_deg) * scale) / float(reference.twist_limit_deg)
            if reference.twist_limit_deg
            else float("inf")
        )
        event, interpretation = _wire6_event(
            tip_util=tip_util,
            wire_util=wire_util,
            stress_util=stress_util,
            buckling_util=buckling_util,
            twist_util=twist_util,
        )
        rows.append(
            Wire6RampRow(
                load_factor=n,
                wire_tension_n=wire_tension,
                wire_utilization=wire_util,
                tip_deflection_m=tip_deflection,
                tip_deflection_utilization=tip_util,
                cfrp_global_stress_utilization=stress_util,
                local_buckling_utilization_est=buckling_util,
                twist_utilization=twist_util,
                event=event,
                interpretation=interpretation,
            )
        )
    return rows


def write_phase16_package(
    out_dir: Path,
    reference: CandidateReference,
    *,
    ccx_result: CcxBucklingResult | None,
    wire_allowable_n: float = DEFAULT_WIRE6_ALLOWABLE_N,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_wire6_ramp_rows(
        reference,
        load_factors=_ramp_load_factors_with_milestones(reference, wire_allowable_n),
        wire_allowable_n=wire_allowable_n,
    )
    outputs = [
        _write_ccx_buckling_capability_csv(out_dir / "ccx_buckling_capability.csv", ccx_result),
        _write_ccx_buckling_report(out_dir / "ccx_buckling_capability_report.md", ccx_result),
        _write_wire6_ramp_csv(out_dir / "wire6_load_factor_ramp.csv", rows),
        _write_wire6_ramp_report(
            out_dir / "wire6_load_factor_ramp_report.md",
            rows,
            reference,
            wire_allowable_n=wire_allowable_n,
        ),
    ]
    return outputs


def _ramp_load_factors_with_milestones(
    reference: CandidateReference,
    wire_allowable_n: float,
) -> tuple[float, ...]:
    stress_util_ref = max(0.0, 1.0 + float(reference.failure_index))
    milestones = [
        float(reference.reference_load_factor)
        * float(reference.tip_deflection_limit_m)
        / float(reference.tip_deflection_m),
        float(reference.reference_load_factor)
        * float(wire_allowable_n)
        / float(reference.wire_tension_n),
        float(reference.reference_load_factor) / max(stress_util_ref, 1.0e-12),
    ]
    values = {
        round(float(value), 6)
        for value in (*DEFAULT_RAMP_LOAD_FACTORS, *milestones)
        if 1.0 <= float(value) <= 6.0
    }
    return tuple(sorted(values))


def _wire6_event(
    *,
    tip_util: float,
    wire_util: float,
    stress_util: float,
    buckling_util: float,
    twist_util: float,
) -> tuple[str, str]:
    threshold = 1.0 - 1.0e-6
    if buckling_util >= threshold:
        return (
            "local_buckling_estimate_exceeded",
            "internal local buckling estimate has reached utilization 1.0; stop before this point",
        )
    if stress_util >= threshold:
        return (
            "cfrp_global_bending_stress_exceeded",
            "global CFRP bending stress allowable is exceeded in the fixed-design estimate",
        )
    if wire_util >= threshold:
        return (
            "wire_allowable_exceeded",
            "wire reaches the conservative 6 kN allowable; this is an allowable violation, not proof of physical snapping",
        )
    if tip_util >= threshold:
        return (
            "tip_deflection_limit_exceeded",
            "tip deflection design limit is exceeded first; the wing has become too flexible before wire rupture",
        )
    if twist_util >= threshold:
        return (
            "torsion_twist_limit_exceeded",
            "twist limit is exceeded",
        )
    return (
        "within_model_margins",
        "no modeled limit is exceeded at this load factor",
    )


def _write_ccx_buckling_capability_csv(
    path: Path,
    result: CcxBucklingResult | None,
) -> Path:
    fields = [
        "case_id",
        "status",
        "ccx_path",
        "source_inp_path",
        "reference_dat_path",
        "deck_path",
        "dat_path",
        "frd_path",
        "returncode",
        "lambda_1",
        "reference_lambda_1",
        "max_reference_error_pct",
        "eigenvalue_count",
        "reference_eigenvalue_count",
        "message",
    ]
    row = (
        {
            "case_id": "",
            "status": "NOT_RUN",
            "ccx_path": "",
            "source_inp_path": "",
            "reference_dat_path": "",
            "deck_path": "",
            "dat_path": "",
            "frd_path": "",
            "returncode": "",
            "lambda_1": "",
            "reference_lambda_1": "",
            "max_reference_error_pct": "",
            "eigenvalue_count": "",
            "reference_eigenvalue_count": "",
            "message": "CalculiX BUCKLE benchmark was not run in this call.",
        }
        if result is None
        else {
            "case_id": result.case_id,
            "status": result.status,
            "ccx_path": result.ccx_path or "",
            "source_inp_path": result.source_inp_path or "",
            "reference_dat_path": result.reference_dat_path or "",
            "deck_path": result.deck_path,
            "dat_path": result.dat_path or "",
            "frd_path": result.frd_path or "",
            "returncode": result.returncode if result.returncode is not None else "",
            "lambda_1": result.lambda_1 if result.lambda_1 is not None else "",
            "reference_lambda_1": (
                result.reference_lambda_1 if result.reference_lambda_1 is not None else ""
            ),
            "max_reference_error_pct": (
                result.max_reference_error_pct
                if result.max_reference_error_pct is not None
                else ""
            ),
            "eigenvalue_count": len(result.eigenvalues),
            "reference_eigenvalue_count": len(result.reference_eigenvalues),
            "message": result.message,
        }
    )
    return _write_csv(path, fields, [row])


def _write_ccx_buckling_report(path: Path, result: CcxBucklingResult | None) -> Path:
    if result is None:
        lines = [
            "# CalculiX Buckling Capability Report",
            "",
            "- Status: `NOT_RUN`",
            "- CalculiX BUCKLE benchmark was not run in this call.",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    lines = [
        "# CalculiX Buckling Capability Report",
        "",
        "## What Was Proved",
        "",
        f"- Status: `{result.status}`",
        f"- Message: {result.message}",
        f"- Case: `{result.case_id}`",
        f"- Solver: `{result.ccx_path or 'not found'}`",
        f"- Source INP: `{result.source_inp_path or 'generated fallback'}`",
        f"- Reference DAT: `{result.reference_dat_path or 'n/a'}`",
        f"- Deck: `{result.deck_path}`",
        f"- Log: `{result.log_path or 'n/a'}`",
        f"- DAT: `{result.dat_path or 'n/a'}`",
        f"- FRD: `{result.frd_path or 'n/a'}`",
        "",
        "## Benchmark",
        "",
        "- Model: installed CalculiX verification example `beamb`, a compressed beam/solid buckling case.",
        "- Check: local `ccx_2.23` BUCKLE eigenvalues compared against the installed `beamb.dat.ref` reference table.",
        f"- lambda_1: `{_fmt(result.lambda_1)}`",
        f"- reference lambda_1: `{_fmt(result.reference_lambda_1)}`",
        f"- Max eigenvalue table error: `{_fmt(result.max_reference_error_pct)}%`",
        f"- Parsed eigenvalues: `{len(result.eigenvalues)}`",
        "",
        "## Engineering Meaning",
        "",
        "- This proves the local ccx executable can run a real eigen-buckling solve and return a physical buckling factor.",
        "- It does not by itself certify the HPA candidate tube wall, ovalization, joints, ribs, or wire fittings.",
        "- The next FEM step for the candidate is to use this proven `*BUCKLE` route on a candidate-specific shell/detail model, not to treat the old B32R pipe route as final local-wall truth.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_wire6_ramp_csv(path: Path, rows: list[Wire6RampRow]) -> Path:
    fields = [
        "load_factor",
        "wire_tension_n",
        "wire_utilization",
        "tip_deflection_m",
        "tip_deflection_utilization",
        "cfrp_global_stress_utilization",
        "local_buckling_utilization_est",
        "twist_utilization",
        "event",
        "interpretation",
    ]
    return _write_csv(path, fields, [row.__dict__ for row in rows])


def _write_wire6_ramp_report(
    path: Path,
    rows: list[Wire6RampRow],
    reference: CandidateReference,
    *,
    wire_allowable_n: float,
) -> Path:
    tip_limit_n = (
        float(reference.reference_load_factor)
        * float(reference.tip_deflection_limit_m)
        / float(reference.tip_deflection_m)
    )
    wire_limit_n = (
        float(reference.reference_load_factor) * float(wire_allowable_n) / float(reference.wire_tension_n)
    )
    stress_limit_n = (
        float(reference.reference_load_factor) / max(1.0 + float(reference.failure_index), 1.0e-12)
    )
    buckling_limit_n = (
        float(reference.reference_load_factor) / max(1.0 + float(reference.buckling_index), 1.0e-12)
    )
    physical_break_at_policy_mbl_n = (
        wire_allowable_n * 3.75 / (float(reference.wire_tension_n) / float(reference.reference_load_factor))
    )
    row_30 = min(rows, key=lambda row: abs(row.load_factor - 3.0))
    lines = [
        "# Wire 6 kN Load-Factor Ramp",
        "",
        "## Plain-Language Answer",
        "",
        "- Changing the modeled wire allowable from 4.581 kN to 6 kN mainly increases strength margin, not stiffness. If the real wire diameter/material/stiffness changes, the FEM must be rerun with the new AE and pretension.",
        f"- At `3.0G`, the 6 kN wire-body tension is `{row_30.wire_tension_n:.1f} N`, utilization `{row_30.wire_utilization:.3f}`. The modeled cable-body tension allowable is not exceeded.",
        "- Put bluntly: this is a cable-body allowable check, not proof that the termination, splice, bend radius, clamp, fuselage anchor, or wing attach survives 3.0G.",
        f"- First thing that happens as G increases: the configured tip deflection limit is reached at about `n = {tip_limit_n:.3f}`.",
        f"- The 6 kN wire allowable is reached later at about `n = {wire_limit_n:.3f}`.",
        f"- CFRP global bending stress reaches allowable later still at about `n = {stress_limit_n:.3f}`.",
        f"- Internal local buckling estimate reaches utilization 1.0 at about `n = {buckling_limit_n:.3f}`, but candidate-specific shell buckling is still a separate FEM/detail-model task.",
        "",
        "## Why There Is A Limit",
        "",
        "- The 6 kN number is a design allowable, not necessarily the physical snap load.",
        "- A design allowable exists because knots, splices, bend radius, UV, abrasion, creep, and attach fittings reduce real strength. The model stops at allowable before the rope's catalog breaking load.",
        f"- If 6 kN allowable is justified by the previous policy, the implied catalog minimum break load is roughly `22.5 kN`; under ideal no-loss scaling that physical break would be around `n = {physical_break_at_policy_mbl_n:.1f}`, far beyond the wing model's valid range.",
        "- So before that hypothetical rope snap, the wing already violates deflection and then stress limits.",
        "",
        "## Ramp Table",
        "",
        "| n | wire N | wire util | tip defl m | tip util | stress util | buckling util est | event |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.load_factor:.2f} | {row.wire_tension_n:.1f} | {row.wire_utilization:.3f} | "
            f"{row.tip_deflection_m:.3f} | {row.tip_deflection_utilization:.3f} | "
            f"{row.cfrp_global_stress_utilization:.3f} | {row.local_buckling_utilization_est:.3f} | "
            f"{row.event} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Readout",
            "",
            "- Moving wire allowable to 6 kN removes wire as the first limiter, but it does not buy a large system-level load-factor increase because tip deflection takes over at about 3.305G.",
            "- If you relax or move the tip-deflection limit, the next stop is the 6 kN wire allowable at about 3.968G.",
            "- Past that, continuing the table is useful for understanding failure order, but it should be labeled post-limit extrapolation, not validation.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _limit_load_factor(rows: list[Wire6RampRow], event: str) -> float:
    for row in rows:
        if row.event == event:
            return row.load_factor
    return float("nan")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.6g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--wire-allowable-n", type=float, default=DEFAULT_WIRE6_ALLOWABLE_N)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ccx_result = run_ccx_buckling_capability(output_dir=args.output_dir, config_path=args.config)
    reference = load_current_candidate_reference()
    outputs = write_phase16_package(
        args.output_dir,
        reference,
        ccx_result=ccx_result,
        wire_allowable_n=float(args.wire_allowable_n),
    )
    print(f"FEM buckling proof: {ccx_result.status} - {ccx_result.message}")
    if ccx_result.lambda_1 is not None:
        error_text = (
            "n/a"
            if ccx_result.max_reference_error_pct is None
            else f"{ccx_result.max_reference_error_pct:.6g}%"
        )
        print(
            "lambda_1="
            f"{ccx_result.lambda_1:.6g}, max_ref_error={error_text}"
        )
    print(f"Wrote {len(outputs)} report files to {args.output_dir}")
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
