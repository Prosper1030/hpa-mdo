#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any, Iterable


CSV_FILENAME = "profile_cd_source_comparison.csv"
MD_FILENAME = "profile_cd_source_comparison.md"
DEFAULT_OUTPUT_DIR = Path("output/profile_cd_source_comparison")
DEFAULT_OUTPUT_ROOT = Path("output")
RATIO_LOWER_BOUND = 0.8
RATIO_UPPER_BOUND = 1.2


CSV_FIELDS = [
    "pool_name",
    "pool_path",
    "candidate_id",
    "rank",
    "overall_rank",
    "profile_cd_proxy",
    "profile_cd_proxy_source",
    "profile_cd_proxy_quality",
    "profile_cd_zone_chord_weighted",
    "profile_cd_zone_source",
    "profile_cd_zone_quality",
    "profile_cd_zone_vs_proxy_delta",
    "profile_cd_zone_vs_proxy_ratio",
    "mean_cd_effective",
    "ratio_outside_0p8_1p2",
    "needs_rerun_for_zone_diagnostic",
    "current_drag_budget_band",
    "estimated_zone_drag_budget_band",
    "drag_budget_band_change_judgment",
]


def _get_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _finite(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and isfinite(float(value))]


def _stats(values: Iterable[float | None]) -> tuple[float | None, float | None, float | None]:
    numbers = _finite(values)
    if not numbers:
        return None, None, None
    return float(min(numbers)), float(median(numbers)), float(max(numbers))


def _count_strings(values: Iterable[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _fmt(value: float | int | str | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _fmt_csv(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.12g}"
    return value


def _fmt_stats(summary: dict[str, Any], prefix: str) -> str:
    return (
        f"{_fmt(summary.get(f'{prefix}_min'))} / "
        f"{_fmt(summary.get(f'{prefix}_median'))} / "
        f"{_fmt(summary.get(f'{prefix}_max'))}"
    )


def _json_counts(counts: dict[str, int]) -> str:
    return json.dumps(counts, sort_keys=True, ensure_ascii=False)


def discover_ranked_pool_paths(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> list[Path]:
    output_root = Path(output_root)
    if not output_root.exists():
        return []
    return sorted(output_root.glob("*/concept_ranked_pool.json"))


def _load_shadow_rows(pool_path: Path) -> dict[str, dict[str, str]]:
    shadow_csv = pool_path.parent / "mission_drag_budget_shadow.csv"
    if not shadow_csv.is_file():
        return {}
    with shadow_csv.open(newline="", encoding="utf-8") as handle:
        return {
            str(row.get("candidate_id", "")): dict(row)
            for row in csv.DictReader(handle)
            if row.get("candidate_id")
        }


def _load_shadow_thresholds(pool_path: Path) -> dict[str, float]:
    summary_path = pool_path.parent / "mission_drag_budget_shadow_summary.json"
    if not summary_path.is_file():
        return {}
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    thresholds = summary.get("budget_thresholds", {})
    if not isinstance(thresholds, dict):
        return {}
    out: dict[str, float] = {}
    for key in ("cd0_total_target", "cd0_total_boundary", "cd0_total_rescue"):
        value = _get_float(thresholds, key)
        if value is not None:
            out[key] = value
    return out


def _band_for_cd0_total(cd0_total: float, thresholds: dict[str, float]) -> str | None:
    target = thresholds.get("cd0_total_target")
    boundary = thresholds.get("cd0_total_boundary")
    rescue = thresholds.get("cd0_total_rescue")
    if target is None or boundary is None or rescue is None:
        return None
    if cd0_total <= target:
        return "target"
    if cd0_total <= boundary:
        return "boundary"
    if cd0_total <= rescue:
        return "rescue"
    return "over_budget"


def _drag_band_judgment(
    *,
    candidate_id: str,
    delta: float | None,
    shadow_rows: dict[str, dict[str, str]],
    thresholds: dict[str, float],
    zone_available: bool,
) -> tuple[str | None, str | None, str]:
    if not zone_available:
        return None, None, "not_assessed_zone_unavailable"
    if not shadow_rows:
        return None, None, "not_assessed_no_shadow_output"
    shadow = shadow_rows.get(candidate_id)
    if shadow is None:
        return None, None, "not_assessed_missing_shadow_row"
    current_band = str(shadow.get("drag_budget_band") or "unknown")
    try:
        current_cd0_total = float(shadow.get("cd0_total_est") or "nan")
    except ValueError:
        current_cd0_total = float("nan")
    if delta is None or not isfinite(current_cd0_total):
        return current_band, None, "not_assessed_missing_shadow_fields"
    estimated_band = _band_for_cd0_total(current_cd0_total + float(delta), thresholds)
    if estimated_band is None:
        return current_band, None, "not_assessed_missing_budget_thresholds"
    if estimated_band != current_band:
        return current_band, estimated_band, "estimated_band_change"
    return current_band, estimated_band, "estimated_band_same"


def _row_from_candidate(
    *,
    pool_path: Path,
    candidate: dict[str, Any],
    index: int,
    shadow_rows: dict[str, dict[str, str]],
    thresholds: dict[str, float],
    ratio_lower_bound: float,
    ratio_upper_bound: float,
) -> dict[str, Any]:
    mission = candidate.get("mission", {})
    if not isinstance(mission, dict):
        mission = {}
    feedback = candidate.get("airfoil_feedback", {})
    if not isinstance(feedback, dict):
        feedback = {}

    candidate_id = str(
        candidate.get("concept_id")
        or candidate.get("evaluation_id")
        or f"candidate-{index:04d}"
    )
    proxy_cd = _get_float(mission, "profile_cd_proxy")
    zone_cd = _get_float(mission, "profile_cd_zone_chord_weighted")
    delta = _get_float(mission, "profile_cd_zone_vs_proxy_delta")
    ratio = _get_float(mission, "profile_cd_zone_vs_proxy_ratio")
    if zone_cd is not None and proxy_cd is not None:
        if delta is None:
            delta = float(zone_cd - proxy_cd)
        if ratio is None and proxy_cd != 0.0:
            ratio = float(zone_cd / proxy_cd)

    zone_available = zone_cd is not None
    zone_source = (
        str(mission.get("profile_cd_zone_source"))
        if zone_available and mission.get("profile_cd_zone_source")
        else "zone_unavailable"
    )
    zone_quality = (
        str(mission.get("profile_cd_zone_quality"))
        if zone_available and mission.get("profile_cd_zone_quality")
        else "zone_unavailable"
    )
    current_band, estimated_band, band_judgment = _drag_band_judgment(
        candidate_id=candidate_id,
        delta=delta,
        shadow_rows=shadow_rows,
        thresholds=thresholds,
        zone_available=zone_available,
    )

    ratio_outside = (
        ratio is not None
        and (float(ratio) < float(ratio_lower_bound) or float(ratio) > float(ratio_upper_bound))
    )
    return {
        "pool_name": pool_path.parent.name,
        "pool_path": str(pool_path),
        "candidate_id": candidate_id,
        "rank": candidate.get("rank"),
        "overall_rank": candidate.get("overall_rank"),
        "profile_cd_proxy": proxy_cd,
        "profile_cd_proxy_source": str(mission.get("profile_cd_proxy_source") or "unknown"),
        "profile_cd_proxy_quality": str(mission.get("profile_cd_proxy_quality") or "unknown"),
        "profile_cd_zone_chord_weighted": zone_cd,
        "profile_cd_zone_source": zone_source,
        "profile_cd_zone_quality": zone_quality,
        "profile_cd_zone_vs_proxy_delta": delta,
        "profile_cd_zone_vs_proxy_ratio": ratio,
        "mean_cd_effective": _get_float(feedback, "mean_cd_effective"),
        "ratio_outside_0p8_1p2": bool(ratio_outside),
        "needs_rerun_for_zone_diagnostic": not zone_available,
        "current_drag_budget_band": current_band,
        "estimated_zone_drag_budget_band": estimated_band,
        "drag_budget_band_change_judgment": band_judgment,
    }


def _rows_for_pool(
    pool_path: Path,
    *,
    ratio_lower_bound: float,
    ratio_upper_bound: float,
) -> list[dict[str, Any]]:
    payload = json.loads(Path(pool_path).read_text(encoding="utf-8"))
    candidates = payload.get("ranked_pool", [])
    if not isinstance(candidates, list):
        candidates = []
    shadow_rows = _load_shadow_rows(Path(pool_path))
    thresholds = _load_shadow_thresholds(Path(pool_path))
    return [
        _row_from_candidate(
            pool_path=Path(pool_path),
            candidate=candidate if isinstance(candidate, dict) else {},
            index=index,
            shadow_rows=shadow_rows,
            thresholds=thresholds,
            ratio_lower_bound=ratio_lower_bound,
            ratio_upper_bound=ratio_upper_bound,
        )
        for index, candidate in enumerate(candidates, start=1)
    ]


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    proxy_min, proxy_median, proxy_max = _stats(
        row.get("profile_cd_proxy") for row in rows
    )
    zone_min, zone_median, zone_max = _stats(
        row.get("profile_cd_zone_chord_weighted") for row in rows
    )
    ratio_min, ratio_median, ratio_max = _stats(
        row.get("profile_cd_zone_vs_proxy_ratio") for row in rows
    )
    zone_available_count = sum(
        1 for row in rows if row.get("profile_cd_zone_chord_weighted") is not None
    )
    band_counts = _count_strings(
        str(row.get("drag_budget_band_change_judgment") or "unknown") for row in rows
    )
    if band_counts.get("estimated_band_change", 0) > 0:
        band_judgment = "possible_change_estimated_from_shadow_outputs"
    elif band_counts.get("estimated_band_same", 0) > 0:
        band_judgment = "no_change_estimated_for_available_shadow_outputs"
    elif zone_available_count == 0:
        band_judgment = "not_assessed_zone_unavailable"
    else:
        band_judgment = "not_assessed_no_shadow_output"

    return {
        "candidate_count": len(rows),
        "profile_cd_proxy_min": proxy_min,
        "profile_cd_proxy_median": proxy_median,
        "profile_cd_proxy_max": proxy_max,
        "profile_cd_zone_min": zone_min,
        "profile_cd_zone_median": zone_median,
        "profile_cd_zone_max": zone_max,
        "zone_proxy_ratio_min": ratio_min,
        "zone_proxy_ratio_median": ratio_median,
        "zone_proxy_ratio_max": ratio_max,
        "zone_available_count": zone_available_count,
        "zone_unavailable_count": len(rows) - zone_available_count,
        "profile_cd_proxy_quality_counts": _count_strings(
            str(row.get("profile_cd_proxy_quality") or "unknown") for row in rows
        ),
        "profile_cd_zone_quality_counts": _count_strings(
            str(row.get("profile_cd_zone_quality") or "zone_unavailable") for row in rows
        ),
        "ratio_outlier_count": sum(
            1 for row in rows if bool(row.get("ratio_outside_0p8_1p2"))
        ),
        "drag_budget_band_change_counts": band_counts,
        "drag_budget_band_preliminary_judgment": band_judgment,
        "needs_rerun_for_zone_diagnostic": any(
            bool(row.get("needs_rerun_for_zone_diagnostic")) for row in rows
        ),
    }


def _summaries_by_pool(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["pool_path"]), []).append(row)
    summaries: list[dict[str, Any]] = []
    for pool_path, pool_rows in grouped.items():
        summary = _summarize_rows(pool_rows)
        summary["pool_name"] = str(pool_rows[0]["pool_name"])
        summary["pool_path"] = pool_path
        summaries.append(summary)
    summaries.sort(key=lambda item: str(item["pool_name"]))
    return summaries


def _write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _fmt_csv(row.get(field)) for field in CSV_FIELDS})


def _build_markdown(
    *,
    pool_summaries: list[dict[str, Any]],
    overall_summary: dict[str, Any],
    ratio_outliers: list[dict[str, Any]],
    ratio_lower_bound: float,
    ratio_upper_bound: float,
) -> str:
    lines = [
        "# Profile CD Source Comparison",
        "",
        "Diagnostic comparison only: this report reads existing ranked-pool artifacts and does not change pipeline behavior, profile CD formulas, ranking, objective, or gates.",
        "",
        "## Overall",
        "",
        f"- ranked pool count: {_fmt(overall_summary.get('pool_count'))}",
        f"- candidate count: {_fmt(overall_summary.get('candidate_count'))}",
        f"- zone available / unavailable count: {_fmt(overall_summary.get('zone_available_count'))} / {_fmt(overall_summary.get('zone_unavailable_count'))}",
        f"- profile_cd_proxy min / median / max: {_fmt_stats(overall_summary, 'profile_cd_proxy')}",
        f"- zone profile CD min / median / max: {_fmt_stats(overall_summary, 'profile_cd_zone')}",
        f"- zone/proxy ratio min / median / max: {_fmt_stats(overall_summary, 'zone_proxy_ratio')}",
        f"- ratio outliers outside {_fmt(ratio_lower_bound)}~{_fmt(ratio_upper_bound)}: {_fmt(overall_summary.get('ratio_outlier_count'))}",
        f"- preliminary drag_budget_band judgment if zone CD were used: {overall_summary.get('drag_budget_band_preliminary_judgment')}",
        "",
        "## Per Ranked Pool",
        "",
        "| ranked pool | candidates | proxy cd min/median/max | zone cd min/median/max | zone/proxy min/median/max | zone available/unavailable | profile quality counts | zone quality counts | preliminary drag_budget_band judgment |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for summary in pool_summaries:
        lines.append(
            "| "
            f"{summary['pool_name']} | "
            f"{summary['candidate_count']} | "
            f"{_fmt_stats(summary, 'profile_cd_proxy')} | "
            f"{_fmt_stats(summary, 'profile_cd_zone')} | "
            f"{_fmt_stats(summary, 'zone_proxy_ratio')} | "
            f"{summary['zone_available_count']} / {summary['zone_unavailable_count']} | "
            f"{_json_counts(summary['profile_cd_proxy_quality_counts'])} | "
            f"{_json_counts(summary['profile_cd_zone_quality_counts'])} | "
            f"{summary['drag_budget_band_preliminary_judgment']} |"
        )

    rerun_pools = [
        summary for summary in pool_summaries if summary["needs_rerun_for_zone_diagnostic"]
    ]
    lines.extend(
        [
            "",
            "## Ratio Outliers",
            "",
            f"Candidates below {_fmt(ratio_lower_bound)} or above {_fmt(ratio_upper_bound)}:",
            "",
            "| ranked pool | candidate_id | proxy_cd | zone_cd | delta | zone/proxy | proxy_quality | zone_quality |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    if not ratio_outliers:
        lines.append("| none | none | n/a | n/a | n/a | n/a | n/a | n/a |")
    else:
        for row in ratio_outliers:
            lines.append(
                "| "
                f"{row['pool_name']} | "
                f"{row['candidate_id']} | "
                f"{_fmt(row.get('profile_cd_proxy'))} | "
                f"{_fmt(row.get('profile_cd_zone_chord_weighted'))} | "
                f"{_fmt(row.get('profile_cd_zone_vs_proxy_delta'))} | "
                f"{_fmt(row.get('profile_cd_zone_vs_proxy_ratio'))} | "
                f"{row.get('profile_cd_proxy_quality')} | "
                f"{row.get('profile_cd_zone_quality')} |"
            )

    lines.extend(
        [
            "",
            "## Pools Needing Rerun For Zone Diagnostic",
            "",
            "舊 ranked pool 若沒有 zone diagnostic 欄位，會標記為 `zone_unavailable`；需要重新跑 pipeline 才能取得 zone diagnostic。",
            "",
        ]
    )
    if not rerun_pools:
        lines.append("- none")
    else:
        for summary in rerun_pools:
            lines.append(
                f"- {summary['pool_name']}: "
                f"{summary['zone_unavailable_count']} / {summary['candidate_count']} candidates need rerun"
            )

    lines.extend(
        [
            "",
            "## Drag Budget Band Preliminary Judgment",
            "",
            "The script only estimates possible band changes when an existing `mission_drag_budget_shadow.csv` and `mission_drag_budget_shadow_summary.json` are present beside the ranked pool. It keeps the shadow non-wing CD0 and thresholds fixed, adds the zone/proxy delta to `cd0_total_est`, and compares the resulting band. This is an audit hint, not a replacement for rerunning the pipeline or shadow evaluator.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_comparison(
    *,
    ranked_pool_paths: list[Path] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    ratio_lower_bound: float = RATIO_LOWER_BOUND,
    ratio_upper_bound: float = RATIO_UPPER_BOUND,
) -> dict[str, Any]:
    paths = (
        discover_ranked_pool_paths(output_root=output_root)
        if ranked_pool_paths is None
        else [Path(path) for path in ranked_pool_paths]
    )
    paths = sorted(paths)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(
            _rows_for_pool(
                Path(path),
                ratio_lower_bound=ratio_lower_bound,
                ratio_upper_bound=ratio_upper_bound,
            )
        )

    pool_summaries = _summaries_by_pool(rows)
    overall_summary = _summarize_rows(rows)
    overall_summary["pool_count"] = len(pool_summaries)
    ratio_outliers = [
        row for row in rows if bool(row.get("ratio_outside_0p8_1p2"))
    ]
    ratio_outliers.sort(
        key=lambda row: (
            str(row.get("pool_name")),
            str(row.get("candidate_id")),
        )
    )

    csv_path = output_dir / CSV_FILENAME
    md_path = output_dir / MD_FILENAME
    _write_csv(rows, csv_path)
    md_path.write_text(
        _build_markdown(
            pool_summaries=pool_summaries,
            overall_summary=overall_summary,
            ratio_outliers=ratio_outliers,
            ratio_lower_bound=ratio_lower_bound,
            ratio_upper_bound=ratio_upper_bound,
        ),
        encoding="utf-8",
    )

    return {
        "csv_path": str(csv_path),
        "markdown_path": str(md_path),
        "overall": overall_summary,
        "pools": pool_summaries,
        "ratio_outliers": ratio_outliers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare profile_cd_proxy and zone diagnostic profile CD across ranked pools."
    )
    parser.add_argument(
        "ranked_pool_json",
        nargs="*",
        type=Path,
        help="Optional concept_ranked_pool.json paths. If omitted, discover under output/.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for profile_cd_source_comparison.csv/.md.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root used for discovery when no ranked pools are provided.",
    )
    parser.add_argument("--ratio-lower-bound", type=float, default=RATIO_LOWER_BOUND)
    parser.add_argument("--ratio-upper-bound", type=float, default=RATIO_UPPER_BOUND)
    args = parser.parse_args()

    summary = run_comparison(
        ranked_pool_paths=args.ranked_pool_json or None,
        output_dir=args.output_dir,
        output_root=args.output_root,
        ratio_lower_bound=args.ratio_lower_bound,
        ratio_upper_bound=args.ratio_upper_bound,
    )
    overall = summary["overall"]
    print(f"wrote {summary['csv_path']}")
    print(f"wrote {summary['markdown_path']}")
    print(
        "overall zone/proxy ratio min/median/max = "
        f"{_fmt_stats(overall, 'zone_proxy_ratio')}"
    )
    print(f"ratio outliers = {overall['ratio_outlier_count']}")


if __name__ == "__main__":
    main()
