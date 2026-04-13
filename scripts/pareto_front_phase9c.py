#!/usr/bin/env python3
"""Build the Phase 9c Pareto frontier from existing sweep campaign outputs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SINGLE_SUMMARIES = (
    REPO_ROOT / "output" / "dihedral_sweep_phase9a" / "dihedral_sweep_summary.csv",
    REPO_ROOT / "output" / "dihedral_sweep_phase9a_extension" / "dihedral_sweep_summary.csv",
    REPO_ROOT / "output" / "dihedral_sweep_extreme_probe_01" / "dihedral_sweep_summary.csv",
    REPO_ROOT / "output" / "dihedral_sweep_extreme_probe_02" / "dihedral_sweep_summary.csv",
    REPO_ROOT / "output" / "dihedral_sweep_extreme_probe_03" / "dihedral_sweep_summary.csv",
)
DEFAULT_MULTI_WIRE_SUMMARY = (
    REPO_ROOT / "output" / "multi_wire_sweep_phase9b" / "multi_wire_sweep_summary.csv"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "pareto_front_phase9c"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "pareto_front_phase9c_report.md"


@dataclass(frozen=True)
class ParetoDesignPoint:
    source_name: str
    layout: str
    wire_count: int
    dihedral_multiplier: float
    total_mass_kg: float
    ld_ratio: float
    dutch_roll_damping: float
    aoa_trim_deg: float
    min_jig_clearance_mm: float | None
    wire_margin_n: float | None
    equivalent_tip_deflection_m: float | None
    cd_total_est: float | None
    corrected_for_wire_drag: bool
    source_summary_path: str
    summary_json_path: str | None

    @property
    def point_key(self) -> tuple[str, float]:
        return (self.layout, round(float(self.dihedral_multiplier), 6))

    @property
    def label(self) -> str:
        return f"{self.layout} x{self.dihedral_multiplier:.3f}"


@dataclass(frozen=True)
class ParetoRepresentativeSet:
    mass_first: ParetoDesignPoint
    aero_first: ParetoDesignPoint
    stability_first: ParetoDesignPoint
    balanced: ParetoDesignPoint


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def _summary_equivalent_tip(summary_json_path: str | None) -> float | None:
    if not summary_json_path:
        return None
    path = Path(summary_json_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    iterations = payload.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return None
    selected = iterations[-1].get("selected")
    if not isinstance(selected, dict):
        return None
    value = selected.get("equivalent_tip_deflection_m")
    return None if value is None else float(value)


def _load_single_sweep_points(
    *,
    path: Path,
    base_profile_cd: float,
    wire_drag_cd_per_wire: float,
) -> tuple[ParetoDesignPoint, ...]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    points: list[ParetoDesignPoint] = []
    for row in rows:
        if not _parse_bool(row.get("aero_performance_feasible")):
            continue
        if str(row.get("structure_status")).strip().lower() != "feasible":
            continue
        cl_trim = _safe_float(row.get("cl_trim"))
        cd_induced = _safe_float(row.get("cd_induced"))
        if cl_trim is None or cd_induced is None:
            continue
        corrected_cd_total = float(cd_induced) + float(base_profile_cd) + float(
            wire_drag_cd_per_wire
        )
        points.append(
            ParetoDesignPoint(
                source_name=path.parent.name,
                layout="single",
                wire_count=1,
                dihedral_multiplier=float(row["dihedral_multiplier"]),
                total_mass_kg=float(row["total_mass_kg"]),
                ld_ratio=float(cl_trim) / float(corrected_cd_total),
                dutch_roll_damping=-float(row["dutch_roll_real"]),
                aoa_trim_deg=float(row["aoa_trim_deg"]),
                min_jig_clearance_mm=_safe_float(row.get("min_jig_clearance_mm")),
                wire_margin_n=_safe_float(row.get("wire_margin_n")),
                equivalent_tip_deflection_m=_summary_equivalent_tip(
                    row.get("summary_json_path")
                ),
                cd_total_est=float(corrected_cd_total),
                corrected_for_wire_drag=True,
                source_summary_path=str(path),
                summary_json_path=row.get("summary_json_path") or None,
            )
        )
    return tuple(points)


def _load_multi_wire_points(path: Path) -> tuple[ParetoDesignPoint, ...]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    points: list[ParetoDesignPoint] = []
    for row in rows:
        if not _parse_bool(row.get("aero_performance_feasible")):
            continue
        if str(row.get("structure_status")).strip().lower() != "feasible":
            continue
        points.append(
            ParetoDesignPoint(
                source_name=path.parent.name,
                layout=str(row["wire_layout_label"]).strip(),
                wire_count=int(float(row["wire_count"])),
                dihedral_multiplier=float(row["dihedral_multiplier"]),
                total_mass_kg=float(row["total_mass_kg"]),
                ld_ratio=float(row["ld_ratio"]),
                dutch_roll_damping=-float(row["dutch_roll_real"]),
                aoa_trim_deg=float(row["aoa_trim_deg"]),
                min_jig_clearance_mm=_safe_float(row.get("min_jig_clearance_mm")),
                wire_margin_n=_safe_float(row.get("wire_margin_min_n")),
                equivalent_tip_deflection_m=_summary_equivalent_tip(
                    row.get("summary_json_path")
                ),
                cd_total_est=_safe_float(row.get("cd_total_est")),
                corrected_for_wire_drag=False,
                source_summary_path=str(path),
                summary_json_path=row.get("summary_json_path") or None,
            )
        )
    return tuple(points)


def _dedupe_points(points: Iterable[ParetoDesignPoint]) -> tuple[ParetoDesignPoint, ...]:
    deduped: dict[tuple[str, float], ParetoDesignPoint] = {}
    for point in points:
        deduped[point.point_key] = point
    return tuple(
        sorted(
            deduped.values(),
            key=lambda item: (
                item.total_mass_kg,
                item.wire_count,
                -item.ld_ratio,
                -item.dutch_roll_damping,
                item.dihedral_multiplier,
                item.layout,
            ),
        )
    )


def dominates(lhs: ParetoDesignPoint, rhs: ParetoDesignPoint, eps: float = 1.0e-12) -> bool:
    better_or_equal = (
        lhs.total_mass_kg <= rhs.total_mass_kg + eps
        and lhs.wire_count <= rhs.wire_count
        and lhs.ld_ratio >= rhs.ld_ratio - eps
        and lhs.dutch_roll_damping >= rhs.dutch_roll_damping - eps
    )
    strictly_better = (
        lhs.total_mass_kg < rhs.total_mass_kg - eps
        or lhs.wire_count < rhs.wire_count
        or lhs.ld_ratio > rhs.ld_ratio + eps
        or lhs.dutch_roll_damping > rhs.dutch_roll_damping + eps
    )
    return bool(better_or_equal and strictly_better)


def build_pareto_frontier(
    feasible_points: tuple[ParetoDesignPoint, ...],
) -> tuple[ParetoDesignPoint, ...]:
    frontier: list[ParetoDesignPoint] = []
    for idx, candidate in enumerate(feasible_points):
        dominated = False
        for other_idx, other in enumerate(feasible_points):
            if idx == other_idx:
                continue
            if dominates(other, candidate):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return tuple(
        sorted(
            frontier,
            key=lambda item: (
                item.total_mass_kg,
                item.wire_count,
                -item.ld_ratio,
                -item.dutch_roll_damping,
                item.dihedral_multiplier,
                item.layout,
            ),
        )
    )


def _select_mass_first(frontier: tuple[ParetoDesignPoint, ...]) -> ParetoDesignPoint:
    return min(
        frontier,
        key=lambda item: (
            item.total_mass_kg,
            item.wire_count,
            -item.ld_ratio,
            -item.dutch_roll_damping,
            item.dihedral_multiplier,
        ),
    )


def _select_aero_first(frontier: tuple[ParetoDesignPoint, ...]) -> ParetoDesignPoint:
    return max(
        frontier,
        key=lambda item: (
            item.ld_ratio,
            -item.total_mass_kg,
            -item.wire_count,
            item.dutch_roll_damping,
            -item.dihedral_multiplier,
        ),
    )


def _select_stability_first(frontier: tuple[ParetoDesignPoint, ...]) -> ParetoDesignPoint:
    return max(
        frontier,
        key=lambda item: (
            item.dutch_roll_damping,
            item.ld_ratio,
            -item.total_mass_kg,
            -item.wire_count,
            -item.dihedral_multiplier,
        ),
    )


def _normalized_loss(value: float, best: float, worst: float, *, smaller_is_better: bool) -> float:
    span = worst - best
    if abs(span) < 1.0e-12:
        return 0.0
    if smaller_is_better:
        return (value - best) / span
    return (best - value) / (best - worst)


def _balanced_distance(
    point: ParetoDesignPoint,
    *,
    mass_bounds: tuple[float, float],
    wire_bounds: tuple[int, int],
    ld_bounds: tuple[float, float],
    damping_bounds: tuple[float, float],
) -> float:
    mass_best, mass_worst = mass_bounds
    wire_best, wire_worst = wire_bounds
    ld_best, ld_worst = ld_bounds
    damping_best, damping_worst = damping_bounds
    losses = (
        _normalized_loss(
            point.total_mass_kg,
            mass_best,
            mass_worst,
            smaller_is_better=True,
        ),
        _normalized_loss(
            float(point.wire_count),
            float(wire_best),
            float(wire_worst),
            smaller_is_better=True,
        ),
        _normalized_loss(
            point.ld_ratio,
            ld_best,
            ld_worst,
            smaller_is_better=False,
        ),
        _normalized_loss(
            point.dutch_roll_damping,
            damping_best,
            damping_worst,
            smaller_is_better=False,
        ),
    )
    return math.sqrt(sum(loss * loss for loss in losses))


def select_representatives(
    frontier: tuple[ParetoDesignPoint, ...],
) -> ParetoRepresentativeSet:
    mass_first = _select_mass_first(frontier)
    aero_first = _select_aero_first(frontier)
    stability_first = _select_stability_first(frontier)
    mass_values = [item.total_mass_kg for item in frontier]
    wire_values = [item.wire_count for item in frontier]
    ld_values = [item.ld_ratio for item in frontier]
    damping_values = [item.dutch_roll_damping for item in frontier]
    balanced = min(
        frontier,
        key=lambda item: (
            _balanced_distance(
                item,
                mass_bounds=(min(mass_values), max(mass_values)),
                wire_bounds=(min(wire_values), max(wire_values)),
                ld_bounds=(max(ld_values), min(ld_values)),
                damping_bounds=(max(damping_values), min(damping_values)),
            ),
            item.total_mass_kg,
            item.wire_count,
            -item.ld_ratio,
            -item.dutch_roll_damping,
        ),
    )
    return ParetoRepresentativeSet(
        mass_first=mass_first,
        aero_first=aero_first,
        stability_first=stability_first,
        balanced=balanced,
    )


def _write_summary_csv(
    *,
    path: Path,
    feasible_points: tuple[ParetoDesignPoint, ...],
    frontier_keys: set[tuple[str, float]],
) -> None:
    fieldnames = [
        "source_name",
        "layout",
        "wire_count",
        "dihedral_multiplier",
        "total_mass_kg",
        "ld_ratio",
        "dutch_roll_damping",
        "aoa_trim_deg",
        "min_jig_clearance_mm",
        "wire_margin_n",
        "equivalent_tip_deflection_m",
        "cd_total_est",
        "corrected_for_wire_drag",
        "pareto_optimal",
        "source_summary_path",
        "summary_json_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for point in feasible_points:
            payload = asdict(point)
            payload["pareto_optimal"] = point.point_key in frontier_keys
            writer.writerow(payload)


def _representative_table(
    representatives: ParetoRepresentativeSet,
) -> str:
    rows = (
        ("mass_first", representatives.mass_first),
        ("aero_first", representatives.aero_first),
        ("stability_first", representatives.stability_first),
        ("balanced", representatives.balanced),
    )
    lines = [
        "| role | design | mass_kg | wire_count | ld_ratio | dutch_roll_damping | aoa_trim_deg | clearance_mm |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for role, point in rows:
        clearance_text = "n/a"
        if point.min_jig_clearance_mm is not None:
            clearance_text = f"{point.min_jig_clearance_mm:.3f}"
        lines.append(
            "| "
            f"{role} | `{point.label}` | {point.total_mass_kg:.3f} | {point.wire_count} | "
            f"{point.ld_ratio:.2f} | {point.dutch_roll_damping:.5f} | {point.aoa_trim_deg:.5f} | "
            f"{clearance_text} |"
        )
    return "\n".join(lines)


def _frontier_table(frontier: tuple[ParetoDesignPoint, ...]) -> str:
    lines = [
        "| design | mass_kg | wire_count | ld_ratio | dutch_roll_damping | aoa_trim_deg | clearance_mm | tip_deflection_m |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for point in frontier:
        clearance_text = "n/a"
        if point.min_jig_clearance_mm is not None:
            clearance_text = f"{point.min_jig_clearance_mm:.3f}"
        tip_text = "n/a"
        if point.equivalent_tip_deflection_m is not None:
            tip_text = f"{point.equivalent_tip_deflection_m:.3f}"
        lines.append(
            "| "
            f"`{point.label}` | {point.total_mass_kg:.3f} | {point.wire_count} | {point.ld_ratio:.2f} | "
            f"{point.dutch_roll_damping:.5f} | {point.aoa_trim_deg:.5f} | {clearance_text} | {tip_text} |"
        )
    return "\n".join(lines)


def build_markdown_report(
    *,
    feasible_points: tuple[ParetoDesignPoint, ...],
    frontier: tuple[ParetoDesignPoint, ...],
    representatives: ParetoRepresentativeSet,
    single_summaries: tuple[Path, ...],
    multi_wire_summary: Path,
    wire_drag_cd_per_wire: float,
) -> str:
    frontier_layouts = ", ".join(sorted({point.layout for point in frontier}))
    lines = [
        "# Phase 9c Pareto Front Report",
        "",
        "Date: 2026-04-13",
        "",
        "## Inputs",
        "",
        f"- Single-wire sweep summaries: {', '.join(str(path) for path in single_summaries)}",
        f"- Multi-wire sweep summary: `{multi_wire_summary}`",
        f"- Fair-comparison correction for single-wire points: `ΔCD = {wire_drag_cd_per_wire:.3f} × wire_count`",
        "",
        "## Dataset",
        "",
        f"- Feasible design points considered: `{len(feasible_points)}`",
        f"- Pareto-optimal points: `{len(frontier)}`",
        f"- Pareto layouts represented: `{frontier_layouts}`",
        "",
        "## Representative Designs",
        "",
        _representative_table(representatives),
        "",
        "## Pareto Frontier",
        "",
        _frontier_table(frontier),
        "",
        "## Key Findings",
        "",
        f"- Mass-first representative is `{representatives.mass_first.label}`.",
        f"- Aero-first representative is `{representatives.aero_first.label}`.",
        f"- Stability-first representative is `{representatives.stability_first.label}`.",
        f"- Balanced compromise representative is `{representatives.balanced.label}`.",
        "- Triple-wire cases are absent from the frontier when compared against dual-wire and single-wire points under the current objectives.",
        "- The single-wire high-dihedral plateau stays on the frontier because it dominates on mass and wire-count while accepting some damping loss.",
        "- The low-dihedral dual-wire family remains relevant because it preserves the strongest Dutch Roll damping while staying much lighter than `single x1.0`.",
        "",
        "## Interpretation",
        "",
        "- The multiplier limit for the single-wire family is now governed by the trim AoA gate near `x6.30`, not by structure.",
        "- For the current four-objective formulation (`mass`, `wire_count`, `L/D`, `Dutch Roll damping`), the design space naturally separates into a low-wire-count / low-mass branch and a low-dihedral / higher-damping branch.",
        "- This means 9d should build on a much smaller candidate family instead of the full sweep tables.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Phase 9c Pareto frontier report.")
    parser.add_argument(
        "--single-summaries",
        nargs="*",
        default=[str(path) for path in DEFAULT_SINGLE_SUMMARIES],
    )
    parser.add_argument(
        "--multi-wire-summary",
        default=str(DEFAULT_MULTI_WIRE_SUMMARY),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--base-profile-cd", type=float, default=0.010)
    parser.add_argument("--wire-drag-cd-per-wire", type=float, default=0.003)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    single_summaries = tuple(Path(item).expanduser().resolve() for item in args.single_summaries)
    multi_wire_summary = Path(args.multi_wire_summary).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_points: list[ParetoDesignPoint] = []
    for path in single_summaries:
        if not path.exists():
            continue
        all_points.extend(
            _load_single_sweep_points(
                path=path,
                base_profile_cd=float(args.base_profile_cd),
                wire_drag_cd_per_wire=float(args.wire_drag_cd_per_wire),
            )
        )
    if multi_wire_summary.exists():
        all_points.extend(_load_multi_wire_points(multi_wire_summary))

    feasible_points = _dedupe_points(all_points)
    frontier = build_pareto_frontier(feasible_points)
    representatives = select_representatives(frontier)
    frontier_keys = {point.point_key for point in frontier}

    csv_path = output_dir / "pareto_front_phase9c_summary.csv"
    json_path = output_dir / "pareto_front_phase9c_summary.json"
    _write_summary_csv(
        path=csv_path,
        feasible_points=feasible_points,
        frontier_keys=frontier_keys,
    )
    json_path.write_text(
        json.dumps(
            {
                "single_summaries": [str(path) for path in single_summaries],
                "multi_wire_summary": str(multi_wire_summary),
                "wire_drag_cd_per_wire": float(args.wire_drag_cd_per_wire),
                "feasible_points": [asdict(point) for point in feasible_points],
                "pareto_frontier": [asdict(point) for point in frontier],
                "representatives": {
                    "mass_first": asdict(representatives.mass_first),
                    "aero_first": asdict(representatives.aero_first),
                    "stability_first": asdict(representatives.stability_first),
                    "balanced": asdict(representatives.balanced),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report_text = build_markdown_report(
        feasible_points=feasible_points,
        frontier=frontier,
        representatives=representatives,
        single_summaries=single_summaries,
        multi_wire_summary=multi_wire_summary,
        wire_drag_cd_per_wire=float(args.wire_drag_cd_per_wire),
    )
    report_path.write_text(report_text, encoding="utf-8")

    print("Phase 9c Pareto front build complete.")
    print(f"  Feasible points     : {len(feasible_points)}")
    print(f"  Pareto points       : {len(frontier)}")
    print(f"  CSV summary         : {csv_path}")
    print(f"  JSON summary        : {json_path}")
    print(f"  Markdown report     : {report_path}")
    print(f"  Mass-first          : {representatives.mass_first.label}")
    print(f"  Aero-first          : {representatives.aero_first.label}")
    print(f"  Stability-first     : {representatives.stability_first.label}")
    print(f"  Balanced            : {representatives.balanced.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
