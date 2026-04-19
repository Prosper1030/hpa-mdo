"""Fixed-design-alpha dihedral load corrector artifacts for coarse screening."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from hpa_mdo.aero.aswing_exporter import parse_avl
from hpa_mdo.aero.base import SpanwiseLoad


def _normalize_surface_name(name: str) -> str:
    base = str(name).split("(", 1)[0]
    normalized = "".join(base.split()).casefold()
    aliases = {
        "mainwing": "wing",
    }
    return aliases.get(normalized, normalized)


def _spanwise_load_to_payload(load: SpanwiseLoad) -> dict[str, Any]:
    return {
        "aoa_deg": float(load.aoa_deg),
        "y": np.asarray(load.y, dtype=float).tolist(),
        "chord": np.asarray(load.chord, dtype=float).tolist(),
        "cl": np.asarray(load.cl, dtype=float).tolist(),
        "cd": np.asarray(load.cd, dtype=float).tolist(),
        "cm": np.asarray(load.cm, dtype=float).tolist(),
        "lift_per_span": np.asarray(load.lift_per_span, dtype=float).tolist(),
        "drag_per_span": np.asarray(load.drag_per_span, dtype=float).tolist(),
        "velocity_mps": float(load.velocity),
        "dynamic_pressure_pa": float(load.dynamic_pressure),
    }


def _spanwise_load_from_payload(payload: dict[str, Any]) -> SpanwiseLoad:
    return SpanwiseLoad(
        y=np.asarray(payload["y"], dtype=float),
        chord=np.asarray(payload["chord"], dtype=float),
        cl=np.asarray(payload["cl"], dtype=float),
        cd=np.asarray(payload["cd"], dtype=float),
        cm=np.asarray(payload["cm"], dtype=float),
        lift_per_span=np.asarray(payload["lift_per_span"], dtype=float),
        drag_per_span=np.asarray(payload["drag_per_span"], dtype=float),
        aoa_deg=float(payload["aoa_deg"]),
        velocity=float(payload["velocity_mps"]),
        dynamic_pressure=float(payload["dynamic_pressure_pa"]),
    )


def _resolve_surface_geometry(
    avl_path: str | Path,
    *,
    target_surface_names: Sequence[str] = ("Wing",),
) -> tuple[np.ndarray, np.ndarray]:
    model = parse_avl(avl_path)
    targets = {_normalize_surface_name(name) for name in target_surface_names}
    matched = [
        surface for surface in model.surfaces if _normalize_surface_name(surface.name) in targets
    ]
    if not matched:
        available = ", ".join(surface.name for surface in model.surfaces) or "none"
        raise ValueError(
            f"No AVL geometry surfaces matched {sorted(targets)} in {avl_path}. Available: {available}"
        )

    sections = sorted(matched[0].sections, key=lambda section: float(section.y))
    y = np.asarray([float(section.y) for section in sections], dtype=float)
    z = np.asarray([float(section.z) for section in sections], dtype=float)
    if y.size < 2:
        raise ValueError(f"Need at least 2 wing sections in AVL geometry: {avl_path}")
    return y, z


def _segment_dihedral_deg_from_avl(
    avl_path: str | Path,
    *,
    target_surface_names: Sequence[str] = ("Wing",),
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y_nodes, z_nodes = _resolve_surface_geometry(avl_path, target_surface_names=target_surface_names)
    dy = np.diff(y_nodes)
    if np.any(dy <= 0.0):
        raise ValueError(f"AVL wing section y stations must be strictly increasing: {avl_path}")
    gamma_deg = np.degrees(np.arctan2(np.diff(z_nodes), dy))
    return y_nodes, z_nodes, gamma_deg


def _segment_gamma_at_y(
    query_y: np.ndarray,
    *,
    section_y: np.ndarray,
    segment_gamma_deg: np.ndarray,
) -> np.ndarray:
    if section_y.size != segment_gamma_deg.size + 1:
        raise ValueError("section_y / segment_gamma_deg shape mismatch.")
    indices = np.searchsorted(section_y[1:], query_y, side="left")
    indices = np.clip(indices, 0, segment_gamma_deg.size - 1)
    return segment_gamma_deg[indices]


def build_fixed_alpha_dihedral_corrected_case(
    *,
    baseline_case: SpanwiseLoad,
    baseline_avl_path: str | Path,
    candidate_avl_path: str | Path,
    target_surface_names: Sequence[str] = ("Wing",),
) -> tuple[SpanwiseLoad, list[dict[str, float]]]:
    """Apply a fixed-alpha dihedral vertical-load correction to a baseline case.

    The current coarse-screening contract keeps the design alpha fixed and
    applies only a first-order vertical-lift correction:

    ``q_new(y) = q_origin(y) * [cos(gamma_new(y)) / cos(gamma_origin(y))]^2``

    Drag and pitching-moment ownership remain on the origin fixed-alpha panel
    baseline because this corrector is only used to get a jig-shape-ready load
    distribution without rebuilding candidate VSP geometry.
    """

    baseline_y_nodes, baseline_z_nodes, baseline_gamma_deg = _segment_dihedral_deg_from_avl(
        baseline_avl_path,
        target_surface_names=target_surface_names,
    )
    candidate_y_nodes, candidate_z_nodes, candidate_gamma_deg = _segment_dihedral_deg_from_avl(
        candidate_avl_path,
        target_surface_names=target_surface_names,
    )

    sample_y = np.asarray(baseline_case.y, dtype=float)
    gamma_origin_deg = _segment_gamma_at_y(
        sample_y,
        section_y=baseline_y_nodes,
        segment_gamma_deg=baseline_gamma_deg,
    )
    gamma_candidate_deg = _segment_gamma_at_y(
        sample_y,
        section_y=candidate_y_nodes,
        segment_gamma_deg=candidate_gamma_deg,
    )

    cos_origin = np.cos(np.radians(gamma_origin_deg))
    cos_candidate = np.cos(np.radians(gamma_candidate_deg))
    scale = np.divide(
        cos_candidate**2,
        np.maximum(cos_origin**2, 1.0e-12),
    )

    corrected_lift = np.asarray(baseline_case.lift_per_span, dtype=float) * scale
    corrected_cl = np.asarray(baseline_case.cl, dtype=float) * scale
    corrected_case = SpanwiseLoad(
        y=np.asarray(baseline_case.y, dtype=float).copy(),
        chord=np.asarray(baseline_case.chord, dtype=float).copy(),
        cl=np.asarray(corrected_cl, dtype=float),
        cd=np.asarray(baseline_case.cd, dtype=float).copy(),
        cm=np.asarray(baseline_case.cm, dtype=float).copy(),
        lift_per_span=np.asarray(corrected_lift, dtype=float),
        drag_per_span=np.asarray(baseline_case.drag_per_span, dtype=float).copy(),
        aoa_deg=float(baseline_case.aoa_deg),
        velocity=float(baseline_case.velocity),
        dynamic_pressure=float(baseline_case.dynamic_pressure),
    )
    correction_rows = [
        {
            "y_m": float(y_val),
            "baseline_gamma_deg": float(gamma_origin),
            "candidate_gamma_deg": float(gamma_candidate),
            "vertical_load_scale_factor": float(local_scale),
        }
        for y_val, gamma_origin, gamma_candidate, local_scale in zip(
            sample_y,
            gamma_origin_deg,
            gamma_candidate_deg,
            scale,
            strict=False,
        )
    ]
    return corrected_case, correction_rows


def build_fixed_alpha_dihedral_corrector_artifact(
    *,
    baseline_case: SpanwiseLoad,
    baseline_avl_path: str | Path,
    candidate_avl_path: str | Path,
    requested_knobs: dict[str, float],
    fixed_design_alpha_deg: float,
    origin_vsp3_path: str | Path | None,
    baseline_output_dir: str | Path | None,
    baseline_lod_path: str | Path | None,
    baseline_polar_path: str | Path | None,
    target_surface_names: Sequence[str] = ("Wing",),
    source_mode: str = "origin_vsp_fixed_alpha_corrector",
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    corrected_case, correction_rows = build_fixed_alpha_dihedral_corrected_case(
        baseline_case=baseline_case,
        baseline_avl_path=baseline_avl_path,
        candidate_avl_path=candidate_avl_path,
        target_surface_names=target_surface_names,
    )
    total_half_lift_n = float(corrected_case.total_lift)
    total_full_lift_n = 2.0 * total_half_lift_n
    return {
        "source_mode": str(source_mode),
        "requested_knobs": {str(key): float(value) for key, value in requested_knobs.items()},
        "fixed_design_alpha_deg": float(fixed_design_alpha_deg),
        "selected_cruise_aoa_deg": float(fixed_design_alpha_deg),
        "selected_cruise_aoa_source": "fixed_design_alpha",
        "selected_load_state_owner": "origin_vsp_panel_fixed_alpha_baseline_plus_dihedral_corrector",
        "velocity_mps": float(corrected_case.velocity),
        "dynamic_pressure_pa": float(corrected_case.dynamic_pressure),
        "density_kgpm3": 2.0 * float(corrected_case.dynamic_pressure) / float(corrected_case.velocity) ** 2,
        "target_surface_names": [str(name) for name in target_surface_names],
        "correction_formula": "vertical_load_scale = [cos(candidate_gamma) / cos(origin_gamma)]^2",
        "correction_policy": {
            "lift_per_span": "candidate_corrected",
            "cl": "candidate_corrected",
            "drag_per_span": "preserve_origin_fixed_alpha_baseline",
            "cd": "preserve_origin_fixed_alpha_baseline",
            "cm": "preserve_origin_fixed_alpha_baseline",
        },
        "total_half_lift_n": float(total_half_lift_n),
        "total_full_lift_n": float(total_full_lift_n),
        "geometry_artifacts": {
            "origin_vsp3_path": (
                None if origin_vsp3_path is None else str(Path(origin_vsp3_path).expanduser().resolve())
            ),
            "baseline_output_dir": (
                None
                if baseline_output_dir is None
                else str(Path(baseline_output_dir).expanduser().resolve())
            ),
            "baseline_lod_path": (
                None if baseline_lod_path is None else str(Path(baseline_lod_path).expanduser().resolve())
            ),
            "baseline_polar_path": (
                None if baseline_polar_path is None else str(Path(baseline_polar_path).expanduser().resolve())
            ),
            "baseline_avl_path": str(Path(baseline_avl_path).expanduser().resolve()),
            "candidate_avl_path": str(Path(candidate_avl_path).expanduser().resolve()),
        },
        "correction_rows": correction_rows,
        "cases": [_spanwise_load_to_payload(corrected_case)],
        "notes": [str(note) for note in notes],
        "baseline_reference": {
            "baseline_case_aoa_deg": float(baseline_case.aoa_deg),
            "baseline_half_lift_n": float(baseline_case.total_lift),
            "baseline_full_lift_n": float(2.0 * baseline_case.total_lift),
        },
    }


def write_fixed_alpha_dihedral_corrector_artifact(
    path: str | Path,
    **kwargs: Any,
) -> Path:
    artifact = build_fixed_alpha_dihedral_corrector_artifact(**kwargs)
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact_path


def load_fixed_alpha_dihedral_corrector_artifact(
    path: str | Path,
) -> tuple[dict[str, Any], list[SpanwiseLoad]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list) or not cases_payload:
        raise ValueError(f"Fixed-alpha dihedral-corrector artifact has no load cases: {path}")
    cases = [_spanwise_load_from_payload(case_payload) for case_payload in cases_payload]
    return payload, cases


__all__ = [
    "build_fixed_alpha_dihedral_corrected_case",
    "build_fixed_alpha_dihedral_corrector_artifact",
    "load_fixed_alpha_dihedral_corrector_artifact",
    "write_fixed_alpha_dihedral_corrector_artifact",
]
