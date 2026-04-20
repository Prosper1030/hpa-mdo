from __future__ import annotations

from pathlib import Path
from typing import Any

from .geometry.loader import load_geometry
from .pipeline import run_job
from .reports.json_report import write_json_report
from .schema import (
    ConvergenceGateCheck,
    MeshJobConfig,
    MeshStudyCFDResult,
    MeshStudyCaseResult,
    MeshStudyComparison,
    MeshStudyMeshStats,
    MeshStudyPreset,
    MeshStudyPresetRuntime,
    MeshStudyReport,
    MeshStudyVerdict,
)


DEFAULT_STUDY_NAME = "baseline_mesh_study"
DEFAULT_PRESET_SPECS = (
    {
        "name": "coarse",
        "tier": "coarse",
        "near_body_factor": 0.11,
        "farfield_factor": 0.45,
        "max_iterations": 40,
        "cfl_number": 4.0,
    },
    {
        "name": "medium",
        "tier": "medium",
        "near_body_factor": 0.08,
        "farfield_factor": 0.35,
        "max_iterations": 60,
        "cfl_number": 3.0,
    },
    {
        "name": "fine",
        "tier": "fine",
        "near_body_factor": 0.06,
        "farfield_factor": 0.27,
        "max_iterations": 80,
        "cfl_number": 2.5,
    },
)
DEFAULT_RELATIVE_RANGE_FLOOR = 1.0e-3
DEFAULT_ALL_CASES_RELATIVE_RANGE = 0.12
DEFAULT_MEDIUM_FINE_RELATIVE_RANGE = 0.08


def _check(
    status: str,
    *,
    observed: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    notes: list[str] | None = None,
) -> ConvergenceGateCheck:
    return ConvergenceGateCheck(
        status=status,
        observed=observed or {},
        expected=expected or {},
        warnings=warnings or [],
        notes=notes or [],
    )


def _relative_range(values: list[float]) -> float:
    scale = max([abs(value) for value in values] + [DEFAULT_RELATIVE_RANGE_FLOOR])
    return (max(values) - min(values)) / scale


def _collect_check_warnings(name: str, check: ConvergenceGateCheck) -> list[str]:
    return [f"{name}:{warning}" for warning in check.warnings]


def build_default_mesh_study_presets(characteristic_length: float) -> list[MeshStudyPreset]:
    presets: list[MeshStudyPreset] = []
    for spec in DEFAULT_PRESET_SPECS:
        near_body_size = characteristic_length * float(spec["near_body_factor"])
        farfield_size = characteristic_length * float(spec["farfield_factor"])
        presets.append(
            MeshStudyPreset(
                name=str(spec["name"]),
                tier=str(spec["tier"]),
                near_body_factor=float(spec["near_body_factor"]),
                farfield_factor=float(spec["farfield_factor"]),
                near_body_size=near_body_size,
                farfield_size=farfield_size,
                runtime=MeshStudyPresetRuntime(
                    max_iterations=int(spec["max_iterations"]),
                    cfl_number=float(spec["cfl_number"]),
                ),
                notes=[
                    "Resolved from body_max_span characteristic length.",
                ],
            )
        )
    return presets


def _resolve_characteristic_length(config: MeshJobConfig) -> float:
    probe_config = config.model_copy(deep=True)
    probe_config.out_dir = config.out_dir / ".study_probe"
    geometry = load_geometry(config.geometry, probe_config)
    provider_result = geometry.provider_result
    topology = None if provider_result is None else provider_result.topology
    bounds = None if topology is None else topology.bounds or topology.import_bounds
    if bounds is None:
        raise RuntimeError(
            "mesh study requires provider topology bounds so default presets can resolve characteristic length"
        )
    spans = [
        float(bounds.x_max) - float(bounds.x_min),
        float(bounds.y_max) - float(bounds.y_min),
        float(bounds.z_max) - float(bounds.z_min),
    ]
    return max(max(spans), 1.0e-3)


def _build_case_config(base_config: MeshJobConfig, preset: MeshStudyPreset) -> MeshJobConfig:
    case_config = base_config.model_copy(deep=True)
    case_config.out_dir = base_config.out_dir / "cases" / preset.name
    case_config.global_min_size = preset.near_body_size
    case_config.global_max_size = preset.farfield_size
    case_config.su2 = case_config.su2.model_copy(
        update={
            "enabled": True,
            "case_name": f"alpha_0_{preset.name}",
            "max_iterations": preset.runtime.max_iterations,
            "cfl_number": preset.runtime.cfl_number,
        }
    )
    return case_config


def _case_result_from_run(
    preset: MeshStudyPreset,
    characteristic_length: float,
    case_config: MeshJobConfig,
    result: dict[str, Any],
) -> MeshStudyCaseResult:
    mesh_payload = result.get("mesh", {})
    su2_payload = result.get("su2", {})
    convergence_payload = su2_payload.get("convergence_gate") or result.get("convergence")
    convergence_gate = None
    if convergence_payload is not None:
        from .schema import BaselineConvergenceGate

        convergence_gate = BaselineConvergenceGate.model_validate(convergence_payload)

    final_coefficients = su2_payload.get("final_coefficients", {})
    overall_gate = None if convergence_gate is None else convergence_gate.overall_convergence_gate
    notes: list[str] = []
    if convergence_gate is None:
        notes.append("convergence_gate_missing")
    return MeshStudyCaseResult(
        preset=preset,
        out_dir=case_config.out_dir,
        report_path=case_config.out_dir / "report.json",
        status="success" if result.get("status") == "success" else "failed",
        failure_code=result.get("failure_code"),
        mesh=MeshStudyMeshStats(
            mesh_dim=mesh_payload.get("mesh_dim"),
            node_count=mesh_payload.get("node_count"),
            element_count=mesh_payload.get("element_count"),
            surface_element_count=mesh_payload.get("surface_element_count"),
            volume_element_count=mesh_payload.get("volume_element_count"),
            characteristic_length=characteristic_length,
            near_body_size=preset.near_body_size,
            farfield_size=preset.farfield_size,
        ),
        cfd=MeshStudyCFDResult(
            case_name=su2_payload.get("case_name") or case_config.su2.case_name,
            history_path=su2_payload.get("history_path"),
            final_iteration=su2_payload.get("final_iteration"),
            cl=final_coefficients.get("cl"),
            cd=final_coefficients.get("cd"),
            cm=final_coefficients.get("cm"),
            cm_axis=final_coefficients.get("cm_axis"),
        ),
        convergence_gate=convergence_gate,
        overall_convergence_status=None if overall_gate is None else overall_gate.status,
        comparability_level=None if overall_gate is None else overall_gate.comparability_level,
        notes=notes,
    )


def _ordered_cases(
    cases: list[MeshStudyCaseResult],
    expected_tiers: list[str],
) -> tuple[list[MeshStudyCaseResult], dict[str, MeshStudyCaseResult]]:
    case_lookup = {case.preset.tier: case for case in cases}
    return [case_lookup[tier] for tier in expected_tiers if tier in case_lookup], case_lookup


def _mesh_hierarchy_check(
    ordered_cases: list[MeshStudyCaseResult],
    *,
    expected_case_count: int,
) -> ConvergenceGateCheck:
    observed = {
        case.preset.tier: {
            "node_count": case.mesh.node_count,
            "element_count": case.mesh.element_count,
            "volume_element_count": case.mesh.volume_element_count,
            "near_body_size": case.mesh.near_body_size,
            "farfield_size": case.mesh.farfield_size,
        }
        for case in ordered_cases
    }
    warnings: list[str] = []
    if len(ordered_cases) != expected_case_count or any(case.status != "success" for case in ordered_cases):
        warnings.append("study_cases_incomplete")
        return _check(
            "fail",
            observed=observed,
            expected={"completed_case_count": expected_case_count, "strict_mesh_order": True},
            warnings=warnings,
        )

    def _strict_increasing(values: list[int | None]) -> bool:
        return all(
            isinstance(left, int)
            and isinstance(right, int)
            and left < right
            for left, right in zip(values, values[1:])
        )

    def _strict_decreasing(values: list[float | None]) -> bool:
        return all(
            isinstance(left, (int, float))
            and isinstance(right, (int, float))
            and float(left) > float(right)
            for left, right in zip(values, values[1:])
        )

    node_counts = [case.mesh.node_count for case in ordered_cases]
    element_counts = [case.mesh.element_count for case in ordered_cases]
    volume_counts = [case.mesh.volume_element_count for case in ordered_cases]
    near_body_sizes = [case.mesh.near_body_size for case in ordered_cases]
    farfield_sizes = [case.mesh.farfield_size for case in ordered_cases]

    if not _strict_increasing(node_counts):
        warnings.append("node_count_not_strictly_increasing")
    if not _strict_increasing(element_counts):
        warnings.append("element_count_not_strictly_increasing")
    if not _strict_increasing(volume_counts):
        warnings.append("volume_element_count_not_strictly_increasing")
    if not _strict_decreasing(near_body_sizes):
        warnings.append("near_body_size_not_strictly_decreasing")
    if not _strict_decreasing(farfield_sizes):
        warnings.append("farfield_size_not_strictly_decreasing")

    status = "pass" if not warnings else "fail"
    return _check(
        status,
        observed=observed,
        expected={
            "node_count": "strictly increasing coarse->fine",
            "element_count": "strictly increasing coarse->fine",
            "volume_element_count": "strictly increasing coarse->fine",
            "near_body_size": "strictly decreasing coarse->fine",
            "farfield_size": "strictly decreasing coarse->fine",
        },
        warnings=warnings,
    )


def _coefficient_spread_check(
    cases: list[MeshStudyCaseResult],
    *,
    threshold: float,
) -> ConvergenceGateCheck:
    observed: dict[str, Any] = {"case_names": [case.preset.name for case in cases]}
    warnings: list[str] = []
    metrics: dict[str, float] = {}
    for coefficient in ("cl", "cd", "cm"):
        values = [getattr(case.cfd, coefficient) for case in cases if case.cfd is not None]
        if len(values) != len(cases) or any(value is None for value in values):
            warnings.append(f"{coefficient}_missing")
            continue
        rel_range = _relative_range([float(value) for value in values if value is not None])
        metrics[f"{coefficient}_relative_range"] = rel_range
        if rel_range > threshold:
            warnings.append(f"{coefficient}_relative_range_above_threshold")
    observed.update(metrics)
    status = "pass" if not warnings else "warn"
    return _check(
        status,
        observed=observed,
        expected={"relative_range_threshold": threshold},
        warnings=warnings,
    )


def _convergence_progress_check(case_lookup: dict[str, MeshStudyCaseResult]) -> ConvergenceGateCheck:
    observed = {
        tier: {
            "status": case_lookup[tier].overall_convergence_status,
            "comparability_level": case_lookup[tier].comparability_level,
        }
        for tier in ("coarse", "medium", "fine")
        if tier in case_lookup
    }
    warnings: list[str] = []
    fine_case = case_lookup.get("fine")
    medium_case = case_lookup.get("medium")
    if fine_case is None or medium_case is None:
        warnings.append("medium_or_fine_case_missing")
        status = "fail"
    elif fine_case.overall_convergence_status == "pass":
        status = "pass"
    elif fine_case.overall_convergence_status == "warn" and medium_case.overall_convergence_status in {"warn", "pass"}:
        warnings.append("fine_case_still_warn")
        status = "warn"
    else:
        warnings.append("fine_case_not_comparable")
        status = "fail"
    return _check(
        status,
        observed=observed,
        expected={"fine_status": "pass", "fine_comparability_level": "preliminary_compare"},
        warnings=warnings,
    )


def evaluate_mesh_study(
    cases: list[MeshStudyCaseResult],
    *,
    expected_tiers: list[str] | None = None,
) -> tuple[MeshStudyComparison, MeshStudyVerdict]:
    expected_tiers = expected_tiers or ["coarse", "medium", "fine"]
    ordered_cases, case_lookup = _ordered_cases(cases, expected_tiers)
    expected_case_count = len(expected_tiers)
    completed_case_count = sum(1 for case in ordered_cases if case.status == "success")

    mesh_hierarchy = _mesh_hierarchy_check(ordered_cases, expected_case_count=expected_case_count)
    all_cases_spread = _coefficient_spread_check(ordered_cases, threshold=DEFAULT_ALL_CASES_RELATIVE_RANGE)
    medium_fine_cases = [case_lookup[tier] for tier in ("medium", "fine") if tier in case_lookup]
    medium_fine_spread = _coefficient_spread_check(
        medium_fine_cases,
        threshold=DEFAULT_MEDIUM_FINE_RELATIVE_RANGE,
    )
    convergence_progress = _convergence_progress_check(case_lookup)

    comparison = MeshStudyComparison(
        expected_case_count=expected_case_count,
        completed_case_count=completed_case_count,
        case_order=expected_tiers,
        mesh_hierarchy=mesh_hierarchy,
        coefficient_spread={
            "all_cases": all_cases_spread,
            "medium_fine": medium_fine_spread,
        },
        convergence_progress=convergence_progress,
        warnings=[
            *_collect_check_warnings("mesh_hierarchy", mesh_hierarchy),
            *_collect_check_warnings("all_cases_spread", all_cases_spread),
            *_collect_check_warnings("medium_fine_spread", medium_fine_spread),
            *_collect_check_warnings("convergence_progress", convergence_progress),
        ],
        notes=[
            "Mesh study compares package-native baseline runs only; it does not claim final CFD truth.",
        ],
    )

    checks = {
        "mesh_hierarchy": mesh_hierarchy,
        "medium_fine_spread": medium_fine_spread,
        "convergence_progress": convergence_progress,
    }
    if mesh_hierarchy.status == "fail" or completed_case_count != expected_case_count:
        verdict_name = "insufficient"
        comparability_level = "not_comparable"
        blockers = [*mesh_hierarchy.warnings]
    elif medium_fine_spread.status == "pass" and convergence_progress.status == "pass":
        verdict_name = "preliminary_compare"
        comparability_level = "preliminary_compare"
        blockers = []
    else:
        verdict_name = "still_run_only"
        comparability_level = "run_only"
        blockers = [*medium_fine_spread.warnings, *convergence_progress.warnings]

    verdict = MeshStudyVerdict(
        verdict=verdict_name,
        comparability_level=comparability_level,
        confidence={
            "preliminary_compare": "high",
            "still_run_only": "medium",
            "insufficient": "low",
        }[verdict_name],
        blockers=blockers,
        checks=checks,
        warnings=comparison.warnings,
        notes=[
            "Study verdict is derived from mesh hierarchy, medium/fine coefficient spread, and convergence progress.",
        ],
    )
    return comparison, verdict


def run_mesh_study(config: MeshJobConfig) -> dict[str, Any]:
    if not config.su2.enabled:
        raise ValueError("mesh study requires su2.enabled=true")

    study_root = config.out_dir
    study_root.mkdir(parents=True, exist_ok=True)
    characteristic_length = _resolve_characteristic_length(config)
    presets = build_default_mesh_study_presets(characteristic_length)

    cases: list[MeshStudyCaseResult] = []
    for preset in presets:
        case_config = _build_case_config(config, preset)
        result = run_job(case_config)
        cases.append(_case_result_from_run(preset, characteristic_length, case_config, result))

    comparison, verdict = evaluate_mesh_study(cases, expected_tiers=[preset.tier for preset in presets])
    report = MeshStudyReport(
        study_name=DEFAULT_STUDY_NAME,
        component=config.component,
        geometry=config.geometry,
        geometry_provider=config.geometry_provider,
        cases=cases,
        comparison=comparison,
        verdict=verdict,
        notes=[
            "Each case uses the package-native provider -> mesh -> SU2 baseline -> convergence gate line.",
        ],
    )
    payload = report.model_dump(mode="json")
    write_json_report(study_root / "report.json", payload)
    return payload
