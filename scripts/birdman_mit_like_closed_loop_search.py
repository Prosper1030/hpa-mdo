#!/usr/bin/env python3
"""Birdman MIT-like closed-loop Stage-1 search.

This is the redirected Stage-1 driver:

* Generate MIT-like high-AR (37-40) sensible-taper (0.30-0.40) Birdman
  candidates with **no** outer chord bump
  (:func:`generate_mit_like_candidates`).
* For each candidate run the AVL-no-airfoil pass via the existing
  :func:`load_zone_requirements_from_avl` (passing
  ``airfoil_templates=None``) — this produces per-zone ``cl_target`` and
  ``reynolds`` from real AVL strip forces, not from the Fourier-shape
  stub.
* Pick a per-zone airfoil from the seed library
  (:mod:`hpa_mdo.concept.zone_airfoil_picker`) using the AVL-derived
  ``cl_target`` and Re.  This is a deterministic placeholder for the
  full CST/XFOIL search — the picker emits the same airfoil-template
  payload that ``load_zone_requirements_from_avl`` already accepts when
  re-running AVL with airfoil files.
* Re-run AVL with the selected airfoils and compute the actual e_CDi,
  outer-loading ratios, and trim CDi.
* Compute a mission power proxy = q∞·S·(CDi + chord-weighted profile
  CD).  Profile CD comes from the picker's zone-level polar fit.
* **Do not** prune candidates by the first-round e_CDi — every
  generated candidate goes through both AVL passes; the report ranks
  them by post-airfoil e_CDi and mission power.

This script does not yet plug into the full CST/XFOIL search inside
:mod:`hpa_mdo.concept.airfoil_selection`; that wiring is the natural
follow-up once we have a stable closed loop on top of the seed library.
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.atmosphere import air_properties_from_environment  # noqa: E402
from hpa_mdo.concept.avl_loader import (  # noqa: E402
    load_zone_requirements_from_avl,
)
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config  # noqa: E402
from hpa_mdo.concept.mit_like_candidate import (  # noqa: E402
    DEFAULT_AR_RANGE,
    DEFAULT_TAPER_RATIO_RANGE,
    DEFAULT_SPAN_RANGE_M,
    MITLikeCandidate,
    generate_mit_like_candidates,
    stations_for_mit_like_candidate,
)
from hpa_mdo.concept.zone_airfoil_picker import (  # noqa: E402
    aerodynamic_summary,
    airfoil_templates_for_avl,
    chord_weighted_profile_cd,
    estimate_zone_profile_cd,
    select_zone_airfoils_from_library,
)


G_MPS2 = 9.80665


@dataclass(frozen=True)
class ClosedLoopResult:
    sample_index: int
    candidate: MITLikeCandidate
    no_airfoil_avl: dict[str, Any]
    selected_airfoils: dict[str, Any]
    with_airfoil_avl: dict[str, Any]
    profile_drag: dict[str, Any]
    mission_power: dict[str, Any]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_index": int(self.sample_index),
            "candidate": self.candidate.to_summary(),
            "no_airfoil_avl": self.no_airfoil_avl,
            "selected_airfoils": self.selected_airfoils,
            "with_airfoil_avl": self.with_airfoil_avl,
            "profile_drag": self.profile_drag,
            "mission_power": self.mission_power,
            "failure_reason": self.failure_reason,
        }


def _summarise_zone_avl(
    *,
    zone_payload: dict[str, dict[str, Any]],
    cruise_speed_mps: float,
) -> dict[str, Any]:
    design_cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in zone_payload.values():
        for case in payload.get("design_cases", []):
            label = str(case.get("case_label"))
            if label in seen:
                continue
            seen.add(label)
            design_cases.append(case)
    e_cdi_per_case: list[dict[str, Any]] = []
    for case in design_cases:
        cl = case.get("trim_cl")
        cd_induced = case.get("trim_cd_induced")
        if cl is None or cd_induced is None or float(cd_induced) <= 0.0:
            continue
        e_cdi_per_case.append(
            {
                "case_label": case.get("case_label"),
                "evaluation_speed_mps": case.get("evaluation_speed_mps"),
                "load_factor": case.get("load_factor"),
                "trim_cl": float(cl),
                "trim_cd_induced": float(cd_induced),
            }
        )
    zone_points: dict[str, list[dict[str, Any]]] = {
        zone_name: list(payload.get("points", []))
        for zone_name, payload in zone_payload.items()
    }
    # Pick the design case whose evaluation_speed_mps is closest to the
    # mission cruise speed and which also has a 1g load factor; that
    # case carries the representative cruise trim for the closed loop.
    cruise_case: dict[str, Any] = {}
    cruise_distance = float("inf")
    for case in design_cases:
        load_factor = float(case.get("load_factor", 1.0) or 1.0)
        if abs(load_factor - 1.0) > 0.05:
            continue
        speed = case.get("evaluation_speed_mps")
        if speed is None:
            continue
        distance = abs(float(speed) - float(cruise_speed_mps))
        if distance < cruise_distance:
            cruise_distance = distance
            cruise_case = case
    if not cruise_case and design_cases:
        cruise_case = design_cases[0]
    return {
        "design_cases": design_cases,
        "trim_cases_with_cd_induced": e_cdi_per_case,
        "cruise_case_label": cruise_case.get("case_label"),
        "cruise_evaluation_speed_mps": cruise_case.get("evaluation_speed_mps"),
        "representative_trim_cl": cruise_case.get("trim_cl"),
        "representative_trim_cd_induced": cruise_case.get("trim_cd_induced"),
        "representative_trim_aoa_deg": cruise_case.get("trim_aoa_deg"),
        "zone_points": zone_points,
    }


def _outer_ratio_metrics(
    *,
    zone_payload: dict[str, dict[str, Any]],
    target_zone_payload: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare AVL-with-airfoil and AVL-no-airfoil per-station cl_target.

    The cl ratio between the two passes is a quick signal for how much
    the selected airfoil shifted the realised loading versus the
    no-airfoil baseline.  A ratio close to 1 means the picker did not
    change the section's effective lift schedule (likely because both
    seeds have similar :math:`\alpha_{L0}`); larger deviations indicate
    the closed loop actually moved circulation around.
    """

    samples: list[dict[str, Any]] = []
    for zone_name, payload in zone_payload.items():
        target_points = target_zone_payload.get(zone_name, {}).get("points", [])
        with_points = payload.get("points", [])
        for with_point, target_point in zip(with_points, target_points, strict=False):
            cl_with = float(with_point.get("cl_target", 0.0))
            cl_no = float(target_point.get("cl_target", 0.0))
            station_y = float(with_point.get("station_y_m", 0.0))
            samples.append(
                {
                    "zone": str(zone_name),
                    "station_y_m": station_y,
                    "no_airfoil_cl": cl_no,
                    "with_airfoil_cl": cl_with,
                    "ratio": (
                        float(cl_with / cl_no) if abs(cl_no) > 1.0e-9 else None
                    ),
                }
            )
    valid_ratios = [
        float(sample["ratio"]) for sample in samples if sample.get("ratio") is not None
    ]
    return {
        "samples": samples,
        "ratio_mean": float(sum(valid_ratios) / len(valid_ratios)) if valid_ratios else None,
        "ratio_min": float(min(valid_ratios)) if valid_ratios else None,
        "ratio_max": float(max(valid_ratios)) if valid_ratios else None,
    }


def _mission_power_proxy(
    *,
    cfg: BirdmanConceptConfig,
    candidate: MITLikeCandidate,
    e_cdi: float,
    cd_profile: float,
    design_speed_mps: float,
    misc_cd: float = 0.0010,
) -> dict[str, Any]:
    """q∞·S·(CL²/πARe + profile CD + misc) → P required at cruise.

    AVL gives us the post-airfoil ``e_CDi``; the mission power proxy
    re-derives the induced CD at the cruise speed (which differs from
    AVL's slow-trim case) and uses the picker's chord-weighted profile
    CD as the parasite term.  This keeps the mission proxy honest for
    candidates whose AVL design case happens to sit at a different
    speed from the cruise leg.
    """

    air = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    weight_n = float(cfg.mass.design_gross_mass_kg) * float(G_MPS2)
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(design_speed_mps) ** 2
    cl_cruise = weight_n / max(
        q_pa * float(candidate.wing_area_m2), 1.0e-9
    )
    cd_induced_cruise = (
        float(cl_cruise) ** 2
        / max(math.pi * float(candidate.aspect_ratio) * float(e_cdi), 1.0e-9)
        if float(e_cdi) > 0.0
        else None
    )
    if cd_induced_cruise is None:
        cd_total = None
        drag_n = None
        power_w = None
    else:
        cd_total = float(cd_induced_cruise) + float(cd_profile) + float(misc_cd)
        drag_n = float(q_pa * float(candidate.wing_area_m2) * cd_total)
        power_w = float(drag_n * float(design_speed_mps))
    return {
        "design_speed_mps": float(design_speed_mps),
        "air_density_kg_per_m3": float(air.density_kg_per_m3),
        "wing_area_m2": float(candidate.wing_area_m2),
        "cl_cruise": float(cl_cruise),
        "e_cdi_avl": float(e_cdi),
        "cd_induced_cruise": cd_induced_cruise,
        "cd_profile": float(cd_profile),
        "cd_misc": float(misc_cd),
        "cd_total": cd_total,
        "drag_n": drag_n,
        "power_required_w": power_w,
    }


def run_closed_loop_for_candidate(
    *,
    cfg: BirdmanConceptConfig,
    candidate: MITLikeCandidate,
    output_dir: Path,
    avl_binary: str | None,
    stations_per_half: int = 9,
    mission_design_speed_mps: float = 6.6,
) -> ClosedLoopResult:
    """Run the AVL no-airfoil → picker → AVL with airfoil loop on one
    candidate.  Returns a :class:`ClosedLoopResult`; failures inside any
    step are captured into ``failure_reason`` rather than raised so the
    driver can still rank surviving candidates.
    """

    sample_id = f"sample_{candidate.sample_index:04d}"
    candidate_dir = output_dir / sample_id
    candidate_dir.mkdir(parents=True, exist_ok=True)

    stations = stations_for_mit_like_candidate(
        candidate=candidate, stations_per_half=stations_per_half
    )

    try:
        no_airfoil_zone = load_zone_requirements_from_avl(
            cfg=cfg,
            concept=candidate.concept,
            stations=stations,
            working_root=candidate_dir / "avl_no_airfoil",
            avl_binary=avl_binary,
            airfoil_templates=None,
            case_tag="no_airfoil",
        )
    except Exception as exc:  # noqa: BLE001 — surface AVL stage-1 errors.
        return ClosedLoopResult(
            sample_index=candidate.sample_index,
            candidate=candidate,
            no_airfoil_avl={"status": "failed", "error": str(exc)},
            selected_airfoils={},
            with_airfoil_avl={"status": "skipped"},
            profile_drag={},
            mission_power={"status": "skipped"},
            failure_reason=f"avl_no_airfoil_failed:{exc}",
        )

    no_airfoil_summary = _summarise_zone_avl(
        zone_payload=no_airfoil_zone, cruise_speed_mps=mission_design_speed_mps
    )
    selected_specs = select_zone_airfoils_from_library(
        zone_requirements=no_airfoil_zone
    )
    selected_payload = airfoil_templates_for_avl(selected_specs)
    aero_summary = aerodynamic_summary(selected_specs)

    try:
        with_airfoil_zone = load_zone_requirements_from_avl(
            cfg=cfg,
            concept=candidate.concept,
            stations=stations,
            working_root=candidate_dir / "avl_with_airfoil",
            avl_binary=avl_binary,
            airfoil_templates=selected_payload,
            case_tag="with_airfoil",
        )
    except Exception as exc:  # noqa: BLE001
        return ClosedLoopResult(
            sample_index=candidate.sample_index,
            candidate=candidate,
            no_airfoil_avl=no_airfoil_summary,
            selected_airfoils={
                "specs": {
                    name: spec.to_template() for name, spec in selected_specs.items()
                },
                "aerodynamic_summary": aero_summary,
            },
            with_airfoil_avl={"status": "failed", "error": str(exc)},
            profile_drag={},
            mission_power={"status": "skipped"},
            failure_reason=f"avl_with_airfoil_failed:{exc}",
        )

    with_airfoil_summary = _summarise_zone_avl(
        zone_payload=with_airfoil_zone, cruise_speed_mps=mission_design_speed_mps
    )
    outer_ratios = _outer_ratio_metrics(
        zone_payload=with_airfoil_zone, target_zone_payload=no_airfoil_zone
    )

    profile_per_zone = estimate_zone_profile_cd(
        selected=selected_specs,
        zone_requirements=with_airfoil_zone,
    )
    cd_profile_total = chord_weighted_profile_cd(zone_profile=profile_per_zone)

    representative_cd_induced = with_airfoil_summary.get("representative_trim_cd_induced")
    if representative_cd_induced is None:
        cd_induced_values = [
            float(case["trim_cd_induced"])
            for case in with_airfoil_summary.get("trim_cases_with_cd_induced", [])
            if float(case.get("trim_cd_induced", 0.0)) > 0.0
        ]
        representative_cd_induced = (
            min(cd_induced_values) if cd_induced_values else None
        )
    e_cdi_post = None
    representative_trim_cl = with_airfoil_summary.get("representative_trim_cl")
    if (
        representative_cd_induced is not None
        and representative_trim_cl is not None
        and float(representative_cd_induced) > 0.0
    ):
        e_cdi_post = float(representative_trim_cl) ** 2 / (
            math.pi
            * float(candidate.aspect_ratio)
            * float(representative_cd_induced)
        )

    mission_power = _mission_power_proxy(
        cfg=cfg,
        candidate=candidate,
        e_cdi=float(e_cdi_post or 0.0),
        cd_profile=float(cd_profile_total),
        design_speed_mps=float(mission_design_speed_mps),
    )
    mission_power["e_cdi_post_airfoil"] = e_cdi_post
    mission_power["representative_avl_trim_cl"] = representative_trim_cl
    mission_power["representative_avl_trim_cd_induced"] = representative_cd_induced

    return ClosedLoopResult(
        sample_index=candidate.sample_index,
        candidate=candidate,
        no_airfoil_avl=no_airfoil_summary,
        selected_airfoils={
            "specs": {
                name: spec.to_template() for name, spec in selected_specs.items()
            },
            "aerodynamic_summary": aero_summary,
        },
        with_airfoil_avl={
            **with_airfoil_summary,
            "outer_ratio_vs_no_airfoil": outer_ratios,
            "representative_e_cdi": e_cdi_post,
        },
        profile_drag={
            "per_zone": profile_per_zone,
            "chord_weighted_cd_profile": float(cd_profile_total),
        },
        mission_power=mission_power,
    )


def _evaluate_one(
    *,
    config_path: Path,
    output_dir: Path,
    avl_binary: str | None,
    stations_per_half: int,
    mission_design_speed_mps: float,
    candidate: MITLikeCandidate,
) -> dict[str, Any]:
    cfg = load_concept_config(config_path)
    result = run_closed_loop_for_candidate(
        cfg=cfg,
        candidate=candidate,
        output_dir=output_dir,
        avl_binary=avl_binary,
        stations_per_half=stations_per_half,
        mission_design_speed_mps=mission_design_speed_mps,
    )
    return result.to_dict()


def run_search(
    *,
    cfg: BirdmanConceptConfig,
    config_path: Path,
    output_dir: Path,
    sample_count: int,
    ar_range: tuple[float, float],
    taper_range: tuple[float, float],
    span_range_m: tuple[float, float],
    mission_design_speed_mps: float,
    avl_binary: str | None,
    workers: int,
    seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = generate_mit_like_candidates(
        cfg=cfg,
        sample_count=int(sample_count),
        ar_range=tuple(float(value) for value in ar_range),
        taper_range=tuple(float(value) for value in taper_range),
        span_range_m=tuple(float(value) for value in span_range_m),
        seed=int(seed),
    )
    results: list[dict[str, Any]] = []
    if workers > 1 and len(candidates) > 1:
        with ProcessPoolExecutor(max_workers=int(workers)) as executor:
            futures = {
                executor.submit(
                    _evaluate_one,
                    config_path=config_path,
                    output_dir=output_dir,
                    avl_binary=avl_binary,
                    stations_per_half=9,
                    mission_design_speed_mps=mission_design_speed_mps,
                    candidate=candidate,
                ): candidate
                for candidate in candidates
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for candidate in candidates:
            result = run_closed_loop_for_candidate(
                cfg=cfg,
                candidate=candidate,
                output_dir=output_dir,
                avl_binary=avl_binary,
                mission_design_speed_mps=mission_design_speed_mps,
            )
            results.append(result.to_dict())
            print(
                json.dumps(
                    {
                        "event": "candidate_done",
                        "sample_index": candidate.sample_index,
                        "AR": round(candidate.aspect_ratio, 3),
                        "taper": round(candidate.taper_ratio, 3),
                        "wing_area_m2": round(candidate.wing_area_m2, 3),
                        "failure_reason": result.failure_reason,
                        "e_cdi_post": (
                            result.mission_power.get("e_cdi_post_airfoil")
                            if isinstance(result.mission_power, dict)
                            else None
                        ),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    results.sort(key=lambda record: int(record.get("sample_index") or 0))
    ranked = sorted(
        [
            record
            for record in results
            if record.get("failure_reason") is None
            and record.get("mission_power", {}).get("e_cdi_post_airfoil") is not None
        ],
        key=lambda record: -float(
            record["mission_power"].get("e_cdi_post_airfoil") or 0.0
        ),
    )
    report = {
        "schema_version": "birdman_mit_like_closed_loop_search_v1",
        "search_parameters": {
            "ar_range": list(ar_range),
            "taper_range": list(taper_range),
            "span_range_m": list(span_range_m),
            "sample_count": int(sample_count),
            "mission_design_speed_mps": float(mission_design_speed_mps),
            "seed": int(seed),
        },
        "candidate_summary": [record["candidate"] for record in results],
        "results": results,
        "ranked_by_e_cdi_post_airfoil": [
            {
                "sample_index": record["sample_index"],
                "candidate": record["candidate"],
                "e_cdi_post_airfoil": record["mission_power"].get(
                    "e_cdi_post_airfoil"
                ),
                "power_required_w": record["mission_power"].get("power_required_w"),
                "cd_total": record["mission_power"].get("cd_total"),
                "no_airfoil_e_cdi": _no_airfoil_e_cdi(record),
            }
            for record in ranked
        ],
        "engineering_read": _engineering_read(ranked, results),
    }
    return report


def _no_airfoil_e_cdi(record: dict[str, Any]) -> float | None:
    summary = record.get("no_airfoil_avl") or {}
    cd_induced = summary.get("representative_trim_cd_induced")
    cl = summary.get("representative_trim_cl")
    if cd_induced is None or cl is None or float(cd_induced) <= 0.0:
        return None
    geometry = record.get("candidate") or {}
    aspect_ratio = float(geometry.get("aspect_ratio", 0.0))
    if aspect_ratio <= 0.0:
        return None
    return float(cl) ** 2 / (math.pi * aspect_ratio * float(cd_induced))


def _engineering_read(
    ranked: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if not results:
        return ["No candidates were generated; check the AR/taper/span ranges."]
    failed = [record for record in results if record.get("failure_reason")]
    if failed:
        reason_counts: dict[str, int] = {}
        for record in failed:
            reason = str(record.get("failure_reason"))
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        lines.append(
            "AVL closed-loop failures: "
            + ", ".join(f"{count}× {reason}" for reason, count in reason_counts.items())
        )
    if ranked:
        best = ranked[0]
        lines.append(
            "Top post-airfoil candidate: "
            f"sample {best['sample_index']} AR={best['candidate']['aspect_ratio']:.2f} "
            f"taper={best['candidate']['taper_ratio']:.3f}, "
            f"e_CDi(post)={best.get('e_cdi_post_airfoil')}, "
            f"P={best.get('power_required_w')} W."
        )
        no_airfoil = best.get("no_airfoil_e_cdi")
        if no_airfoil is not None:
            lines.append(
                f"e_CDi: no-airfoil={no_airfoil:.4f} → with-airfoil={best.get('e_cdi_post_airfoil'):.4f} "
                f"(Δ={float(best.get('e_cdi_post_airfoil') or 0.0) - float(no_airfoil):+.4f})."
            )
    return lines


def write_markdown(report: dict[str, Any], path: Path) -> None:
    parameters = report.get("search_parameters") or {}
    lines = [
        "# Birdman MIT-like Closed-Loop Stage-1 Search",
        "",
        f"- AR range: {parameters.get('ar_range')}",
        f"- Taper range: {parameters.get('taper_range')}",
        f"- Span range (m): {parameters.get('span_range_m')}",
        f"- Sample count: {parameters.get('sample_count')}",
        f"- Mission design speed: {parameters.get('mission_design_speed_mps')} m/s",
        f"- Seed: {parameters.get('seed')}",
        "",
        "## Engineering Read",
        "",
    ]
    for entry in report.get("engineering_read", []):
        lines.append(f"- {entry}")
    lines.append("")
    lines.append("## Closed-Loop Ranking (post-airfoil e_CDi descending)")
    lines.append("")
    lines.append(
        "| rank | sample | AR | taper | S | root | tip | e_CDi(no-AF) | e_CDi(with-AF) | P req (W) | CD total |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for rank, record in enumerate(report.get("ranked_by_e_cdi_post_airfoil", []), start=1):
        cand = record.get("candidate", {})
        no_af = record.get("no_airfoil_e_cdi")
        with_af = record.get("e_cdi_post_airfoil")
        power = record.get("power_required_w")
        cd_total = record.get("cd_total")
        lines.append(
            "| "
            f"{rank} | "
            f"{record['sample_index']} | "
            f"{cand.get('aspect_ratio', '-')} | "
            f"{cand.get('taper_ratio', '-')} | "
            f"{cand.get('wing_area_m2', '-')} | "
            f"{cand.get('root_chord_m', '-')} | "
            f"{cand.get('tip_chord_m', '-')} | "
            f"{no_af if no_af is not None else '-'} | "
            f"{with_af if with_af is not None else '-'} | "
            f"{power if power is not None else '-'} | "
            f"{cd_total if cd_total is not None else '-'} |"
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
        default=Path("output/birdman_mit_like_closed_loop"),
    )
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument(
        "--ar-min", type=float, default=DEFAULT_AR_RANGE[0]
    )
    parser.add_argument(
        "--ar-max", type=float, default=DEFAULT_AR_RANGE[1]
    )
    parser.add_argument(
        "--taper-min", type=float, default=DEFAULT_TAPER_RATIO_RANGE[0]
    )
    parser.add_argument(
        "--taper-max", type=float, default=DEFAULT_TAPER_RATIO_RANGE[1]
    )
    parser.add_argument(
        "--span-min-m", type=float, default=DEFAULT_SPAN_RANGE_M[0]
    )
    parser.add_argument(
        "--span-max-m", type=float, default=DEFAULT_SPAN_RANGE_M[1]
    )
    parser.add_argument("--mission-design-speed-mps", type=float, default=6.6)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--seed", type=int, default=20260504)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    report = run_search(
        cfg=cfg,
        config_path=args.config.expanduser().resolve(),
        output_dir=args.output_dir,
        sample_count=int(args.sample_count),
        ar_range=(float(args.ar_min), float(args.ar_max)),
        taper_range=(float(args.taper_min), float(args.taper_max)),
        span_range_m=(float(args.span_min_m), float(args.span_max_m)),
        mission_design_speed_mps=float(args.mission_design_speed_mps),
        avl_binary=args.avl_binary,
        workers=int(args.workers),
        seed=int(args.seed),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "mit_like_closed_loop_report.json"
    md_path = args.output_dir / "mit_like_closed_loop_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
