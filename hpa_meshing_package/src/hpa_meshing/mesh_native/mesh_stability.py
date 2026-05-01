from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


DEFAULT_COEFFICIENT_TOLERANCES = {
    "cl": 0.02,
    "cd": 0.005,
    "cmy": 0.02,
}


COEFFICIENT_ALIASES = {
    "cm": ("cm", "cmy"),
    "cmy": ("cmy", "cm"),
}


def select_cheapest_stable_mesh(
    cases: Sequence[Mapping[str, Any]],
    *,
    coefficient_tolerances: Mapping[str, float] | None = None,
    coefficient_relative_tolerances: Mapping[str, float] | None = None,
    relative_scale_floor: float = 1.0e-6,
    require_successful_case_gates: bool = False,
    require_iterative_gate_pass: bool = False,
    require_coefficient_sanity: bool = False,
    require_cfd_evidence_gate_pass: bool = False,
) -> dict[str, Any]:
    tolerances = dict(coefficient_tolerances or DEFAULT_COEFFICIENT_TOLERANCES)
    relative_tolerances = (
        None if coefficient_relative_tolerances is None else dict(coefficient_relative_tolerances)
    )
    if relative_scale_floor <= 0.0:
        raise ValueError("relative_scale_floor must be positive")
    ordered_cases = sorted(cases, key=lambda case: int(case["volume_element_count"]))
    ineligible_cases = []
    if require_successful_case_gates:
        eligible_cases = []
        for case in ordered_cases:
            reasons = _case_gate_failure_reasons(
                case,
                require_iterative_gate_pass=require_iterative_gate_pass,
                require_coefficient_sanity=require_coefficient_sanity,
                require_cfd_evidence_gate_pass=require_cfd_evidence_gate_pass,
            )
            if reasons:
                ineligible_cases.append(
                    {
                        "case_name": case.get("case_name"),
                        "volume_element_count": int(case["volume_element_count"]),
                        "reasons": reasons,
                    }
                )
            else:
                eligible_cases.append(case)
        ordered_cases = eligible_cases
    comparisons: list[dict[str, Any]] = []

    for coarse, fine in zip(ordered_cases[:-1], ordered_cases[1:]):
        deltas = _coefficient_deltas(coarse, fine, tolerances.keys())
        relative_deltas = _coefficient_relative_deltas(
            coarse,
            fine,
            (relative_tolerances or tolerances).keys(),
            scale_floor=relative_scale_floor,
        )
        missing = sorted(key for key, value in deltas.items() if value is None)
        missing_relative = (
            []
            if relative_tolerances is None
            else sorted(key for key, value in relative_deltas.items() if value is None)
        )
        numeric_deltas = {key: value for key, value in deltas.items() if value is not None}
        numeric_relative_deltas = {
            key: value for key, value in relative_deltas.items() if value is not None
        }
        absolute_stable = not missing and all(
            float(numeric_deltas[key]) <= float(tolerances[key]) for key in tolerances
        )
        relative_stable = (
            True
            if relative_tolerances is None
            else not missing_relative
            and all(
                float(numeric_relative_deltas[key]) <= float(relative_tolerances[key])
                for key in relative_tolerances
            )
        )
        stable = absolute_stable and relative_stable
        comparison = {
            "status": "stable" if stable else "unstable",
            "coarse_case": coarse,
            "fine_case": fine,
            "deltas": numeric_deltas,
            "relative_deltas": numeric_relative_deltas,
            "missing_coefficients": missing,
            "missing_relative_coefficients": missing_relative,
            "coefficient_tolerances": tolerances,
            "coefficient_relative_tolerances": relative_tolerances,
            "relative_scale_floor": float(relative_scale_floor),
        }
        comparisons.append(comparison)
        if stable:
            return {
                "status": "stable_pair_found",
                "selected_case": coarse,
                "compared_to_case": fine,
                "comparison": comparison,
                "comparisons": comparisons,
                "ineligible_cases": ineligible_cases,
                "selection_policy": "cheapest_case_from_first_stable_adjacent_pair",
            }

    return {
        "status": "no_stable_pair",
        "selected_case": None,
        "compared_to_case": None,
        "comparison": None,
        "comparisons": comparisons,
        "ineligible_cases": ineligible_cases,
        "selection_policy": "cheapest_case_from_first_stable_adjacent_pair",
    }


def _coefficient_deltas(
    coarse: Mapping[str, Any],
    fine: Mapping[str, Any],
    coefficient_keys,
) -> dict[str, float | None]:
    coarse_coefficients = _final_coefficients(coarse)
    fine_coefficients = _final_coefficients(fine)
    deltas: dict[str, float | None] = {}
    for key in coefficient_keys:
        left = _coefficient_value(coarse_coefficients, key)
        right = _coefficient_value(fine_coefficients, key)
        if left is None or right is None:
            deltas[key] = None
        else:
            deltas[key] = abs(float(right) - float(left))
    return deltas


def _coefficient_relative_deltas(
    coarse: Mapping[str, Any],
    fine: Mapping[str, Any],
    coefficient_keys,
    *,
    scale_floor: float,
) -> dict[str, float | None]:
    coarse_coefficients = _final_coefficients(coarse)
    fine_coefficients = _final_coefficients(fine)
    deltas: dict[str, float | None] = {}
    for key in coefficient_keys:
        left = _coefficient_value(coarse_coefficients, key)
        right = _coefficient_value(fine_coefficients, key)
        if left is None or right is None:
            deltas[key] = None
        else:
            left_value = float(left)
            right_value = float(right)
            scale = max(abs(left_value), abs(right_value), scale_floor)
            deltas[key] = abs(right_value - left_value) / scale
    return deltas


def _coefficient_value(coefficients: Mapping[str, Any], key: str) -> Any:
    for candidate_key in COEFFICIENT_ALIASES.get(key, (key,)):
        value = coefficients.get(candidate_key)
        if value is not None:
            return value
    return None


def _case_gate_failure_reasons(
    case: Mapping[str, Any],
    *,
    require_iterative_gate_pass: bool,
    require_coefficient_sanity: bool,
    require_cfd_evidence_gate_pass: bool,
) -> list[str]:
    reasons = []
    if case.get("run_status") != "completed":
        reasons.append("run_status_not_completed")
    if case.get("returncode") != 0:
        reasons.append("returncode_nonzero")
    if (case.get("marker_audit") or {}).get("status") != "pass":
        reasons.append("marker_audit_not_pass")
    if (case.get("mesh_quality_gate") or {}).get("status") != "pass":
        reasons.append("mesh_quality_gate_not_pass")
    iterative_gate_status = case.get("iterative_gate_status")
    if iterative_gate_status is None and isinstance(case.get("iterative_gate"), Mapping):
        iterative_gate_status = case["iterative_gate"].get("status")
    if require_iterative_gate_pass and iterative_gate_status != "pass":
        reasons.append("iterative_gate_not_pass")
    if require_coefficient_sanity:
        reasons.extend(_coefficient_sanity_failure_reasons(case))
    if require_cfd_evidence_gate_pass:
        gate = case.get("cfd_evidence_gate")
        if not isinstance(gate, Mapping) or gate.get("status") != "pass":
            reasons.append("cfd_evidence_gate_not_pass")
    return reasons


def _coefficient_sanity_failure_reasons(case: Mapping[str, Any]) -> list[str]:
    coefficients = _final_coefficients(case)
    cd = _coefficient_value(coefficients, "cd")
    if cd is None:
        return ["missing_cd"]
    try:
        cd_value = float(cd)
    except (TypeError, ValueError):
        return ["non_numeric_cd"]
    if not math.isfinite(cd_value):
        return ["non_finite_cd"]
    if cd_value < 0.0:
        return ["negative_cd"]
    return []


def _final_coefficients(case: Mapping[str, Any]) -> Mapping[str, Any]:
    history = case.get("history") or {}
    if not isinstance(history, Mapping):
        return {}
    coefficients = history.get("final_coefficients") or {}
    if not isinstance(coefficients, Mapping):
        return {}
    return coefficients
