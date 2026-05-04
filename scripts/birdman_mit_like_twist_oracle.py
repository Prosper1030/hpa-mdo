#!/usr/bin/env python3
"""Birdman MIT-like fixed-planform cruise-aware twist oracle.

Run the 4-DOF no-airfoil twist optimisation on each MIT-like
high-AR / sensible-taper candidate and report the upper-bound on
e_CDi the planform can reach **before** any airfoil work happens.

Workflow per candidate:

1. Generate MIT-like planform via
   :func:`hpa_mdo.concept.mit_like_candidate.generate_mit_like_candidates`
   (no outer chord bump, AR 37-40, taper 0.30-0.40).
2. Build trapezoidal stations.
3. Build the Fourier-target spanload at cruise CL_required to give
   per-station ``target_circulation_norm`` / ``target_local_cl``.
4. Hand stations + target records to
   :func:`hpa_mdo.concept.cruise_twist_oracle.optimize_twist_for_candidate`,
   which runs a 4-DOF (root, linear, outer-bump, tip-cubic) twist
   sweep + Powell at the cruise CL.
5. Record best e_CDi, outer ratios, twist distribution, gate failures,
   target match.  Decide acceptance band (>= 0.88, 0.85-0.88, < 0.85).

The script does NOT touch chord, does NOT call XFOIL/CST, and does NOT
compute final mission power — the brief explicitly forbids treating
the no-airfoil result as a mission verdict.  Mission power and
profile-drag scoring come back once the CST/XFOIL leg is wired.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.atmosphere import air_properties_from_environment  # noqa: E402
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config  # noqa: E402
from hpa_mdo.concept.cruise_twist_oracle import (  # noqa: E402
    OUTER_RATIO_TARGET_FLOOR,
    TWIST_BOUNDS_DEG,
    optimize_twist_for_candidate,
)
from hpa_mdo.concept.geometry import _fourier_spanload_shape  # noqa: E402
from hpa_mdo.concept.mit_like_candidate import (  # noqa: E402
    DEFAULT_AR_RANGE,
    DEFAULT_SPAN_RANGE_M,
    DEFAULT_TAPER_RATIO_RANGE,
    MITLikeCandidate,
    generate_mit_like_candidates,
    stations_for_mit_like_candidate,
)


G_MPS2: float = 9.80665


def _build_target_records(
    *,
    cfg: BirdmanConceptConfig,
    candidate: MITLikeCandidate,
    cruise_speed_mps: float,
    spanload_a3_over_a1: float,
    spanload_a5_over_a1: float,
    eta_grid_count: int = 17,
) -> list[dict[str, Any]]:
    """Per-station Fourier target spanload at cruise.

    ``target_local_cl`` is sized so that the integrated lift over the
    half-span matches the cruise weight — so the AVL trim CL_required
    and the target cl_target schedule live on the same operating point.
    """

    spanload_design = cfg.geometry_family.spanload_design
    air = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(cruise_speed_mps) ** 2
    design_cl = float(cfg.mass.design_gross_mass_kg) * G_MPS2 / max(
        q_pa * float(candidate.wing_area_m2), 1.0e-9
    )

    half_span_m = 0.5 * float(candidate.span_m)
    grid_eta = [
        float(value)
        for value in (i / float(eta_grid_count - 1) for i in range(eta_grid_count))
    ]
    integration_records: list[dict[str, float]] = []
    for eta in grid_eta:
        shape = max(
            0.0,
            _fourier_spanload_shape(
                a3_over_a1=float(spanload_a3_over_a1),
                a5_over_a1=float(spanload_a5_over_a1),
                eta=float(eta),
            ),
        )
        chord_m = (
            float(candidate.root_chord_m)
            + (float(candidate.tip_chord_m) - float(candidate.root_chord_m)) * float(eta)
        )
        integration_records.append(
            {
                "eta": float(eta),
                "y_m": float(eta * half_span_m),
                "chord_m": float(chord_m),
                "shape": float(shape),
            }
        )
    shape_integral_m = 0.0
    for left, right in zip(integration_records, integration_records[1:]):
        dy = float(right["y_m"]) - float(left["y_m"])
        shape_integral_m += 0.5 * dy * (float(left["shape"]) + float(right["shape"]))
    cl_scale = (
        float(design_cl)
        * float(candidate.wing_area_m2)
        / max(2.0 * shape_integral_m, 1.0e-9)
    )
    max_shape = max(float(record["shape"]) for record in integration_records) or 1.0

    safe_clmax = float(spanload_design.local_clmax_safe_floor)
    target_records: list[dict[str, Any]] = []
    for record in integration_records:
        eta = float(record["eta"])
        chord_m = float(record["chord_m"])
        shape = float(record["shape"])
        local_cl = float(cl_scale) * shape / max(chord_m, 1.0e-9)
        reynolds = (
            float(air.density_kg_per_m3)
            * float(cruise_speed_mps)
            * chord_m
            / max(float(air.dynamic_viscosity_pa_s), 1.0e-12)
        )
        target_records.append(
            {
                "eta": float(eta),
                "y_m": float(record["y_m"]),
                "chord_m": float(chord_m),
                "reynolds": float(reynolds),
                "shape": float(shape),
                "target_circulation_norm": float(shape / max_shape),
                "target_local_cl": float(local_cl),
                "target_clmax_safe_floor": float(safe_clmax),
                "target_clmax_utilization": float(local_cl / max(safe_clmax, 1.0e-9)),
            }
        )
    return target_records


@dataclass(frozen=True)
class CandidateOracleSummary:
    sample_index: int
    candidate: dict[str, Any]
    cl_required: float
    cruise_speed_mps: float
    best: dict[str, Any] | None
    status: str
    failure_reason: str | None
    target_records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_index": int(self.sample_index),
            "candidate": self.candidate,
            "cl_required": float(self.cl_required),
            "cruise_speed_mps": float(self.cruise_speed_mps),
            "best": self.best,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "target_records": self.target_records,
        }


def _classify(best: dict[str, Any] | None) -> str:
    if best is None or best.get("e_cdi") is None:
        return "no_valid_evaluation"
    e_cdi = float(best.get("e_cdi", 0.0))
    if best.get("twist_gate_failures"):
        return "twist_gate_failed"
    if e_cdi >= 0.88:
        return "e_cdi_ge_0p88_primary"
    if e_cdi >= 0.85:
        return "e_cdi_0p85_to_0p88_diagnostic"
    return "e_cdi_below_0p85"


def _diagnose_blocker(best: dict[str, Any] | None) -> dict[str, Any]:
    if best is None:
        return {"primary_driver": "no_valid_evaluation"}
    drivers: list[str] = []
    twist_gate_failures = best.get("twist_gate_failures") or []
    if twist_gate_failures:
        drivers.append(f"twist_gate:{','.join(twist_gate_failures)}")
    if (best.get("local_cl_max_utilization") or 0.0) > 0.90:
        drivers.append("local_cl_above_safe_utilisation")
    outer_ratio_min = best.get("outer_ratio_min")
    if outer_ratio_min is not None and float(outer_ratio_min) < OUTER_RATIO_TARGET_FLOOR:
        drivers.append("outer_loading_below_target_floor")
    if (best.get("target_match_max_norm_delta") or 0.0) > 0.30:
        drivers.append("target_match_max_delta_above_30pct")
    if not drivers:
        drivers.append("no_clear_blocker")
    return {
        "drivers": drivers,
        "primary_driver": drivers[0],
        "outer_ratio_min": outer_ratio_min,
        "outer_ratio_mean": best.get("outer_ratio_mean"),
        "local_cl_max_utilization": best.get("local_cl_max_utilization"),
        "target_match_rms_norm_delta": best.get("target_match_rms_norm_delta"),
        "target_match_max_norm_delta": best.get("target_match_max_norm_delta"),
    }


def run_twist_oracle_search(
    *,
    cfg: BirdmanConceptConfig,
    output_dir: Path,
    sample_count: int,
    ar_range: tuple[float, float],
    taper_range: tuple[float, float],
    span_range_m: tuple[float, float],
    cruise_speed_mps: float,
    spanload_a3_over_a1: float,
    spanload_a5_over_a1: float,
    optimizer_maxfev: int,
    optimizer_maxiter: int,
    avl_binary: str | None,
    seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = generate_mit_like_candidates(
        cfg=cfg,
        sample_count=int(sample_count),
        ar_range=ar_range,
        taper_range=taper_range,
        span_range_m=span_range_m,
        seed=int(seed),
    )

    summaries: list[dict[str, Any]] = []
    for candidate in candidates:
        sample_dir = output_dir / f"sample_{candidate.sample_index:04d}"
        stations = stations_for_mit_like_candidate(
            candidate=candidate, stations_per_half=9
        )
        target_records = _build_target_records(
            cfg=cfg,
            candidate=candidate,
            cruise_speed_mps=cruise_speed_mps,
            spanload_a3_over_a1=spanload_a3_over_a1,
            spanload_a5_over_a1=spanload_a5_over_a1,
        )
        oracle_result = optimize_twist_for_candidate(
            cfg=cfg,
            concept=candidate.concept,
            base_stations=stations,
            target_records=target_records,
            cruise_speed_mps=cruise_speed_mps,
            output_dir=sample_dir,
            avl_binary=avl_binary,
            optimizer_maxfev=int(optimizer_maxfev),
            optimizer_maxiter=int(optimizer_maxiter),
        )
        summary = CandidateOracleSummary(
            sample_index=candidate.sample_index,
            candidate=candidate.to_summary(),
            cl_required=float(oracle_result.get("cl_required", float("nan"))),
            cruise_speed_mps=float(cruise_speed_mps),
            best=oracle_result.get("best"),
            status=str(oracle_result.get("status", "ok")),
            failure_reason=(
                None
                if oracle_result.get("status") == "ok"
                else str(oracle_result.get("status"))
            ),
            target_records=target_records,
        )
        record = summary.to_dict()
        record["classification"] = _classify(summary.best)
        record["blocker_diagnosis"] = _diagnose_blocker(summary.best)
        summaries.append(record)
        print(
            json.dumps(
                {
                    "event": "candidate_done",
                    "sample_index": candidate.sample_index,
                    "AR": round(candidate.aspect_ratio, 3),
                    "taper": round(candidate.taper_ratio, 3),
                    "S": round(candidate.wing_area_m2, 3),
                    "classification": record["classification"],
                    "best_e_cdi": (
                        None
                        if summary.best is None
                        else summary.best.get("e_cdi")
                    ),
                    "outer_ratio_min_080_092": (
                        None
                        if summary.best is None
                        else summary.best.get("outer_ratio_min")
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    ranked = sorted(
        [
            record
            for record in summaries
            if isinstance(record.get("best"), dict)
            and record["best"].get("e_cdi") is not None
        ],
        key=lambda record: -float(record["best"]["e_cdi"]),
    )
    classifications: dict[str, int] = {}
    for record in summaries:
        bucket = str(record.get("classification", "unknown"))
        classifications[bucket] = classifications.get(bucket, 0) + 1
    report = {
        "schema_version": "birdman_mit_like_twist_oracle_v1",
        "search_parameters": {
            "ar_range": list(ar_range),
            "taper_range": list(taper_range),
            "span_range_m": list(span_range_m),
            "sample_count": int(sample_count),
            "cruise_speed_mps": float(cruise_speed_mps),
            "spanload_a3_over_a1": float(spanload_a3_over_a1),
            "spanload_a5_over_a1": float(spanload_a5_over_a1),
            "optimizer_maxfev": int(optimizer_maxfev),
            "optimizer_maxiter": int(optimizer_maxiter),
            "twist_bounds_deg": {key: list(value) for key, value in TWIST_BOUNDS_DEG.items()},
            "seed": int(seed),
        },
        "candidate_count": len(summaries),
        "classification_counts": classifications,
        "summaries": summaries,
        "ranked_by_e_cdi": [
            {
                "sample_index": record["sample_index"],
                "candidate": record["candidate"],
                "best": record["best"],
                "classification": record["classification"],
                "blocker_diagnosis": record["blocker_diagnosis"],
            }
            for record in ranked
        ],
        "engineering_read": _engineering_read(summaries, ranked),
    }
    return report


def _engineering_read(
    summaries: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if not summaries:
        return ["No candidates generated; check the AR/taper/span ranges."]
    counts: dict[str, int] = {}
    for record in summaries:
        bucket = str(record.get("classification", "unknown"))
        counts[bucket] = counts.get(bucket, 0) + 1
    lines.append(f"Classification counts: {counts}")
    if ranked:
        best = ranked[0]
        diag = best["blocker_diagnosis"]
        lines.append(
            "Best candidate: "
            f"sample {best['sample_index']} "
            f"AR={best['candidate']['aspect_ratio']:.2f} "
            f"taper={best['candidate']['taper_ratio']:.3f} "
            f"e_CDi={best['best'].get('e_cdi'):.4f} "
            f"outer_min[0.80-0.92]={best['best'].get('outer_ratio_min')} "
            f"local_cl_util={best['best'].get('local_cl_max_utilization'):.3f} "
            f"twist={best['best']['twist']}"
        )
        lines.append(
            "Blocker drivers (best candidate): "
            + ", ".join(diag.get("drivers", []))
        )
    if any(
        record["classification"] == "e_cdi_ge_0p88_primary" for record in summaries
    ):
        lines.append(
            "MIT-like fixed-planform with no-airfoil twist optimisation can already "
            "hit e_CDi >= 0.88; planform is viable. Next step: plug in CST/XFOIL "
            "search to lift the post-airfoil bound further."
        )
    elif any(
        record["classification"] == "e_cdi_0p85_to_0p88_diagnostic" for record in summaries
    ):
        lines.append(
            "MIT-like planform sits in the 0.85-0.88 diagnostic band even after "
            "twist optimisation. Acceptable as an upper bound, but the airfoil leg "
            "must close the remaining ~0.03 to land in the e_CDi >= 0.88 zone."
        )
    else:
        lines.append(
            "MIT-like planform is below 0.85 even with twist optimisation. "
            "The blocker is documented per candidate; revisit taper / target "
            "spanload mapping / local CL gate before chasing CST/XFOIL."
        )
    return lines


def write_markdown(report: dict[str, Any], path: Path) -> None:
    parameters = report.get("search_parameters") or {}
    lines = [
        "# Birdman MIT-like Cruise-Aware Twist Oracle",
        "",
        f"- AR range: {parameters.get('ar_range')}",
        f"- Taper range: {parameters.get('taper_range')}",
        f"- Span range (m): {parameters.get('span_range_m')}",
        f"- Sample count: {parameters.get('sample_count')}",
        f"- Cruise speed: {parameters.get('cruise_speed_mps')} m/s",
        f"- Fourier shape (a3, a5): {parameters.get('spanload_a3_over_a1')}, "
        f"{parameters.get('spanload_a5_over_a1')}",
        f"- Optimizer maxfev / maxiter: {parameters.get('optimizer_maxfev')}, "
        f"{parameters.get('optimizer_maxiter')}",
        "",
        "## Engineering Read",
        "",
    ]
    for entry in report.get("engineering_read", []):
        lines.append(f"- {entry}")
    lines.append("")
    lines.append("## Classification Counts")
    lines.append("")
    for key, value in (report.get("classification_counts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Ranked Candidates (post-twist no-airfoil e_CDi descending)")
    lines.append("")
    lines.append(
        "| rank | sample | AR | taper | S | e_CDi | outer_min[0.80-0.92] | "
        "local_cl_util | aoa_trim | linear_washout | outer_bump | classification |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for rank, record in enumerate(report.get("ranked_by_e_cdi", []), start=1):
        cand = record.get("candidate", {})
        best = record.get("best", {}) or {}
        twist = best.get("twist", {}) if isinstance(best.get("twist"), dict) else {}
        lines.append(
            "| "
            f"{rank} | "
            f"{record['sample_index']} | "
            f"{cand.get('aspect_ratio')} | "
            f"{cand.get('taper_ratio')} | "
            f"{cand.get('wing_area_m2')} | "
            f"{best.get('e_cdi')} | "
            f"{best.get('outer_ratio_min')} | "
            f"{best.get('local_cl_max_utilization')} | "
            f"{best.get('aoa_trim_deg')} | "
            f"{twist.get('linear_washout_deg')} | "
            f"{twist.get('outer_bump_amp_deg')} | "
            f"{record.get('classification')} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/birdman_upstream_concept_baseline.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/birdman_mit_like_twist_oracle"),
    )
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--ar-min", type=float, default=DEFAULT_AR_RANGE[0])
    parser.add_argument("--ar-max", type=float, default=DEFAULT_AR_RANGE[1])
    parser.add_argument("--taper-min", type=float, default=DEFAULT_TAPER_RATIO_RANGE[0])
    parser.add_argument("--taper-max", type=float, default=DEFAULT_TAPER_RATIO_RANGE[1])
    parser.add_argument("--span-min-m", type=float, default=DEFAULT_SPAN_RANGE_M[0])
    parser.add_argument("--span-max-m", type=float, default=DEFAULT_SPAN_RANGE_M[1])
    parser.add_argument("--cruise-speed-mps", type=float, default=6.6)
    parser.add_argument("--spanload-a3-over-a1", type=float, default=-0.05)
    parser.add_argument("--spanload-a5-over-a1", type=float, default=0.0)
    parser.add_argument("--optimizer-maxfev", type=int, default=24)
    parser.add_argument("--optimizer-maxiter", type=int, default=4)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--seed", type=int, default=20260504)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    report = run_twist_oracle_search(
        cfg=cfg,
        output_dir=args.output_dir,
        sample_count=int(args.sample_count),
        ar_range=(float(args.ar_min), float(args.ar_max)),
        taper_range=(float(args.taper_min), float(args.taper_max)),
        span_range_m=(float(args.span_min_m), float(args.span_max_m)),
        cruise_speed_mps=float(args.cruise_speed_mps),
        spanload_a3_over_a1=float(args.spanload_a3_over_a1),
        spanload_a5_over_a1=float(args.spanload_a5_over_a1),
        optimizer_maxfev=int(args.optimizer_maxfev),
        optimizer_maxiter=int(args.optimizer_maxiter),
        avl_binary=args.avl_binary,
        seed=int(args.seed),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "mit_like_twist_oracle_report.json"
    md_path = args.output_dir / "mit_like_twist_oracle_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
