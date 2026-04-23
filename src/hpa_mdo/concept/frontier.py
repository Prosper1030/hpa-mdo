from __future__ import annotations

from collections import Counter
from statistics import fmean, median
from typing import Any, Iterable, Mapping

_FAILURE_GATES: tuple[tuple[str, str], ...] = (
    ("launch", "launch"),
    ("turn", "turn"),
    ("trim", "trim"),
    ("local_stall", "local_stall"),
    ("mission", "mission"),
)


def _gate_feasible(record: Mapping[str, Any], gate: str) -> bool:
    payload = record.get(gate, {})
    if not isinstance(payload, Mapping):
        return False
    if gate == "mission":
        return bool(payload.get("mission_feasible", False))
    return bool(payload.get("feasible", False))


def failure_signature(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(label for gate, label in _FAILURE_GATES if not _gate_feasible(record, gate))


def _numeric_stats(values: Iterable[float | int | None]) -> dict[str, Any]:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "mean": None,
            "max": None,
        }
    return {
        "count": len(numeric),
        "min": min(numeric),
        "median": median(numeric),
        "mean": fmean(numeric),
        "max": max(numeric),
    }


def _top_counts(counter: Counter[str], *, key_name: str) -> list[dict[str, Any]]:
    return [
        {key_name: label, "count": count}
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _geometry_subset_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "span_m": _numeric_stats(record.get("span_m") for record in records),
        "wing_loading_target_Npm2": _numeric_stats(
            record.get("wing_loading_target_Npm2") for record in records
        ),
        "wing_area_m2": _numeric_stats(record.get("wing_area_m2") for record in records),
        "aspect_ratio": _numeric_stats(record.get("aspect_ratio") for record in records),
    }


def _margin_subset_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "combined_feasibility_margin": _numeric_stats(
            (
                record.get("ranking", {}).get("combined_feasibility_margin")
                if isinstance(record.get("ranking"), Mapping)
                else None
            )
            for record in records
        ),
        "mission_margin_m": _numeric_stats(
            (
                record.get("ranking", {}).get("mission_margin_m")
                if isinstance(record.get("ranking"), Mapping)
                else None
            )
            for record in records
        ),
        "best_range_m": _numeric_stats(
            (
                record.get("mission", {}).get("best_range_m")
                if isinstance(record.get("mission"), Mapping)
                else None
            )
            for record in records
        ),
        "required_wing_area_for_local_stall_limit_m2": _numeric_stats(
            (
                record.get("local_stall", {}).get("required_wing_area_for_limit_m2")
                if isinstance(record.get("local_stall"), Mapping)
                else None
            )
            for record in records
        ),
        "delta_wing_area_for_local_stall_limit_m2": _numeric_stats(
            (
                record.get("local_stall", {}).get("delta_wing_area_for_limit_m2")
                if isinstance(record.get("local_stall"), Mapping)
                else None
            )
            for record in records
        ),
        "launch_stall_utilization": _numeric_stats(
            (
                record.get("launch", {}).get("stall_utilization")
                if isinstance(record.get("launch"), Mapping)
                else None
            )
            for record in records
        ),
        "local_stall_utilization": _numeric_stats(
            (
                record.get("local_stall", {}).get("stall_utilization")
                if isinstance(record.get("local_stall"), Mapping)
                else None
            )
            for record in records
        ),
    }


def _gate_failure_counts(records: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        label: sum(0 if _gate_feasible(record, gate) else 1 for record in records)
        for gate, label in _FAILURE_GATES
    }


def _failure_signature_counts(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        signature = failure_signature(record)
        if signature:
            counter["+".join(signature)] += 1
    return _top_counts(counter, key_name="signature")


def _mission_limiter_counts(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        mission = record.get("mission", {})
        if not isinstance(mission, Mapping):
            continue
        if bool(mission.get("mission_feasible", False)):
            continue
        limiter_audit = mission.get("limiter_audit", {})
        if not isinstance(limiter_audit, Mapping):
            continue
        limiter = limiter_audit.get("dominant_limiter")
        if limiter is not None:
            counter[str(limiter)] += 1
    return _top_counts(counter, key_name="limiter")


def build_frontier_summary(
    records: Iterable[Mapping[str, Any]],
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    ordered = sorted(
        [dict(record) for record in records],
        key=lambda item: int(item.get("overall_rank", 10**9)),
    )
    frontier_size = max(1, int(top_n))
    top_ranked = ordered[:frontier_size]
    fully_feasible = [
        record for record in ordered if bool(record.get("ranking", {}).get("fully_feasible", False))
    ]
    safety_feasible = [
        record for record in ordered if bool(record.get("ranking", {}).get("safety_feasible", False))
    ]
    mission_feasible = [
        record
        for record in ordered
        if isinstance(record.get("mission"), Mapping)
        and bool(record["mission"].get("mission_feasible", False))
    ]
    best_infeasible = [
        record for record in ordered if not bool(record.get("ranking", {}).get("fully_feasible", False))
    ][:frontier_size]

    subsets = {
        "overall": ordered,
        "top_ranked": top_ranked,
        "fully_feasible": fully_feasible,
        "safety_feasible": safety_feasible,
        "mission_feasible": mission_feasible,
        "best_infeasible": best_infeasible,
    }

    return {
        "counts": {
            "evaluated_count": len(ordered),
            "frontier_count": len(top_ranked),
            "fully_feasible_count": len(fully_feasible),
            "safety_feasible_count": len(safety_feasible),
            "mission_feasible_count": len(mission_feasible),
            "best_infeasible_count": len(ordered) - len(fully_feasible),
        },
        "failure_gate_counts": {
            name: _gate_failure_counts(records_subset) for name, records_subset in subsets.items()
        },
        "dominant_failure_signatures": {
            name: _failure_signature_counts(records_subset) for name, records_subset in subsets.items()
        },
        "mission_dominant_limiters": {
            name: _mission_limiter_counts(records_subset) for name, records_subset in subsets.items()
        },
        "geometry_subsets": {
            name: _geometry_subset_summary(records_subset) for name, records_subset in subsets.items()
        },
        "margin_subsets": {
            name: _margin_subset_summary(records_subset) for name, records_subset in subsets.items()
        },
    }
