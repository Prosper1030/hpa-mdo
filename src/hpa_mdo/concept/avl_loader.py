from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Sequence

import numpy as np

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files
from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept.config import BirdmanConceptConfig
from hpa_mdo.concept.geometry import GeometryConcept, WingStation
from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.zone_requirements import build_zone_requirements, default_zone_definitions
from hpa_mdo.mission.objective import (
    FakeAnchorCurve,
    MissionEvaluationInputs,
    evaluate_mission_objective,
)

_FLOAT_TOKEN = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"
_ROOT_SEED_AIRFOIL = "fx76mp140"
_TIP_SEED_AIRFOIL = "clarkysm"


def _air_density_from_environment(cfg: BirdmanConceptConfig) -> float:
    temp_c = float(cfg.environment.temperature_c)
    temp_k = temp_c + 273.15
    altitude_m = float(cfg.environment.altitude_m)
    relative_humidity = max(0.0, min(1.0, float(cfg.environment.relative_humidity) / 100.0))

    pressure_pa = 101325.0 * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588
    saturation_vapor_pa = 610.94 * math.exp((17.625 * temp_c) / (temp_c + 243.04))
    vapor_pa = relative_humidity * saturation_vapor_pa
    dry_pa = max(0.0, pressure_pa - vapor_pa)
    return dry_pa / (287.058 * temp_k) + vapor_pa / (461.495 * temp_k)


def _speed_sweep_mps(cfg: BirdmanConceptConfig) -> tuple[float, ...]:
    point_count = int(cfg.mission.speed_sweep_points)
    if point_count < 2:
        raise ValueError("mission.speed_sweep_points must be at least 2.")
    min_speed = float(cfg.mission.speed_sweep_min_mps)
    max_speed = float(cfg.mission.speed_sweep_max_mps)
    step = (max_speed - min_speed) / float(point_count - 1)
    return tuple(min_speed + step * index for index in range(point_count))


def _oswald_efficiency_proxy(concept: GeometryConcept) -> float:
    dihedral_delta = max(0.0, float(concept.dihedral_tip_deg) - float(concept.dihedral_root_deg))
    twist_delta = abs(float(concept.twist_tip_deg) - float(concept.twist_root_deg))
    efficiency = 0.88 - 0.012 * dihedral_delta - 0.008 * twist_delta
    return max(0.68, min(0.92, efficiency))


def _shaft_power_required_w(
    *,
    drag_n: float,
    speed_mps: float,
    prop_model: SimplifiedPropModel,
) -> float:
    shaft_power_w = drag_n * speed_mps / max(prop_model.design_efficiency, 1.0e-6)
    for _ in range(3):
        eta_prop = prop_model.efficiency(
            speed_mps=speed_mps,
            shaft_power_w=max(shaft_power_w, 1.0),
        )
        shaft_power_w = drag_n * speed_mps / max(eta_prop, 1.0e-6)
    return shaft_power_w


def select_avl_reference_condition(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    profile_cd_proxy: float = 0.020,
) -> dict[str, Any]:
    speed_sweep_mps = _speed_sweep_mps(cfg)
    aspect_ratio = float(concept.span_m**2 / max(concept.wing_area_m2, 1.0e-9))
    oswald_efficiency = _oswald_efficiency_proxy(concept)
    tail_area_ratio = float(concept.tail_area_m2 / max(concept.wing_area_m2, 1.0e-9))
    misc_cd = float(0.0035 + 0.20 * tail_area_ratio * profile_cd_proxy)
    prop_model = SimplifiedPropModel(
        diameter_m=float(cfg.prop.diameter_m),
        rpm_min=float(cfg.prop.rpm_min),
        rpm_max=float(cfg.prop.rpm_max),
        design_efficiency=0.83,
    )
    rider_curve = FakeAnchorCurve(
        anchor_power_w=float(cfg.mission.anchor_power_w),
        anchor_duration_min=float(cfg.mission.anchor_duration_min),
    )

    mass_cases: list[dict[str, Any]] = []
    for gross_mass_kg in cfg.mass.gross_mass_sweep_kg:
        weight_n = float(gross_mass_kg) * 9.80665
        power_required_w: list[float] = []
        for speed_mps in speed_sweep_mps:
            dynamic_pressure_pa = 0.5 * air_density_kg_per_m3 * speed_mps**2
            cl_required = weight_n / max(dynamic_pressure_pa * concept.wing_area_m2, 1.0e-9)
            induced_cd = cl_required**2 / max(math.pi * aspect_ratio * oswald_efficiency, 1.0e-9)
            total_cd = float(profile_cd_proxy) + induced_cd + misc_cd
            drag_n = dynamic_pressure_pa * concept.wing_area_m2 * total_cd
            power_required_w.append(
                _shaft_power_required_w(
                    drag_n=drag_n,
                    speed_mps=speed_mps,
                    prop_model=prop_model,
                )
            )

        mission_result = evaluate_mission_objective(
            MissionEvaluationInputs(
                objective_mode=str(cfg.mission.objective_mode),
                target_range_km=float(cfg.mission.target_distance_km),
                speed_mps=speed_sweep_mps,
                power_required_w=tuple(power_required_w),
                rider_curve=rider_curve,
            )
        )
        mass_cases.append(
            {
                "gross_mass_kg": float(gross_mass_kg),
                "best_range_m": float(mission_result.best_range_m),
                "best_range_speed_mps": float(mission_result.best_range_speed_mps),
                "min_power_w": float(mission_result.min_power_w),
                "min_power_speed_mps": float(mission_result.min_power_speed_mps),
                "mission_feasible": bool(mission_result.mission_feasible),
                "target_range_passed": bool(mission_result.target_range_passed),
                "mission_score": float(mission_result.mission_score),
            }
        )

    objective_mode = str(cfg.mission.objective_mode)
    if objective_mode == "max_range":
        selected_mass_case = min(mass_cases, key=lambda case: float(case["best_range_m"]))
        mass_selection_reason = "min_best_range"
        reference_speed_reason = "best_range_speed_mps"
        reference_speed_mps = float(selected_mass_case["best_range_speed_mps"])
    elif objective_mode == "min_power":
        selected_mass_case = max(mass_cases, key=lambda case: float(case["min_power_w"]))
        mass_selection_reason = "max_min_power"
        reference_speed_reason = "min_power_speed_mps"
        reference_speed_mps = float(selected_mass_case["min_power_speed_mps"])
    else:
        raise ValueError(f"Unsupported mission objective mode: {objective_mode}")

    return {
        "objective_mode": objective_mode,
        "reference_speed_mps": float(reference_speed_mps),
        "reference_gross_mass_kg": float(selected_mass_case["gross_mass_kg"]),
        "reference_speed_reason": reference_speed_reason,
        "mass_selection_reason": mass_selection_reason,
        "reference_condition_policy": "mission_objective_and_limiting_mass_proxy_v1",
        "selected_mass_case": selected_mass_case,
        "mass_cases": mass_cases,
    }


def _concept_case_slug(concept: GeometryConcept) -> str:
    payload = {
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "root_chord_m": concept.root_chord_m,
        "tip_chord_m": concept.tip_chord_m,
        "twist_root_deg": concept.twist_root_deg,
        "twist_tip_deg": concept.twist_tip_deg,
        "dihedral_root_deg": concept.dihedral_root_deg,
        "dihedral_tip_deg": concept.dihedral_tip_deg,
        "dihedral_exponent": concept.dihedral_exponent,
        "tail_area_m2": concept.tail_area_m2,
        "cg_xc": concept.cg_xc,
        "segment_lengths_m": list(concept.segment_lengths_m),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"concept_{digest}"


def _station_z_positions(stations: tuple[WingStation, ...]) -> tuple[float, ...]:
    if not stations:
        return ()
    z_positions = [0.0]
    for left, right in zip(stations[:-1], stations[1:]):
        dy_m = float(right.y_m) - float(left.y_m)
        mean_dihedral_rad = math.radians(0.5 * (float(left.dihedral_deg) + float(right.dihedral_deg)))
        z_positions.append(z_positions[-1] + dy_m * math.tan(mean_dihedral_rad))
    return tuple(z_positions)


def _station_airfoil_name(station: WingStation, half_span_m: float) -> str:
    eta = 0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
    return _ROOT_SEED_AIRFOIL if eta <= 0.55 else _TIP_SEED_AIRFOIL


def write_concept_wing_only_avl(
    *,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    output_path: Path,
) -> Path:
    if not stations:
        raise ValueError("stations must not be empty.")

    z_positions = _station_z_positions(stations)
    half_span_m = 0.5 * float(concept.span_m)
    c_ref_m = 0.5 * (float(concept.root_chord_m) + float(concept.tip_chord_m))
    # AVL needs appreciably more spanwise vortices than section breaks once
    # multiple section airfoils are present, otherwise it aborts before trim
    # with "Insufficient number of spanwise vortices to work with."
    span_panels = max(24, 4 * max(len(stations) - 1, 1))

    lines = [
        "Birdman concept wing-only AVL",
        "#Mach",
        "0.000000",
        "#IYsym  iZsym  Zsym",
        "1  0  0.000000",
        "#Sref  Cref  Bref",
        f"{float(concept.wing_area_m2):.9f}  {c_ref_m:.9f}  {float(concept.span_m):.9f}",
        "#Xref  Yref  Zref",
        f"{0.25 * c_ref_m:.9f}  0.000000000  0.000000000",
        "#CDp",
        "0.000000",
        "#",
        "SURFACE",
        "Wing",
        f"16  1.0  {span_panels}  1.0",
        "#",
    ]
    for station, z_le_m in zip(stations, z_positions):
        lines.extend(
            [
                "SECTION",
                (
                    f"0.000000000  {float(station.y_m):.9f}  {float(z_le_m):.9f}  "
                    f"{float(station.chord_m):.9f}  {float(station.twist_deg):.9f}"
                ),
                "AFILE",
                _station_airfoil_name(station, half_span_m),
                "#",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _parse_avl_scalar(text: str, label: str) -> float | None:
    pattern = re.compile(
        rf"\b{re.escape(label)}\s*=\s*(?P<value>{_FLOAT_TOKEN}|\*{{3,}})",
    )
    match = pattern.search(text)
    if match is None:
        return None
    value_text = match.group("value")
    if "*" in value_text:
        return None
    return float(value_text)


def _parse_avl_force_totals(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    alpha_deg = _parse_avl_scalar(text, "Alpha")
    cl_trim = _parse_avl_scalar(text, "CLtot")
    if alpha_deg is None and cl_trim is None:
        return None
    payload: dict[str, float] = {}
    if alpha_deg is not None:
        payload["aoa_trim_deg"] = float(alpha_deg)
    if cl_trim is not None:
        payload["cl_trim"] = float(cl_trim)
    return payload


def _resolve_avl_binary(avl_binary: str | Path | None) -> Path:
    if avl_binary is not None:
        as_path = Path(avl_binary).expanduser()
        if as_path.is_absolute() and as_path.exists():
            return as_path.resolve()
        which_hit = shutil.which(str(as_path))
        if which_hit:
            return Path(which_hit)
    which_hit = shutil.which("avl")
    if which_hit is None:
        raise FileNotFoundError("AVL binary not found on PATH.")
    return Path(which_hit)


def _stage_avl_case(avl_path: Path, case_dir: Path) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    staged_avl = case_dir / avl_path.name
    if staged_avl.resolve() != avl_path.resolve():
        staged_avl.write_bytes(avl_path.read_bytes())
    stage_avl_airfoil_files(staged_avl)
    return staged_avl


def _run_avl_trim_case(
    *,
    avl_path: Path,
    case_dir: Path,
    cl_required: float,
    velocity_mps: float,
    density_kgpm3: float,
    avl_binary: str | Path | None = None,
) -> dict[str, float]:
    avl_bin = _resolve_avl_binary(avl_binary)
    staged_avl = _stage_avl_case(avl_path, case_dir)
    trim_file = case_dir / "concept_trim.ft"
    stdout_log = case_dir / "concept_trim_stdout.log"
    if trim_file.exists():
        trim_file.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {staged_avl.name}",
            "oper",
            "m",
            f"v {float(velocity_mps):.9f}",
            f"d {float(density_kgpm3):.9f}",
            "",
            "c1",
            f"c {float(cl_required):.9f}",
            "",
            "x",
            "ft",
            trim_file.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"AVL trim run failed with return code {proc.returncode}.")
    if "Cannot trim." in stdout_text:
        raise RuntimeError("AVL trim did not converge for the requested CL.")

    parsed = _parse_avl_force_totals(trim_file)
    if parsed is None or "aoa_trim_deg" not in parsed or "cl_trim" not in parsed:
        raise RuntimeError("AVL trim output missing Alpha/CLtot.")
    return parsed


def _run_avl_spanwise_case(
    *,
    avl_path: Path,
    case_dir: Path,
    alpha_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
    avl_binary: str | Path | None = None,
) -> Path:
    avl_bin = _resolve_avl_binary(avl_binary)
    staged_avl = _stage_avl_case(avl_path, case_dir)
    fs_path = case_dir / "concept_spanwise.fs"
    stdout_log = case_dir / "concept_spanwise_stdout.log"
    if fs_path.exists():
        fs_path.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {staged_avl.name}",
            "oper",
            "m",
            f"v {float(velocity_mps):.9f}",
            f"d {float(density_kgpm3):.9f}",
            "",
            "a",
            "a",
            f"{float(alpha_deg):.9f}",
            "x",
            "fs",
            fs_path.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"AVL spanwise run failed with return code {proc.returncode}.")
    if not fs_path.exists():
        raise RuntimeError("AVL spanwise run did not emit an .fs file.")
    return fs_path


def resample_spanwise_load_to_stations(
    *,
    spanwise_load: SpanwiseLoad,
    stations: tuple[WingStation, ...],
) -> SpanwiseLoad:
    if not stations:
        raise ValueError("stations must not be empty.")
    station_y = np.asarray([float(station.y_m) for station in stations], dtype=float)
    if station_y[0] < float(np.min(spanwise_load.y)) - 1.0e-6:
        raise ValueError("station root lies outside spanwise load coverage.")
    if station_y[-1] > float(np.max(spanwise_load.y)) + 1.0e-6:
        raise ValueError("station tip lies outside spanwise load coverage.")

    def interp(values: np.ndarray) -> np.ndarray:
        return np.interp(station_y, np.asarray(spanwise_load.y, dtype=float), values)

    return SpanwiseLoad(
        y=station_y,
        chord=interp(np.asarray(spanwise_load.chord, dtype=float)),
        cl=interp(np.asarray(spanwise_load.cl, dtype=float)),
        cd=interp(np.asarray(spanwise_load.cd, dtype=float)),
        cm=interp(np.asarray(spanwise_load.cm, dtype=float)),
        lift_per_span=interp(np.asarray(spanwise_load.lift_per_span, dtype=float)),
        drag_per_span=interp(np.asarray(spanwise_load.drag_per_span, dtype=float)),
        aoa_deg=float(spanwise_load.aoa_deg),
        velocity=float(spanwise_load.velocity),
        dynamic_pressure=float(spanwise_load.dynamic_pressure),
    )


def _station_span_fractions(stations: tuple[WingStation, ...]) -> tuple[float, ...]:
    if not stations:
        raise ValueError("stations must not be empty.")
    start_y_m = float(stations[0].y_m)
    end_y_m = float(stations[-1].y_m)
    half_span_m = end_y_m - start_y_m
    if half_span_m <= 0.0:
        raise ValueError("stations must span a positive half-span.")
    return tuple((float(station.y_m) - start_y_m) / half_span_m for station in stations)


def _zone_station_positions(
    *,
    stations: tuple[WingStation, ...],
    zone_names: Sequence[str],
) -> dict[str, list[float]]:
    zone_definitions = default_zone_definitions()
    span_fractions = _station_span_fractions(stations)
    zone_positions = {zone.name: [] for zone in zone_definitions}

    for station, span_frac in zip(stations, span_fractions):
        for zone_index, zone in enumerate(zone_definitions):
            is_last_zone = zone_index == len(zone_definitions) - 1
            in_zone = zone.y0_frac <= span_frac < zone.y1_frac
            if is_last_zone and span_frac <= zone.y1_frac:
                in_zone = zone.y0_frac <= span_frac <= zone.y1_frac
            if in_zone:
                zone_positions[zone.name].append(float(station.y_m))
                break

    missing = set(zone_names) - set(zone_positions)
    if missing:
        raise ValueError(f"Unknown zone names in payload conversion: {sorted(missing)}")
    return zone_positions


def avl_zone_payload_from_spanwise_load(
    *,
    spanwise_load: SpanwiseLoad,
    stations: tuple[WingStation, ...],
) -> dict[str, dict[str, Any]]:
    zone_requirements = build_zone_requirements(
        spanwise_load=spanwise_load,
        stations=stations,
        zone_definitions=default_zone_definitions(),
    )
    zone_positions = _zone_station_positions(
        stations=stations,
        zone_names=tuple(zone_requirements.keys()),
    )

    payload: dict[str, dict[str, Any]] = {}
    for zone_name, zone_requirement in zone_requirements.items():
        station_positions = zone_positions[zone_name]
        if len(station_positions) != len(zone_requirement.points):
            raise ValueError(
                f"Zone '{zone_name}' has {len(zone_requirement.points)} operating points but "
                f"{len(station_positions)} station positions."
            )
        payload[zone_name] = {
            "source": "avl_strip_forces",
            "min_tc_ratio": float(zone_requirement.min_tc_ratio),
            "points": [
                {
                    "reynolds": float(point.reynolds),
                    "chord_m": float(point.chord_m),
                    "cl_target": float(point.cl_target),
                    "cm_target": float(point.cm_target),
                    "weight": float(point.weight),
                    "station_y_m": float(station_y_m),
                }
                for point, station_y_m in zip(
                    zone_requirement.points,
                    station_positions,
                    strict=True,
                )
            ],
        }
    return payload


def load_zone_requirements_from_avl(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    working_root: Path,
    avl_binary: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    if not stations:
        raise ValueError("stations must not be empty.")

    working_root = Path(working_root)
    case_dir = working_root / _concept_case_slug(concept)
    avl_path = case_dir / "concept_wing.avl"
    write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=avl_path,
    )

    air_density_kgpm3 = _air_density_from_environment(cfg)
    reference_condition = select_avl_reference_condition(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kgpm3,
    )
    reference_speed_mps = float(reference_condition["reference_speed_mps"])
    reference_gross_mass_kg = float(reference_condition["reference_gross_mass_kg"])
    dynamic_pressure_pa = 0.5 * air_density_kgpm3 * reference_speed_mps**2
    cl_required = (reference_gross_mass_kg * 9.80665) / max(
        dynamic_pressure_pa * float(concept.wing_area_m2),
        1.0e-9,
    )

    trim_totals = _run_avl_trim_case(
        avl_path=avl_path,
        case_dir=case_dir,
        cl_required=cl_required,
        velocity_mps=reference_speed_mps,
        density_kgpm3=air_density_kgpm3,
        avl_binary=avl_binary,
    )
    fs_path = _run_avl_spanwise_case(
        avl_path=avl_path,
        case_dir=case_dir,
        alpha_deg=float(trim_totals["aoa_trim_deg"]),
        velocity_mps=reference_speed_mps,
        density_kgpm3=air_density_kgpm3,
        avl_binary=avl_binary,
    )

    avl_spanwise_load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=float(trim_totals["aoa_trim_deg"]),
        velocity_mps=reference_speed_mps,
        density_kgpm3=air_density_kgpm3,
        target_surface_names=("Wing",),
        positive_y_only=True,
    )
    station_load = resample_spanwise_load_to_stations(
        spanwise_load=avl_spanwise_load,
        stations=stations,
    )
    payload = avl_zone_payload_from_spanwise_load(
        spanwise_load=station_load,
        stations=stations,
    )
    for zone_payload in payload.values():
        zone_payload["reference_speed_mps"] = float(reference_speed_mps)
        zone_payload["reference_gross_mass_kg"] = float(reference_gross_mass_kg)
        zone_payload["reference_speed_reason"] = str(reference_condition["reference_speed_reason"])
        zone_payload["mass_selection_reason"] = str(reference_condition["mass_selection_reason"])
        zone_payload["reference_cl_required"] = float(cl_required)
        zone_payload["trim_aoa_deg"] = float(trim_totals["aoa_trim_deg"])
        zone_payload["trim_cl"] = float(trim_totals["cl_trim"])
        zone_payload["reference_condition_policy"] = str(
            reference_condition["reference_condition_policy"]
        )
    return payload


def _annotate_fallback_payload(
    zone_payload: dict[str, dict[str, Any]],
    *,
    fallback_reason: str,
) -> dict[str, dict[str, Any]]:
    annotated: dict[str, dict[str, Any]] = {}
    for zone_name, zone_data in zone_payload.items():
        annotated[zone_name] = {
            **zone_data,
            "source": "fallback_coarse_loader",
            "fallback_reason": str(zone_data.get("fallback_reason", fallback_reason)),
            "reference_condition_policy": str(
                zone_data.get("reference_condition_policy", "fallback_coarse_loader")
            ),
        }
    return annotated


def build_avl_backed_spanwise_loader(
    *,
    cfg: BirdmanConceptConfig,
    working_root: Path,
    fallback_loader: Callable[[GeometryConcept, tuple[WingStation, ...]], dict[str, dict[str, Any]]],
    avl_binary: str | Path | None = None,
) -> Callable[[GeometryConcept, tuple[WingStation, ...]], dict[str, dict[str, Any]]]:
    def _loader(
        concept: GeometryConcept,
        stations: tuple[WingStation, ...],
    ) -> dict[str, dict[str, Any]]:
        try:
            return load_zone_requirements_from_avl(
                cfg=cfg,
                concept=concept,
                stations=stations,
                working_root=working_root,
                avl_binary=avl_binary,
            )
        except Exception as exc:  # pragma: no cover - exercised via fallback behavior
            print(
                (
                    "[birdman-concept] AVL-backed spanwise loader failed; "
                    f"falling back to coarse loader: {exc}"
                ),
                file=sys.stderr,
            )
            return _annotate_fallback_payload(
                fallback_loader(concept, stations),
                fallback_reason=str(exc),
            )

    return _loader
