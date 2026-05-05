#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any, Iterable


CSV_FILENAME = "profile_cd_source_sensitivity.csv"
MD_FILENAME = "profile_cd_source_sensitivity.md"
DEFAULT_OUTPUT_DIR = Path("output/profile_cd_source_comparison")
DEFAULT_OUTPUT_ROOT = Path("output")


CSV_FIELDS = [
    "pool_name",
    "pool_path",
    "candidate_id",
    "original_order",
    "rank",
    "overall_rank",
    "rank_bucket",
    "is_top10",
    "profile_cd_proxy",
    "profile_cd_proxy_quality",
    "profile_cd_zone_chord_weighted",
    "profile_cd_zone_quality",
    "profile_cd_zone_vs_proxy_delta",
    "profile_cd_zone_vs_proxy_ratio",
    "pool_ratio_median",
    "ratio_delta_from_pool_median",
    "sensitivity_status",
    "cd0_total_est",
    "drag_budget_band",
    "cd0_wing_profile",
    "cda_nonwing_m2",
    "wing_area_m2",
    "cd0_total_est_if_zone",
    "drag_budget_band_if_zone",
    "band_change",
    "band_change_direction",
    "band_sensitivity_status",
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


def _fmt(value: float | int | str | bool | None) -> str:
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


def _count_strings(values: Iterable[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def discover_ranked_pool_paths(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> list[Path]:
    output_root = Path(output_root)
    if not output_root.exists():
        return []
    return sorted(output_root.glob("*/concept_ranked_pool.json"))


def _load_ranked_pool(pool_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(pool_path).read_text(encoding="utf-8"))
    candidates = payload.get("ranked_pool", []) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        return []
    return [candidate if isinstance(candidate, dict) else {} for candidate in candidates]


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


def _candidate_id(candidate: dict[str, Any], index: int) -> str:
    return str(
        candidate.get("concept_id")
        or candidate.get("evaluation_id")
        or f"candidate-{index:04d}"
    )


def _rank_bucket(order: int) -> str:
    if order <= 10:
        return "top_10"
    if order <= 25:
        return "rank_11_25"
    if order <= 50:
        return "rank_26_50"
    return "rank_51_plus"


def _band_sensitivity(
    *,
    candidate_id: str,
    zone_cd: float | None,
    shadow_rows: dict[str, dict[str, str]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    if zone_cd is None:
        return {
            "cd0_total_est": None,
            "drag_budget_band": None,
            "cd0_wing_profile": None,
            "cda_nonwing_m2": None,
            "wing_area_m2": None,
            "cd0_total_est_if_zone": None,
            "drag_budget_band_if_zone": None,
            "band_change": False,
            "band_change_direction": None,
            "band_sensitivity_status": "zone_unavailable",
        }
    if not shadow_rows:
        return {
            "cd0_total_est": None,
            "drag_budget_band": None,
            "cd0_wing_profile": None,
            "cda_nonwing_m2": None,
            "wing_area_m2": None,
            "cd0_total_est_if_zone": None,
            "drag_budget_band_if_zone": None,
            "band_change": False,
            "band_change_direction": None,
            "band_sensitivity_status": "no_shadow_output",
        }
    shadow = shadow_rows.get(candidate_id)
    if shadow is None:
        return {
            "cd0_total_est": None,
            "drag_budget_band": None,
            "cd0_wing_profile": None,
            "cda_nonwing_m2": None,
            "wing_area_m2": None,
            "cd0_total_est_if_zone": None,
            "drag_budget_band_if_zone": None,
            "band_change": False,
            "band_change_direction": None,
            "band_sensitivity_status": "missing_shadow_row",
        }

    cd0_total = _get_float(shadow, "cd0_total_est")
    cd0_wing_profile = _get_float(shadow, "cd0_wing_profile")
    cda_nonwing = _get_float(shadow, "cda_nonwing_m2")
    wing_area = _get_float(shadow, "wing_area_m2")
    current_band = str(shadow.get("drag_budget_band") or "unknown")
    if cda_nonwing is None or wing_area is None or wing_area == 0.0:
        status = "missing_shadow_fields"
        cd0_if_zone = None
    else:
        status = "ok"
        cd0_if_zone = float(zone_cd + cda_nonwing / wing_area)

    band_if_zone = (
        _band_for_cd0_total(cd0_if_zone, thresholds)
        if cd0_if_zone is not None
        else None
    )
    if status == "ok" and band_if_zone is None:
        status = "missing_budget_thresholds"
    band_change = bool(band_if_zone is not None and band_if_zone != current_band)
    direction = f"{current_band}_to_{band_if_zone}" if band_change else None
    return {
        "cd0_total_est": cd0_total,
        "drag_budget_band": current_band,
        "cd0_wing_profile": cd0_wing_profile,
        "cda_nonwing_m2": cda_nonwing,
        "wing_area_m2": wing_area,
        "cd0_total_est_if_zone": cd0_if_zone,
        "drag_budget_band_if_zone": band_if_zone,
        "band_change": band_change,
        "band_change_direction": direction,
        "band_sensitivity_status": status,
    }


def _rows_for_pool(pool_path: Path) -> list[dict[str, Any]]:
    pool_path = Path(pool_path)
    candidates = _load_ranked_pool(pool_path)
    shadow_rows = _load_shadow_rows(pool_path)
    thresholds = _load_shadow_thresholds(pool_path)
    rows: list[dict[str, Any]] = []
    ratios: list[float] = []
    pending_ratio_rows: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates, start=1):
        mission = candidate.get("mission", {})
        if not isinstance(mission, dict):
            mission = {}

        candidate_id = _candidate_id(candidate, index)
        proxy_cd = _get_float(mission, "profile_cd_proxy")
        zone_cd = _get_float(mission, "profile_cd_zone_chord_weighted")
        delta = _get_float(mission, "profile_cd_zone_vs_proxy_delta")
        ratio = _get_float(mission, "profile_cd_zone_vs_proxy_ratio")
        if zone_cd is not None and proxy_cd is not None:
            if delta is None:
                delta = float(zone_cd - proxy_cd)
            if ratio is None and proxy_cd != 0.0:
                ratio = float(zone_cd / proxy_cd)
        if ratio is not None:
            ratios.append(ratio)

        status = "ok" if zone_cd is not None and ratio is not None else "zone_unavailable"
        row = {
            "pool_name": pool_path.parent.name,
            "pool_path": str(pool_path),
            "candidate_id": candidate_id,
            "original_order": index,
            "rank": candidate.get("rank"),
            "overall_rank": candidate.get("overall_rank"),
            "rank_bucket": _rank_bucket(index),
            "is_top10": index <= 10,
            "profile_cd_proxy": proxy_cd,
            "profile_cd_proxy_quality": str(mission.get("profile_cd_proxy_quality") or "unknown"),
            "profile_cd_zone_chord_weighted": zone_cd,
            "profile_cd_zone_quality": (
                str(mission.get("profile_cd_zone_quality"))
                if zone_cd is not None and mission.get("profile_cd_zone_quality")
                else "zone_unavailable"
            ),
            "profile_cd_zone_vs_proxy_delta": delta,
            "profile_cd_zone_vs_proxy_ratio": ratio,
            "pool_ratio_median": None,
            "ratio_delta_from_pool_median": None,
            "sensitivity_status": status,
        }
        row.update(
            _band_sensitivity(
                candidate_id=candidate_id,
                zone_cd=zone_cd,
                shadow_rows=shadow_rows,
                thresholds=thresholds,
            )
        )
        rows.append(row)
        if ratio is not None:
            pending_ratio_rows.append(row)

    pool_ratio_median = float(median(ratios)) if ratios else None
    for row in pending_ratio_rows:
        row["pool_ratio_median"] = pool_ratio_median
        if pool_ratio_median is not None:
            row["ratio_delta_from_pool_median"] = float(
                row["profile_cd_zone_vs_proxy_ratio"] - pool_ratio_median
            )
    return rows


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ratio_min, ratio_median, ratio_max = _stats(
        row.get("profile_cd_zone_vs_proxy_ratio") for row in rows
    )
    top10 = [row for row in rows if bool(row.get("is_top10"))]
    top10_ratios = [row.get("profile_cd_zone_vs_proxy_ratio") for row in top10]
    top10_min, top10_median, top10_max = _stats(top10_ratios)
    zone_available_count = sum(
        1 for row in rows if row.get("profile_cd_zone_chord_weighted") is not None
    )
    band_change_rows = [row for row in rows if bool(row.get("band_change"))]
    assessed_no_change = sum(
        1
        for row in rows
        if row.get("band_sensitivity_status") == "ok" and not row.get("band_change")
    )
    directions = _count_strings(
        str(row.get("band_change_direction")) for row in band_change_rows
    )
    top10_delta = (
        float(top10_median - ratio_median)
        if top10_median is not None and ratio_median is not None
        else None
    )
    top10_stability = (
        "unavailable"
        if top10_delta is None
        else ("stable" if abs(top10_delta) <= 0.05 else "shifted")
    )
    bucket_distribution: dict[str, dict[str, Any]] = {}
    for bucket in ("top_10", "rank_11_25", "rank_26_50", "rank_51_plus"):
        bucket_rows = [row for row in rows if row.get("rank_bucket") == bucket]
        bmin, bmedian, bmax = _stats(
            row.get("profile_cd_zone_vs_proxy_ratio") for row in bucket_rows
        )
        bucket_distribution[bucket] = {
            "candidate_count": len(bucket_rows),
            "ratio_min": bmin,
            "ratio_median": bmedian,
            "ratio_max": bmax,
        }

    return {
        "candidate_count": len(rows),
        "zone_available_count": zone_available_count,
        "zone_unavailable_count": len(rows) - zone_available_count,
        "zone_proxy_ratio_min": ratio_min,
        "zone_proxy_ratio_median": ratio_median,
        "zone_proxy_ratio_max": ratio_max,
        "top10_ratio_min": top10_min,
        "top10_ratio_median": top10_median,
        "top10_ratio_max": top10_max,
        "top10_vs_pool_median_delta": top10_delta,
        "top10_ratio_stability": top10_stability,
        "ratio_outside_0p9_1p1_count": sum(
            1
            for row in rows
            if row.get("profile_cd_zone_vs_proxy_ratio") is not None
            and (
                row["profile_cd_zone_vs_proxy_ratio"] < 0.9
                or row["profile_cd_zone_vs_proxy_ratio"] > 1.1
            )
        ),
        "band_change_count": len(band_change_rows),
        "band_change_directions": directions,
        "target_to_boundary_count": directions.get("target_to_boundary", 0),
        "boundary_to_target_count": directions.get("boundary_to_target", 0),
        "over_budget_to_boundary_count": directions.get("over_budget_to_boundary", 0),
        "no_change_count": assessed_no_change,
        "band_sensitivity_status_counts": _count_strings(
            str(row.get("band_sensitivity_status") or "unknown") for row in rows
        ),
        "rank_bucket_distribution": bucket_distribution,
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


def _top_ratio_rows(rows: list[dict[str, Any]], reverse: bool) -> list[dict[str, Any]]:
    available = [
        row for row in rows if row.get("profile_cd_zone_vs_proxy_ratio") is not None
    ]
    return sorted(
        available,
        key=lambda row: float(row["profile_cd_zone_vs_proxy_ratio"]),
        reverse=reverse,
    )


def _build_markdown(
    *,
    rows: list[dict[str, Any]],
    pool_summaries: list[dict[str, Any]],
    overall_summary: dict[str, Any],
    band_change_candidates: list[dict[str, Any]],
) -> str:
    lines = [
        "# Profile CD Source Sensitivity",
        "",
        "Diagnostic sensitivity only: this report estimates candidate-order and drag-budget-band sensitivity from existing artifacts. It does not change pipeline behavior, profile CD formulas, ranking, objective, gates, penalties, or optimizer behavior.",
        "",
        "## Overall",
        "",
        f"- ranked pool count: {_fmt(overall_summary.get('pool_count'))}",
        f"- candidate count: {_fmt(overall_summary.get('candidate_count'))}",
        f"- zone available / unavailable count: {_fmt(overall_summary.get('zone_available_count'))} / {_fmt(overall_summary.get('zone_unavailable_count'))}",
        f"- zone/proxy ratio min / median / max: {_fmt_stats(overall_summary, 'zone_proxy_ratio')}",
        f"- ratio outside 0.9~1.1: {_fmt(overall_summary.get('ratio_outside_0p9_1p1_count'))}",
        f"- band_change_count: {_fmt(overall_summary.get('band_change_count'))}",
        f"- target_to_boundary_count: {_fmt(overall_summary.get('target_to_boundary_count'))}",
        f"- boundary_to_target_count: {_fmt(overall_summary.get('boundary_to_target_count'))}",
        f"- over_budget_to_boundary_count: {_fmt(overall_summary.get('over_budget_to_boundary_count'))}",
        f"- no_change_count: {_fmt(overall_summary.get('no_change_count'))}",
        "",
        "## Per Ranked Pool",
        "",
        "| ranked pool | candidates | zone available/unavailable | zone/proxy min/median/max | top10 ratio min/median/max | top10 vs pool median | top ratio stability | band changes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for summary in pool_summaries:
        lines.append(
            "| "
            f"{summary['pool_name']} | "
            f"{summary['candidate_count']} | "
            f"{summary['zone_available_count']} / {summary['zone_unavailable_count']} | "
            f"{_fmt_stats(summary, 'zone_proxy_ratio')} | "
            f"{_fmt_stats(summary, 'top10_ratio')} | "
            f"{_fmt(summary.get('top10_vs_pool_median_delta'))} | "
            f"{summary['top10_ratio_stability']} | "
            f"{summary['band_change_count']} |"
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["pool_name"]), []).append(row)
    lines.extend(["", "## Candidate Order Sensitivity", ""])
    for summary in pool_summaries:
        pool_name = str(summary["pool_name"])
        pool_rows = grouped.get(pool_name, [])
        available = _top_ratio_rows(pool_rows, reverse=False)
        min_row = available[0] if available else None
        max_row = _top_ratio_rows(pool_rows, reverse=True)[0] if available else None
        lines.extend(
            [
                f"### {pool_name}",
                "",
                f"- lowest ratio candidate: {min_row['candidate_id'] if min_row else 'n/a'} ({_fmt(min_row.get('profile_cd_zone_vs_proxy_ratio') if min_row else None)})",
                f"- highest ratio candidate: {max_row['candidate_id'] if max_row else 'n/a'} ({_fmt(max_row.get('profile_cd_zone_vs_proxy_ratio') if max_row else None)})",
                f"- top candidates ratio stability: {summary['top10_ratio_stability']}",
                "- rank-bucket ratio distribution:",
                "",
                "| bucket | candidates | ratio min/median/max |",
                "| --- | ---: | ---: |",
            ]
        )
        for bucket, bucket_summary in summary["rank_bucket_distribution"].items():
            lines.append(
                "| "
                f"{bucket} | "
                f"{bucket_summary['candidate_count']} | "
                f"{_fmt(bucket_summary['ratio_min'])} / {_fmt(bucket_summary['ratio_median'])} / {_fmt(bucket_summary['ratio_max'])} |"
            )
        lines.extend(
            [
                "",
                "top 10 candidates:",
                "",
                "| order | candidate_id | zone/proxy | delta from pool median | drag budget band if zone |",
                "| ---: | --- | ---: | ---: | --- |",
            ]
        )
        top10_rows = sorted(pool_rows, key=lambda row: int(row["original_order"]))[:10]
        for row in top10_rows:
            lines.append(
                "| "
                f"{row['original_order']} | "
                f"{row['candidate_id']} | "
                f"{_fmt(row.get('profile_cd_zone_vs_proxy_ratio'))} | "
                f"{_fmt(row.get('ratio_delta_from_pool_median'))} | "
                f"{row.get('drag_budget_band_if_zone') or 'n/a'} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Drag Budget Band Sensitivity",
            "",
            "| ranked pool | candidate_id | current band | band if zone | cd0_total_est | cd0_total_est_if_zone | direction |",
            "| --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    if not band_change_candidates:
        lines.append("| none | none | n/a | n/a | n/a | n/a | n/a |")
    else:
        for row in band_change_candidates:
            lines.append(
                "| "
                f"{row['pool_name']} | "
                f"{row['candidate_id']} | "
                f"{row.get('drag_budget_band') or 'n/a'} | "
                f"{row.get('drag_budget_band_if_zone') or 'n/a'} | "
                f"{_fmt(row.get('cd0_total_est'))} | "
                f"{_fmt(row.get('cd0_total_est_if_zone'))} | "
                f"{row.get('band_change_direction') or 'n/a'} |"
            )
    return "\n".join(lines) + "\n"


def run_sensitivity(
    *,
    ranked_pool_paths: list[Path] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
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
        rows.extend(_rows_for_pool(Path(path)))

    pool_summaries = _summaries_by_pool(rows)
    overall_summary = _summarize_rows(rows)
    overall_summary["pool_count"] = len(pool_summaries)
    band_change_candidates = [row for row in rows if bool(row.get("band_change"))]
    band_change_candidates.sort(
        key=lambda row: (
            str(row.get("pool_name")),
            int(row.get("original_order") or 0),
        )
    )

    csv_path = output_dir / CSV_FILENAME
    md_path = output_dir / MD_FILENAME
    _write_csv(rows, csv_path)
    md_path.write_text(
        _build_markdown(
            rows=rows,
            pool_summaries=pool_summaries,
            overall_summary=overall_summary,
            band_change_candidates=band_change_candidates,
        ),
        encoding="utf-8",
    )

    return {
        "csv_path": str(csv_path),
        "markdown_path": str(md_path),
        "overall": overall_summary,
        "pools": pool_summaries,
        "band_change_candidates": band_change_candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze candidate-order and drag-budget sensitivity for profile CD source diagnostics."
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
        help="Directory for profile_cd_source_sensitivity.csv/.md.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root used for discovery when no ranked pools are provided.",
    )
    args = parser.parse_args()

    summary = run_sensitivity(
        ranked_pool_paths=args.ranked_pool_json or None,
        output_dir=args.output_dir,
        output_root=args.output_root,
    )
    overall = summary["overall"]
    print(f"wrote {summary['csv_path']}")
    print(f"wrote {summary['markdown_path']}")
    print(
        "overall zone/proxy ratio min/median/max = "
        f"{_fmt_stats(overall, 'zone_proxy_ratio')}"
    )
    print(f"band_change_count = {overall['band_change_count']}")


if __name__ == "__main__":
    main()
