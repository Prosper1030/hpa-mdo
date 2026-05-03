#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config  # noqa: E402
from hpa_mdo.concept.geometry import GeometryConcept, WingStation  # noqa: E402

import scripts.birdman_spanload_design_smoke as spanload_smoke  # noqa: E402


def _uniform_fx_zone_paths() -> dict[str, Path]:
    path = Path("data/airfoils/fx76mp140.dat").resolve()
    return {zone: path for zone in ("root", "mid1", "mid2", "tip")}


def _concept_from_stations(
    *,
    cfg: BirdmanConceptConfig,
    span_m: float,
    stations: tuple[WingStation, ...],
    tail_area_m2: float = 4.0,
) -> GeometryConcept:
    wing_area_m2 = spanload_smoke._integrate_station_chords(stations)
    segment_lengths_m = tuple(
        float(right.y_m - left.y_m)
        for left, right in zip(stations[:-1], stations[1:])
    )
    return GeometryConcept(
        span_m=float(span_m),
        wing_area_m2=float(wing_area_m2),
        root_chord_m=float(stations[0].chord_m),
        tip_chord_m=float(stations[-1].chord_m),
        twist_root_deg=float(stations[0].twist_deg),
        twist_tip_deg=float(stations[-1].twist_deg),
        twist_control_points=((0.0, float(stations[0].twist_deg)), (1.0, float(stations[-1].twist_deg))),
        tail_area_m2=float(tail_area_m2),
        cg_xc=float(cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths_m,
        spanload_a3_over_a1=0.0,
        spanload_a5_over_a1=0.0,
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / max(wing_area_m2, 1.0e-9)),
        mean_chord_target_m=float(wing_area_m2 / max(float(span_m), 1.0e-9)),
        wing_area_is_derived=True,
        planform_parameterization="spanload_inverse_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
    )


def _near_elliptic_uniform_case(cfg: BirdmanConceptConfig) -> dict[str, Any]:
    span_m = 34.5
    target_area_m2 = 30.5
    half_span_m = 0.5 * span_m
    root_chord_m = 4.0 * target_area_m2 / (math.pi * span_m)
    etas = (0.0, 0.125, 0.25, 0.375, 0.50, 0.625, 0.75, 0.875, 0.95, 1.0)
    chords = [
        root_chord_m * math.sqrt(max(1.0 - eta**2, 0.0))
        for eta in etas
    ]
    chords[-2] = max(0.25, chords[-2])
    chords[-1] = 0.08
    stations = tuple(
        WingStation(
            y_m=float(eta * half_span_m),
            chord_m=float(chord),
            twist_deg=0.0,
            dihedral_deg=0.0,
        )
        for eta, chord in zip(etas, chords, strict=True)
    )
    concept = _concept_from_stations(cfg=cfg, span_m=span_m, stations=stations)
    return {
        "case_id": "near_elliptic_uniform_airfoil",
        "description": "Near-elliptic planform with one airfoil family to isolate AVL/Sref/Bref/paneling.",
        "expected_e_cdi_min": 0.95,
        "expected_e_cdi_note": "Contract sanity should be close to elliptic induced efficiency.",
        "airfoil_policy": "uniform_fx76mp140_contract_isolation",
        "zone_airfoil_paths": _uniform_fx_zone_paths(),
        "concept": concept,
        "stations": stations,
    }


def _hpa_taper_uniform_case(cfg: BirdmanConceptConfig) -> dict[str, Any]:
    span_m = 34.5
    wing_area_m2 = 31.0
    taper_ratio = 1.0 / 3.0
    half_span_m = 0.5 * span_m
    root_chord_m = 2.0 * wing_area_m2 / (span_m * (1.0 + taper_ratio))
    tip_chord_m = root_chord_m * taper_ratio
    etas = (0.0, 0.125, 0.25, 0.375, 0.50, 0.625, 0.75, 0.875, 0.95, 1.0)
    stations = tuple(
        WingStation(
            y_m=float(eta * half_span_m),
            chord_m=float(root_chord_m + eta * (tip_chord_m - root_chord_m)),
            twist_deg=float(-6.0 * eta**1.5),
            dihedral_deg=0.0,
        )
        for eta in etas
    )
    concept = _concept_from_stations(cfg=cfg, span_m=span_m, stations=stations)
    return {
        "case_id": "hpa_taper_uniform_airfoil",
        "description": "Daedalus-like one-third taper and smooth washout with uniform airfoil to test HPA-scale geometry.",
        "expected_e_cdi_min": 0.88,
        "expected_e_cdi_note": "This should land in a researchable HPA range without relying on mixed-airfoil incidence effects.",
        "airfoil_policy": "uniform_fx76mp140_contract_isolation",
        "zone_airfoil_paths": _uniform_fx_zone_paths(),
        "concept": concept,
        "stations": stations,
    }


def _current_inverse_chord_case(cfg: BirdmanConceptConfig) -> dict[str, Any]:
    return {
        "case_id": "current_inverse_chord_mixed_seed_airfoils",
        "description": "Current optimizer path: inverse chord plus mixed root/tip seed airfoils and residual Ainc.",
        "expected_e_cdi_min": None,
        "expected_e_cdi_note": "Diagnostic only; expected to reproduce current e_CDi around 0.8 if outer wing remains underloaded.",
        "airfoil_policy": "mixed_seed_airfoils_current_optimizer_path",
        "zone_airfoil_paths": None,
        "concept": None,
        "stations": None,
    }


def build_benchmark_cases(cfg: BirdmanConceptConfig) -> list[dict[str, Any]]:
    return [
        _near_elliptic_uniform_case(cfg),
        _hpa_taper_uniform_case(cfg),
        _current_inverse_chord_case(cfg),
    ]


def contract_gate_status(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for benchmark in report.get("benchmarks", []):
        threshold = benchmark.get("expected_e_cdi_min")
        e_cdi = benchmark.get("avl_e_cdi")
        if threshold is None:
            continue
        if e_cdi is None or float(e_cdi) < float(threshold):
            failures.append(
                {
                    "case_id": benchmark.get("case_id"),
                    "avl_e_cdi": e_cdi,
                    "expected_e_cdi_min": threshold,
                }
            )
    return {
        "contract_benchmarks_pass": not failures,
        "halt_optimizer_until_avl_contract_fixed": bool(failures),
        "failures": failures,
    }


def _outer_underload_summary(record: dict[str, Any]) -> dict[str, Any]:
    rows = record.get("station_table", [])
    ratios: list[dict[str, Any]] = []
    for eta in (0.70, 0.82, 0.90, 0.95):
        if not rows:
            continue
        nearest = min(rows, key=lambda row: abs(float(row.get("eta", 0.0)) - eta))
        target = nearest.get("target_circulation_norm")
        avl = nearest.get("avl_circulation_norm")
        ratio = None
        if target is not None and avl is not None and abs(float(target)) > 1.0e-9:
            ratio = float(avl) / max(float(target), 1.0e-9)
        ratios.append(
            {
                "requested_eta": float(eta),
                "station_eta": nearest.get("eta"),
                "target_circulation_norm": target,
                "avl_circulation_norm": avl,
                "avl_to_target_circulation_ratio": ratio,
                "target_local_cl": nearest.get("target_local_cl"),
                "avl_local_cl": nearest.get("avl_local_cl"),
            }
        )
    outer_ratios = [
        float(row["avl_to_target_circulation_ratio"])
        for row in ratios
        if row.get("avl_to_target_circulation_ratio") is not None
        and float(row["requested_eta"]) >= 0.82
    ]
    return {
        "ratios": ratios,
        "outer_underloaded": bool(outer_ratios and min(outer_ratios) < 0.85),
        "min_outer_avl_to_target_ratio": min(outer_ratios) if outer_ratios else None,
    }


def _compact_benchmark_result(
    *,
    case: dict[str, Any],
    avl: dict[str, Any],
    concept: GeometryConcept,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "description": case["description"],
        "airfoil_policy": case["airfoil_policy"],
        "expected_e_cdi_min": case["expected_e_cdi_min"],
        "expected_e_cdi_note": case["expected_e_cdi_note"],
        "status": avl.get("status"),
        "avl_e_cdi": avl.get("avl_e_cdi"),
        "avl_reported_e": avl.get("avl_reported_e"),
        "trim_cd_induced": avl.get("trim_cd_induced"),
        "trim_cl": avl.get("trim_cl"),
        "trim_aoa_deg": avl.get("trim_aoa_deg"),
        "geometry": spanload_smoke._geometry_summary(concept),
        "avl_file_path": avl.get("avl_file_path"),
        **(extra or {}),
    }


def run_benchmark_suite(
    *,
    cfg: BirdmanConceptConfig,
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    current_stage0_samples: int,
    current_optimizer_maxfev: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmarks: list[dict[str, Any]] = []
    for case in build_benchmark_cases(cfg)[:2]:
        concept = case["concept"]
        stations = case["stations"]
        assert isinstance(concept, GeometryConcept)
        assert isinstance(stations, tuple)
        avl = spanload_smoke._run_reference_avl_case(
            cfg=cfg,
            concept=concept,
            stations=stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            design_mass_kg=float(cfg.mass.design_gross_mass_kg),
            status_for_ranking="avl_e_contract_benchmark",
            avl_binary=avl_binary,
            case_tag=str(case["case_id"]),
            zone_airfoil_paths=case["zone_airfoil_paths"],
        )
        benchmarks.append(_compact_benchmark_result(case=case, avl=avl, concept=concept))

    stage0 = spanload_smoke._stage0_inverse_chord_sobol_prefilter(
        cfg=cfg,
        sample_count=int(current_stage0_samples),
        design_speed_mps=design_speed_mps,
        seed=20260503,
    )
    selected = spanload_smoke._select_stage1_inputs(
        list(stage0["accepted"]),
        top_k=1,
    )
    current_case = build_benchmark_cases(cfg)[2]
    if selected:
        current_record = spanload_smoke._optimize_regularized_twist_candidate(
            cfg=cfg,
            stage0_metric=selected[0],
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            optimizer_maxfev=int(current_optimizer_maxfev),
            optimizer_maxiter=2,
            optimize_spanload_coefficients=False,
        )
        benchmarks.append(
            _compact_benchmark_result(
                case=current_case,
                avl=current_record["avl_reference_case"],
                concept=current_record["concept"] if "concept" in current_record else selected[0]["concept"],
                extra={
                    "sample_index": current_record.get("sample_index"),
                    "status": current_record.get("status"),
                    "physical_acceptance": current_record.get("physical_acceptance"),
                    "outer_underload_summary": _outer_underload_summary(current_record),
                    "twist_gate_metrics": current_record.get("twist_gate_metrics"),
                },
            )
        )
    else:
        benchmarks.append(
            {
                "case_id": current_case["case_id"],
                "status": "not_run_no_stage0_candidate",
                "expected_e_cdi_min": None,
                "stage0_counts": stage0["counts"],
            }
        )

    report = {
        "schema_version": "birdman_avl_e_sanity_benchmark_v1",
        "design_speed_mps": float(design_speed_mps),
        "design_mass_kg": float(cfg.mass.design_gross_mass_kg),
        "benchmarks": benchmarks,
        "stage0_counts_for_current_inverse_case": stage0["counts"],
    }
    report["contract_gate_status"] = contract_gate_status(report)
    return report


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Birdman AVL e Sanity Benchmark",
        "",
        f"- Design case: {report['design_speed_mps']:.2f} m/s, {report['design_mass_kg']:.1f} kg",
        f"- Contract benchmarks pass: {report['contract_gate_status']['contract_benchmarks_pass']}",
        f"- Halt optimizer until AVL contract fixed: {report['contract_gate_status']['halt_optimizer_until_avl_contract_fixed']}",
        "",
        "| case | airfoil policy | e_CDi | reported e | CDi | expected min | status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for benchmark in report["benchmarks"]:
        lines.append(
            "| "
            f"{benchmark.get('case_id')} | "
            f"{benchmark.get('airfoil_policy')} | "
            f"{benchmark.get('avl_e_cdi')} | "
            f"{benchmark.get('avl_reported_e')} | "
            f"{benchmark.get('trim_cd_induced')} | "
            f"{benchmark.get('expected_e_cdi_min')} | "
            f"{benchmark.get('status')} |"
        )
    lines.append("")
    lines.append("## Engineering Read")
    lines.append("")
    if report["contract_gate_status"]["contract_benchmarks_pass"]:
        lines.append(
            "- AVL Sref/Bref/Cref/paneling contract passes the uniform-airfoil sanity checks; low current e is therefore a spanload/incidence problem, not an AVL reference-area bug."
        )
    else:
        lines.append(
            "- At least one reference benchmark failed; do not continue optimizer work until the AVL contract is fixed."
        )
    current = next(
        (
            item
            for item in report["benchmarks"]
            if item.get("case_id") == "current_inverse_chord_mixed_seed_airfoils"
        ),
        {},
    )
    if current:
        lines.append(
            "- Current inverse-chord mixed-airfoil benchmark: "
            f"e_CDi={current.get('avl_e_cdi')}, "
            f"outer_underloaded={current.get('outer_underload_summary', {}).get('outer_underloaded')}."
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/birdman_upstream_concept_baseline.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/birdman_avl_e_sanity_benchmark"))
    parser.add_argument("--design-speed-mps", type=float, default=6.8)
    parser.add_argument("--current-stage0-samples", type=int, default=64)
    parser.add_argument("--current-optimizer-maxfev", type=int, default=0)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--fail-on-contract-benchmark-fail", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    report = run_benchmark_suite(
        cfg=cfg,
        output_dir=args.output_dir,
        design_speed_mps=float(args.design_speed_mps),
        avl_binary=args.avl_binary,
        current_stage0_samples=int(args.current_stage0_samples),
        current_optimizer_maxfev=int(args.current_optimizer_maxfev),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "avl_e_sanity_benchmark.json"
    md_path = args.output_dir / "avl_e_sanity_benchmark.md"
    json_path.write_text(json.dumps(spanload_smoke._round(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown(spanload_smoke._round(report), md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))
    if args.fail_on_contract_benchmark_fail and report["contract_gate_status"]["halt_optimizer_until_avl_contract_fixed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
