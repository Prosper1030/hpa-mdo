from __future__ import annotations

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
    require_successful_case_gates: bool = False,
) -> dict[str, Any]:
    tolerances = dict(coefficient_tolerances or DEFAULT_COEFFICIENT_TOLERANCES)
    ordered_cases = sorted(cases, key=lambda case: int(case["volume_element_count"]))
    ineligible_cases = []
    if require_successful_case_gates:
        eligible_cases = []
        for case in ordered_cases:
            reasons = _case_gate_failure_reasons(case)
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
        missing = sorted(key for key, value in deltas.items() if value is None)
        numeric_deltas = {key: value for key, value in deltas.items() if value is not None}
        stable = not missing and all(
            float(numeric_deltas[key]) <= float(tolerances[key]) for key in tolerances
        )
        comparison = {
            "status": "stable" if stable else "unstable",
            "coarse_case": coarse,
            "fine_case": fine,
            "deltas": numeric_deltas,
            "missing_coefficients": missing,
            "coefficient_tolerances": tolerances,
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


def _coefficient_value(coefficients: Mapping[str, Any], key: str) -> Any:
    for candidate_key in COEFFICIENT_ALIASES.get(key, (key,)):
        value = coefficients.get(candidate_key)
        if value is not None:
            return value
    return None


def _case_gate_failure_reasons(case: Mapping[str, Any]) -> list[str]:
    reasons = []
    if case.get("run_status") != "completed":
        reasons.append("run_status_not_completed")
    if case.get("returncode") != 0:
        reasons.append("returncode_nonzero")
    if (case.get("marker_audit") or {}).get("status") != "pass":
        reasons.append("marker_audit_not_pass")
    if (case.get("mesh_quality_gate") or {}).get("status") != "pass":
        reasons.append("mesh_quality_gate_not_pass")
    return reasons


def _final_coefficients(case: Mapping[str, Any]) -> Mapping[str, Any]:
    history = case.get("history") or {}
    if not isinstance(history, Mapping):
        return {}
    coefficients = history.get("final_coefficients") or {}
    if not isinstance(coefficients, Mapping):
        return {}
    return coefficients
