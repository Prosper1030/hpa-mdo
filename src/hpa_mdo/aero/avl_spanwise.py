"""Parse AVL strip-force output into SpanwiseLoad and candidate-owned artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from hpa_mdo.aero.aswing_exporter import parse_avl
from hpa_mdo.aero.base import SpanwiseLoad


_SURFACE_RE = re.compile(r"^\s*Surface\s+#\s*(?P<index>\d+)\s+(?P<name>.+?)\s*$")
_REF_RE = re.compile(
    r"\b(?P<label>Sref|Cref|Bref)\s*=\s*(?P<value>[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?)"
)
_BOUNDARY_PADDING_NOTE = "nearest_strip_coefficients_with_avl_root_tip_chord"


def _normalize_surface_name(name: str) -> str:
    base = str(name).split("(", 1)[0]
    normalized = "".join(base.split()).casefold()
    aliases = {
        "mainwing": "wing",
    }
    return aliases.get(normalized, normalized)


def _strip_payload(
    *,
    strip_index: int,
    x_le_m: float,
    y_le_m: float,
    z_le_m: float,
    chord_m: float,
    area_m2: float,
    cl: float,
    cd: float,
    cm_c4: float,
) -> dict[str, float]:
    return {
        "strip_index": int(strip_index),
        "x_le_m": float(x_le_m),
        "y_le_m": float(y_le_m),
        "z_le_m": float(z_le_m),
        "chord_m": float(chord_m),
        "area_m2": float(area_m2),
        "cl": float(cl),
        "cd": float(cd),
        "cm_c4": float(cm_c4),
    }


def parse_avl_strip_forces(
    fs_path: str | Path,
    *,
    target_surface_names: Sequence[str] = ("Wing",),
    positive_y_only: bool = True,
) -> dict[str, Any]:
    """Parse an AVL ``.fs`` strip-force file into machine-readable rows."""

    path = Path(fs_path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    targets = {_normalize_surface_name(name) for name in target_surface_names}

    refs: dict[str, float] = {}
    surfaces: list[dict[str, Any]] = []
    current_surface: dict[str, Any] | None = None
    in_strip_table = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue

        for match in _REF_RE.finditer(line):
            refs[match.group("label").lower()] = float(match.group("value"))

        surface_match = _SURFACE_RE.match(line)
        if surface_match is not None:
            current_surface = {
                "surface_index": int(surface_match.group("index")),
                "surface_name": surface_match.group("name").strip(),
                "strips": [],
            }
            surfaces.append(current_surface)
            in_strip_table = False
            continue

        if current_surface is None:
            continue

        if "Strip Forces referred to Strip Area, Chord" in line:
            in_strip_table = True
            continue

        if not in_strip_table:
            continue

        tokens = line.split()
        if len(tokens) < 15:
            continue
        try:
            strip_index = int(tokens[0])
            row_values = [float(token) for token in tokens[1:15]]
        except ValueError:
            continue

        strip = _strip_payload(
            strip_index=strip_index,
            x_le_m=row_values[0],
            y_le_m=row_values[1],
            z_le_m=row_values[2],
            chord_m=row_values[3],
            area_m2=row_values[4],
            cl=row_values[8],
            cd=row_values[9],
            cm_c4=row_values[11],
        )
        current_surface["strips"].append(strip)

    matched_surfaces = [
        surface
        for surface in surfaces
        if _normalize_surface_name(surface["surface_name"]) in targets
    ]
    if not matched_surfaces:
        available = ", ".join(surface["surface_name"] for surface in surfaces) or "none"
        raise ValueError(
            f"No AVL strip-force surfaces matched {sorted(targets)} in {path}. Available: {available}"
        )

    selected_strips: list[dict[str, float]] = []
    for surface in matched_surfaces:
        for strip in surface["strips"]:
            if positive_y_only and float(strip["y_le_m"]) < -1.0e-9:
                continue
            selected_strips.append(dict(strip))

    if not selected_strips:
        raise ValueError(f"No matching strip rows found in AVL strip-force file: {path}")

    selected_strips.sort(key=lambda strip: (float(strip["y_le_m"]), int(strip["strip_index"])))
    return {
        "fs_path": str(path.resolve()),
        "reference_values": {
            "sref_m2": refs.get("sref"),
            "cref_m": refs.get("cref"),
            "bref_m": refs.get("bref"),
        },
        "surface_names": [surface["surface_name"] for surface in matched_surfaces],
        "strips": selected_strips,
    }


def _resolve_surface_geometry(
    avl_path: str | Path,
    *,
    target_surface_names: Sequence[str],
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
    chord = np.asarray([float(section.chord) for section in sections], dtype=float)
    return y, chord


def _pad_spanwise_boundaries(
    *,
    y: np.ndarray,
    chord: np.ndarray,
    cl: np.ndarray,
    cd: np.ndarray,
    cm: np.ndarray,
    geom_y: np.ndarray,
    geom_chord: np.ndarray,
    tol_m: float = 1.0e-6,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    padded_y = np.asarray(y, dtype=float).copy()
    padded_chord = np.asarray(chord, dtype=float).copy()
    padded_cl = np.asarray(cl, dtype=float).copy()
    padded_cd = np.asarray(cd, dtype=float).copy()
    padded_cm = np.asarray(cm, dtype=float).copy()

    root_y = float(geom_y[0])
    tip_y = float(geom_y[-1])
    root_chord = float(np.interp(root_y, geom_y, geom_chord))
    tip_chord = float(np.interp(tip_y, geom_y, geom_chord))

    if padded_y[0] > root_y + tol_m:
        padded_y = np.concatenate(([root_y], padded_y))
        padded_chord = np.concatenate(([root_chord], padded_chord))
        padded_cl = np.concatenate(([float(padded_cl[0])], padded_cl))
        padded_cd = np.concatenate(([float(padded_cd[0])], padded_cd))
        padded_cm = np.concatenate(([float(padded_cm[0])], padded_cm))
    elif abs(float(padded_y[0]) - root_y) <= tol_m:
        padded_y[0] = root_y
        padded_chord[0] = root_chord

    if padded_y[-1] < tip_y - tol_m:
        padded_y = np.concatenate((padded_y, [tip_y]))
        padded_chord = np.concatenate((padded_chord, [tip_chord]))
        padded_cl = np.concatenate((padded_cl, [float(padded_cl[-1])]))
        padded_cd = np.concatenate((padded_cd, [float(padded_cd[-1])]))
        padded_cm = np.concatenate((padded_cm, [float(padded_cm[-1])]))
    elif abs(float(padded_y[-1]) - tip_y) <= tol_m:
        padded_y[-1] = tip_y
        padded_chord[-1] = tip_chord

    return padded_y, padded_chord, padded_cl, padded_cd, padded_cm


def build_spanwise_load_from_avl_strip_forces(
    *,
    fs_path: str | Path,
    avl_path: str | Path,
    aoa_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
    target_surface_names: Sequence[str] = ("Wing",),
    positive_y_only: bool = True,
) -> SpanwiseLoad:
    """Convert an AVL ``.fs`` strip-force file into a ``SpanwiseLoad``."""

    parsed = parse_avl_strip_forces(
        fs_path,
        target_surface_names=target_surface_names,
        positive_y_only=positive_y_only,
    )
    geom_y, geom_chord = _resolve_surface_geometry(
        avl_path,
        target_surface_names=target_surface_names,
    )
    strips = parsed["strips"]
    y = np.asarray([float(strip["y_le_m"]) for strip in strips], dtype=float)
    chord = np.asarray([float(strip["chord_m"]) for strip in strips], dtype=float)
    cl = np.asarray([float(strip["cl"]) for strip in strips], dtype=float)
    cd = np.asarray([float(strip["cd"]) for strip in strips], dtype=float)
    cm = np.asarray([float(strip["cm_c4"]) for strip in strips], dtype=float)

    order = np.argsort(y)
    y = y[order]
    chord = chord[order]
    cl = cl[order]
    cd = cd[order]
    cm = cm[order]

    y, chord, cl, cd, cm = _pad_spanwise_boundaries(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        geom_y=geom_y,
        geom_chord=geom_chord,
    )

    dynamic_pressure = 0.5 * float(density_kgpm3) * float(velocity_mps) ** 2
    lift_per_span = dynamic_pressure * chord * cl
    drag_per_span = dynamic_pressure * chord * cd
    return SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=lift_per_span,
        drag_per_span=drag_per_span,
        aoa_deg=float(aoa_deg),
        velocity=float(velocity_mps),
        dynamic_pressure=float(dynamic_pressure),
    )


def _spanwise_load_to_payload(
    load: SpanwiseLoad,
    *,
    fs_path: str | None,
    stdout_log_path: str | None,
) -> dict[str, Any]:
    return {
        "aoa_deg": float(load.aoa_deg),
        "fs_path": None if fs_path is None else str(Path(fs_path).expanduser().resolve()),
        "stdout_log_path": (
            None if stdout_log_path is None else str(Path(stdout_log_path).expanduser().resolve())
        ),
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


def build_candidate_avl_spanwise_artifact(
    *,
    avl_path: str | Path,
    candidate_output_dir: str | Path | None,
    requested_knobs: dict[str, float],
    selected_cruise_aoa_deg: float,
    selected_cruise_aoa_source: str = "outer_loop_avl_trim",
    selected_load_state_owner: str = "outer_loop_avl_trim_and_gates",
    velocity_mps: float,
    density_kgpm3: float,
    load_case_specs: Iterable[dict[str, Any]],
    trim_force_path: str | Path | None = None,
    trim_stdout_log_path: str | Path | None = None,
    target_surface_names: Sequence[str] = ("Wing",),
    source_mode: str = "candidate_avl_spanwise",
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a JSON-ready candidate-owned AVL spanwise-load artifact."""

    load_cases_payload: list[dict[str, Any]] = []
    aoa_values: list[float] = []
    for spec in load_case_specs:
        load = build_spanwise_load_from_avl_strip_forces(
            fs_path=spec["fs_path"],
            avl_path=avl_path,
            aoa_deg=float(spec["aoa_deg"]),
            velocity_mps=float(velocity_mps),
            density_kgpm3=float(density_kgpm3),
            target_surface_names=target_surface_names,
        )
        load_cases_payload.append(
            _spanwise_load_to_payload(
                load,
                fs_path=spec.get("fs_path"),
                stdout_log_path=spec.get("stdout_log_path"),
            )
        )
        aoa_values.append(float(load.aoa_deg))

    if not load_cases_payload:
        raise ValueError("Need at least one AVL spanwise load case to build an artifact.")

    ordered_cases = sorted(load_cases_payload, key=lambda payload: float(payload["aoa_deg"]))
    dynamic_pressure = 0.5 * float(density_kgpm3) * float(velocity_mps) ** 2
    return {
        "source_mode": str(source_mode),
        "requested_knobs": {key: float(value) for key, value in requested_knobs.items()},
        "selected_cruise_aoa_deg": float(selected_cruise_aoa_deg),
        "selected_cruise_aoa_source": str(selected_cruise_aoa_source),
        "selected_load_state_owner": str(selected_load_state_owner),
        "aoa_sweep_deg": [float(value) for value in sorted({float(value) for value in aoa_values})],
        "velocity_mps": float(velocity_mps),
        "density_kgpm3": float(density_kgpm3),
        "dynamic_pressure_pa": float(dynamic_pressure),
        "target_surface_names": [str(name) for name in target_surface_names],
        "boundary_padding": _BOUNDARY_PADDING_NOTE,
        "geometry_artifacts": {
            "candidate_output_dir": (
                None
                if candidate_output_dir is None
                else str(Path(candidate_output_dir).expanduser().resolve())
            ),
            "avl_path": str(Path(avl_path).expanduser().resolve()),
            "trim_force_path": (
                None if trim_force_path is None else str(Path(trim_force_path).expanduser().resolve())
            ),
            "trim_stdout_log_path": (
                None
                if trim_stdout_log_path is None
                else str(Path(trim_stdout_log_path).expanduser().resolve())
            ),
        },
        "cases": ordered_cases,
        "notes": [str(note) for note in notes],
    }


def write_candidate_avl_spanwise_artifact(
    path: str | Path,
    **kwargs,
) -> Path:
    artifact = build_candidate_avl_spanwise_artifact(**kwargs)
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact_path


def load_candidate_avl_spanwise_artifact(
    path: str | Path,
) -> tuple[dict[str, Any], list[SpanwiseLoad]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list) or not cases_payload:
        raise ValueError(f"Candidate AVL spanwise artifact has no load cases: {path}")
    cases = [_spanwise_load_from_payload(case_payload) for case_payload in cases_payload]
    return payload, cases


__all__ = [
    "build_candidate_avl_spanwise_artifact",
    "build_spanwise_load_from_avl_strip_forces",
    "load_candidate_avl_spanwise_artifact",
    "parse_avl_strip_forces",
    "write_candidate_avl_spanwise_artifact",
]
