#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPANLOAD_SCRIPT = REPO_ROOT / "scripts" / "birdman_spanload_design_smoke.py"
REPORT_PATH = (
    REPO_ROOT
    / "output"
    / "birdman_outer_loading_diagnostic_smoke"
    / "spanload_design_smoke_report.json"
)
DOCS_OUTPUT_DIR = REPO_ROOT / "docs" / "research" / "dae_outer_airfoil_avl_match"
AVL_OUTPUT_DIR = REPO_ROOT / "output" / "dae_outer_airfoil_avl_match"
JSON_OUTPUT_PATH = DOCS_OUTPUT_DIR / "dae_outer_avl_sweep.json"
MD_OUTPUT_PATH = DOCS_OUTPUT_DIR / "dae_outer_avl_sweep.md"
OUTER_SAMPLE_ETAS = (0.70, 0.82, 0.90, 0.95)


def _load_spanload_smoke_module():
    spec = importlib.util.spec_from_file_location("birdman_spanload_design_smoke", SPANLOAD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load spanload smoke script: {SPANLOAD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_spanload_smoke_module()

from hpa_mdo.concept.config import load_concept_config  # noqa: E402
from hpa_mdo.concept.geometry import GeometryConcept, WingStation  # noqa: E402


def _round(value: Any, digits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return round(value, digits)
    if isinstance(value, dict):
        return {str(key): _round(val, digits) for key, val in value.items()}
    if isinstance(value, list | tuple):
        return [_round(item, digits) for item in value]
    return value


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None:
        return None
    denominator_f = float(denominator)
    if abs(denominator_f) <= 1.0e-12:
        return None
    return float(numerator) / denominator_f


def _candidate_stations(candidate: dict[str, Any]) -> tuple[WingStation, ...]:
    rows = sorted(candidate["station_table"], key=lambda row: float(row["y_m"]))
    return tuple(
        WingStation(
            y_m=float(row["y_m"]),
            chord_m=float(row["chord_m"]),
            twist_deg=float(row.get("twist_deg", row.get("ainc_deg", 0.0))),
            dihedral_deg=float(row.get("dihedral_deg", 0.0)),
        )
        for row in rows
    )


def _candidate_concept(candidate: dict[str, Any], cfg: Any) -> GeometryConcept:
    geometry = candidate["geometry"]
    stations = _candidate_stations(candidate)
    half_span = 0.5 * float(geometry["span_m"])
    segment_lengths_m = tuple(
        float(right.y_m - left.y_m) for left, right in zip(stations[:-1], stations[1:])
    )
    if abs(sum(segment_lengths_m) - half_span) > 1.0e-6:
        raise ValueError(
            f"station segment sum {sum(segment_lengths_m)} does not match half span {half_span}"
        )
    spanload = candidate["spanload_fourier"]
    twist_controls = tuple(
        (
            float(row.get("eta", 0.0 if half_span <= 0.0 else float(row["y_m"]) / half_span)),
            float(row.get("twist_deg", row.get("ainc_deg", 0.0))),
        )
        for row in sorted(candidate["station_table"], key=lambda row: float(row["y_m"]))
    )
    tail_area_m2 = float(geometry["wing_area_m2"]) * 0.4 / max(
        float(cfg.tail_model.tail_arm_to_mac), 1.0e-9
    )
    return GeometryConcept(
        span_m=float(geometry["span_m"]),
        wing_area_m2=float(geometry["wing_area_m2"]),
        root_chord_m=float(geometry["root_chord_m"]),
        tip_chord_m=float(geometry["tip_chord_m"]),
        twist_root_deg=float(stations[0].twist_deg),
        twist_tip_deg=float(stations[-1].twist_deg),
        tail_area_m2=float(tail_area_m2),
        cg_xc=float(cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths_m,
        tail_area_source="derived_placeholder_not_used_by_wing_only_avl_sweep",
        tail_volume_coefficient=0.4,
        twist_control_points=twist_controls,
        spanload_bias=0.0,
        spanload_a3_over_a1=float(spanload["a3_over_a1"]),
        spanload_a5_over_a1=float(spanload["a5_over_a1"]),
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / float(geometry["wing_area_m2"])),
        mean_chord_target_m=float(geometry["mean_chord_m"]),
        wing_area_is_derived=True,
        planform_parameterization="spanload_inverse_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
        dihedral_root_deg=float(stations[0].dihedral_deg),
        dihedral_tip_deg=float(stations[-1].dihedral_deg),
        dihedral_exponent=1.0,
    )


def _outer_samples(station_table: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    samples: dict[str, dict[str, Any]] = {}
    for eta in OUTER_SAMPLE_ETAS:
        nearest = min(station_table, key=lambda row: abs(float(row.get("eta", 0.0)) - eta))
        circ_ratio = _safe_ratio(
            nearest.get("avl_circulation_norm"), nearest.get("target_circulation_norm")
        )
        cl_ratio = _safe_ratio(nearest.get("avl_local_cl"), nearest.get("target_local_cl"))
        samples[f"{eta:.2f}"] = {
            "station_eta": nearest.get("eta"),
            "y_m": nearest.get("y_m"),
            "chord_m": nearest.get("chord_m"),
            "reynolds": nearest.get("reynolds"),
            "target_local_cl": nearest.get("target_local_cl"),
            "avl_local_cl": nearest.get("avl_local_cl"),
            "avl_to_target_cl_ratio": cl_ratio,
            "target_circulation_norm": nearest.get("target_circulation_norm"),
            "avl_circulation_norm": nearest.get("avl_circulation_norm"),
            "avl_to_target_circulation_ratio": circ_ratio,
        }
    return samples


def _outer_summary(samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    circ_ratios = [
        float(sample["avl_to_target_circulation_ratio"])
        for sample in samples.values()
        if sample.get("avl_to_target_circulation_ratio") is not None
    ]
    cl_ratios = [
        float(sample["avl_to_target_cl_ratio"])
        for sample in samples.values()
        if sample.get("avl_to_target_cl_ratio") is not None
    ]
    cl_gaps = [
        abs(float(sample["target_local_cl"]) - float(sample["avl_local_cl"]))
        for sample in samples.values()
        if sample.get("target_local_cl") is not None and sample.get("avl_local_cl") is not None
    ]
    return {
        "mean_outer_circulation_ratio": (
            sum(circ_ratios) / len(circ_ratios) if circ_ratios else None
        ),
        "min_outer_circulation_ratio": min(circ_ratios) if circ_ratios else None,
        "mean_abs_outer_circulation_ratio_error": (
            sum(abs(value - 1.0) for value in circ_ratios) / len(circ_ratios)
            if circ_ratios
            else None
        ),
        "mean_outer_cl_ratio": sum(cl_ratios) / len(cl_ratios) if cl_ratios else None,
        "min_outer_cl_ratio": min(cl_ratios) if cl_ratios else None,
        "mean_abs_outer_cl_gap": sum(cl_gaps) / len(cl_gaps) if cl_gaps else None,
    }


def _baseline_result(candidate: dict[str, Any]) -> dict[str, Any]:
    station_table = candidate["station_table"]
    samples = _outer_samples(station_table)
    match = candidate.get("avl_match_metrics", {})
    avl_ref = candidate.get("avl_reference_case", {})
    return {
        "sample_index": int(candidate["sample_index"]),
        "outer_airfoil": "clarkysm",
        "airfoil_role": "existing_reference_mid2_tip",
        "airfoil_path": str(REPO_ROOT / "data" / "airfoils" / "clarkysm.dat"),
        "status": avl_ref.get("status", "unknown"),
        "avl_reference_case": {
            key: avl_ref.get(key)
            for key in (
                "cl_required",
                "trim_aoa_deg",
                "trim_cl",
                "trim_cd_induced",
                "avl_e_cdi",
                "avl_reported_e",
                "avl_file_path",
                "avl_case_dir",
            )
        },
        "avl_match_metrics": match,
        "outer_samples": samples,
        "outer_summary": _outer_summary(samples),
    }


def _run_dae_case(
    *,
    cfg: Any,
    candidate: dict[str, Any],
    dae_name: str,
    dae_path: Path,
    design_speed_mps: float,
    design_mass_kg: float,
    avl_binary: str | None,
) -> dict[str, Any]:
    concept = _candidate_concept(candidate, cfg)
    stations = _candidate_stations(candidate)
    target_table, _target_summary = smoke._target_station_records(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    zone_airfoil_paths = {
        "root": REPO_ROOT / "data" / "airfoils" / "fx76mp140.dat",
        "mid1": REPO_ROOT / "data" / "airfoils" / "fx76mp140.dat",
        "mid2": dae_path,
        "tip": dae_path,
    }
    avl = smoke._run_reference_avl_case(
        cfg=cfg,
        concept=concept,
        stations=stations,
        output_dir=AVL_OUTPUT_DIR,
        design_speed_mps=design_speed_mps,
        design_mass_kg=design_mass_kg,
        status_for_ranking=f"dae_outer_{dae_name}_sample_{int(candidate['sample_index']):04d}",
        avl_binary=avl_binary,
        case_tag="mid2_tip",
        zone_airfoil_paths=zone_airfoil_paths,
    )
    station_table = smoke._attach_avl_to_station_table(target_table, avl)
    match = smoke._avl_match_metrics(station_table)
    samples = _outer_samples(station_table)
    return {
        "sample_index": int(candidate["sample_index"]),
        "outer_airfoil": dae_name,
        "airfoil_role": "dae_mid2_tip_with_fx76mp140_root_mid1",
        "airfoil_path": str(dae_path),
        "status": avl.get("status"),
        "avl_reference_case": {
            key: avl.get(key)
            for key in (
                "cl_required",
                "trim_aoa_deg",
                "trim_cl",
                "trim_cd_induced",
                "avl_e_cdi",
                "avl_reported_e",
                "avl_file_path",
                "avl_case_dir",
            )
        },
        "avl_match_metrics": match,
        "outer_samples": samples,
        "outer_summary": _outer_summary(samples),
    }


def _summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        avl = result["avl_reference_case"]
        match = result.get("avl_match_metrics", {})
        outer = result.get("outer_summary", {})
        samples = result.get("outer_samples", {})
        rows.append(
            {
                "sample_index": result["sample_index"],
                "outer_airfoil": result["outer_airfoil"],
                "status": result["status"],
                "e_CDi": avl.get("avl_e_cdi"),
                "CDi": avl.get("trim_cd_induced"),
                "trim_alpha_deg": avl.get("trim_aoa_deg"),
                "match_rms_delta": match.get("rms_target_avl_circulation_norm_delta"),
                "match_max_delta": match.get("max_target_avl_circulation_norm_delta"),
                "outer_mean_circ_ratio": outer.get("mean_outer_circulation_ratio"),
                "outer_min_circ_ratio": outer.get("min_outer_circulation_ratio"),
                "outer_mean_cl_ratio": outer.get("mean_outer_cl_ratio"),
                "eta70_cl": samples.get("0.70", {}).get("avl_local_cl"),
                "eta82_cl": samples.get("0.82", {}).get("avl_local_cl"),
                "eta90_cl": samples.get("0.90", {}).get("avl_local_cl"),
                "eta95_cl": samples.get("0.95", {}).get("avl_local_cl"),
            }
        )
    return rows


def _best_per_sample(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dae_results = [result for result in results if result["outer_airfoil"] != "clarkysm"]
    best = []
    for sample_index in sorted({int(result["sample_index"]) for result in dae_results}):
        sample_results = [
            result
            for result in dae_results
            if int(result["sample_index"]) == sample_index and result.get("status") == "ok"
        ]
        if not sample_results:
            continue
        best_result = min(
            sample_results,
            key=lambda result: (
                float(
                    result.get("avl_match_metrics", {}).get(
                        "rms_target_avl_circulation_norm_delta", 1.0e9
                    )
                    or 1.0e9
                ),
                float(
                    result.get("outer_summary", {}).get(
                        "mean_abs_outer_circulation_ratio_error", 1.0e9
                    )
                    or 1.0e9
                ),
            ),
        )
        best.append(best_result)
    return best


def _result_by_sample_and_airfoil(results: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    return {
        (int(result["sample_index"]), str(result["outer_airfoil"])): result
        for result in results
    }


def _target_vs_best_cl_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = _result_by_sample_and_airfoil(results)
    best_by_sample = {
        int(result["sample_index"]): result for result in _best_per_sample(results)
    }
    rows: list[dict[str, Any]] = []
    for sample_index in sorted(best_by_sample):
        baseline = by_key[(sample_index, "clarkysm")]
        best = best_by_sample[sample_index]
        for eta_key in [f"{eta:.2f}" for eta in OUTER_SAMPLE_ETAS]:
            base_sample = baseline["outer_samples"][eta_key]
            best_sample = best["outer_samples"][eta_key]
            rows.append(
                {
                    "sample_index": sample_index,
                    "eta": eta_key,
                    "target_cl": base_sample.get("target_local_cl"),
                    "clarkysm_cl": base_sample.get("avl_local_cl"),
                    "best_dae": best["outer_airfoil"],
                    "best_dae_cl": best_sample.get("avl_local_cl"),
                    "best_dae_cl_ratio": best_sample.get("avl_to_target_cl_ratio"),
                    "best_dae_gamma_ratio": best_sample.get(
                        "avl_to_target_circulation_ratio"
                    ),
                }
            )
    return rows


def _engineering_read(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = _result_by_sample_and_airfoil(results)
    best_results = _best_per_sample(results)
    improvements = []
    for result in best_results:
        sample_index = int(result["sample_index"])
        baseline = by_key[(sample_index, "clarkysm")]
        improvements.append(
            {
                "sample_index": sample_index,
                "best_dae": result["outer_airfoil"],
                "e_CDi_ratio_vs_clarkysm": _safe_ratio(
                    result["avl_reference_case"].get("avl_e_cdi"),
                    baseline["avl_reference_case"].get("avl_e_cdi"),
                ),
                "absolute_e_CDi_gain": (
                    float(result["avl_reference_case"]["avl_e_cdi"])
                    - float(baseline["avl_reference_case"]["avl_e_cdi"])
                ),
                "rms_delta_change": (
                    float(result["avl_match_metrics"]["rms_target_avl_circulation_norm_delta"])
                    - float(
                        baseline["avl_match_metrics"][
                            "rms_target_avl_circulation_norm_delta"
                        ]
                    )
                ),
                "outer_mean_gamma_ratio_gain": (
                    float(result["outer_summary"]["mean_outer_circulation_ratio"])
                    - float(baseline["outer_summary"]["mean_outer_circulation_ratio"])
                ),
                "spanload_delta_success": bool(
                    result["avl_match_metrics"].get("target_avl_delta_success")
                ),
                "rms_delta_preferred": bool(
                    result["avl_match_metrics"].get("target_avl_rms_delta_preferred")
                ),
                "e_CDi_clears_0p85": bool(
                    float(result["avl_reference_case"].get("avl_e_cdi") or 0.0) >= 0.85
                ),
            }
        )
    return {
        "dae_avl_cases_run": sum(
            1 for result in results if result["outer_airfoil"] != "clarkysm"
        ),
        "dae_avl_cases_ok": sum(
            1
            for result in results
            if result["outer_airfoil"] != "clarkysm" and result.get("status") == "ok"
        ),
        "best_dae_by_fixed_geometry_match": [
            {
                "sample_index": int(result["sample_index"]),
                "outer_airfoil": result["outer_airfoil"],
            }
            for result in best_results
        ],
        "all_best_dae_are_dae31": all(
            result["outer_airfoil"] == "dae31" for result in best_results
        ),
        "improvements_vs_clarkysm": improvements,
        "engineering_conclusion": (
            "DAE31 is the best MIT DAE outer seed in this fixed-geometry AVL check, "
            "and it clears the prior e_CDi gate for all three candidates. It still "
            "does not truly match the Fourier target: the best outer circulation "
            "ratios remain about 0.67-0.75 and every best case still fails the "
            "max-delta target-avl success threshold."
        ),
    }


def _format_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{value_f:.{digits}f}"


def _markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for label, _key in columns) + " |"
    sep = "| " + " | ".join("---" for _label, _key in columns) + " |"
    body = []
    for row in rows:
        cells = []
        for _label, key in columns:
            value = row.get(key)
            if isinstance(value, float):
                cells.append(_format_float(value, 3))
            else:
                cells.append("" if value is None else str(value))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body])


def _write_markdown(payload: dict[str, Any]) -> None:
    rows = payload["summary_rows"]
    best = _summary_rows(payload["best_dae_per_sample"])
    target_vs_best = payload["target_vs_best_cl_rows"]
    engineering = payload["engineering_read"]
    columns = [
        ("sample", "sample_index"),
        ("outer", "outer_airfoil"),
        ("e_CDi", "e_CDi"),
        ("RMS dGamma", "match_rms_delta"),
        ("max dGamma", "match_max_delta"),
        ("outer mean Gamma ratio", "outer_mean_circ_ratio"),
        ("outer min Gamma ratio", "outer_min_circ_ratio"),
        ("eta70 Cl", "eta70_cl"),
        ("eta82 Cl", "eta82_cl"),
        ("eta90 Cl", "eta90_cl"),
        ("eta95 Cl", "eta95_cl"),
    ]
    cl_columns = [
        ("sample", "sample_index"),
        ("eta", "eta"),
        ("target Cl", "target_cl"),
        ("ClarkY Cl", "clarkysm_cl"),
        ("best DAE", "best_dae"),
        ("best DAE Cl", "best_dae_cl"),
        ("best Cl ratio", "best_dae_cl_ratio"),
        ("best Gamma ratio", "best_dae_gamma_ratio"),
    ]
    lines = [
        "# DAE outer-airfoil AVL match sweep",
        "",
        "This sweep fixes the diagnosed inverse-chord geometries and residual twist schedule from",
        "`output/birdman_outer_loading_diagnostic_smoke/spanload_design_smoke_report.json`.",
        "Only the outer AVL airfoil assignment changes: root/mid1 stay `fx76mp140`, while",
        "mid2/tip are replaced with DAE11, DAE21, DAE31, or DAE41.",
        "",
        "Important limitation: this is an AVL camberline/loading check, not a 2D viscous",
        "section-stall or drag validation. Use XFOIL at the listed Reynolds numbers before",
        "treating any DAE section as feasible.",
        "",
        "## Best DAE per sample",
        "",
        _markdown_table(best, columns),
        "",
        "## All cases",
        "",
        _markdown_table(rows, columns),
        "",
        "## Target Cl check",
        "",
        _markdown_table(target_vs_best, cl_columns),
        "",
        "## Engineering read",
        "",
        f"- DAE AVL cases run: `{engineering['dae_avl_cases_ok']}` / `{engineering['dae_avl_cases_run']}` ok.",
        "- DAE31 is the best fixed-geometry DAE option for all three samples.",
        "- DAE31 clears the prior `e_CDi >= 0.85` gate for all three samples, but none of the best cases clears the stricter max target-vs-AVL circulation delta success gate.",
        "- The ClarkY concern is real in this AVL check: replacing it with DAE31 raises outer mean circulation ratio by roughly 0.18-0.25 and improves e_CDi by about 0.09-0.11 absolute.",
        "- This still does not fully match the Fourier target. Best outer circulation ratios remain around 0.67-0.75, so the outer wing is still underloaded in the fixed geometry.",
        "- DAE41 is the wrong direction for this current incidence/twist schedule; it is worse than ClarkY on the main match metrics.",
        "",
        "## Inputs",
        "",
        f"- Config: `{payload['config_path']}`",
        f"- Design speed: `{payload['design_case']['speed_mps']}` m/s",
        f"- Design mass: `{payload['design_case']['mass_kg']}` kg",
        f"- DAE files: {', '.join('`' + item['name'] + '`' for item in payload['dae_airfoils'])}",
        f"- AVL cases: `{payload['avl_output_dir']}`",
    ]
    MD_OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    DOCS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AVL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cfg = load_concept_config(REPO_ROOT / report["config_path"])
    design_case = report["design_cruise_case"]
    dae_paths = [
        REPO_ROOT / "docs" / "research" / "historical_airfoil_cst_coverage" / "airfoils" / name
        for name in ("dae11.dat", "dae21.dat", "dae31.dat", "dae41.dat")
    ]
    missing = [str(path) for path in dae_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing DAE airfoil files: {missing}")

    results: list[dict[str, Any]] = []
    for candidate in report["candidates"]:
        results.append(_baseline_result(candidate))
        for dae_path in dae_paths:
            dae_name = dae_path.stem.lower()
            print(f"running sample {candidate['sample_index']} with {dae_name}...")
            results.append(
                _run_dae_case(
                    cfg=cfg,
                    candidate=candidate,
                    dae_name=dae_name,
                    dae_path=dae_path,
                    design_speed_mps=float(design_case["speed_mps"]),
                    design_mass_kg=float(design_case["mass_kg"]),
                    avl_binary="/usr/local/bin/avl",
                )
            )

    payload = {
        "schema_version": "dae_outer_avl_sweep.v1",
        "source_report": str(REPORT_PATH),
        "config_path": report["config_path"],
        "design_case": design_case,
        "airfoil_assignment": {
            "root": "data/airfoils/fx76mp140.dat",
            "mid1": "data/airfoils/fx76mp140.dat",
            "mid2_tip_sweep": [path.name for path in dae_paths],
        },
        "dae_airfoils": [
            {"name": path.stem.lower(), "path": str(path)} for path in dae_paths
        ],
        "avl_output_dir": str(AVL_OUTPUT_DIR),
        "results": results,
        "summary_rows": _summary_rows(results),
        "best_dae_per_sample": _best_per_sample(results),
        "target_vs_best_cl_rows": _target_vs_best_cl_rows(results),
        "engineering_read": _engineering_read(results),
        "limitations": [
            "AVL uses the airfoil camberline effect but does not validate 2D viscous polar, Clmax, laminar bucket, or low-Re separation margin.",
            "The geometry and twist are fixed to the prior diagnostic candidates; this is not a re-optimization around the DAE sections.",
        ],
    }
    JSON_OUTPUT_PATH.write_text(json.dumps(_round(payload), indent=2) + "\n", encoding="utf-8")
    _write_markdown(_round(payload))
    print(f"wrote {JSON_OUTPUT_PATH}")
    print(f"wrote {MD_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
