#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from hpa_mdo.concept.config import load_concept_config  # noqa: E402
from hpa_mdo.concept.frontier import build_frontier_summary  # noqa: E402


def _resolve_run_path(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Run spec must look like label=PATH, got: {raw}")
    label, path_str = raw.split("=", 1)
    path = Path(path_str).expanduser().resolve()
    if path.is_dir():
        return label, path
    if path.name == "concept_summary.json":
        return label, path.parent
    raise ValueError(f"Run path must be an output directory or concept_summary.json: {path}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dominant_gate(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _top_entry(items: list[dict[str, Any]], key: str) -> Any:
    if not items:
        return None
    return items[0].get(key)


def _first_matching(records: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for record in records:
        if predicate(record):
            return record
    return None


def _run_digest(label: str, run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "concept_summary.json"
    ranked_pool_path = run_dir / "concept_ranked_pool.json"
    frontier_path = run_dir / "frontier_summary.json"

    summary = _load_json(summary_path)
    ranked_pool_payload = _load_json(ranked_pool_path)
    ranked_pool = list(ranked_pool_payload.get("ranked_pool", []))
    frontier = _load_json(frontier_path) if frontier_path.is_file() else build_frontier_summary(ranked_pool)
    cfg = load_concept_config(Path(summary["config_path"]))
    top_record = ranked_pool[0] if ranked_pool else None
    best_infeasible = _first_matching(
        ranked_pool,
        lambda record: not bool(record.get("ranking", {}).get("fully_feasible", False)),
    )
    first_feasible = _first_matching(
        ranked_pool,
        lambda record: bool(record.get("ranking", {}).get("fully_feasible", False)),
    )
    geometry_sampling = summary.get("evaluation_scope", {}).get("geometry_sampling", {})

    return {
        "label": label,
        "run_dir": str(run_dir),
        "config_path": summary["config_path"],
        "sample_count": cfg.geometry_family.sampling.sample_count,
        "accepted_concept_count": geometry_sampling.get("accepted_concept_count"),
        "rejected_concept_count": geometry_sampling.get("rejected_concept_count"),
        "fully_feasible_count": frontier["counts"]["fully_feasible_count"],
        "safety_feasible_count": frontier["counts"]["safety_feasible_count"],
        "mission_feasible_count": frontier["counts"]["mission_feasible_count"],
        "dominant_frontier_gate": _dominant_gate(frontier["failure_gate_counts"]["top_ranked"]),
        "dominant_frontier_signature": _top_entry(
            frontier["dominant_failure_signatures"]["top_ranked"], "signature"
        ),
        "dominant_frontier_mission_limiter": _top_entry(
            frontier["mission_dominant_limiters"]["top_ranked"], "limiter"
        ),
        "frontier_wing_loading_min": frontier["geometry_subsets"]["top_ranked"][
            "wing_loading_target_Npm2"
        ]["min"],
        "frontier_wing_loading_median": frontier["geometry_subsets"]["top_ranked"][
            "wing_loading_target_Npm2"
        ]["median"],
        "frontier_wing_area_max": frontier["geometry_subsets"]["top_ranked"]["wing_area_m2"][
            "max"
        ],
        "frontier_wing_area_median": frontier["geometry_subsets"]["top_ranked"]["wing_area_m2"][
            "median"
        ],
        "frontier_required_area_for_local_stall_limit_m2": frontier["margin_subsets"][
            "top_ranked"
        ]["required_wing_area_for_local_stall_limit_m2"]["median"],
        "frontier_delta_area_for_local_stall_limit_m2": frontier["margin_subsets"][
            "top_ranked"
        ]["delta_wing_area_for_local_stall_limit_m2"]["median"],
        "frontier_mission_margin_m": frontier["margin_subsets"]["top_ranked"]["mission_margin_m"][
            "median"
        ],
        "top_record": {
            "concept_id": None if top_record is None else top_record["concept_id"],
            "overall_rank": None if top_record is None else top_record["overall_rank"],
            "wing_loading_target_Npm2": None if top_record is None else top_record["wing_loading_target_Npm2"],
            "wing_area_m2": None if top_record is None else top_record["wing_area_m2"],
            "aspect_ratio": None if top_record is None else top_record["aspect_ratio"],
            "failure_signature": None
            if top_record is None
            else "+".join(
                reason
                for reason, failed in (
                    ("launch", not bool(top_record["launch"]["feasible"])),
                    ("turn", not bool(top_record["turn"]["feasible"])),
                    ("trim", not bool(top_record["trim"]["feasible"])),
                    ("local_stall", not bool(top_record["local_stall"]["feasible"])),
                    ("mission", not bool(top_record["mission"]["mission_feasible"])),
                )
                if failed
            ),
        },
        "best_infeasible": {
            "concept_id": None if best_infeasible is None else best_infeasible["concept_id"],
            "wing_loading_target_Npm2": None
            if best_infeasible is None
            else best_infeasible["wing_loading_target_Npm2"],
            "wing_area_m2": None if best_infeasible is None else best_infeasible["wing_area_m2"],
            "required_wing_area_for_local_stall_limit_m2": None
            if best_infeasible is None
            else best_infeasible["local_stall"].get("required_wing_area_for_limit_m2"),
            "delta_wing_area_for_local_stall_limit_m2": None
            if best_infeasible is None
            else best_infeasible["local_stall"].get("delta_wing_area_for_limit_m2"),
            "mission_margin_m": None
            if best_infeasible is None
            else best_infeasible["mission"].get("target_range_margin_m"),
        },
        "first_feasible": {
            "concept_id": None if first_feasible is None else first_feasible["concept_id"],
            "wing_loading_target_Npm2": None
            if first_feasible is None
            else first_feasible["wing_loading_target_Npm2"],
            "wing_area_m2": None if first_feasible is None else first_feasible["wing_area_m2"],
        },
    }


def _render_markdown(digests: list[dict[str, Any]]) -> str:
    lines = [
        "# Birdman Upstream Frontier Comparison",
        "",
        "| Run | Samples | Accepted | Rejected | Fully feasible | Frontier W/S min | Frontier area max | Dominant frontier gate | Dominant mission limiter |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for digest in digests:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(digest["label"]),
                    str(digest["sample_count"]),
                    str(digest["accepted_concept_count"]),
                    str(digest["rejected_concept_count"]),
                    str(digest["fully_feasible_count"]),
                    (
                        "n/a"
                        if digest["frontier_wing_loading_min"] is None
                        else f"{float(digest['frontier_wing_loading_min']):.2f}"
                    ),
                    (
                        "n/a"
                        if digest["frontier_wing_area_max"] is None
                        else f"{float(digest['frontier_wing_area_max']):.2f}"
                    ),
                    str(digest["dominant_frontier_gate"]),
                    str(digest["dominant_frontier_mission_limiter"]),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Run Notes", ""])
    for digest in digests:
        lines.append(f"### {digest['label']}")
        lines.append(f"- output: `{digest['run_dir']}`")
        lines.append(f"- config: `{digest['config_path']}`")
        lines.append(
            f"- top concept: W/S={digest['top_record']['wing_loading_target_Npm2']}, "
            f"area={digest['top_record']['wing_area_m2']}, "
            f"AR={digest['top_record']['aspect_ratio']}, "
            f"failure={digest['top_record']['failure_signature']}"
        )
        lines.append(
            f"- best infeasible area needed for local stall limit: "
            f"{digest['best_infeasible']['required_wing_area_for_local_stall_limit_m2']}"
        )
        lines.append(
            f"- best infeasible extra area to local stall limit: "
            f"{digest['best_infeasible']['delta_wing_area_for_local_stall_limit_m2']}"
        )
        lines.append(
            f"- frontier median mission margin: {digest['frontier_mission_margin_m']}"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Birdman upstream concept frontier outputs across multiple runs."
    )
    parser.add_argument(
        "runs",
        nargs="+",
        help="Run specs in the form label=OUTPUT_DIR or label=/path/to/concept_summary.json",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for the comparison markdown/json artifacts.",
    )
    args = parser.parse_args()

    digests = [_run_digest(*_resolve_run_path(raw)) for raw in args.runs]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_json_path = output_dir / "frontier_comparison.json"
    summary_json_path.write_text(
        json.dumps({"runs": digests}, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    summary_md_path = output_dir / "frontier_comparison.md"
    summary_md = _render_markdown(digests)
    summary_md_path.write_text(summary_md, encoding="utf-8")

    print(summary_md)
    print(f"Wrote JSON: {summary_json_path}")
    print(f"Wrote MD  : {summary_md_path}")


if __name__ == "__main__":
    main()
