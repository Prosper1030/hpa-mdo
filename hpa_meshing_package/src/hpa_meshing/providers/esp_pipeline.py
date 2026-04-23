from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..gmsh_runtime import GmshRuntimeError, load_gmsh
from ..schema import (
    GeometryHandle,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshJobConfig,
)
from ..reference_geometry import load_openvsp_reference_data
from ..geometry.validator import classify_geometry_family, validate_component_geometry
from ..mesh.recipes import build_recipe
from ..fallback.policy import run_with_fallback
from ..mesh.quality import quality_check
from .openvsp_surface_intersection import _probe_step_topology, _read_step_units_and_bounds

Runner = Callable[[List[str], Path], subprocess.CompletedProcess]

OCSM_SCRIPT_NAME = "rebuild.csm"
UNION_SCRIPT_NAME = "union_groups.csm"
RAW_EXPORT_FILE_NAME = "raw_dump.stp"
EXPORT_FILE_NAME = "normalized.stp"
UNION_EXPORT_FILE_NAME = "union_groups.step"
COMMAND_LOG_NAME = "ocsm.log"
UNION_COMMAND_LOG_NAME = "ocsm_union.log"
TOPOLOGY_REPORT_NAME = "topology.json"
TOPOLOGY_LINEAGE_REPORT_NAME = "topology_lineage_report.json"
TOPOLOGY_SUPPRESSION_REPORT_NAME = "topology_suppression_report.json"
RAW_TOPOLOGY_REPORT_NAME = "raw_topology.json"
NORMALIZATION_REPORT_NAME = "normalization.json"
_STEP_MILLI_UNIT_PATTERN = re.compile(r"SI_UNIT\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)")
_STEP_COORDS_LOOK_LIKE_METERS_MAX_REF_RATIO = 500.0
_IMPORT_SCALE_IDENTITY_TOL = 1.0e-6
_MAIN_WING_ALIASES = {"mainwing", "main", "wing"}
_HORIZONTAL_TAIL_ALIASES = {
    "elevator",
    "htail",
    "horizontaltail",
    "hstab",
    "tailplane",
    "tailwing",
}
_VERTICAL_TAIL_ALIASES = {
    "fin",
    "vtail",
    "verticaltail",
    "verticalfin",
    "vstab",
    "rudder",
}
_WING_SECTION_PARAM_NAMES = (
    "Root_Chord",
    "Tip_Chord",
    "Span",
    "Sweep",
    "Sweep_Location",
    "Dihedral",
    "Twist",
    "ThickChord",
    "Camber",
    "CamberLoc",
    "SectTess_U",
    "TE_Close_Thick",
    "TE_Close_Thick_Chord",
    "LE_Cap_Type",
    "TE_Cap_Type",
)
_AUTONOMOUS_TIP_TOPOLOGY_CONTROLLER_VERSION = "source_section5_tip_topology_repair_v0"
_AUTONOMOUS_CANDIDATE_3D_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True)
class _InterfaceFaceRecord:
    body_tag: int
    face_tag: int
    axis: str
    plane_coordinate: float
    area: float
    bbox: tuple[float, float, float, float, float, float]
    projected_bounds: tuple[float, float, float, float]
    center_of_mass: tuple[float, float, float]


@dataclass(frozen=True)
class _BodyRecord:
    body_tag: int
    bbox: tuple[float, float, float, float, float, float]
    center_of_mass: tuple[float, float, float]
    face_count: int


@dataclass(frozen=True)
class _SymmetryTouchingAnalysis:
    body_count: int
    surface_count: int
    volume_count: int
    body_records: list[_BodyRecord]
    duplicate_face_pairs: list[dict[str, Any]]
    touching_groups: list[dict[str, Any]]
    singleton_body_tags: list[int]
    grouped_body_tags: list[int]
    internal_cap_face_tags: list[int]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _VspWingCandidate:
    geom_id: str
    name: str
    type_name: str
    normalized_name: str
    is_symmetric_xz: bool
    x_location: float
    x_rotation_deg: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]

    @property
    def span_y(self) -> float:
        return self.bbox_max[1] - self.bbox_min[1]

    @property
    def span_z(self) -> float:
        return self.bbox_max[2] - self.bbox_min[2]

    @property
    def chord_x(self) -> float:
        return self.bbox_max[0] - self.bbox_min[0]


@dataclass(frozen=True)
class _NativeSectionRecord:
    x_le: float
    y_le: float
    z_le: float
    chord: float
    twist_deg: float
    airfoil_name: Optional[str]
    airfoil_source: str
    airfoil_coordinates: tuple[tuple[float, float], ...]
    thickness_tc: Optional[float] = None
    camber: Optional[float] = None
    camber_loc: Optional[float] = None


@dataclass(frozen=True)
class _NativeSurfaceRecord:
    component: str
    geom_id: str
    name: str
    caps_group: str
    symmetric_xz: bool
    sections: tuple[_NativeSectionRecord, ...]
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class _NativeRebuildModel:
    source_path: Path
    surfaces: tuple[_NativeSurfaceRecord, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ComponentInputModel:
    input_model_path: Path
    notes: list[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class EspMaterializationResult:
    status: str
    normalized_geometry_path: Optional[Path]
    topology_report_path: Optional[Path]
    topology: Optional[GeometryTopologyMetadata] = None
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    failure_code: Optional[str] = None
    provider_version: Optional[str] = None
    command_log_path: Optional[Path] = None
    script_path: Optional[Path] = None
    input_model_path: Optional[Path] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Path] = field(default_factory=dict)


def _load_openvsp():
    import openvsp as vsp  # type: ignore

    return vsp


def _default_runner(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_batch_binary() -> Optional[str]:
    for candidate in ("serveCSM", "ocsm"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    return None


def _format_csm_number(value: float) -> str:
    return f"{float(value):.12g}"


def _unique_sorted_ints(values: Sequence[int]) -> list[int]:
    return sorted({int(value) for value in values})


def _rotate_xyz(
    point: tuple[float, float, float],
    rotation_deg: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in point)
    rx, ry, rz = (math.radians(float(value)) for value in rotation_deg)

    y, z = (
        y * math.cos(rx) - z * math.sin(rx),
        y * math.sin(rx) + z * math.cos(rx),
    )
    x, z = (
        x * math.cos(ry) + z * math.sin(ry),
        -x * math.sin(ry) + z * math.cos(ry),
    )
    x, y = (
        x * math.cos(rz) - y * math.sin(rz),
        x * math.sin(rz) + y * math.cos(rz),
    )
    return float(x), float(y), float(z)


def _rotate_about_local_span(
    point: tuple[float, float, float],
    twist_deg: float,
) -> tuple[float, float, float]:
    angle = math.radians(-float(twist_deg))
    x, y, z = (float(value) for value in point)
    return (
        x * math.cos(angle) + z * math.sin(angle),
        y,
        -x * math.sin(angle) + z * math.cos(angle),
    )


def _naca_four_series_name(camber_frac: float, camber_loc: float, tc: float) -> str:
    d1 = max(0, min(9, int(round(float(camber_frac) * 100))))
    d2 = max(0, min(9, int(round(float(camber_loc) * 10))))
    d34 = max(0, min(99, int(round(float(tc) * 100))))
    return f"NACA {d1}{d2}{d34:02d}"


def _normalize_airfoil_coordinates(
    coordinates: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    if not coordinates:
        return ()
    xs = [float(pair[0]) for pair in coordinates]
    zs = [float(pair[1]) for pair in coordinates]
    min_x = min(xs)
    max_x = max(xs)
    chord = max(max_x - min_x, 1.0e-9)
    normalized = tuple(
        ((float(x) - min_x) / chord, float(z) / chord)
        for x, z in zip(xs, zs)
    )
    return normalized


def _extract_airfoil_coordinates(vsp, xsec: Any) -> tuple[tuple[float, float], ...]:
    try:
        upper = list(vsp.GetAirfoilUpperPnts(xsec))
        lower = list(vsp.GetAirfoilLowerPnts(xsec))
    except Exception:
        return ()
    if not upper or not lower:
        return ()

    axis_spans: dict[str, float] = {}
    all_points = list(upper) + list(lower)
    for axis in ("y", "z"):
        try:
            values = [_vsp_point_component(point, axis) for point in all_points]
        except Exception:
            axis_spans[axis] = float("-inf")
            continue
        axis_spans[axis] = max(values) - min(values) if values else float("-inf")
    ordinate_axis = "y" if axis_spans.get("y", float("-inf")) >= axis_spans.get("z", float("-inf")) else "z"

    upper_pairs = sorted(
        [(_vsp_point_component(point, "x"), _vsp_point_component(point, ordinate_axis)) for point in upper],
        key=lambda pair: pair[0],
        reverse=True,
    )
    lower_pairs = sorted(
        [(_vsp_point_component(point, "x"), _vsp_point_component(point, ordinate_axis)) for point in lower],
        key=lambda pair: pair[0],
    )
    if not upper_pairs or not lower_pairs:
        return ()
    if (
        abs(upper_pairs[-1][0] - lower_pairs[0][0]) <= 1.0e-9
        and abs(upper_pairs[-1][1] - lower_pairs[0][1]) <= 1.0e-9
    ):
        combined = upper_pairs + lower_pairs[1:]
    else:
        combined = upper_pairs + lower_pairs
    return _normalize_airfoil_coordinates([(float(x), float(z)) for x, z in combined])


def _coalesce_trailing_edge_seam(
    points: list[tuple[float, float]],
    *,
    chord: Optional[float],
    target_bridge_length_m: float = 10.0e-3,
    ratio_cap: float = 3.0,
    max_drops_per_side: int = 5,
) -> list[tuple[float, float]]:
    if len(points) < 6:
        return points
    closed = (
        abs(points[0][0] - points[-1][0]) <= 1.0e-9
        and abs(points[0][1] - points[-1][1]) <= 1.0e-9
    )
    work = list(points[:-1]) if closed else list(points)
    if len(work) < 5:
        return points
    if chord and chord > 0.0:
        target_norm = float(target_bridge_length_m) / float(chord)
    else:
        target_norm = 0.02

    def _dist(lhs: tuple[float, float], rhs: tuple[float, float]) -> float:
        return math.hypot(lhs[0] - rhs[0], lhs[1] - rhs[1])

    drops = 0
    while drops < max_drops_per_side and len(work) >= 6:
        seam_seg = _dist(work[0], work[1])
        next_seg = _dist(work[1], work[2])
        below_target = seam_seg < target_norm
        ratio_bad = next_seg > 0.0 and next_seg / max(seam_seg, 1.0e-12) > ratio_cap
        if not (below_target or ratio_bad):
            break
        del work[1]
        drops += 1

    drops = 0
    if closed:
        while drops < max_drops_per_side and len(work) >= 6:
            closure_seg = _dist(work[-1], work[0])
            prior_seg = _dist(work[-2], work[-1])
            below_target = closure_seg < target_norm
            ratio_bad = prior_seg > 0.0 and prior_seg / max(closure_seg, 1.0e-12) > ratio_cap
            if not (below_target or ratio_bad):
                break
            del work[-1]
            drops += 1
    else:
        while drops < max_drops_per_side and len(work) >= 6:
            seam_seg = _dist(work[-1], work[-2])
            prior_seg = _dist(work[-2], work[-3])
            below_target = seam_seg < target_norm
            ratio_bad = prior_seg > 0.0 and prior_seg / max(seam_seg, 1.0e-12) > ratio_cap
            if not (below_target or ratio_bad):
                break
            del work[-2]
            drops += 1

    if closed:
        work.append(work[0])
    return work


def _downsample_airfoil_coordinates(
    coordinates: Sequence[tuple[float, float]],
    *,
    max_points: int = 61,
    chord: Optional[float] = None,
) -> tuple[tuple[float, float], ...]:
    if len(coordinates) <= max_points:
        prepared = [(float(x), float(z)) for x, z in coordinates]
        coalesced = _coalesce_trailing_edge_seam(prepared, chord=chord)
        return tuple(coalesced)
    if max_points < 3:
        max_points = 3
    interior_budget = max_points - 2
    step = (len(coordinates) - 2) / max(interior_budget, 1)
    sampled = [coordinates[0]]
    for idx in range(1, max_points - 1):
        sample_index = min(len(coordinates) - 2, max(1, int(round(idx * step))))
        sampled.append(coordinates[sample_index])
    sampled.append(coordinates[-1])
    deduped: list[tuple[float, float]] = []
    for point in sampled:
        normalized = (float(point[0]), float(point[1]))
        if deduped and all(abs(a - b) <= 1.0e-9 for a, b in zip(deduped[-1], normalized)):
            continue
        deduped.append(normalized)
    deduped = _coalesce_trailing_edge_seam(deduped, chord=chord)
    if len(deduped) >= 2 and all(abs(a - b) <= 1.0e-9 for a, b in zip(deduped[0], deduped[-1])):
        return tuple(deduped)
    deduped.append(deduped[0])
    return tuple(deduped)


def _naca_profile_coordinates(
    *,
    thickness_tc: float,
    camber: float,
    camber_loc: float,
    num_points: int = 41,
) -> tuple[tuple[float, float], ...]:
    xs = [
        0.5 * (1.0 - math.cos(math.pi * idx / max(num_points - 1, 1)))
        for idx in range(num_points)
    ]
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    m = max(float(camber), 0.0)
    p = float(camber_loc)
    t = max(float(thickness_tc), 1.0e-4)
    for x in xs:
        yt = 5.0 * t * (
            0.2969 * math.sqrt(max(x, 0.0))
            - 0.1260 * x
            - 0.3516 * x**2
            + 0.2843 * x**3
            - 0.1015 * x**4
        )
        if m <= 1.0e-9 or p <= 1.0e-9 or p >= 1.0:
            yc = 0.0
            dyc_dx = 0.0
        elif x < p:
            yc = m / (p**2) * (2.0 * p * x - x**2)
            dyc_dx = 2.0 * m / (p**2) * (p - x)
        else:
            yc = m / ((1.0 - p) ** 2) * ((1.0 - 2.0 * p) + 2.0 * p * x - x**2)
            dyc_dx = 2.0 * m / ((1.0 - p) ** 2) * (p - x)
        theta = math.atan(dyc_dx)
        upper.append((x - yt * math.sin(theta), yc + yt * math.cos(theta)))
        lower.append((x + yt * math.sin(theta), yc - yt * math.cos(theta)))
    return tuple(reversed(upper)) + tuple(lower[1:])


def _resolve_section_airfoil_coordinates(
    section: _NativeSectionRecord,
) -> tuple[tuple[float, float], ...]:
    if section.airfoil_coordinates:
        return _downsample_airfoil_coordinates(
            section.airfoil_coordinates,
            chord=float(section.chord) if section.chord else None,
        )
    return _naca_profile_coordinates(
        thickness_tc=section.thickness_tc or 0.12,
        camber=section.camber or 0.0,
        camber_loc=section.camber_loc or 0.4,
    )


def _mirrored_section(section: _NativeSectionRecord) -> _NativeSectionRecord:
    return _NativeSectionRecord(
        x_le=section.x_le,
        y_le=-section.y_le,
        z_le=section.z_le,
        chord=section.chord,
        twist_deg=section.twist_deg,
        airfoil_name=section.airfoil_name,
        airfoil_source=section.airfoil_source,
        airfoil_coordinates=section.airfoil_coordinates,
        thickness_tc=section.thickness_tc,
        camber=section.camber,
        camber_loc=section.camber_loc,
    )


def _surface_sections_for_rule(surface: _NativeSurfaceRecord) -> list[_NativeSectionRecord]:
    sections = list(surface.sections)
    if not surface.symmetric_xz or len(sections) <= 1:
        return sections
    mirrored = [_mirrored_section(section) for section in reversed(sections[1:])]
    return [*mirrored, *sections]


def _surface_sections_with_lineage(surface: _NativeSurfaceRecord) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sections = list(surface.sections)
    if surface.symmetric_xz and len(sections) > 1:
        for source_index in range(len(sections) - 1, 0, -1):
            entries.append(
                {
                    "section": _mirrored_section(sections[source_index]),
                    "source_section_index": int(source_index),
                    "mirrored": True,
                    "side": "left_span",
                }
            )
    for source_index, section in enumerate(sections):
        entries.append(
            {
                "section": section,
                "source_section_index": int(source_index),
                "mirrored": False,
                "side": "right_span" if surface.symmetric_xz and source_index > 0 else "center_or_start",
            }
        )
    if entries:
        entries[0]["side"] = "left_tip" if surface.symmetric_xz else "start_tip"
        entries[-1]["side"] = "right_tip" if surface.symmetric_xz else "end_tip"
    return entries


def _distance_xy(lhs: tuple[float, float], rhs: tuple[float, float]) -> float:
    return math.hypot(float(lhs[0]) - float(rhs[0]), float(lhs[1]) - float(rhs[1]))


def _build_terminal_strip_candidate(
    *,
    section: _NativeSectionRecord,
    source_section_index: int,
    mirrored: bool,
    side: str,
) -> Dict[str, Any]:
    coordinates = list(_resolve_section_airfoil_coordinates(section))
    if not coordinates:
        return {
            "side": side,
            "source_section_index": int(source_section_index),
            "mirrored": bool(mirrored),
            "would_suppress": False,
            "reason": "section_has_no_profile_coordinates",
        }
    if len(coordinates) >= 2 and all(
        abs(float(lhs) - float(rhs)) <= 1.0e-12 for lhs, rhs in zip(coordinates[0], coordinates[-1])
    ):
        closed = coordinates
    else:
        closed = [*coordinates, coordinates[0]]
    if len(closed) < 4:
        return {
            "side": side,
            "source_section_index": int(source_section_index),
            "mirrored": bool(mirrored),
            "would_suppress": False,
            "reason": "insufficient_closed_profile_points",
        }

    seam_point = closed[0]
    next_point = closed[1]
    prev_point = closed[-2]
    chord = float(section.chord)
    next_length = _distance_xy(seam_point, next_point) * chord
    prev_length = _distance_xy(seam_point, prev_point) * chord
    trailing_edge_gap = _distance_xy(prev_point, next_point) * chord
    perimeter = (
        sum(_distance_xy(closed[idx], closed[idx + 1]) for idx in range(len(closed) - 1)) * chord
    )
    threshold = max(chord * 0.006, 1.5e-3)
    would_suppress = bool(max(next_length, prev_length) <= threshold)
    return {
        "side": side,
        "source_section_index": int(source_section_index),
        "mirrored": bool(mirrored),
        "y_le": float(section.y_le),
        "chord": chord,
        "profile_point_count": max(len(closed) - 1, 0),
        "seam_point_xy": [float(seam_point[0]), float(seam_point[1])],
        "seam_adjacent_points_xy": {
            "next": [float(next_point[0]), float(next_point[1])],
            "prev": [float(prev_point[0]), float(prev_point[1])],
        },
        "seam_adjacent_edge_lengths_m": [float(next_length), float(prev_length)],
        "trailing_edge_gap_m": float(trailing_edge_gap),
        "profile_perimeter_m": float(perimeter),
        "suppression_threshold_m": float(threshold),
        "would_suppress": would_suppress,
        "suppression_reason": (
            "terminal_tip_te_strip_candidate" if would_suppress else "terminal_tip_te_edges_not_small_enough"
        ),
    }


def _build_topology_lineage_report(rebuild_model: _NativeRebuildModel) -> Dict[str, Any]:
    surfaces: list[Dict[str, Any]] = []
    suppression_candidate_count = 0
    for surface in rebuild_model.surfaces:
        rule_sections = _surface_sections_with_lineage(surface)
        terminal_strip_candidates: list[Dict[str, Any]] = []
        for entry in rule_sections:
            if entry["side"] not in {"left_tip", "right_tip", "start_tip", "end_tip"}:
                continue
            candidate = _build_terminal_strip_candidate(
                section=entry["section"],
                source_section_index=int(entry["source_section_index"]),
                mirrored=bool(entry["mirrored"]),
                side=str(entry["side"]),
            )
            terminal_strip_candidates.append(candidate)
            if candidate.get("would_suppress"):
                suppression_candidate_count += 1
        surfaces.append(
            {
                "component": surface.component,
                "geom_id": surface.geom_id,
                "name": surface.name,
                "caps_group": surface.caps_group,
                "symmetric_xz": bool(surface.symmetric_xz),
                "source_section_count": len(surface.sections),
                "rule_section_count": len(rule_sections),
                "rule_sections": [
                    {
                        "rule_section_index": int(index),
                        "source_section_index": int(entry["source_section_index"]),
                        "mirrored": bool(entry["mirrored"]),
                        "side": str(entry["side"]),
                        "x_le": float(entry["section"].x_le),
                        "y_le": float(entry["section"].y_le),
                        "z_le": float(entry["section"].z_le),
                        "chord": float(entry["section"].chord),
                        "twist_deg": float(entry["section"].twist_deg),
                        "airfoil_source": str(entry["section"].airfoil_source),
                    }
                    for index, entry in enumerate(rule_sections)
                ],
                "terminal_strip_candidates": terminal_strip_candidates,
            }
        )
    return {
        "status": "captured",
        "source_path": str(rebuild_model.source_path),
        "surface_count": len(rebuild_model.surfaces),
        "suppression_candidate_count": suppression_candidate_count,
        "surfaces": surfaces,
        "notes": list(rebuild_model.notes),
    }


def _suppress_terminal_strip_coordinates(
    coordinates: Sequence[tuple[float, float]],
    *,
    chord: float,
    min_bridge_length: float,
) -> tuple[tuple[tuple[float, float], ...], Dict[str, Any]]:
    profile = [(float(x), float(z)) for x, z in coordinates]
    if not profile:
        return (), {"trim_count_per_side": 0, "bridge_length_m": 0.0}
    if len(profile) >= 2 and all(abs(lhs - rhs) <= 1.0e-12 for lhs, rhs in zip(profile[0], profile[-1])):
        closed = profile
    else:
        closed = [*profile, profile[0]]
    if len(closed) < 5:
        return tuple(closed), {"trim_count_per_side": 0, "bridge_length_m": 0.0}
    max_trim = max((len(closed) - 3) // 2, 1)
    selected_core = closed
    selected_trim = 0
    selected_bridge = _distance_xy(closed[1], closed[-2]) * float(chord)
    for trim_count in range(1, max_trim + 1):
        candidate_core = closed[trim_count:-trim_count]
        if len(candidate_core) < 4:
            break
        bridge_length = _distance_xy(candidate_core[0], candidate_core[-1]) * float(chord)
        selected_core = candidate_core
        selected_trim = trim_count
        selected_bridge = bridge_length
        if bridge_length >= float(min_bridge_length):
            break
    simplified = [(float(x), float(z)) for x, z in selected_core]
    if simplified and not all(abs(lhs - rhs) <= 1.0e-12 for lhs, rhs in zip(simplified[0], simplified[-1])):
        simplified.append(simplified[0])
    return tuple(simplified), {
        "trim_count_per_side": int(selected_trim),
        "bridge_length_m": float(selected_bridge),
    }


def _clone_section_with_airfoil_coordinates(
    section: _NativeSectionRecord,
    coordinates: Sequence[tuple[float, float]],
    *,
    source_suffix: str,
) -> _NativeSectionRecord:
    return _NativeSectionRecord(
        x_le=section.x_le,
        y_le=section.y_le,
        z_le=section.z_le,
        chord=section.chord,
        twist_deg=section.twist_deg,
        airfoil_name=section.airfoil_name,
        airfoil_source=f"{section.airfoil_source}|{source_suffix}",
        airfoil_coordinates=tuple((float(x), float(z)) for x, z in coordinates),
        thickness_tc=section.thickness_tc,
        camber=section.camber,
        camber_loc=section.camber_loc,
    )


def _apply_terminal_strip_suppression(
    rebuild_model: _NativeRebuildModel,
) -> tuple[_NativeRebuildModel, Dict[str, Any]]:
    suppressed_surfaces: list[_NativeSurfaceRecord] = []
    surface_reports: list[Dict[str, Any]] = []
    suppressed_source_section_count = 0
    for surface in rebuild_model.surfaces:
        rule_sections = _surface_sections_with_lineage(surface)
        terminal_candidates: list[Dict[str, Any]] = []
        suppressed_source_indices: list[int] = []
        for entry in rule_sections:
            if entry["side"] not in {"left_tip", "right_tip", "start_tip", "end_tip"}:
                continue
            candidate = _build_terminal_strip_candidate(
                section=entry["section"],
                source_section_index=int(entry["source_section_index"]),
                mirrored=bool(entry["mirrored"]),
                side=str(entry["side"]),
            )
            terminal_candidates.append(candidate)
            if candidate.get("would_suppress"):
                suppressed_source_indices.append(int(entry["source_section_index"]))
        unique_source_indices = _unique_sorted_ints(suppressed_source_indices)
        updated_sections = list(surface.sections)
        applied_sections: list[Dict[str, Any]] = []
        for source_index in unique_source_indices:
            original_section = updated_sections[source_index]
            resolved_coordinates = _resolve_section_airfoil_coordinates(original_section)
            suppression_threshold = max(float(original_section.chord) * 0.006, 1.5e-3)
            suppressed_coordinates, suppression_details = _suppress_terminal_strip_coordinates(
                resolved_coordinates,
                chord=float(original_section.chord),
                min_bridge_length=suppression_threshold,
            )
            if len(suppressed_coordinates) >= len(resolved_coordinates):
                continue
            updated_sections[source_index] = _clone_section_with_airfoil_coordinates(
                original_section,
                suppressed_coordinates,
                source_suffix="terminal_tip_strip_suppressed",
            )
            applied_sections.append(
                {
                    "source_section_index": int(source_index),
                    "before_profile_point_count": len(resolved_coordinates),
                    "after_profile_point_count": len(suppressed_coordinates),
                    "before_first_point": [
                        float(resolved_coordinates[0][0]),
                        float(resolved_coordinates[0][1]),
                    ] if resolved_coordinates else None,
                    "after_first_point": [
                        float(suppressed_coordinates[0][0]),
                        float(suppressed_coordinates[0][1]),
                    ] if suppressed_coordinates else None,
                    "trim_count_per_side": int(suppression_details["trim_count_per_side"]),
                    "bridge_length_m": float(suppression_details["bridge_length_m"]),
                    "suppression_threshold_m": float(suppression_threshold),
                }
            )
        if applied_sections:
            suppressed_source_section_count += len(applied_sections)
        suppressed_surfaces.append(
            _NativeSurfaceRecord(
                component=surface.component,
                geom_id=surface.geom_id,
                name=surface.name,
                caps_group=surface.caps_group,
                symmetric_xz=surface.symmetric_xz,
                sections=tuple(updated_sections),
                rotation_deg=surface.rotation_deg,
            )
        )
        surface_reports.append(
            {
                "component": surface.component,
                "geom_id": surface.geom_id,
                "name": surface.name,
                "caps_group": surface.caps_group,
                "terminal_strip_candidates": terminal_candidates,
                "suppressed_source_section_indices": [
                    int(section["source_section_index"]) for section in applied_sections
                ],
                "suppressed_sections": applied_sections,
                "applied": bool(applied_sections),
            }
        )
    applied = bool(suppressed_source_section_count)
    notes = list(rebuild_model.notes)
    if applied:
        notes.append("terminal_tip_strip_suppression_applied")
    suppressed_model = _NativeRebuildModel(
        source_path=rebuild_model.source_path,
        surfaces=tuple(suppressed_surfaces),
        notes=tuple(notes),
    )
    report = {
        "status": "captured",
        "applied": applied,
        "source_path": str(rebuild_model.source_path),
        "surface_count": len(rebuild_model.surfaces),
        "suppressed_source_section_count": suppressed_source_section_count,
        "surfaces": surface_reports,
        "notes": notes,
    }
    return suppressed_model, report


def _as_closed_profile(
    coordinates: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    closed = [(float(x), float(z)) for x, z in coordinates]
    if not closed:
        return []
    if not (
        abs(closed[0][0] - closed[-1][0]) <= 1.0e-12
        and abs(closed[0][1] - closed[-1][1]) <= 1.0e-12
    ):
        closed.append(closed[0])
    return closed


def _resample_closed_profile(
    coordinates: Sequence[tuple[float, float]],
    *,
    target_count: int,
) -> tuple[tuple[float, float], ...]:
    closed = _as_closed_profile(coordinates)
    if len(closed) <= 1 or target_count <= 1:
        return tuple(closed)
    if len(closed) == target_count:
        return tuple(closed)

    cumulative = [0.0]
    for index in range(1, len(closed)):
        cumulative.append(
            cumulative[-1] + _distance_xy(closed[index - 1], closed[index])
        )
    total_length = cumulative[-1]
    if total_length <= 1.0e-12:
        return tuple(closed[: target_count - 1] + [closed[0]])

    samples: list[tuple[float, float]] = []
    unique_target = max(target_count - 1, 1)
    for sample_index in range(unique_target):
        position = total_length * float(sample_index) / float(unique_target)
        segment_index = 1
        while segment_index < len(cumulative) and cumulative[segment_index] < position:
            segment_index += 1
        segment_index = min(max(segment_index, 1), len(closed) - 1)
        start = closed[segment_index - 1]
        end = closed[segment_index]
        start_length = cumulative[segment_index - 1]
        end_length = cumulative[segment_index]
        if abs(end_length - start_length) <= 1.0e-12:
            samples.append(start)
            continue
        blend = (position - start_length) / (end_length - start_length)
        samples.append(
            (
                float(start[0] + blend * (end[0] - start[0])),
                float(start[1] + blend * (end[1] - start[1])),
            )
        )
    samples.append(samples[0])
    return tuple(samples)


def _clone_surface_with_section_updates(
    surface: _NativeSurfaceRecord,
    updates: Dict[int, _NativeSectionRecord],
) -> _NativeSurfaceRecord:
    sections = list(surface.sections)
    for index, section in updates.items():
        sections[int(index)] = section
    return _NativeSurfaceRecord(
        component=surface.component,
        geom_id=surface.geom_id,
        name=surface.name,
        caps_group=surface.caps_group,
        symmetric_xz=surface.symmetric_xz,
        sections=tuple(sections),
        rotation_deg=surface.rotation_deg,
    )


def _clone_rebuild_model_with_surface_updates(
    rebuild_model: _NativeRebuildModel,
    *,
    surface_index: int,
    updated_surface: _NativeSurfaceRecord,
    note: str,
) -> _NativeRebuildModel:
    surfaces = list(rebuild_model.surfaces)
    surfaces[int(surface_index)] = updated_surface
    notes = list(rebuild_model.notes)
    if note not in notes:
        notes.append(note)
    return _NativeRebuildModel(
        source_path=rebuild_model.source_path,
        surfaces=tuple(surfaces),
        notes=tuple(notes),
    )


def _surface_index_for_component(
    rebuild_model: _NativeRebuildModel,
    component: str = "main_wing",
) -> int:
    for index, surface in enumerate(rebuild_model.surfaces):
        if surface.component == component:
            return int(index)
    return 0


def _tip_source_section_index(topology_lineage_report: Dict[str, Any]) -> int:
    candidates: list[int] = []
    fallback_candidates: list[int] = []
    for surface in topology_lineage_report.get("surfaces", []):
        for candidate in surface.get("terminal_strip_candidates", []):
            fallback_candidates.append(int(candidate.get("source_section_index", 0)))
            if candidate.get("would_suppress"):
                candidates.append(int(candidate.get("source_section_index", 0)))
    if candidates:
        return max(candidates)
    if fallback_candidates:
        return max(fallback_candidates)
    return 0


def _profile_segment_lengths_m(
    section: _NativeSectionRecord,
    coordinates: Sequence[tuple[float, float]],
) -> list[float]:
    closed = _as_closed_profile(coordinates)
    if len(closed) < 2:
        return []
    return [
        _distance_xy(closed[index], closed[index + 1]) * float(section.chord)
        for index in range(len(closed) - 1)
    ]


def _section_world_points(
    section: _NativeSectionRecord,
    *,
    rotation_deg: tuple[float, float, float],
    coordinates: Sequence[tuple[float, float]],
) -> list[tuple[float, float, float]]:
    world_points: list[tuple[float, float, float]] = []
    for x_rel, z_rel in coordinates:
        local_offset = _rotate_about_local_span(
            (float(x_rel) * section.chord, 0.0, float(z_rel) * section.chord),
            section.twist_deg,
        )
        rotated_offset = _rotate_xyz(local_offset, rotation_deg)
        world_points.append(
            (
                float(section.x_le + rotated_offset[0]),
                float(section.y_le + rotated_offset[1]),
                float(section.z_le + rotated_offset[2]),
            )
        )
    return world_points


def _tip_surface_id_family(active_hotspot_family: Dict[str, Any]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for surface_id in active_hotspot_family.get("observed_surfaces", []) or []:
        side = "right" if int(surface_id) == max(active_hotspot_family.get("observed_surfaces", [surface_id])) else "left"
        mapping[f"legacy_surface_{int(surface_id)}"] = f"section5_tip_adjacent_{side}"
    for surface_id in active_hotspot_family.get("legacy_surfaces", []) or []:
        side = "right" if int(surface_id) == max(active_hotspot_family.get("legacy_surfaces", [surface_id])) else "left"
        mapping[f"legacy_surface_{int(surface_id)}"] = f"section5_terminal_strip_{side}"
    return mapping


def _build_autonomous_repair_context(
    *,
    artifacts: Dict[str, Any],
) -> Dict[str, Any]:
    required_artifacts = [
        "topology_lineage_report",
        "topology_suppression_report",
        "hotspot_patch_report",
        "brep_hotspot_report",
        "sliver_cluster_report",
        "sliver_volume_pocket_summary",
        "rule_loft_pairing_repair_spec",
        "mesh_metadata",
    ]
    missing_artifacts = [name for name in required_artifacts if name not in artifacts]

    mesh_metadata = dict(artifacts.get("mesh_metadata", {}) or {})
    mesh_stats = dict(mesh_metadata.get("mesh", {}) or {})
    quality_metrics = dict(mesh_metadata.get("quality_metrics", {}) or {})
    mesh3d_watchdog = dict(mesh_metadata.get("mesh3d_watchdog", {}) or {})
    hotspot_patch_report = dict(artifacts.get("hotspot_patch_report", {}) or {})
    topology_suppression_report = dict(artifacts.get("topology_suppression_report", {}) or {})
    repair_spec = dict(artifacts.get("rule_loft_pairing_repair_spec", {}) or {})

    observed_surfaces = [
        int(entry.get("surface_id"))
        for entry in sorted(
            hotspot_patch_report.get("surface_reports", []),
            key=lambda record: int((record.get("worst_tets_near_this_surface") or {}).get("count", 0)),
            reverse=True,
        )
        if int((entry.get("worst_tets_near_this_surface") or {}).get("count", 0)) > 0
    ]
    legacy_surfaces = sorted(
        {
            int(entry.get("surface_id"))
            for entry in hotspot_patch_report.get("surface_reports", [])
            if int(entry.get("surface_id", -1)) in {31, 32}
        }
    )
    trim_count = 0
    for surface in topology_suppression_report.get("surfaces", []):
        suppressed_sections = surface.get("suppressed_sections", [])
        if suppressed_sections:
            trim_count = int(suppressed_sections[0].get("trim_count_per_side", 0))
            break

    return {
        "baseline": "shell_v2_strip_suppression",
        "mesh_only_no_go": True,
        "source_section_index": int(repair_spec.get("source_section_index", 5)),
        "known_good_trim_count_per_side": int(trim_count),
        "bad_aggressive_trim": bool(repair_spec.get("bad_aggressive_probe")),
        "baseline_metrics": {
            "surface_triangle_count": int(mesh_stats.get("surface_element_count", 0) or 0),
            "volume_element_count": int(mesh_stats.get("volume_element_count", 0) or 0),
            "nodes_created_per_boundary_node": float(
                mesh3d_watchdog.get("nodes_created_per_boundary_node", 0.0) or 0.0
            ),
            "ill_shaped_tet_count": int(quality_metrics.get("ill_shaped_tet_count", 0) or 0),
        },
        "active_hotspot_family": {
            "primary": ["tip-adjacent panel family"] if observed_surfaces else [],
            "observed_surfaces": observed_surfaces[:2],
            "legacy_surfaces": legacy_surfaces,
        },
        "do_not_repeat": [
            "compound",
            "optimizer zoo",
            "surface tip buffer",
            "Ball/Cylinder pocket",
            "more aggressive trim",
        ],
        "missing_artifacts": missing_artifacts,
    }


def _build_tip_topology_diagnostics(
    *,
    rebuild_model: _NativeRebuildModel,
    topology_lineage_report: Dict[str, Any],
    topology_suppression_report: Dict[str, Any],
    hotspot_patch_report: Dict[str, Any],
    active_hotspot_family: Dict[str, Any],
) -> Dict[str, Any]:
    surface_index = _surface_index_for_component(rebuild_model, component="main_wing")
    surface = rebuild_model.surfaces[surface_index]
    source_section_index = _tip_source_section_index(topology_lineage_report)
    previous_section_index = max(source_section_index - 1, 0)

    tip_section = surface.sections[source_section_index]
    previous_section = surface.sections[previous_section_index]
    tip_coords = _resolve_section_airfoil_coordinates(tip_section)
    previous_coords = _resolve_section_airfoil_coordinates(previous_section)
    previous_resampled = _resample_closed_profile(previous_coords, target_count=len(tip_coords))

    tip_widths = _profile_segment_lengths_m(tip_section, tip_coords)
    sampled_indices = list(range(min(4, len(tip_widths))))
    sampled_indices.extend(
        index for index in range(max(len(tip_widths) - 4, 0), len(tip_widths)) if index not in sampled_indices
    )
    sampled_indices = sorted(sampled_indices)

    tip_world = _section_world_points(
        tip_section,
        rotation_deg=surface.rotation_deg,
        coordinates=tip_coords,
    )
    prev_world = _section_world_points(
        previous_section,
        rotation_deg=surface.rotation_deg,
        coordinates=previous_resampled,
    )

    panel_lengths_m: list[float] = []
    panel_widths_m: list[float] = []
    width_length_ratios: list[float] = []
    candidate_bad_panels: list[Dict[str, Any]] = []
    previous_width = None
    consecutive_width_ratio_max = 0.0
    for panel_index in sampled_indices:
        width = float(tip_widths[panel_index])
        tip_point = tip_world[min(panel_index, len(tip_world) - 1)]
        prev_point = prev_world[min(panel_index, len(prev_world) - 1)]
        length = math.dist(tip_point, prev_point)
        panel_widths_m.append(width)
        panel_lengths_m.append(length)
        ratio = width / max(length, 1.0e-9)
        width_length_ratios.append(ratio)
        if previous_width is not None and min(previous_width, width) > 1.0e-12:
            consecutive_width_ratio_max = max(
                consecutive_width_ratio_max,
                max(previous_width, width) / min(previous_width, width),
            )
        previous_width = width
        panel_reason: list[str] = []
        if width < 0.006:
            panel_reason.append("panel_width_below_threshold")
        if ratio < 0.01:
            panel_reason.append("width_length_ratio_below_threshold")
        if panel_reason:
            candidate_bad_panels.append(
                {
                    "panel_index": int(panel_index),
                    "width_m": width,
                    "length_m": length,
                    "width_length_ratio": ratio,
                    "reason": panel_reason,
                }
            )

    adjacent_bridge_lengths = panel_widths_m[:2]
    terminal_bridge = float(tip_widths[0]) if tip_widths else 0.0
    bridge_length_ratios = [
        terminal_bridge / max(length, 1.0e-9) for length in adjacent_bridge_lengths
    ]

    classification_reason: list[str] = []
    if candidate_bad_panels:
        classification_reason.append("panel_width_or_ratio_threshold_triggered")
    if consecutive_width_ratio_max > 3.0:
        classification_reason.append("consecutive_width_ratio_above_threshold")
    hotspot_hits = sum(
        int((entry.get("worst_tets_near_this_surface") or {}).get("count", 0))
        for entry in hotspot_patch_report.get("surface_reports", [])
        if int(entry.get("surface_id", -1)) in set(active_hotspot_family.get("observed_surfaces", []))
    )
    if hotspot_hits > 0:
        classification_reason.append("tip_adjacent_panel_family_hit_by_worst_tets")

    old_face_to_source_panel = _tip_surface_id_family(active_hotspot_family)
    source_panel_to_faces: Dict[str, list[int]] = defaultdict(list)
    for face_key, family_name in old_face_to_source_panel.items():
        source_panel_to_faces[family_name].append(int(face_key.split("_")[-1]))

    return {
        "source_section_index": int(source_section_index),
        "terminal_tip_neighborhood": {
            "section_point_count_before": int(
                next(
                    (
                        suppressed.get("before_profile_point_count", len(tip_coords))
                        for surface_report in topology_suppression_report.get("surfaces", [])
                        for suppressed in surface_report.get("suppressed_sections", [])
                        if int(suppressed.get("source_section_index", -1)) == int(source_section_index)
                    ),
                    len(tip_coords),
                )
            ),
            "section_point_count_after_v2": len(tip_coords),
            "te_point_indices": [0, 1, max(len(tip_coords) - 2, 0), max(len(tip_coords) - 1, 0)],
            "trim_count_per_side": int(
                next(
                    (
                        suppressed.get("trim_count_per_side", 0)
                        for surface_report in topology_suppression_report.get("surfaces", [])
                        for suppressed in surface_report.get("suppressed_sections", [])
                        if int(suppressed.get("source_section_index", -1)) == int(source_section_index)
                    ),
                    0,
                )
            ),
            "terminal_bridge_m": terminal_bridge,
            "adjacent_bridge_lengths_m": adjacent_bridge_lengths,
            "bridge_length_ratios": bridge_length_ratios,
            "panel_widths_m": panel_widths_m,
            "panel_lengths_m": panel_lengths_m,
            "width_length_ratios": width_length_ratios,
            "consecutive_width_ratio_max": float(consecutive_width_ratio_max),
            "candidate_bad_panels": candidate_bad_panels,
        },
        "lineage": {
            "old_face_to_source_panel": old_face_to_source_panel,
            "source_panel_to_faces": dict(source_panel_to_faces),
            "attributes": {
                family_name: {"caps_group": surface.caps_group, "component": surface.component}
                for family_name in source_panel_to_faces
            },
            "physical_groups": {
                family_name: "aircraft"
                for family_name in source_panel_to_faces
            },
        },
        "classification": {
            "has_residual_sliver_sensitive_topology": bool(classification_reason),
            "reason": classification_reason,
        },
    }


def _max_profile_delta_m(
    baseline_section: _NativeSectionRecord,
    candidate_section: _NativeSectionRecord,
) -> float:
    baseline_coords = _resample_closed_profile(
        _resolve_section_airfoil_coordinates(baseline_section),
        target_count=65,
    )
    candidate_coords = _resample_closed_profile(
        _resolve_section_airfoil_coordinates(candidate_section),
        target_count=65,
    )
    return max(
        (
            math.hypot(
                (candidate[0] - baseline[0]) * float(candidate_section.chord),
                (candidate[1] - baseline[1]) * float(candidate_section.chord),
            )
            for baseline, candidate in zip(baseline_coords, candidate_coords)
        ),
        default=0.0,
    )


def _build_candidate_topology_repair_report(
    *,
    candidate_name: str,
    repair_type: str,
    source_section_index: int,
    changes: Dict[str, Any],
    old_face_to_new_face_map: Dict[str, Any],
    expected_effect: str,
    risk: str,
    attribute_remap: Optional[Dict[str, Any]] = None,
    physical_group_remap: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "candidate_name": str(candidate_name),
        "repair_type": str(repair_type),
        "source_section_index": int(source_section_index),
        "changes": dict(changes),
        "old_face_to_new_face_map": dict(old_face_to_new_face_map),
        "attribute_remap": dict(attribute_remap or {}),
        "physical_group_remap": dict(physical_group_remap or {}),
        "expected_effect": str(expected_effect),
        "risk": str(risk),
    }


def _build_candidate_face_map(
    diagnostics: Dict[str, Any],
    *,
    family_suffix: str,
) -> Dict[str, Any]:
    mapping = {}
    for face_key, source_panel in diagnostics.get("lineage", {}).get("old_face_to_source_panel", {}).items():
        mapping[str(face_key)] = {
            "source_panel_family": str(source_panel),
            "repaired_panel_family": f"{source_panel}|{family_suffix}",
        }
    return mapping


def _build_section5_pairing_smooth_candidate(
    *,
    baseline_rebuild_model: _NativeRebuildModel,
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    source_section_index = int(diagnostics["source_section_index"])
    previous_section_index = max(source_section_index - 1, 0)
    surface_index = _surface_index_for_component(baseline_rebuild_model, component="main_wing")
    baseline_surface = baseline_rebuild_model.surfaces[surface_index]
    tip_section = baseline_surface.sections[source_section_index]
    previous_section = baseline_surface.sections[previous_section_index]

    previous_resampled = _resample_closed_profile(
        _resolve_section_airfoil_coordinates(previous_section),
        target_count=len(_resolve_section_airfoil_coordinates(tip_section)),
    )
    updated_previous = _clone_section_with_airfoil_coordinates(
        previous_section,
        previous_resampled,
        source_suffix="section5_pairing_smooth_v0",
    )
    updated_surface = _clone_surface_with_section_updates(
        baseline_surface,
        {previous_section_index: updated_previous},
    )
    candidate_model = _clone_rebuild_model_with_surface_updates(
        baseline_rebuild_model,
        surface_index=surface_index,
        updated_surface=updated_surface,
        note="section5_pairing_smooth_v0",
    )
    face_map = _build_candidate_face_map(diagnostics, family_suffix="pairing_smooth")
    return {
        "candidate_name": "section5_pairing_smooth_v0",
        "repair_type": "pairing_smooth",
        "rebuild_model": candidate_model,
        "old_face_to_new_face_map": face_map,
        "report": _build_candidate_topology_repair_report(
            candidate_name="section5_pairing_smooth_v0",
            repair_type="pairing_smooth",
            source_section_index=source_section_index,
            changes={
                "paired_section_indices": [previous_section_index, source_section_index],
                "paired_profile_point_count": len(previous_resampled),
                "max_geometry_delta_m": _max_profile_delta_m(previous_section, updated_previous),
            },
            old_face_to_new_face_map=face_map,
            expected_effect="smooth section4-section5 pairing in the terminal tip TE neighborhood without increasing trim",
            risk="paired reparameterization can move the residual hotspot into a neighboring healthy panel",
            attribute_remap={value["repaired_panel_family"]: {"caps_group": baseline_surface.caps_group} for value in face_map.values()},
            physical_group_remap={value["repaired_panel_family"]: "aircraft" for value in face_map.values()},
        ),
    }


def _blend_profile_neighborhood(
    baseline_tip: Sequence[tuple[float, float]],
    previous_resampled: Sequence[tuple[float, float]],
    *,
    blend_count: int,
    blend_weight: float,
) -> tuple[tuple[float, float], ...]:
    tip = list(_as_closed_profile(baseline_tip))
    previous = list(_as_closed_profile(previous_resampled))
    if len(tip) != len(previous):
        previous = list(_resample_closed_profile(previous, target_count=len(tip)))
    last_interior = max(len(tip) - 2, 0)
    for index in range(1, min(blend_count + 1, last_interior + 1)):
        upper = index
        lower = max(last_interior - index, 0)
        for target_index in {upper, lower}:
            tip[target_index] = (
                float((1.0 - blend_weight) * tip[target_index][0] + blend_weight * previous[target_index][0]),
                float((1.0 - blend_weight) * tip[target_index][1] + blend_weight * previous[target_index][1]),
            )
    tip[-1] = tip[0]
    return tuple(tip)


def _build_section5_te_pair_coalesce_candidate(
    *,
    baseline_rebuild_model: _NativeRebuildModel,
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    source_section_index = int(diagnostics["source_section_index"])
    previous_section_index = max(source_section_index - 1, 0)
    surface_index = _surface_index_for_component(baseline_rebuild_model, component="main_wing")
    baseline_surface = baseline_rebuild_model.surfaces[surface_index]
    tip_section = baseline_surface.sections[source_section_index]
    previous_section = baseline_surface.sections[previous_section_index]

    tip_coords = _resolve_section_airfoil_coordinates(tip_section)
    previous_resampled = _resample_closed_profile(
        _resolve_section_airfoil_coordinates(previous_section),
        target_count=len(tip_coords),
    )
    coalesced_tip = _blend_profile_neighborhood(
        tip_coords,
        previous_resampled,
        blend_count=4,
        blend_weight=0.35,
    )
    updated_previous = _clone_section_with_airfoil_coordinates(
        previous_section,
        previous_resampled,
        source_suffix="section5_te_pair_coalesce_v0",
    )
    updated_tip = _clone_section_with_airfoil_coordinates(
        tip_section,
        coalesced_tip,
        source_suffix="section5_te_pair_coalesce_v0",
    )
    updated_surface = _clone_surface_with_section_updates(
        baseline_surface,
        {
            previous_section_index: updated_previous,
            source_section_index: updated_tip,
        },
    )
    candidate_model = _clone_rebuild_model_with_surface_updates(
        baseline_rebuild_model,
        surface_index=surface_index,
        updated_surface=updated_surface,
        note="section5_te_pair_coalesce_v0",
    )
    face_map = _build_candidate_face_map(diagnostics, family_suffix="te_pair_coalesce")
    return {
        "candidate_name": "section5_te_pair_coalesce_v0",
        "repair_type": "te_pair_coalesce",
        "rebuild_model": candidate_model,
        "old_face_to_new_face_map": face_map,
        "report": _build_candidate_topology_repair_report(
            candidate_name="section5_te_pair_coalesce_v0",
            repair_type="te_pair_coalesce",
            source_section_index=source_section_index,
            changes={
                "paired_section_indices": [previous_section_index, source_section_index],
                "coalesced_bridge_blend_weight": 0.35,
                "coalesced_profile_point_count": len(coalesced_tip),
                "max_geometry_delta_m": max(
                    _max_profile_delta_m(previous_section, updated_previous),
                    _max_profile_delta_m(tip_section, updated_tip),
                ),
            },
            old_face_to_new_face_map=face_map,
            expected_effect="coalesce the residual tip-adjacent panel family before BRep face emission",
            risk="coalescing can shift the hotspot across the terminal tip family if the blend is too aggressive",
            attribute_remap={value["repaired_panel_family"]: {"caps_group": baseline_surface.caps_group} for value in face_map.values()},
            physical_group_remap={value["repaired_panel_family"]: "aircraft" for value in face_map.values()},
        ),
    }


def _build_terminal_tip_cap_rebuild_candidate(
    *,
    baseline_rebuild_model: _NativeRebuildModel,
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    source_section_index = int(diagnostics["source_section_index"])
    previous_section_index = max(source_section_index - 1, 0)
    surface_index = _surface_index_for_component(baseline_rebuild_model, component="main_wing")
    baseline_surface = baseline_rebuild_model.surfaces[surface_index]
    tip_section = baseline_surface.sections[source_section_index]
    previous_section = baseline_surface.sections[previous_section_index]

    tip_coords = _resolve_section_airfoil_coordinates(tip_section)
    previous_resampled = _resample_closed_profile(
        _resolve_section_airfoil_coordinates(previous_section),
        target_count=len(tip_coords),
    )
    rebuilt_tip = _blend_profile_neighborhood(
        tip_coords,
        previous_resampled,
        blend_count=6,
        blend_weight=0.6,
    )
    updated_tip = _clone_section_with_airfoil_coordinates(
        tip_section,
        rebuilt_tip,
        source_suffix="terminal_tip_cap_rebuild_v0",
    )
    updated_surface = _clone_surface_with_section_updates(
        baseline_surface,
        {source_section_index: updated_tip},
    )
    candidate_model = _clone_rebuild_model_with_surface_updates(
        baseline_rebuild_model,
        surface_index=surface_index,
        updated_surface=updated_surface,
        note="terminal_tip_cap_rebuild_v0",
    )
    face_map = _build_candidate_face_map(diagnostics, family_suffix="terminal_tip_cap_rebuild")
    return {
        "candidate_name": "terminal_tip_cap_rebuild_v0",
        "repair_type": "tip_cap_rebuild",
        "rebuild_model": candidate_model,
        "old_face_to_new_face_map": face_map,
        "report": _build_candidate_topology_repair_report(
            candidate_name="terminal_tip_cap_rebuild_v0",
            repair_type="tip_cap_rebuild",
            source_section_index=source_section_index,
            changes={
                "tip_rebuild_blend_weight": 0.6,
                "tip_profile_point_count": len(rebuilt_tip),
                "max_geometry_delta_m": _max_profile_delta_m(tip_section, updated_tip),
            },
            old_face_to_new_face_map=face_map,
            expected_effect="rebuild the terminal tip cap/bridge patch without increasing trim count",
            risk="tip cap rebuild can move the hotspot if the repaired footprint drifts too far from the v2 baseline",
            attribute_remap={value["repaired_panel_family"]: {"caps_group": baseline_surface.caps_group} for value in face_map.values()},
            physical_group_remap={value["repaired_panel_family"]: "aircraft" for value in face_map.values()},
        ),
    }


def _build_diagnostic_noop_candidate(
    *,
    baseline_rebuild_model: _NativeRebuildModel,
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    face_map = _build_candidate_face_map(diagnostics, family_suffix="noop_v2_control")
    return {
        "candidate_name": "diagnostic_noop_v2_control",
        "repair_type": "noop_control",
        "rebuild_model": baseline_rebuild_model,
        "old_face_to_new_face_map": face_map,
        "report": _build_candidate_topology_repair_report(
            candidate_name="diagnostic_noop_v2_control",
            repair_type="noop_control",
            source_section_index=int(diagnostics["source_section_index"]),
            changes={"baseline": "shell_v2_strip_suppression"},
            old_face_to_new_face_map=face_map,
            expected_effect="preserve the v2 suppression baseline as the control candidate",
            risk="no geometry repair is applied",
            attribute_remap={value["repaired_panel_family"]: {"caps_group": "main_wing"} for value in face_map.values()},
            physical_group_remap={value["repaired_panel_family"]: "aircraft" for value in face_map.values()},
        ),
    }


def _generate_bounded_tip_topology_repair_candidates(
    *,
    baseline_rebuild_model: _NativeRebuildModel,
    diagnostics: Dict[str, Any],
    egads_effective_topology_available: bool,
) -> List[Dict[str, Any]]:
    candidates = [
        _build_section5_pairing_smooth_candidate(
            baseline_rebuild_model=baseline_rebuild_model,
            diagnostics=diagnostics,
        ),
        _build_section5_te_pair_coalesce_candidate(
            baseline_rebuild_model=baseline_rebuild_model,
            diagnostics=diagnostics,
        ),
        _build_terminal_tip_cap_rebuild_candidate(
            baseline_rebuild_model=baseline_rebuild_model,
            diagnostics=diagnostics,
        ),
        _build_diagnostic_noop_candidate(
            baseline_rebuild_model=baseline_rebuild_model,
            diagnostics=diagnostics,
        ),
    ]
    if egads_effective_topology_available:
        face_map = _build_candidate_face_map(diagnostics, family_suffix="egads_effective_topology")
        candidates.append(
            {
                "candidate_name": "egads_effective_topology_probe_v0",
                "repair_type": "egads_effective_topology_probe",
                "rebuild_model": baseline_rebuild_model,
                "old_face_to_new_face_map": face_map,
                "report": _build_candidate_topology_repair_report(
                    candidate_name="egads_effective_topology_probe_v0",
                    repair_type="egads_effective_topology_probe",
                    source_section_index=int(diagnostics["source_section_index"]),
                    changes={"enabled": True},
                    old_face_to_new_face_map=face_map,
                    expected_effect="coalesce residual tip-adjacent faces using EGADS effective topology",
                    risk="effective topology semantics may differ from the current rule-loft face lineage",
                ),
            }
        )
    return candidates


def _geometry_filter_decision(
    *,
    candidate_report: Dict[str, Any],
    brep_hotspot_report: Dict[str, Any],
    provider_metadata: Dict[str, Any],
    candidate_hotspot_patch_report_2d: Dict[str, Any],
    mesh_metadata: Dict[str, Any],
    baseline_reference: Dict[str, Any],
) -> Dict[str, Any]:
    hard_reject_reasons: list[str] = []
    mesh_stats = mesh_metadata.get("mesh", {}) or {}
    surface_triangle_count = int(mesh_stats.get("surface_element_count", 0) or 0)
    status = str(mesh_metadata.get("status", "failed"))
    generate_2d_returned = bool(
        status in {"success", "surface_mesh_only"}
        and surface_triangle_count > 0
    )
    old_face_to_new_face_map = candidate_report.get("old_face_to_new_face_map", {}) or {}
    brep_valid_default = brep_hotspot_report.get("shape_valid_default")
    brep_valid_exact = brep_hotspot_report.get("shape_valid_exact")
    physical_groups_preserved = bool(provider_metadata.get("physical_groups_preserved", False))
    physical_group_remap = provider_metadata.get("physical_group_remap", {}) or {}
    tip_topology_diagnostics = dict(provider_metadata.get("tip_topology_diagnostics") or {})
    terminal_tip = dict(tip_topology_diagnostics.get("terminal_tip_neighborhood") or {})
    candidate_width_ratios = [float(value) for value in terminal_tip.get("width_length_ratios", [])]
    candidate_panel_widths = [float(value) for value in terminal_tip.get("panel_widths_m", [])]
    candidate_min_width_ratio = min(candidate_width_ratios) if candidate_width_ratios else None
    candidate_min_panel_width = min(candidate_panel_widths) if candidate_panel_widths else None
    candidate_consecutive_ratio = terminal_tip.get("consecutive_width_ratio_max")
    candidate_consecutive_ratio = (
        float(candidate_consecutive_ratio) if candidate_consecutive_ratio is not None else None
    )

    if not generate_2d_returned:
        hard_reject_reasons.append("generate_2d_failed")
    if not old_face_to_new_face_map:
        hard_reject_reasons.append("old_face_to_new_face_map_missing")
    if brep_valid_default is not True:
        hard_reject_reasons.append("brep_invalid_default")
    if brep_valid_exact is not True:
        hard_reject_reasons.append("brep_invalid_exact")
    if not physical_groups_preserved and not physical_group_remap:
        hard_reject_reasons.append("physical_groups_lost_without_remap")
    if surface_triangle_count >= 120000:
        hard_reject_reasons.append("surface_triangle_count_limit")

    surface_reports = candidate_hotspot_patch_report_2d.get("surface_reports", []) or []
    candidate_tip_min_gamma = min(
        (
            float((report.get("surface_triangle_quality") or {}).get("gamma", {}).get("min"))
            for report in surface_reports
            if (report.get("surface_triangle_quality") or {}).get("gamma", {}).get("min") is not None
        ),
        default=None,
    )
    baseline_tip_min_gamma = baseline_reference.get("tip_surface_min_gamma")
    if (
        candidate_tip_min_gamma is not None
        and baseline_tip_min_gamma is not None
        and float(candidate_tip_min_gamma) < float(baseline_tip_min_gamma) * 0.5
    ):
        hard_reject_reasons.append("tip_surface_min_gamma_regressed")
    baseline_min_width_ratio = baseline_reference.get("min_width_length_ratio")
    if (
        candidate_min_width_ratio is not None
        and baseline_min_width_ratio is not None
        and float(candidate_min_width_ratio) < float(baseline_min_width_ratio) * 0.8
    ):
        hard_reject_reasons.append("residual_strip_severity_regressed")
    baseline_min_panel_width = baseline_reference.get("min_panel_width_m")
    if (
        candidate_min_panel_width is not None
        and baseline_min_panel_width is not None
        and float(candidate_min_panel_width) < float(baseline_min_panel_width) * 0.8
    ):
        hard_reject_reasons.append("panel_width_regressed")

    geometry_score = 0.0
    if not hard_reject_reasons:
        geometry_score += 10.0
    if physical_groups_preserved:
        geometry_score += 2.0
    if candidate_tip_min_gamma is not None:
        geometry_score += min(float(candidate_tip_min_gamma) * 25.0, 10.0)
    if candidate_min_width_ratio is not None:
        geometry_score += min(float(candidate_min_width_ratio) * 500.0, 5.0)
    if candidate_min_panel_width is not None:
        geometry_score += min(float(candidate_min_panel_width) * 200.0, 3.0)
    if candidate_consecutive_ratio is not None:
        geometry_score -= max(float(candidate_consecutive_ratio) - float(baseline_reference.get("max_consecutive_width_ratio", candidate_consecutive_ratio)), 0.0)
    geometry_score -= max(0.0, surface_triangle_count - int(baseline_reference.get("surface_triangle_count", 0) or 0)) / 2000.0
    geometry_score -= len(
        [
            report
            for report in surface_reports
            if int(report.get("surface_id", -1)) not in set(baseline_reference.get("focus_surface_ids", []))
            and "high_aspect_strip_candidate" in set(report.get("family_hints", []))
        ]
    )

    return {
        "passed": not hard_reject_reasons,
        "geometry_score": geometry_score,
        "hard_reject_reasons": hard_reject_reasons,
        "generate_2d_returned": generate_2d_returned,
        "surface_triangle_count": surface_triangle_count,
        "candidate_tip_min_gamma": candidate_tip_min_gamma,
        "candidate_min_width_length_ratio": candidate_min_width_ratio,
        "candidate_min_panel_width_m": candidate_min_panel_width,
        "candidate_consecutive_width_ratio_max": candidate_consecutive_ratio,
        "brep_valid_default": brep_valid_default,
        "brep_valid_exact": brep_valid_exact,
        "physical_groups_preserved": physical_groups_preserved,
    }


def _select_top_geometry_candidates(
    candidate_reports: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    passed = [
        dict(report)
        for report in candidate_reports
        if bool(report.get("geometry_filter_passed", False))
    ]
    return sorted(
        passed,
        key=lambda report: float(report.get("geometry_score", float("-inf"))),
        reverse=True,
    )[:2]


def _candidate_passes_quality_gate(candidate: Dict[str, Any]) -> bool:
    return bool(
        candidate.get("generate_2d_returned")
        and candidate.get("generate_3d_returned")
        and candidate.get("brep_valid_default") is True
        and candidate.get("brep_valid_exact") is True
        and (
            candidate.get("physical_groups_preserved") is True
            or bool(candidate.get("physical_group_remap"))
        )
        and int(candidate.get("surface_triangle_count", 0) or 0) < 120000
        and int(candidate.get("volume_element_count", 0) or 0) < 180000
        and float(candidate.get("nodes_created_per_boundary_node", 0.0) or 0.0) < 0.5
        and str(candidate.get("timeout_phase_classification")) != "volume_insertion"
        and int(candidate.get("ill_shaped_tet_count", 0) or 0) == 0
        and float(candidate.get("min_volume", 0.0) or 0.0) > 0.0
        and float(candidate.get("minSICN", 0.0) or 0.0) > 0.0
        and float(candidate.get("minSIGE", 0.0) or 0.0) > 0.0
    )


def _select_topology_repair_winner(
    candidates: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    passing = [dict(candidate) for candidate in candidates if _candidate_passes_quality_gate(candidate)]
    if not passing:
        return None
    return sorted(
        passing,
        key=lambda candidate: (
            int(candidate.get("volume_element_count", 0) or 0),
            int(candidate.get("surface_triangle_count", 0) or 0),
            -float(candidate.get("minSICN", 0.0) or 0.0),
            -float(candidate.get("minSIGE", 0.0) or 0.0),
            float(candidate.get("geometry_delta_m", 0.0) or 0.0),
        ),
    )[0]


def _build_upstream_pairing_no_go_summary() -> Dict[str, Any]:
    return {
        "reason": "bounded upstream pairing/coalescing candidates did not clear residual slivers",
        "confirmed_no_go": [
            "compound",
            "optimizer",
            "surface tip buffer",
            "Ball/Cylinder volume pocket",
            "more aggressive trim",
        ],
        "source_section_index": 5,
        "next_required_action": "manual review of rule-loft section pairing or geometry construction contract",
        "minimum_information_for_manual_review": [
            "tip_topology_diagnostics.json",
            "candidate_topology_repair_report.json",
            "old_face_to_new_face_map",
            "brep_hotspot_report",
            "hotspot_patch_report",
            "sliver_cluster_report",
        ],
    }


def _build_section_sketch_lines(
    section: _NativeSectionRecord,
    *,
    rotation_deg: tuple[float, float, float],
) -> list[str]:
    coordinates = _resolve_section_airfoil_coordinates(section)
    if len(coordinates) < 3:
        raise ValueError("native rebuild section needs at least three profile points")
    global_points: list[tuple[float, float, float]] = []
    for x_rel, z_rel in coordinates:
        local_offset = _rotate_about_local_span(
            (float(x_rel) * section.chord, 0.0, float(z_rel) * section.chord),
            section.twist_deg,
        )
        rotated_offset = _rotate_xyz(local_offset, rotation_deg)
        global_points.append(
            (
                section.x_le + rotated_offset[0],
                section.y_le + rotated_offset[1],
                section.z_le + rotated_offset[2],
            )
        )

    lines = [
        "skbeg "
        + " ".join(_format_csm_number(value) for value in global_points[0])
    ]
    for index, point in enumerate(global_points[1:], start=1):
        opcode = "linseg" if index == 1 or index == len(global_points) - 1 else "spline"
        lines.append(
            f"   {opcode} " + " ".join(_format_csm_number(value) for value in point)
        )
    lines.append("skend")
    return lines


def _sanitize_caps_group(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    return sanitized or "surface"


def _build_native_geometry_lines(rebuild_model: _NativeRebuildModel) -> list[str]:
    lines = [
        "# Native lifting-surface rebuild generated from OpenVSP section data",
        f"# Source model: {rebuild_model.source_path}",
    ]
    for surface in rebuild_model.surfaces:
        sections = _surface_sections_for_rule(surface)
        if len(sections) < 2:
            continue
        lines.append("")
        lines.append(f"# Surface: {surface.component} ({surface.name})")
        lines.append("mark")
        for section in sections:
            lines.extend(_build_section_sketch_lines(section, rotation_deg=surface.rotation_deg))
        caps_group = _sanitize_caps_group(surface.caps_group)
        lines.append("rule")
        lines.append(f"ATTRIBUTE _name ${caps_group}")
        lines.append(f"ATTRIBUTE capsGroup ${caps_group}")
    return lines


def _build_csm_script_from_rebuild_model(
    rebuild_model: _NativeRebuildModel,
    export_path: Path,
) -> str:
    script_lines = [
        "# Auto-generated by hpa_meshing.providers.esp_pipeline",
        "# Rebuilds OpenVSP lifting surfaces into native OpenCSM rule lofts",
        f"SET export_path $\"{export_path}\"",
        *_build_native_geometry_lines(rebuild_model),
        "DUMP !export_path 0 1",
        "END",
        "",
    ]
    return "\n".join(script_lines)


def _build_union_csm_script_from_rebuild_model(
    rebuild_model: _NativeRebuildModel,
    export_path: Path,
    body_count: int,
) -> str:
    script_lines = [
        "# Auto-generated by hpa_meshing.providers.esp_pipeline",
        "# Rebuilds OpenVSP lifting surfaces into native OpenCSM rule lofts",
        f"SET export_path $\"{export_path}\"",
        *_build_native_geometry_lines(rebuild_model),
        f"UNION {body_count}",
        "DUMP !export_path 0 1",
        "END",
        "",
    ]
    return "\n".join(script_lines)


def _build_native_rebuild_model(
    *,
    source_path: Path,
    component: str,
) -> _NativeRebuildModel:
    if source_path.suffix.lower() != ".vsp3":
        raise RuntimeError(f"native ESP rebuild requires a .vsp3 source, got {source_path.suffix or '<none>'}")

    vsp = _load_openvsp()
    try:
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(source_path))
        vsp.Update()
        candidates = _collect_vsp_wing_candidates(vsp)
        selected_components: list[tuple[str, _VspWingCandidate]] = []
        seen_geom_ids: set[str] = set()
        effective_component = _component_alias(component)
        component_order = (
            ("main_wing", "horizontal_tail", "vertical_tail")
            if effective_component == "aircraft_assembly"
            else (effective_component,)
        )
        for component_name in component_order:
            try:
                candidate = _select_component_candidate(component_name, candidates)
            except Exception:
                continue
            if candidate.geom_id in seen_geom_ids:
                continue
            seen_geom_ids.add(candidate.geom_id)
            selected_components.append((component_name, candidate))

        surfaces: list[_NativeSurfaceRecord] = []
        notes: list[str] = []
        for component_name, candidate in selected_components:
            geom_rotation = (
                _safe_vsp_parm(vsp, candidate.geom_id, ["X_Rotation", "X_Rel_Rotation"], "XForm"),
                _safe_vsp_parm(vsp, candidate.geom_id, ["Y_Rotation", "Y_Rel_Rotation"], "XForm"),
                _safe_vsp_parm(vsp, candidate.geom_id, ["Z_Rotation", "Z_Rel_Rotation"], "XForm"),
            )
            geom_translation = (
                _safe_vsp_parm(vsp, candidate.geom_id, ["X_Location", "X_Rel_Location"], "XForm"),
                _safe_vsp_parm(vsp, candidate.geom_id, ["Y_Location", "Y_Rel_Location"], "XForm"),
                _safe_vsp_parm(vsp, candidate.geom_id, ["Z_Location", "Z_Rel_Location"], "XForm"),
            )
            xsec_surf = vsp.GetXSecSurf(candidate.geom_id, 0)
            section_count = int(vsp.GetNumXSec(xsec_surf))
            if section_count <= 0:
                notes.append(f"skip_{component_name}:no_xsecs")
                continue

            local_positions: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
            root_chord = None
            if section_count > 1:
                first_segment = vsp.GetXSec(xsec_surf, 1)
                root_chord = _safe_get_xsec_parm_value(vsp, first_segment, "Root_Chord")
            if root_chord is None:
                first_root = vsp.GetXSec(xsec_surf, 0)
                root_chord = (
                    _safe_get_xsec_parm_value(vsp, first_root, "Root_Chord")
                    or _safe_get_xsec_parm_value(vsp, first_root, "Tip_Chord")
                    or 1.0
                )
            section_specs: list[tuple[Any, tuple[float, float, float], float, float]] = []
            root_xsec = vsp.GetXSec(xsec_surf, 0)
            section_specs.append((root_xsec, local_positions[0], float(root_chord), _safe_get_xsec_parm_value(vsp, root_xsec, "Twist") or 0.0))

            for index in range(1, section_count):
                xsec = vsp.GetXSec(xsec_surf, index)
                root_c = _safe_get_xsec_parm_value(vsp, xsec, "Root_Chord") or section_specs[-1][2]
                tip_c = _safe_get_xsec_parm_value(vsp, xsec, "Tip_Chord") or root_c
                span = _safe_get_xsec_parm_value(vsp, xsec, "Span") or 0.0
                sweep = _safe_get_xsec_parm_value(vsp, xsec, "Sweep") or 0.0
                sweep_location = _safe_get_xsec_parm_value(vsp, xsec, "Sweep_Location")
                if sweep_location is None:
                    sweep_location = 0.25
                dihedral = _safe_get_xsec_parm_value(vsp, xsec, "Dihedral") or 0.0
                prev_x, prev_y, prev_z = local_positions[-1]
                dx = span * math.tan(math.radians(sweep)) - sweep_location * (tip_c - root_c)
                dz = span * math.tan(math.radians(dihedral))
                local_position = (prev_x + dx, prev_y + span, prev_z + dz)
                local_positions.append(local_position)
                section_specs.append(
                    (
                        xsec,
                        local_position,
                        float(tip_c),
                        _safe_get_xsec_parm_value(vsp, xsec, "Twist") or 0.0,
                    )
                )

            section_records: list[_NativeSectionRecord] = []
            for xsec, local_position, chord, twist_deg in section_specs:
                rotated_position = _rotate_xyz(local_position, geom_rotation)
                global_le = (
                    geom_translation[0] + rotated_position[0],
                    geom_translation[1] + rotated_position[1],
                    geom_translation[2] + rotated_position[2],
                )
                thickness_tc = _safe_get_xsec_parm_value(vsp, xsec, "ThickChord")
                camber = _safe_get_xsec_parm_value(vsp, xsec, "Camber")
                camber_loc = _safe_get_xsec_parm_value(vsp, xsec, "CamberLoc")
                coordinates = _extract_airfoil_coordinates(vsp, xsec)
                try:
                    shape = int(vsp.GetXSecShape(xsec))
                except Exception:
                    shape = -1
                if coordinates:
                    airfoil_source = "inline_coordinates"
                elif shape == int(getattr(vsp, "XS_FOUR_SERIES", -1)):
                    airfoil_source = "naca"
                else:
                    airfoil_source = f"vsp_shape_{shape}"
                airfoil_name = None
                if shape == int(getattr(vsp, "XS_FOUR_SERIES", -1)) and thickness_tc is not None:
                    airfoil_name = _naca_four_series_name(camber or 0.0, camber_loc or 0.4, thickness_tc)
                section_records.append(
                    _NativeSectionRecord(
                        x_le=global_le[0],
                        y_le=global_le[1],
                        z_le=global_le[2],
                        chord=float(chord),
                        twist_deg=float(twist_deg),
                        airfoil_name=airfoil_name,
                        airfoil_source=airfoil_source,
                        airfoil_coordinates=coordinates,
                        thickness_tc=thickness_tc,
                        camber=camber,
                        camber_loc=camber_loc,
                    )
                )

            if len(section_records) < 2:
                notes.append(f"skip_{component_name}:insufficient_sections")
                continue
            surfaces.append(
                _NativeSurfaceRecord(
                    component=component_name,
                    geom_id=candidate.geom_id,
                    name=candidate.name,
                    caps_group=component_name,
                    symmetric_xz=bool(candidate.is_symmetric_xz and component_name != "vertical_tail"),
                    sections=tuple(section_records),
                    rotation_deg=geom_rotation,
                )
            )
        if not surfaces:
            raise RuntimeError("native ESP rebuild could not extract any loftable wing-like surfaces from the .vsp3")
        return _NativeRebuildModel(
            source_path=source_path,
            surfaces=tuple(surfaces),
            notes=tuple(notes),
        )
    finally:
        try:
            vsp.ClearVSPModel()
        except Exception:
            pass


def extract_native_lifting_surface_sections(
    *,
    source_path: Path,
    component: str = "main_wing",
    include_mirrored: bool = False,
) -> dict[str, Any]:
    rebuild_model = _build_native_rebuild_model(source_path=source_path, component=component)
    surfaces_payload: list[dict[str, Any]] = []
    for surface in rebuild_model.surfaces:
        section_records = (
            _surface_sections_for_rule(surface)
            if include_mirrored
            else list(surface.sections)
        )
        surfaces_payload.append(
            {
                "component": surface.component,
                "geom_id": surface.geom_id,
                "name": surface.name,
                "caps_group": surface.caps_group,
                "symmetric_xz": bool(surface.symmetric_xz),
                "rotation_deg": [float(value) for value in surface.rotation_deg],
                "sections": [
                    {
                        "x_le": float(section.x_le),
                        "y_le": float(section.y_le),
                        "z_le": float(section.z_le),
                        "chord": float(section.chord),
                        "twist_deg": float(section.twist_deg),
                        "airfoil_name": section.airfoil_name,
                        "airfoil_source": section.airfoil_source,
                        "thickness_tc": None if section.thickness_tc is None else float(section.thickness_tc),
                        "camber": None if section.camber is None else float(section.camber),
                        "camber_loc": None if section.camber_loc is None else float(section.camber_loc),
                        "airfoil_coordinates": [
                            [float(x_value), float(z_value)]
                            for x_value, z_value in _resolve_section_airfoil_coordinates(section)
                        ],
                    }
                    for section in section_records
                ],
            }
        )
    return {
        "source_path": str(source_path),
        "component": str(component),
        "include_mirrored": bool(include_mirrored),
        "surface_count": len(surfaces_payload),
        "notes": list(rebuild_model.notes),
        "surfaces": surfaces_payload,
    }


def _build_csm_script(
    source_path: Path,
    export_path: Path,
    *,
    component: str,
) -> str:
    rebuild_model = _build_native_rebuild_model(source_path=source_path, component=component)
    return _build_csm_script_from_rebuild_model(rebuild_model, export_path)


def _build_union_csm_script(source_path: Path, export_path: Path, body_count: int, *, component: str) -> str:
    rebuild_model = _build_native_rebuild_model(source_path=source_path, component=component)
    return _build_union_csm_script_from_rebuild_model(rebuild_model, export_path, body_count)


def _normalize_component_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _vsp_point_component(point: Any, axis: str) -> float:
    value = getattr(point, axis, None)
    if callable(value):
        return float(value())
    if value is None:
        raise AttributeError(f"point does not expose axis {axis}")
    return float(value)


def _safe_vsp_parm(vsp, geom_id: str, parm_names: list[str], group: str) -> float:
    for parm_name in parm_names:
        try:
            parm_id = vsp.FindParm(geom_id, parm_name, group)
        except Exception:
            parm_id = ""
        if not parm_id:
            continue
        try:
            return float(vsp.GetParmVal(parm_id))
        except Exception:
            continue
    return 0.0


def _is_symmetric_xz(vsp, geom_id: str) -> bool:
    try:
        parm_id = vsp.FindParm(geom_id, "Sym_Planar_Flag", "Sym")
    except Exception:
        parm_id = ""
    if not parm_id:
        return False
    try:
        flag = int(vsp.GetParmVal(parm_id))
    except Exception:
        return False
    return bool(flag & int(getattr(vsp, "SYM_XZ", 2)))


def _bbox_xyz(vsp, geom_id: str) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bbox_min = vsp.GetGeomBBoxMin(geom_id)
    bbox_max = vsp.GetGeomBBoxMax(geom_id)
    return (
        (
            _vsp_point_component(bbox_min, "x"),
            _vsp_point_component(bbox_min, "y"),
            _vsp_point_component(bbox_min, "z"),
        ),
        (
            _vsp_point_component(bbox_max, "x"),
            _vsp_point_component(bbox_max, "y"),
            _vsp_point_component(bbox_max, "z"),
        ),
    )


def _collect_vsp_wing_candidates(vsp) -> list[_VspWingCandidate]:
    candidates: list[_VspWingCandidate] = []
    for geom_id in vsp.FindGeoms():
        type_name = str(vsp.GetGeomTypeName(geom_id) or "")
        if type_name.lower() != "wing":
            continue
        name = str(vsp.GetGeomName(geom_id) or "")
        bbox_min, bbox_max = _bbox_xyz(vsp, geom_id)
        candidates.append(
            _VspWingCandidate(
                geom_id=str(geom_id),
                name=name,
                type_name=type_name,
                normalized_name=_normalize_component_name(name),
                is_symmetric_xz=_is_symmetric_xz(vsp, geom_id),
                x_location=_safe_vsp_parm(vsp, geom_id, ["X_Location", "X_Rel_Location"], "XForm"),
                x_rotation_deg=_safe_vsp_parm(vsp, geom_id, ["X_Rotation", "X_Rel_Rotation"], "XForm"),
                bbox_min=bbox_min,
                bbox_max=bbox_max,
            )
        )
    return candidates


def _component_alias(component: str) -> str:
    if component == "tail_wing":
        return "horizontal_tail"
    return component


def _candidate_priority(
    candidate: _VspWingCandidate,
    *,
    aliases: set[str],
    require_symmetric: bool | None = None,
    downstream_x: float | None = None,
) -> tuple[int, int, int, float, float, float]:
    alias_match = int(candidate.normalized_name in aliases)
    symmetric_match = (
        0
        if require_symmetric is None
        else int(candidate.is_symmetric_xz is require_symmetric)
    )
    downstream_match = 0
    if downstream_x is not None:
        downstream_match = int(candidate.x_location > downstream_x + 1.0e-6)
    vertical_orientation = int(
        abs(abs(candidate.x_rotation_deg) - 90.0) <= 15.0
        or candidate.span_z > max(candidate.span_y * 2.0, 1.0e-6)
    )
    return (
        alias_match,
        symmetric_match,
        downstream_match,
        candidate.span_y,
        vertical_orientation,
        candidate.span_z,
    )


def _select_component_candidate(
    component: str,
    candidates: list[_VspWingCandidate],
) -> _VspWingCandidate:
    effective_component = _component_alias(component)
    if effective_component == "aircraft_assembly":
        raise ValueError("assembly does not require component candidate selection")

    symmetric_candidates = [candidate for candidate in candidates if candidate.is_symmetric_xz]
    if effective_component == "main_wing":
        if not symmetric_candidates:
            raise ValueError("no symmetric OpenVSP wing candidates were available for main_wing")
        return max(
            symmetric_candidates,
            key=lambda candidate: (
                int(candidate.normalized_name in _MAIN_WING_ALIASES),
                candidate.span_y,
                -candidate.x_location,
                candidate.chord_x,
            ),
        )

    if effective_component == "horizontal_tail":
        main_wing = _select_component_candidate("main_wing", candidates)
        tail_candidates = [candidate for candidate in symmetric_candidates if candidate.geom_id != main_wing.geom_id]
        if not tail_candidates:
            raise ValueError("no symmetric OpenVSP wing candidates remained for horizontal_tail")
        return max(
            tail_candidates,
            key=lambda candidate: (
                int(candidate.normalized_name in _HORIZONTAL_TAIL_ALIASES),
                int(candidate.x_location > main_wing.x_location + 1.0e-6),
                candidate.span_y,
                candidate.x_location,
            ),
        )

    if effective_component == "vertical_tail":
        vertical_candidates = [candidate for candidate in candidates if not candidate.is_symmetric_xz]
        if not vertical_candidates:
            raise ValueError("no non-symmetric OpenVSP wing candidates were available for vertical_tail")
        return max(
            vertical_candidates,
            key=lambda candidate: (
                int(candidate.normalized_name in _VERTICAL_TAIL_ALIASES),
                int(abs(abs(candidate.x_rotation_deg) - 90.0) <= 15.0),
                int(candidate.span_z > max(candidate.span_y * 2.0, 1.0e-6)),
                candidate.span_z,
                candidate.x_location,
            ),
        )

    raise ValueError(f"component {component!r} is not selectable from a VSP wing subset")


def _collect_descendant_geom_ids(vsp, geom_id: str) -> list[str]:
    descendants: list[str] = []
    pending = [geom_id]
    seen = {geom_id}
    while pending:
        current = pending.pop()
        try:
            children = list(vsp.GetGeomChildren(current))
        except Exception:
            children = []
        for child_id in children:
            child_id = str(child_id)
            if child_id in seen:
                continue
            seen.add(child_id)
            descendants.append(child_id)
            pending.append(child_id)
    return descendants


def _cap_type_name(vsp, value: float) -> str:
    cap_value = int(round(float(value)))
    cap_names = {
        int(getattr(vsp, "NO_END_CAP", -1)): "NO_END_CAP",
        int(getattr(vsp, "FLAT_END_CAP", -2)): "FLAT_END_CAP",
        int(getattr(vsp, "ROUND_END_CAP", -3)): "ROUND_END_CAP",
        int(getattr(vsp, "EDGE_END_CAP", -4)): "EDGE_END_CAP",
        int(getattr(vsp, "SHARP_END_CAP", -5)): "SHARP_END_CAP",
        int(getattr(vsp, "POINT_END_CAP", -6)): "POINT_END_CAP",
        int(getattr(vsp, "ROUND_EXT_END_CAP_NONE", -7)): "ROUND_EXT_END_CAP_NONE",
        int(getattr(vsp, "ROUND_EXT_END_CAP_LE", -8)): "ROUND_EXT_END_CAP_LE",
        int(getattr(vsp, "ROUND_EXT_END_CAP_TE", -9)): "ROUND_EXT_END_CAP_TE",
        int(getattr(vsp, "ROUND_EXT_END_CAP_BOTH", -10)): "ROUND_EXT_END_CAP_BOTH",
    }
    return cap_names.get(cap_value, f"UNKNOWN_CAP_TYPE_{cap_value}")


def _safe_get_xsec_parm_value(vsp, xsec: Any, parm_name: str) -> Optional[float]:
    try:
        parm_id = vsp.GetXSecParm(xsec, parm_name)
    except Exception:
        return None
    if not parm_id:
        return None
    try:
        return float(vsp.GetParmVal(parm_id))
    except Exception:
        return None


def _collect_wing_section_report(vsp, geom_id: str) -> Dict[str, Any]:
    xsec_surf = vsp.GetXSecSurf(geom_id, 0)
    section_count = int(vsp.GetNumXSec(xsec_surf))
    sections: list[Dict[str, Any]] = []
    for index in range(section_count):
        xsec = vsp.GetXSec(xsec_surf, index)
        params: Dict[str, Any] = {}
        for parm_name in _WING_SECTION_PARAM_NAMES:
            value = _safe_get_xsec_parm_value(vsp, xsec, parm_name)
            if value is not None:
                params[parm_name] = value
        if "LE_Cap_Type" in params:
            params["LE_Cap_Type_Name"] = _cap_type_name(vsp, params["LE_Cap_Type"])
        if "TE_Cap_Type" in params:
            params["TE_Cap_Type_Name"] = _cap_type_name(vsp, params["TE_Cap_Type"])
        sections.append(
            {
                "index": index,
                "xsec_shape": int(vsp.GetXSecShape(xsec)),
                "params": params,
            }
        )
    return {
        "section_count": section_count,
        "sections": sections,
        "terminal_section": sections[-1] if sections else None,
    }


def _collect_wing_component_report(
    vsp,
    *,
    candidates: list[_VspWingCandidate],
    selected_geom_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "selected_geom_id": selected_geom_id,
        "candidate_count": len(candidates),
        "candidates": [
            {
                "geom_id": candidate.geom_id,
                "name": candidate.name,
                "type_name": candidate.type_name,
                "normalized_name": candidate.normalized_name,
                "is_symmetric_xz": candidate.is_symmetric_xz,
                "x_location": candidate.x_location,
                "x_rotation_deg": candidate.x_rotation_deg,
                "bbox_min": list(candidate.bbox_min),
                "bbox_max": list(candidate.bbox_max),
                "span_y": candidate.span_y,
                "span_z": candidate.span_z,
                "chord_x": candidate.chord_x,
                "section_report": _collect_wing_section_report(vsp, candidate.geom_id),
            }
            for candidate in candidates
        ],
    }


def _prepare_component_input_model(
    *,
    source_path: Path,
    artifact_dir: Path,
    component: str,
) -> _ComponentInputModel:
    effective_component = _component_alias(component)
    selection_report_path = (artifact_dir / "component_selection.json").resolve()
    wing_report_path = (artifact_dir / "wing_component_report.json").resolve()
    base_payload: Dict[str, Any] = {
        "requested_component": component,
        "effective_component": effective_component,
        "source_path": str(source_path),
    }
    if effective_component == "aircraft_assembly":
        payload = {
            **base_payload,
            "selection_mode": "full_assembly_source",
        }
        selection_report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return _ComponentInputModel(
            input_model_path=source_path,
            notes=["component_selection_mode=full_assembly_source"],
            provenance=payload,
            artifacts={"component_selection_report": selection_report_path},
        )

    if source_path.suffix.lower() != ".vsp3":
        raise RuntimeError(
            f"component subset export requires a .vsp3 source, got {source_path.suffix or '<none>'}"
        )

    vsp = _load_openvsp()
    wing_report: Optional[Dict[str, Any]] = None
    try:
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(source_path))
        vsp.Update()
        candidates = _collect_vsp_wing_candidates(vsp)
        selected = _select_component_candidate(effective_component, candidates)
        wing_report = _collect_wing_component_report(
            vsp,
            candidates=candidates,
            selected_geom_id=selected.geom_id,
        )
        selected_descendants = _collect_descendant_geom_ids(vsp, selected.geom_id)
        top_level_geom_ids = [str(geom_id) for geom_id in vsp.FindGeoms()]
        delete_ids = [geom_id for geom_id in top_level_geom_ids if geom_id != selected.geom_id]
        if delete_ids:
            try:
                vsp.DeleteGeomVec(delete_ids)
            except Exception:
                for geom_id in delete_ids:
                    vsp.DeleteGeom(geom_id)
        vsp.Update()
        subset_path = (artifact_dir / f"{effective_component}.vsp3").resolve()
        vsp.WriteVSPFile(str(subset_path), int(getattr(vsp, "SET_ALL", 0)))
    finally:
        try:
            vsp.ClearVSPModel()
        except Exception:
            pass

    payload = {
        **base_payload,
        "selection_mode": "openvsp_single_component_subset",
        "selected_geom": {
            "geom_id": selected.geom_id,
            "name": selected.name,
            "type_name": selected.type_name,
            "is_symmetric_xz": selected.is_symmetric_xz,
            "x_location": selected.x_location,
            "x_rotation_deg": selected.x_rotation_deg,
            "bbox_min": list(selected.bbox_min),
            "bbox_max": list(selected.bbox_max),
            "span_y": selected.span_y,
            "span_z": selected.span_z,
            "chord_x": selected.chord_x,
        },
        "selected_geom_ids": [selected.geom_id, *selected_descendants],
        "removed_top_level_geom_ids": delete_ids,
        "candidate_summary": [
            {
                "geom_id": candidate.geom_id,
                "name": candidate.name,
                "type_name": candidate.type_name,
                "is_symmetric_xz": candidate.is_symmetric_xz,
                "x_location": candidate.x_location,
                "x_rotation_deg": candidate.x_rotation_deg,
                "span_y": candidate.span_y,
                "span_z": candidate.span_z,
                "bbox_min": list(candidate.bbox_min),
                "bbox_max": list(candidate.bbox_max),
            }
            for candidate in candidates
        ],
        "subset_path": str(subset_path),
    }
    artifacts: Dict[str, Path] = {
        "component_selection_report": selection_report_path,
        "component_input_model": subset_path,
    }
    if wing_report is not None:
        wing_report_path.write_text(json.dumps(wing_report, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["wing_component_report"] = str(wing_report_path)
        artifacts["wing_component_report"] = wing_report_path
    selection_report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _ComponentInputModel(
        input_model_path=subset_path,
        notes=[f"component_subset_exported={effective_component}"],
        provenance=payload,
        artifacts=artifacts,
    )


def _bbox_close(lhs: tuple[float, ...], rhs: tuple[float, ...], tol: float) -> bool:
    return all(abs(float(a) - float(b)) <= tol for a, b in zip(lhs, rhs))


def _body_is_mirrored_across_plane(
    lhs: _BodyRecord,
    rhs: _BodyRecord,
    *,
    axis_index: int,
    plane_coordinate: float,
    tol: float,
) -> bool:
    lhs_bbox = lhs.bbox
    rhs_bbox = rhs.bbox
    lhs_min = lhs_bbox[axis_index]
    lhs_max = lhs_bbox[axis_index + 3]
    rhs_min = rhs_bbox[axis_index]
    rhs_max = rhs_bbox[axis_index + 3]
    lhs_dist = max(abs(lhs_min - plane_coordinate), abs(lhs_max - plane_coordinate))
    rhs_dist = max(abs(rhs_min - plane_coordinate), abs(rhs_max - plane_coordinate))
    if abs(lhs_dist - rhs_dist) > tol:
        return False

    if not (
        (abs(lhs_min - plane_coordinate) <= tol and abs(rhs_max - plane_coordinate) <= tol)
        or (abs(lhs_max - plane_coordinate) <= tol and abs(rhs_min - plane_coordinate) <= tol)
    ):
        return False

    for offset in (0, 1, 2):
        if offset == axis_index:
            continue
        if abs(lhs_bbox[offset] - rhs_bbox[offset]) > tol:
            return False
        if abs(lhs_bbox[offset + 3] - rhs_bbox[offset + 3]) > tol:
            return False

    lhs_com = lhs.center_of_mass[axis_index]
    rhs_com = rhs.center_of_mass[axis_index]
    if abs(((lhs_com + rhs_com) / 2.0) - plane_coordinate) > tol:
        return False

    return True


def _write_normalization_report(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _analyze_symmetry_touching_solids(step_path: Path) -> _SymmetryTouchingAnalysis:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError:
        return _SymmetryTouchingAnalysis(
            body_count=0,
            surface_count=0,
            volume_count=0,
            body_records=[],
            duplicate_face_pairs=[],
            touching_groups=[],
            singleton_body_tags=[],
            grouped_body_tags=[],
            internal_cap_face_tags=[],
            notes=["gmsh_python_api_not_available_for_symmetry_touching_analysis"],
        )

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"esp_symmetry_probe_{next(tempfile._get_candidate_names())}")
        imported_entities = gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        body_dim_tags = [entity for entity in imported_entities if entity[0] == 3]
        if not body_dim_tags:
            body_dim_tags = gmsh.model.getEntities(3)
        surface_count = len(gmsh.model.getEntities(2))
        if not body_dim_tags:
            return _SymmetryTouchingAnalysis(
                body_count=0,
                surface_count=surface_count,
                volume_count=0,
                body_records=[],
                duplicate_face_pairs=[],
                touching_groups=[],
                singleton_body_tags=[],
                grouped_body_tags=[],
                internal_cap_face_tags=[],
                notes=["step_import_contains_no_occ_volumes"],
            )

        model_bbox = [float("inf"), float("inf"), float("inf"), float("-inf"), float("-inf"), float("-inf")]
        body_records: dict[int, _BodyRecord] = {}
        planar_faces_by_body: dict[int, list[_InterfaceFaceRecord]] = defaultdict(list)
        for _, body_tag in body_dim_tags:
            bbox = tuple(float(value) for value in gmsh.model.getBoundingBox(3, body_tag))
            model_bbox[0] = min(model_bbox[0], bbox[0])
            model_bbox[1] = min(model_bbox[1], bbox[1])
            model_bbox[2] = min(model_bbox[2], bbox[2])
            model_bbox[3] = max(model_bbox[3], bbox[3])
            model_bbox[4] = max(model_bbox[4], bbox[4])
            model_bbox[5] = max(model_bbox[5], bbox[5])
            body_boundary = gmsh.model.getBoundary([(3, body_tag)], oriented=False, recursive=False)
            face_tags = [int(tag) for dim, tag in body_boundary if dim == 2]
            body_records[body_tag] = _BodyRecord(
                body_tag=body_tag,
                bbox=bbox,
                center_of_mass=tuple(float(value) for value in gmsh.model.occ.getCenterOfMass(3, body_tag)),
                face_count=len(face_tags),
            )
            for face_tag in face_tags:
                face_bbox = tuple(float(value) for value in gmsh.model.getBoundingBox(2, face_tag))
                spans = (
                    face_bbox[3] - face_bbox[0],
                    face_bbox[4] - face_bbox[1],
                    face_bbox[5] - face_bbox[2],
                )
                axis_index = min(range(3), key=spans.__getitem__)
                global_span = max(
                    model_bbox[3] - model_bbox[0],
                    model_bbox[4] - model_bbox[1],
                    model_bbox[5] - model_bbox[2],
                    1.0,
                )
                plane_tol = global_span * 1.0e-7
                if spans[axis_index] > plane_tol:
                    continue
                other_axes = [index for index in range(3) if index != axis_index]
                projected_bounds = (
                    face_bbox[other_axes[0]],
                    face_bbox[other_axes[0] + 3],
                    face_bbox[other_axes[1]],
                    face_bbox[other_axes[1] + 3],
                )
                planar_faces_by_body[body_tag].append(
                    _InterfaceFaceRecord(
                        body_tag=body_tag,
                        face_tag=face_tag,
                        axis="xyz"[axis_index],
                        plane_coordinate=0.5 * (face_bbox[axis_index] + face_bbox[axis_index + 3]),
                        area=float(gmsh.model.occ.getMass(2, face_tag)),
                        bbox=face_bbox,
                        projected_bounds=projected_bounds,
                        center_of_mass=tuple(
                            float(value) for value in gmsh.model.occ.getCenterOfMass(2, face_tag)
                        ),
                    )
                )

        global_span = max(
            model_bbox[3] - model_bbox[0],
            model_bbox[4] - model_bbox[1],
            model_bbox[5] - model_bbox[2],
            1.0,
        )
        plane_tol = global_span * 1.0e-7
        bbox_tol = global_span * 2.0e-6
        area_tol = max(global_span * global_span * 1.0e-8, 1.0e-12)

        duplicate_face_pairs: list[dict[str, Any]] = []
        group_evidence: list[dict[str, Any]] = []
        edge_map: dict[int, set[int]] = defaultdict(set)
        body_tags = sorted(body_records)
        for index, lhs_body in enumerate(body_tags):
            lhs_record = body_records[lhs_body]
            lhs_faces = planar_faces_by_body.get(lhs_body, [])
            if not lhs_faces:
                continue
            for rhs_body in body_tags[index + 1:]:
                rhs_record = body_records[rhs_body]
                rhs_faces = planar_faces_by_body.get(rhs_body, [])
                if not rhs_faces:
                    continue
                exact_pairs: list[dict[str, Any]] = []
                for lhs_face in lhs_faces:
                    for rhs_face in rhs_faces:
                        if lhs_face.axis != rhs_face.axis:
                            continue
                        if abs(lhs_face.plane_coordinate - rhs_face.plane_coordinate) > plane_tol:
                            continue
                        if not _bbox_close(lhs_face.projected_bounds, rhs_face.projected_bounds, bbox_tol):
                            continue
                        if abs(lhs_face.area - rhs_face.area) > max(area_tol, abs(lhs_face.area) * 1.0e-6):
                            continue
                        exact_pairs.append(
                            {
                                "body_tags": [lhs_body, rhs_body],
                                "face_tags": [lhs_face.face_tag, rhs_face.face_tag],
                                "axis": lhs_face.axis,
                                "plane_coordinate": lhs_face.plane_coordinate,
                                "area": lhs_face.area,
                                "projected_bounds": list(lhs_face.projected_bounds),
                                "bbox_lhs": list(lhs_face.bbox),
                                "bbox_rhs": list(rhs_face.bbox),
                            }
                        )
                if exact_pairs:
                    plane_coordinate = float(
                        sum(pair["plane_coordinate"] for pair in exact_pairs) / len(exact_pairs)
                    )
                    axis_index = "xyz".index(exact_pairs[0]["axis"])
                    if _body_is_mirrored_across_plane(
                        lhs_record,
                        rhs_record,
                        axis_index=axis_index,
                        plane_coordinate=plane_coordinate,
                        tol=bbox_tol,
                    ):
                        duplicate_face_pairs.extend(exact_pairs)
                        group_evidence.append(
                            {
                                "body_tags": [lhs_body, rhs_body],
                                "axis": exact_pairs[0]["axis"],
                                "plane_coordinate": plane_coordinate,
                                "match_kind": "exact_duplicate_faces",
                                "duplicate_face_pairs": len(exact_pairs),
                                "interface_area": sum(pair["area"] for pair in exact_pairs),
                            }
                        )
                        edge_map[lhs_body].add(rhs_body)
                        edge_map[rhs_body].add(lhs_body)
                        continue

                for axis in "xyz":
                    lhs_axis_faces = [face for face in lhs_faces if face.axis == axis]
                    rhs_axis_faces = [face for face in rhs_faces if face.axis == axis]
                    if not lhs_axis_faces or not rhs_axis_faces:
                        continue

                    def _cluster_by_plane_coordinate(
                        faces: list[_InterfaceFaceRecord],
                    ) -> list[list[_InterfaceFaceRecord]]:
                        clusters: list[list[_InterfaceFaceRecord]] = []
                        for face in sorted(faces, key=lambda item: item.plane_coordinate):
                            if not clusters:
                                clusters.append([face])
                                continue
                            cluster_coord = sum(
                                member.plane_coordinate for member in clusters[-1]
                            ) / len(clusters[-1])
                            if abs(face.plane_coordinate - cluster_coord) <= plane_tol:
                                clusters[-1].append(face)
                            else:
                                clusters.append([face])
                        return clusters

                    lhs_clusters = _cluster_by_plane_coordinate(lhs_axis_faces)
                    rhs_clusters = _cluster_by_plane_coordinate(rhs_axis_faces)
                    matched_cluster = False
                    for lhs_cluster in lhs_clusters:
                        lhs_coord = sum(face.plane_coordinate for face in lhs_cluster) / len(lhs_cluster)
                        lhs_projected = (
                            min(face.projected_bounds[0] for face in lhs_cluster),
                            max(face.projected_bounds[1] for face in lhs_cluster),
                            min(face.projected_bounds[2] for face in lhs_cluster),
                            max(face.projected_bounds[3] for face in lhs_cluster),
                        )
                        lhs_area = sum(face.area for face in lhs_cluster)
                        for rhs_cluster in rhs_clusters:
                            rhs_coord = sum(face.plane_coordinate for face in rhs_cluster) / len(rhs_cluster)
                            if abs(lhs_coord - rhs_coord) > plane_tol:
                                continue
                            rhs_projected = (
                                min(face.projected_bounds[0] for face in rhs_cluster),
                                max(face.projected_bounds[1] for face in rhs_cluster),
                                min(face.projected_bounds[2] for face in rhs_cluster),
                                max(face.projected_bounds[3] for face in rhs_cluster),
                            )
                            if not _bbox_close(lhs_projected, rhs_projected, bbox_tol):
                                continue
                            rhs_area = sum(face.area for face in rhs_cluster)
                            if abs(lhs_area - rhs_area) > max(area_tol, max(lhs_area, rhs_area) * 1.0e-6):
                                continue
                            axis_index = "xyz".index(axis)
                            plane_coordinate = 0.5 * (lhs_coord + rhs_coord)
                            if not _body_is_mirrored_across_plane(
                                lhs_record,
                                rhs_record,
                                axis_index=axis_index,
                                plane_coordinate=plane_coordinate,
                                tol=bbox_tol,
                            ):
                                continue
                            group_evidence.append(
                                {
                                    "body_tags": [lhs_body, rhs_body],
                                    "axis": axis,
                                    "plane_coordinate": plane_coordinate,
                                    "match_kind": "aggregate_planar_interface",
                                    "duplicate_face_pairs": 0,
                                    "interface_area": min(lhs_area, rhs_area),
                                    "lhs_face_tags": [face.face_tag for face in lhs_cluster],
                                    "rhs_face_tags": [face.face_tag for face in rhs_cluster],
                                }
                            )
                            edge_map[lhs_body].add(rhs_body)
                            edge_map[rhs_body].add(lhs_body)
                            matched_cluster = True
                            break
                        if matched_cluster:
                            break
                    if matched_cluster:
                        break

        visited: set[int] = set()
        touching_groups: list[dict[str, Any]] = []
        grouped_body_tags: list[int] = []
        for body_tag in body_tags:
            if body_tag in visited or not edge_map.get(body_tag):
                continue
            component: list[int] = []
            stack = [body_tag]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                stack.extend(sorted(edge_map.get(current, set()) - visited))
            component.sort()
            grouped_body_tags.extend(component)
            evidence = [
                item
                for item in group_evidence
                if set(item["body_tags"]).issubset(component)
            ]
            planes = [
                {
                    "axis": item["axis"],
                    "plane_coordinate": item["plane_coordinate"],
                    "match_kind": item["match_kind"],
                    "interface_area": item["interface_area"],
                    "duplicate_face_pairs": item["duplicate_face_pairs"],
                }
                for item in evidence
            ]
            touching_groups.append(
                {
                    "body_tags": component,
                    "plane_count": len(planes),
                    "planes": planes,
                }
            )

        grouped_body_tag_set = set(grouped_body_tags)
        singleton_body_tags = [tag for tag in body_tags if tag not in grouped_body_tag_set]
        internal_cap_face_tags = sorted(
            {
                face_tag
                for pair in duplicate_face_pairs
                for face_tag in pair["face_tags"]
            }
        )

        return _SymmetryTouchingAnalysis(
            body_count=len(body_dim_tags),
            surface_count=surface_count,
            volume_count=len(body_dim_tags),
            body_records=[body_records[tag] for tag in body_tags],
            duplicate_face_pairs=duplicate_face_pairs,
            touching_groups=touching_groups,
            singleton_body_tags=singleton_body_tags,
            grouped_body_tags=sorted(grouped_body_tag_set),
            internal_cap_face_tags=internal_cap_face_tags,
            notes=[],
        )
    except Exception as exc:
        return _SymmetryTouchingAnalysis(
            body_count=0,
            surface_count=0,
            volume_count=0,
            body_records=[],
            duplicate_face_pairs=[],
            touching_groups=[],
            singleton_body_tags=[],
            grouped_body_tags=[],
            internal_cap_face_tags=[],
            notes=[f"symmetry_touching_analysis_error={exc}"],
        )
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _apply_import_scale_if_needed(gmsh, entities: list[tuple[int, int]], import_scale: float | None) -> None:
    if import_scale is None:
        return
    if abs(float(import_scale) - 1.0) <= _IMPORT_SCALE_IDENTITY_TOL:
        return
    gmsh.model.occ.dilate(
        entities,
        0.0,
        0.0,
        0.0,
        float(import_scale),
        float(import_scale),
        float(import_scale),
    )
    gmsh.model.occ.synchronize()


def _combine_union_groups_with_singletons(
    *,
    raw_step_path: Path,
    raw_topology: GeometryTopologyMetadata,
    singleton_body_tags: list[int],
    union_step_path: Path,
    union_topology: GeometryTopologyMetadata,
    output_path: Path,
) -> None:
    gmsh = load_gmsh()
    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"esp_normalize_{next(tempfile._get_candidate_names())}")
        raw_entities = gmsh.model.occ.importShapes(str(raw_step_path))
        gmsh.model.occ.synchronize()
        _apply_import_scale_if_needed(gmsh, raw_entities, raw_topology.import_scale_to_units)
        raw_volume_tags = [tag for dim, tag in gmsh.model.getEntities(3) if dim == 3]
        remove_entities = [(3, tag) for tag in raw_volume_tags if tag not in set(singleton_body_tags)]
        if remove_entities:
            gmsh.model.occ.remove(remove_entities, recursive=True)
            gmsh.model.occ.synchronize()
        union_entities = gmsh.model.occ.importShapes(str(union_step_path))
        gmsh.model.occ.synchronize()
        _apply_import_scale_if_needed(gmsh, union_entities, union_topology.import_scale_to_units)
        gmsh.write(str(output_path))
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _prepare_runtime_dirs(staging_dir: Path) -> tuple[Path, Path]:
    artifact_dir = (staging_dir / "esp_runtime").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = Path(
        tempfile.mkdtemp(prefix="hpa_esp_runtime_", dir="/tmp")
    ).resolve()
    work_dir = scratch_root / "runtime"
    work_dir.symlink_to(artifact_dir, target_is_directory=True)
    return artifact_dir, work_dir


def _stage_source_model(
    source_path: Path,
    artifact_dir: Path,
    work_dir: Path,
) -> tuple[Path, Path]:
    resolved_source = source_path.resolve()
    artifact_source = (artifact_dir / resolved_source.name).resolve()
    if artifact_source != resolved_source:
        shutil.copy2(resolved_source, artifact_source)
    work_source = work_dir / artifact_source.name
    return artifact_source, work_source


def _write_topology_report(
    *,
    report_path: Path,
    export_path: Path,
    source_path: Path,
    input_model_path: Path,
    batch_binary: str,
    runtime_exec_dir: Path,
    stdout: str,
    stderr: str,
    extra_notes: Optional[List[str]] = None,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> GeometryTopologyMetadata:
    topology = _probe_step_topology(export_path, report_path.parent)
    for note in extra_notes or []:
        if note not in topology.notes:
            topology.notes.append(note)
    payload: Dict[str, Any] = topology.model_dump(mode="json")
    payload.update(
        {
        "source_path": str(source_path),
        "input_model_path": str(input_model_path),
        "export_path": str(export_path),
        "export_exists": export_path.exists(),
        "export_size_bytes": export_path.stat().st_size if export_path.exists() else None,
        "batch_binary": batch_binary,
        "runtime_exec_dir": str(runtime_exec_dir),
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-2000:] if stderr else "",
        }
    )
    if extra_payload:
        payload.update(extra_payload)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return topology


def _rewrite_mislabeled_mm_step_to_meters_if_needed(
    *,
    export_path: Path,
    source_path: Path,
) -> List[str]:
    declared_units, bounds = _read_step_units_and_bounds(export_path)
    if declared_units != "mm" or bounds is None:
        return []

    reference_data = load_openvsp_reference_data(source_path)
    ref_length = None if reference_data is None else reference_data.get("ref_length")
    if not isinstance(ref_length, (int, float)) or float(ref_length) <= 0.0:
        return []

    max_span = max(
        bounds.x_max - bounds.x_min,
        bounds.y_max - bounds.y_min,
        bounds.z_max - bounds.z_min,
    )
    if max_span <= 0.0:
        return []

    # For aircraft assemblies, meter-scale coordinates should stay O(1..100) times the
    # reference chord. If the STEP says "mm" but the coordinates are still in this
    # range, ESP likely mislabeled the units rather than scaling the geometry.
    if (max_span / float(ref_length)) >= _STEP_COORDS_LOOK_LIKE_METERS_MAX_REF_RATIO:
        return []

    original_text = export_path.read_text(encoding="utf-8", errors="ignore")
    rewritten_text, replacements = _STEP_MILLI_UNIT_PATTERN.subn(
        "SI_UNIT(.UNSET.,.METRE.)",
        original_text,
    )
    if replacements == 0:
        return []

    export_path.write_text(rewritten_text, encoding="utf-8")
    return [
        "rewrote_step_length_units:mm_to_m_based_on_reference_length"
        f":ref_length={float(ref_length):.12g}:max_span={max_span:.12g}"
    ]


def _write_command_log(
    *,
    log_path: Path,
    args: List[str],
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    log_path.write_text(
        "\n".join(
            [
                "command: " + " ".join(args),
                f"returncode: {returncode}",
                "--- stdout ---",
                stdout,
                "--- stderr ---",
                stderr,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_ocsm_batch(
    *,
    runner: Runner,
    batch_binary: str,
    work_dir: Path,
    script_path: Path,
    command_log_path: Path,
) -> subprocess.CompletedProcess:
    args = [batch_binary, "-batch", str(script_path)]
    completed = runner(args, work_dir)
    _write_command_log(
        log_path=command_log_path,
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    return completed


def _materialize_prebuilt_rebuild_model(
    *,
    source_path: Path,
    artifact_source_path: Path,
    component_input: _ComponentInputModel,
    rebuild_model: _NativeRebuildModel,
    topology_lineage_report: Dict[str, Any],
    topology_suppression_report: Dict[str, Any],
    artifact_dir: Path,
    work_dir: Path,
    runner: Optional[Runner] = None,
    batch_binary: Optional[str] = None,
) -> EspMaterializationResult:
    script_path = (artifact_dir / OCSM_SCRIPT_NAME).resolve()
    union_script_path = (artifact_dir / UNION_SCRIPT_NAME).resolve()
    raw_export_path = (artifact_dir / RAW_EXPORT_FILE_NAME).resolve()
    export_path = (artifact_dir / EXPORT_FILE_NAME).resolve()
    union_export_path = (artifact_dir / UNION_EXPORT_FILE_NAME).resolve()
    command_log_path = (artifact_dir / COMMAND_LOG_NAME).resolve()
    union_command_log_path = (artifact_dir / UNION_COMMAND_LOG_NAME).resolve()
    topology_report_path = (artifact_dir / TOPOLOGY_REPORT_NAME).resolve()
    topology_lineage_report_path = (artifact_dir / TOPOLOGY_LINEAGE_REPORT_NAME).resolve()
    topology_suppression_report_path = (artifact_dir / TOPOLOGY_SUPPRESSION_REPORT_NAME).resolve()
    raw_topology_report_path = (artifact_dir / RAW_TOPOLOGY_REPORT_NAME).resolve()
    normalization_report_path = (artifact_dir / NORMALIZATION_REPORT_NAME).resolve()
    work_script_path = work_dir / OCSM_SCRIPT_NAME
    work_union_script_path = work_dir / UNION_SCRIPT_NAME
    work_raw_export_path = work_dir / RAW_EXPORT_FILE_NAME
    work_export_path = work_dir / EXPORT_FILE_NAME
    work_union_export_path = work_dir / UNION_EXPORT_FILE_NAME

    topology_lineage_report_path.write_text(
        json.dumps(topology_lineage_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    topology_suppression_report_path.write_text(
        json.dumps(topology_suppression_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    script_path.write_text(
        _build_csm_script_from_rebuild_model(
            rebuild_model,
            work_raw_export_path,
        ),
        encoding="utf-8",
    )

    resolved_runner = runner or _default_runner
    resolved_binary = batch_binary or _resolve_batch_binary()
    if resolved_binary is None:
        reason = "Neither serveCSM nor ocsm was resolvable on PATH."
        _write_command_log(
            log_path=command_log_path,
            args=[],
            returncode=-1,
            stdout="",
            stderr=reason,
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_batch_binary_missing",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                **component_input.artifacts,
            },
        )

    completed = _run_ocsm_batch(
        runner=resolved_runner,
        batch_binary=resolved_binary,
        work_dir=work_dir,
        script_path=work_script_path,
        command_log_path=command_log_path,
    )

    if completed.returncode != 0:
        reason = (
            f"OpenCSM batch exited with status {completed.returncode}. "
            "Inspect the command log for serveCSM/ocsm diagnostics."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_ocsm_batch_failed",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                "command_log": command_log_path,
                **component_input.artifacts,
            },
        )

    if not raw_export_path.exists():
        reason = (
            "OpenCSM batch returned success but did not emit the expected normalized "
            f"STEP export at {raw_export_path}."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_export_missing",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                "command_log": command_log_path,
                **component_input.artifacts,
            },
        )

    raw_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
        export_path=raw_export_path,
        source_path=source_path,
    )
    raw_topology = _write_topology_report(
        report_path=raw_topology_report_path,
        export_path=raw_export_path,
        source_path=source_path,
        input_model_path=component_input.input_model_path,
        batch_binary=resolved_binary,
        runtime_exec_dir=work_dir,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        extra_notes=[*component_input.notes, *raw_unit_notes],
    )
    raw_analysis = _analyze_symmetry_touching_solids(raw_export_path)

    normalization_payload: Dict[str, Any] = {
        "strategy": "ocsm_union_touching_groups_plus_occ_singletons",
        "applied": False,
        "raw_counts": {
            "body_count": raw_topology.body_count,
            "surface_count": raw_topology.surface_count,
            "volume_count": raw_topology.volume_count,
        },
        "raw_analysis": {
            "touching_groups": raw_analysis.touching_groups,
            "singleton_body_tags": raw_analysis.singleton_body_tags,
            "grouped_body_tags": raw_analysis.grouped_body_tags,
            "duplicate_interface_face_pair_count": len(raw_analysis.duplicate_face_pairs),
            "duplicate_interface_face_pairs": raw_analysis.duplicate_face_pairs,
            "internal_cap_face_count": len(raw_analysis.internal_cap_face_tags),
            "internal_cap_face_tags": raw_analysis.internal_cap_face_tags,
            "body_records": [
                {
                    "body_tag": record.body_tag,
                    "bbox": list(record.bbox),
                    "center_of_mass": list(record.center_of_mass),
                    "face_count": record.face_count,
                }
                for record in raw_analysis.body_records
            ],
            "notes": raw_analysis.notes,
        },
        "actions": [],
    }

    final_notes = list(raw_unit_notes)
    final_warnings: list[str] = []
    final_stdout = completed.stdout or ""
    final_stderr = completed.stderr or ""
    output_artifacts: Dict[str, Path] = {
        "esp_script": script_path,
        "esp_input_model": component_input.input_model_path,
        "source_model": artifact_source_path,
        "topology_lineage_report": topology_lineage_report_path,
        "topology_suppression_report": topology_suppression_report_path,
        "command_log": command_log_path,
        "raw_geometry": raw_export_path,
        "raw_topology_report": raw_topology_report_path,
        "normalization_report": normalization_report_path,
        **component_input.artifacts,
    }

    if raw_analysis.touching_groups:
        union_script_path.write_text(
            _build_union_csm_script_from_rebuild_model(
                rebuild_model,
                export_path=work_union_export_path,
                body_count=max(raw_analysis.body_count, 1),
            ),
            encoding="utf-8",
        )
        union_completed = _run_ocsm_batch(
            runner=resolved_runner,
            batch_binary=resolved_binary,
            work_dir=work_dir,
            script_path=work_union_script_path,
            command_log_path=union_command_log_path,
        )
        output_artifacts.update(
            {
                "union_geometry": union_export_path,
                "union_command_log": union_command_log_path,
                "union_script": union_script_path,
            }
        )
        if union_completed.returncode != 0:
            reason = (
                f"OpenCSM union normalization batch exited with status {union_completed.returncode}. "
                "Inspect the union command log for diagnostics."
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_batch_failed",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": normalization_payload,
                },
                artifacts=output_artifacts,
            )
        if not union_export_path.exists():
            reason = (
                "OpenCSM union normalization batch returned success but did not emit "
                f"the expected STEP export at {union_export_path}."
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_export_missing",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": normalization_payload,
                },
                artifacts=output_artifacts,
            )

        union_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
            export_path=union_export_path,
            source_path=source_path,
        )
        union_topology = _probe_step_topology(union_export_path, artifact_dir)
        expected_group_count = len(raw_analysis.touching_groups)
        union_validation_errors: list[str] = []
        if union_topology.body_count != expected_group_count:
            union_validation_errors.append(
                "union_volume_count_mismatch:"
                f"expected={expected_group_count},actual={union_topology.body_count}"
            )

        expected_group_bounds: list[tuple[float, float, float, float, float, float]] = []
        raw_body_lookup = {record.body_tag: record for record in raw_analysis.body_records}
        for group in raw_analysis.touching_groups:
            group_boxes = [raw_body_lookup[tag].bbox for tag in group["body_tags"] if tag in raw_body_lookup]
            if not group_boxes:
                continue
            expected_group_bounds.append(
                (
                    min(box[0] for box in group_boxes),
                    min(box[1] for box in group_boxes),
                    min(box[2] for box in group_boxes),
                    max(box[3] for box in group_boxes),
                    max(box[4] for box in group_boxes),
                    max(box[5] for box in group_boxes),
                )
            )

        union_analysis = _analyze_symmetry_touching_solids(union_export_path)
        union_body_records = union_analysis.body_records
        bbox_tol = max(
            max(
                raw_topology.bounds.x_max - raw_topology.bounds.x_min if raw_topology.bounds else 0.0,
                raw_topology.bounds.y_max - raw_topology.bounds.y_min if raw_topology.bounds else 0.0,
                raw_topology.bounds.z_max - raw_topology.bounds.z_min if raw_topology.bounds else 0.0,
                1.0,
            )
            * 2.0e-6,
            1.0e-9,
        )
        remaining_union_bounds = [record.bbox for record in union_body_records]
        for expected_bounds in expected_group_bounds:
            matched_index = None
            for candidate_index, candidate_bounds in enumerate(remaining_union_bounds):
                if _bbox_close(expected_bounds, candidate_bounds, bbox_tol):
                    matched_index = candidate_index
                    break
            if matched_index is None:
                union_validation_errors.append(
                    "union_bbox_mismatch:"
                    f"expected={list(expected_bounds)}"
                )
            else:
                remaining_union_bounds.pop(matched_index)

        if union_validation_errors:
            reason = (
                "OpenCSM union normalization did not preserve the expected wetted-envelope "
                "groups cleanly: " + "; ".join(union_validation_errors)
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_validation_failed",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": {
                        **normalization_payload,
                        "union_topology": union_topology.model_dump(mode="json"),
                        "union_analysis": {
                            "touching_groups": union_analysis.touching_groups,
                            "duplicate_interface_face_pair_count": len(union_analysis.duplicate_face_pairs),
                            "internal_cap_face_count": len(union_analysis.internal_cap_face_tags),
                        },
                        "errors": union_validation_errors,
                    }
                },
                artifacts=output_artifacts,
            )

        if raw_analysis.singleton_body_tags:
            _combine_union_groups_with_singletons(
                raw_step_path=raw_export_path,
                raw_topology=raw_topology,
                singleton_body_tags=raw_analysis.singleton_body_tags,
                union_step_path=union_export_path,
                union_topology=union_topology,
                output_path=export_path,
            )
            normalization_payload["actions"].append("combine_union_groups_with_rescaled_singletons")
            final_notes.append("combined_union_groups_with_rescaled_singletons")
        else:
            shutil.copy2(union_export_path, export_path)
            normalization_payload["actions"].append("promote_union_groups_as_final_geometry")
            final_notes.append("promoted_union_groups_as_final_geometry")

        final_notes.extend(union_unit_notes)
        final_stdout = "\n".join(
            text for text in (completed.stdout or "", union_completed.stdout or "") if text
        )
        final_stderr = "\n".join(
            text for text in (completed.stderr or "", union_completed.stderr or "") if text
        )
        normalization_payload["applied"] = True
        normalization_payload["union_topology"] = union_topology.model_dump(mode="json")
        normalization_payload["union_analysis"] = {
            "touching_groups": union_analysis.touching_groups,
            "singleton_body_tags": union_analysis.singleton_body_tags,
            "grouped_body_tags": union_analysis.grouped_body_tags,
            "duplicate_interface_face_pair_count": len(union_analysis.duplicate_face_pairs),
            "internal_cap_face_count": len(union_analysis.internal_cap_face_tags),
            "notes": union_analysis.notes,
        }
    else:
        shutil.copy2(raw_export_path, export_path)
        normalization_payload["actions"].append("raw_export_already_cfd_clean_enough")
        final_notes.append("normalization_pass_not_needed")

    final_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
        export_path=export_path,
        source_path=source_path,
    )
    final_notes.extend(final_unit_notes)
    final_analysis = _analyze_symmetry_touching_solids(export_path)
    normalization_payload["final_analysis"] = {
        "touching_groups": final_analysis.touching_groups,
        "singleton_body_tags": final_analysis.singleton_body_tags,
        "grouped_body_tags": final_analysis.grouped_body_tags,
        "duplicate_interface_face_pair_count": len(final_analysis.duplicate_face_pairs),
        "internal_cap_face_count": len(final_analysis.internal_cap_face_tags),
        "notes": final_analysis.notes,
    }
    if final_analysis.touching_groups or final_analysis.duplicate_face_pairs:
        reason = (
            "Final normalized geometry still contains symmetry-generated touching solids or "
            "duplicate interface faces that would pollute CFD meshing."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=export_path if export_path.exists() else None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_normalized_geometry_not_cfd_clean",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={
                "component_selection": component_input.provenance,
                "normalization": normalization_payload,
            },
            artifacts=output_artifacts,
        )

    topology = _write_topology_report(
        report_path=topology_report_path,
        export_path=export_path,
        source_path=source_path,
        input_model_path=component_input.input_model_path,
        batch_binary=resolved_binary,
        runtime_exec_dir=work_dir,
        stdout=final_stdout,
        stderr=final_stderr,
        extra_notes=[*component_input.notes, *final_notes, *raw_analysis.notes, *final_analysis.notes],
        extra_payload={
            "component_selection": component_input.provenance,
            "normalization": normalization_payload,
            "topology_lineage_report": {
                "artifact": str(topology_lineage_report_path),
                "suppression_candidate_count": topology_lineage_report.get("suppression_candidate_count", 0),
            },
            "topology_suppression_report": {
                "artifact": str(topology_suppression_report_path),
                "applied": topology_suppression_report.get("applied", False),
                "suppressed_source_section_count": topology_suppression_report.get(
                    "suppressed_source_section_count", 0
                ),
            },
        },
    )
    topology.normalization = {
        **normalization_payload,
        "normalized_counts": {
            "body_count": topology.body_count,
            "surface_count": topology.surface_count,
            "volume_count": topology.volume_count,
        },
    }
    normalization_payload["normalized_counts"] = topology.normalization["normalized_counts"]
    _write_normalization_report(normalization_report_path, normalization_payload)

    provider_version = None
    if completed.stdout:
        first_line = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        if first_line:
            provider_version = first_line[:120]

    return EspMaterializationResult(
        status="success",
        normalized_geometry_path=export_path,
        topology_report_path=topology_report_path,
        notes=[
            *final_notes,
            f"OpenCSM batch succeeded via {Path(resolved_binary).name}.",
        ],
        warnings=final_warnings,
        failure_code=None,
        provider_version=provider_version,
        command_log_path=command_log_path,
        script_path=script_path,
        input_model_path=component_input.input_model_path,
        topology=topology,
        provenance={
            "component_selection": component_input.provenance,
            "normalization": normalization_payload,
        },
        artifacts=output_artifacts,
    )


def materialize_with_esp(
    *,
    source_path: Path,
    staging_dir: Path,
    component: str = "aircraft_assembly",
    runner: Optional[Runner] = None,
    batch_binary: Optional[str] = None,
    prebuilt_component_input: Optional[_ComponentInputModel] = None,
    prebuilt_rebuild_model: Optional[_NativeRebuildModel] = None,
    skip_terminal_strip_suppression: bool = False,
) -> EspMaterializationResult:
    artifact_dir, work_dir = _prepare_runtime_dirs(staging_dir)

    source_path = source_path.resolve()
    artifact_source_path, work_source_path = _stage_source_model(
        source_path,
        artifact_dir,
        work_dir,
    )
    try:
        component_input = prebuilt_component_input or _prepare_component_input_model(
            source_path=artifact_source_path,
            artifact_dir=artifact_dir,
            component=component,
        )
    except Exception as exc:
        reason = f"ESP component selection failed for {component}: {exc}"
        command_log_path = (artifact_dir / COMMAND_LOG_NAME).resolve()
        script_path = (artifact_dir / OCSM_SCRIPT_NAME).resolve()
        selection_artifacts: Dict[str, Path] = {
            "esp_input_model": artifact_source_path,
        }
        selection_report_path = (artifact_dir / "component_selection.json").resolve()
        if selection_report_path.exists():
            selection_artifacts["component_selection_report"] = selection_report_path
        _write_command_log(
            log_path=command_log_path,
            args=[],
            returncode=-1,
            stdout="",
            stderr=reason,
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_component_selection_failed",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=artifact_source_path,
            provenance={"component_selection": {"requested_component": component, "error": str(exc)}},
            artifacts=selection_artifacts,
        )
    work_input_model_path = work_dir / component_input.input_model_path.name
    script_path = (artifact_dir / OCSM_SCRIPT_NAME).resolve()
    union_script_path = (artifact_dir / UNION_SCRIPT_NAME).resolve()
    raw_export_path = (artifact_dir / RAW_EXPORT_FILE_NAME).resolve()
    export_path = (artifact_dir / EXPORT_FILE_NAME).resolve()
    union_export_path = (artifact_dir / UNION_EXPORT_FILE_NAME).resolve()
    command_log_path = (artifact_dir / COMMAND_LOG_NAME).resolve()
    union_command_log_path = (artifact_dir / UNION_COMMAND_LOG_NAME).resolve()
    topology_report_path = (artifact_dir / TOPOLOGY_REPORT_NAME).resolve()
    topology_lineage_report_path = (artifact_dir / TOPOLOGY_LINEAGE_REPORT_NAME).resolve()
    topology_suppression_report_path = (artifact_dir / TOPOLOGY_SUPPRESSION_REPORT_NAME).resolve()
    raw_topology_report_path = (artifact_dir / RAW_TOPOLOGY_REPORT_NAME).resolve()
    normalization_report_path = (artifact_dir / NORMALIZATION_REPORT_NAME).resolve()
    work_script_path = work_dir / OCSM_SCRIPT_NAME
    work_union_script_path = work_dir / UNION_SCRIPT_NAME
    work_raw_export_path = work_dir / RAW_EXPORT_FILE_NAME
    work_export_path = work_dir / EXPORT_FILE_NAME
    work_union_export_path = work_dir / UNION_EXPORT_FILE_NAME

    rebuild_model = prebuilt_rebuild_model or _build_native_rebuild_model(
        source_path=component_input.input_model_path,
        component=component,
    )
    topology_lineage_report = _build_topology_lineage_report(rebuild_model)
    topology_lineage_report_path.write_text(
        json.dumps(topology_lineage_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if skip_terminal_strip_suppression:
        suppressed_rebuild_model = rebuild_model
        topology_suppression_report = {
            "status": "captured",
            "applied": False,
            "source_path": str(rebuild_model.source_path),
            "surface_count": len(rebuild_model.surfaces),
            "suppressed_source_section_count": 0,
            "surfaces": [],
            "notes": [*list(rebuild_model.notes), "terminal_tip_strip_suppression_skipped_for_prebuilt_candidate"],
        }
    else:
        suppressed_rebuild_model, topology_suppression_report = _apply_terminal_strip_suppression(rebuild_model)
    topology_suppression_report_path.write_text(
        json.dumps(topology_suppression_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    script_path.write_text(
        _build_csm_script_from_rebuild_model(
            suppressed_rebuild_model,
            work_raw_export_path,
        ),
        encoding="utf-8",
    )

    resolved_runner = runner or _default_runner
    resolved_binary = batch_binary or _resolve_batch_binary()
    if resolved_binary is None:
        reason = "Neither serveCSM nor ocsm was resolvable on PATH."
        _write_command_log(
            log_path=command_log_path,
            args=[],
            returncode=-1,
            stdout="",
            stderr=reason,
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_batch_binary_missing",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                **component_input.artifacts,
            },
        )

    completed = _run_ocsm_batch(
        runner=resolved_runner,
        batch_binary=resolved_binary,
        work_dir=work_dir,
        script_path=work_script_path,
        command_log_path=command_log_path,
    )

    if completed.returncode != 0:
        reason = (
            f"OpenCSM batch exited with status {completed.returncode}. "
            "Inspect the command log for serveCSM/ocsm diagnostics."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_ocsm_batch_failed",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                "command_log": command_log_path,
                **component_input.artifacts,
            },
        )

    if not raw_export_path.exists():
        reason = (
            "OpenCSM batch returned success but did not emit the expected normalized "
            f"STEP export at {raw_export_path}."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_export_missing",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={"component_selection": component_input.provenance},
            artifacts={
                "esp_script": script_path,
                "esp_input_model": component_input.input_model_path,
                "source_model": artifact_source_path,
                "command_log": command_log_path,
                **component_input.artifacts,
            },
        )

    raw_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
        export_path=raw_export_path,
        source_path=source_path,
    )
    raw_topology = _write_topology_report(
        report_path=raw_topology_report_path,
        export_path=raw_export_path,
        source_path=source_path,
        input_model_path=component_input.input_model_path,
        batch_binary=resolved_binary,
        runtime_exec_dir=work_dir,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        extra_notes=[*component_input.notes, *raw_unit_notes],
    )
    raw_analysis = _analyze_symmetry_touching_solids(raw_export_path)

    normalization_payload: Dict[str, Any] = {
        "strategy": "ocsm_union_touching_groups_plus_occ_singletons",
        "applied": False,
        "raw_counts": {
            "body_count": raw_topology.body_count,
            "surface_count": raw_topology.surface_count,
            "volume_count": raw_topology.volume_count,
        },
        "raw_analysis": {
            "touching_groups": raw_analysis.touching_groups,
            "singleton_body_tags": raw_analysis.singleton_body_tags,
            "grouped_body_tags": raw_analysis.grouped_body_tags,
            "duplicate_interface_face_pair_count": len(raw_analysis.duplicate_face_pairs),
            "duplicate_interface_face_pairs": raw_analysis.duplicate_face_pairs,
            "internal_cap_face_count": len(raw_analysis.internal_cap_face_tags),
            "internal_cap_face_tags": raw_analysis.internal_cap_face_tags,
            "body_records": [
                {
                    "body_tag": record.body_tag,
                    "bbox": list(record.bbox),
                    "center_of_mass": list(record.center_of_mass),
                    "face_count": record.face_count,
                }
                for record in raw_analysis.body_records
            ],
            "notes": raw_analysis.notes,
        },
        "actions": [],
    }

    final_notes = list(raw_unit_notes)
    final_warnings: list[str] = []
    final_stdout = completed.stdout or ""
    final_stderr = completed.stderr or ""
    output_artifacts: Dict[str, Path] = {
        "esp_script": script_path,
        "esp_input_model": component_input.input_model_path,
        "source_model": artifact_source_path,
        "topology_lineage_report": topology_lineage_report_path,
        "topology_suppression_report": topology_suppression_report_path,
        "command_log": command_log_path,
        "raw_geometry": raw_export_path,
        "raw_topology_report": raw_topology_report_path,
        "normalization_report": normalization_report_path,
        **component_input.artifacts,
    }

    if raw_analysis.touching_groups:
        union_script_path.write_text(
            _build_union_csm_script_from_rebuild_model(
                suppressed_rebuild_model,
                export_path=work_union_export_path,
                body_count=max(raw_analysis.body_count, 1),
            ),
            encoding="utf-8",
        )
        union_completed = _run_ocsm_batch(
            runner=resolved_runner,
            batch_binary=resolved_binary,
            work_dir=work_dir,
            script_path=work_union_script_path,
            command_log_path=union_command_log_path,
        )
        output_artifacts.update(
            {
                "union_geometry": union_export_path,
                "union_command_log": union_command_log_path,
                "union_script": union_script_path,
            }
        )
        if union_completed.returncode != 0:
            reason = (
                f"OpenCSM union normalization batch exited with status {union_completed.returncode}. "
                "Inspect the union command log for diagnostics."
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_batch_failed",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": normalization_payload,
                },
                artifacts=output_artifacts,
            )
        if not union_export_path.exists():
            reason = (
                "OpenCSM union normalization batch returned success but did not emit "
                f"the expected STEP export at {union_export_path}."
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_export_missing",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": normalization_payload,
                },
                artifacts=output_artifacts,
            )

        union_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
            export_path=union_export_path,
            source_path=source_path,
        )
        union_topology = _probe_step_topology(union_export_path, artifact_dir)
        expected_group_count = len(raw_analysis.touching_groups)
        union_validation_errors: list[str] = []
        if union_topology.body_count != expected_group_count:
            union_validation_errors.append(
                "union_volume_count_mismatch:"
                f"expected={expected_group_count},actual={union_topology.body_count}"
            )

        expected_group_bounds: list[tuple[float, float, float, float, float, float]] = []
        raw_body_lookup = {record.body_tag: record for record in raw_analysis.body_records}
        for group in raw_analysis.touching_groups:
            group_boxes = [raw_body_lookup[tag].bbox for tag in group["body_tags"] if tag in raw_body_lookup]
            if not group_boxes:
                continue
            expected_group_bounds.append(
                (
                    min(box[0] for box in group_boxes),
                    min(box[1] for box in group_boxes),
                    min(box[2] for box in group_boxes),
                    max(box[3] for box in group_boxes),
                    max(box[4] for box in group_boxes),
                    max(box[5] for box in group_boxes),
                )
            )

        union_analysis = _analyze_symmetry_touching_solids(union_export_path)
        union_body_records = union_analysis.body_records
        bbox_tol = max(
            max(
                raw_topology.bounds.x_max - raw_topology.bounds.x_min if raw_topology.bounds else 0.0,
                raw_topology.bounds.y_max - raw_topology.bounds.y_min if raw_topology.bounds else 0.0,
                raw_topology.bounds.z_max - raw_topology.bounds.z_min if raw_topology.bounds else 0.0,
                1.0,
            )
            * 2.0e-6,
            1.0e-9,
        )
        remaining_union_bounds = [record.bbox for record in union_body_records]
        for expected_bounds in expected_group_bounds:
            matched_index = None
            for candidate_index, candidate_bounds in enumerate(remaining_union_bounds):
                if _bbox_close(expected_bounds, candidate_bounds, bbox_tol):
                    matched_index = candidate_index
                    break
            if matched_index is None:
                union_validation_errors.append(
                    "union_bbox_mismatch:"
                    f"expected={list(expected_bounds)}"
                )
            else:
                remaining_union_bounds.pop(matched_index)

        if union_validation_errors:
            reason = (
                "OpenCSM union normalization did not preserve the expected wetted-envelope "
                "groups cleanly: " + "; ".join(union_validation_errors)
            )
            return EspMaterializationResult(
                status="failed",
                normalized_geometry_path=None,
                topology_report_path=None,
                notes=[reason],
                warnings=[reason],
                failure_code="esp_union_validation_failed",
                command_log_path=union_command_log_path,
                script_path=union_script_path,
                input_model_path=component_input.input_model_path,
                provenance={
                    "component_selection": component_input.provenance,
                    "normalization": {
                        **normalization_payload,
                        "union_topology": union_topology.model_dump(mode="json"),
                        "union_analysis": {
                            "touching_groups": union_analysis.touching_groups,
                            "duplicate_interface_face_pair_count": len(union_analysis.duplicate_face_pairs),
                            "internal_cap_face_count": len(union_analysis.internal_cap_face_tags),
                        },
                        "errors": union_validation_errors,
                    }
                },
                artifacts=output_artifacts,
            )

        if raw_analysis.singleton_body_tags:
            _combine_union_groups_with_singletons(
                raw_step_path=raw_export_path,
                raw_topology=raw_topology,
                singleton_body_tags=raw_analysis.singleton_body_tags,
                union_step_path=union_export_path,
                union_topology=union_topology,
                output_path=export_path,
            )
            normalization_payload["actions"].append("combine_union_groups_with_rescaled_singletons")
            final_notes.append("combined_union_groups_with_rescaled_singletons")
        else:
            shutil.copy2(union_export_path, export_path)
            normalization_payload["actions"].append("promote_union_groups_as_final_geometry")
            final_notes.append("promoted_union_groups_as_final_geometry")

        final_notes.extend(union_unit_notes)
        final_stdout = "\n".join(
            text for text in (completed.stdout or "", union_completed.stdout or "") if text
        )
        final_stderr = "\n".join(
            text for text in (completed.stderr or "", union_completed.stderr or "") if text
        )
        normalization_payload["applied"] = True
        normalization_payload["union_topology"] = union_topology.model_dump(mode="json")
        normalization_payload["union_analysis"] = {
            "touching_groups": union_analysis.touching_groups,
            "singleton_body_tags": union_analysis.singleton_body_tags,
            "grouped_body_tags": union_analysis.grouped_body_tags,
            "duplicate_interface_face_pair_count": len(union_analysis.duplicate_face_pairs),
            "internal_cap_face_count": len(union_analysis.internal_cap_face_tags),
            "notes": union_analysis.notes,
        }
    else:
        shutil.copy2(raw_export_path, export_path)
        normalization_payload["actions"].append("raw_export_already_cfd_clean_enough")
        final_notes.append("normalization_pass_not_needed")

    final_unit_notes = _rewrite_mislabeled_mm_step_to_meters_if_needed(
        export_path=export_path,
        source_path=source_path,
    )
    final_notes.extend(final_unit_notes)
    final_analysis = _analyze_symmetry_touching_solids(export_path)
    normalization_payload["final_analysis"] = {
        "touching_groups": final_analysis.touching_groups,
        "singleton_body_tags": final_analysis.singleton_body_tags,
        "grouped_body_tags": final_analysis.grouped_body_tags,
        "duplicate_interface_face_pair_count": len(final_analysis.duplicate_face_pairs),
        "internal_cap_face_count": len(final_analysis.internal_cap_face_tags),
        "notes": final_analysis.notes,
    }
    if final_analysis.touching_groups or final_analysis.duplicate_face_pairs:
        reason = (
            "Final normalized geometry still contains symmetry-generated touching solids or "
            "duplicate interface faces that would pollute CFD meshing."
        )
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=export_path if export_path.exists() else None,
            topology_report_path=None,
            notes=[reason],
            warnings=[reason],
            failure_code="esp_normalized_geometry_not_cfd_clean",
            command_log_path=command_log_path,
            script_path=script_path,
            input_model_path=component_input.input_model_path,
            provenance={
                "component_selection": component_input.provenance,
                "normalization": normalization_payload,
            },
            artifacts=output_artifacts,
        )

    topology = _write_topology_report(
        report_path=topology_report_path,
        export_path=export_path,
        source_path=source_path,
        input_model_path=component_input.input_model_path,
        batch_binary=resolved_binary,
        runtime_exec_dir=work_dir,
        stdout=final_stdout,
        stderr=final_stderr,
        extra_notes=[*component_input.notes, *final_notes, *raw_analysis.notes, *final_analysis.notes],
        extra_payload={
            "component_selection": component_input.provenance,
            "normalization": normalization_payload,
            "topology_lineage_report": {
                "artifact": str(topology_lineage_report_path),
                "suppression_candidate_count": topology_lineage_report.get("suppression_candidate_count", 0),
            },
            "topology_suppression_report": {
                "artifact": str(topology_suppression_report_path),
                "applied": topology_suppression_report.get("applied", False),
                "suppressed_source_section_count": topology_suppression_report.get(
                    "suppressed_source_section_count", 0
                ),
            },
        },
    )
    topology.normalization = {
        **normalization_payload,
        "normalized_counts": {
            "body_count": topology.body_count,
            "surface_count": topology.surface_count,
            "volume_count": topology.volume_count,
        },
    }
    normalization_payload["normalized_counts"] = topology.normalization["normalized_counts"]
    _write_normalization_report(normalization_report_path, normalization_payload)

    provider_version = None
    if completed.stdout:
        first_line = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        if first_line:
            provider_version = first_line[:120]

    return EspMaterializationResult(
        status="success",
        normalized_geometry_path=export_path,
        topology_report_path=topology_report_path,
        notes=[
            *final_notes,
            f"OpenCSM batch succeeded via {Path(resolved_binary).name}.",
        ],
        warnings=final_warnings,
        failure_code=None,
        provider_version=provider_version,
        command_log_path=command_log_path,
        script_path=script_path,
        input_model_path=component_input.input_model_path,
        topology=topology,
        provenance={
            "component_selection": component_input.provenance,
            "normalization": normalization_payload,
        },
        artifacts=output_artifacts,
    )


def _json_load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_autonomous_repair_artifacts(
    *,
    workspace_root: Path,
    baseline_run_dir: Path | None = None,
    sliver_run_dir: Path | None = None,
) -> Dict[str, Path]:
    runs_root = workspace_root / ".tmp" / "runs"
    resolved_baseline_dir = baseline_run_dir
    if resolved_baseline_dir is None:
        matches = sorted(
            runs_root.glob(
                "codex_c1_main_wing_strip_suppression_*/main_wing_volume_smoke_shell_v2_strip_suppression"
            )
        )
        resolved_baseline_dir = matches[-1] if matches else None
    resolved_sliver_dir = sliver_run_dir
    if resolved_sliver_dir is None:
        matches = sorted(
            runs_root.glob("codex_c1_main_wing_sliver_volume_pocket_*")
        )
        resolved_sliver_dir = matches[-1] if matches else None

    artifacts: Dict[str, Path] = {}
    if resolved_baseline_dir is not None:
        baseline_mesh_dir = resolved_baseline_dir / "artifacts" / "mesh"
        baseline_provider_dir = (
            resolved_baseline_dir / "artifacts" / "providers" / "esp_rebuilt" / "esp_runtime"
        )
        artifacts.update(
            {
                "baseline_report": resolved_baseline_dir / "report.json",
                "mesh_metadata": baseline_mesh_dir / "mesh_metadata.json",
                "surface_patch_diagnostics": baseline_mesh_dir / "surface_patch_diagnostics.json",
                "surface_mesh_2d": baseline_mesh_dir / "surface_mesh_2d.msh",
                "hotspot_patch_report": baseline_mesh_dir / "hotspot_patch_report.json",
                "brep_hotspot_report": baseline_mesh_dir / "brep_hotspot_report.json",
                "mesh3d_watchdog": baseline_mesh_dir / "mesh3d_watchdog.json",
                "topology_lineage_report": baseline_provider_dir / "topology_lineage_report.json",
                "topology_suppression_report": baseline_provider_dir / "topology_suppression_report.json",
            }
        )
    if resolved_sliver_dir is not None:
        artifacts.update(
            {
                "sliver_cluster_report": resolved_sliver_dir / "sliver_cluster_report.json",
                "sliver_volume_pocket_summary": resolved_sliver_dir / "sliver_volume_pocket_summary.json",
                "rule_loft_pairing_repair_spec": resolved_sliver_dir / "rule_loft_pairing_repair_spec.json",
            }
        )
    return artifacts


def _build_autonomous_topology_base_config(
    *,
    source_path: Path,
    out_dir: Path,
    baseline_report: Dict[str, Any],
) -> MeshJobConfig:
    backend_result = dict((baseline_report.get("run") or {}).get("backend_result") or {})
    mesh_field = dict((backend_result.get("provenance") or {}).get("mesh_field") or {})
    coarse_profile = dict(mesh_field.get("coarse_first_tetra") or {})
    volume_smoke = dict(mesh_field.get("volume_smoke_decoupled") or {})
    near_body_shell = dict(volume_smoke.get("near_body_shell") or {})
    reference_geometry = load_openvsp_reference_data(source_path)
    metadata: Dict[str, Any] = {
        "coarse_first_tetra_enabled": bool(coarse_profile.get("enabled", False)),
        "coarse_first_tetra_surface_nodes_per_reference_length": coarse_profile.get(
            "surface_nodes_per_reference_length",
            mesh_field.get("surface_target_nodes_per_reference_length", 24.0),
        ),
        "coarse_first_tetra_edge_refinement_ratio": coarse_profile.get("edge_refinement_ratio", 1.0),
        "coarse_first_tetra_span_extreme_strip_floor_size": coarse_profile.get(
            "span_extreme_strip_floor_size", 0.12
        ),
        "coarse_first_tetra_suspect_strip_floor_size": coarse_profile.get(
            "suspect_strip_floor_size", 0.08
        ),
        "coarse_first_tetra_suspect_surface_algorithm": coarse_profile.get(
            "suspect_surface_algorithm", mesh_field.get("mesh_algorithm_2d", 6)
        ),
        "coarse_first_tetra_general_surface_algorithm": coarse_profile.get(
            "general_surface_algorithm", mesh_field.get("mesh_algorithm_2d", 6)
        ),
        "coarse_first_tetra_farfield_surface_algorithm": coarse_profile.get(
            "farfield_surface_algorithm", mesh_field.get("mesh_algorithm_2d", 6)
        ),
        "coarse_first_tetra_clamp_mesh_size_min_to_near_body": coarse_profile.get(
            "clamp_mesh_size_min_to_near_body", True
        ),
        "mesh_field_distance_max": mesh_field.get("distance_max"),
        "mesh_field_edge_distance_max": mesh_field.get("edge_distance_max"),
        "volume_smoke_decoupled_enabled": bool(volume_smoke.get("enabled", False)),
        "volume_smoke_base_size": (volume_smoke.get("base_far_volume_field") or {}).get("size", 12.0),
        "volume_smoke_shell_enabled": bool(near_body_shell.get("enabled", True)),
        "volume_smoke_shell_dist_min": near_body_shell.get("dist_min", 0.0),
        "volume_smoke_shell_dist_max": near_body_shell.get("dist_max", 0.18),
        "volume_smoke_shell_size_max": near_body_shell.get("size_max", 3.0),
        "volume_smoke_shell_stop_at_dist_max": near_body_shell.get("stop_at_dist_max", True),
    }
    if isinstance(reference_geometry, dict):
        metadata["reference_geometry"] = reference_geometry
    return MeshJobConfig(
        component=str(baseline_report.get("component") or "main_wing"),
        geometry=source_path,
        out_dir=out_dir,
        geometry_source=str(baseline_report.get("geometry_source") or "esp_rebuilt"),
        geometry_family=str(baseline_report.get("geometry_family") or "thin_sheet_lifting_surface"),
        geometry_provider=str(baseline_report.get("geometry_provider") or "esp_rebuilt"),
        mesh_algorithm_2d=int(mesh_field.get("mesh_algorithm_2d", 6) or 6),
        mesh_algorithm_3d=int(mesh_field.get("mesh_algorithm_3d", 1) or 1),
        metadata=metadata,
    )


def _build_provider_result_from_materialization(
    *,
    source_path: Path,
    component: str,
    pipeline_result: EspMaterializationResult,
) -> GeometryProviderResult:
    topology = pipeline_result.topology
    if topology is None:
        topology = GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind=(pipeline_result.normalized_geometry_path or source_path).suffix.lstrip(".") or "stp",
            units="m",
            notes=list(pipeline_result.notes),
        )
    return GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="materialized",
        geometry_source="esp_rebuilt",
        source_path=source_path,
        normalized_geometry_path=pipeline_result.normalized_geometry_path,
        geometry_family_hint="thin_sheet_lifting_surface" if component == "main_wing" else None,
        provider_version=pipeline_result.provider_version,
        topology=topology,
        artifacts={key: Path(value) for key, value in pipeline_result.artifacts.items()},
        provenance=dict(pipeline_result.provenance),
        warnings=list(pipeline_result.warnings),
        notes=list(pipeline_result.notes),
    )


def _build_geometry_handle_from_provider_result(
    *,
    source_path: Path,
    component: str,
    provider_result: GeometryProviderResult,
    metadata: Dict[str, Any],
) -> GeometryHandle:
    geometry_path = provider_result.normalized_geometry_path or source_path
    return GeometryHandle(
        source_path=source_path,
        path=geometry_path,
        exists=geometry_path.exists(),
        suffix=geometry_path.suffix.lower(),
        loader=f"provider:{provider_result.provider}",
        geometry_source=provider_result.geometry_source,
        declared_family=provider_result.geometry_family_hint,
        component=component,
        provider=provider_result.provider,
        provider_status=provider_result.status,
        provider_result=provider_result,
        metadata=metadata,
    )


def _execute_mesh_run(
    *,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    classification = classify_geometry_family(handle, config)
    validation = validate_component_geometry(handle, classification, config)
    if not validation.ok:
        return {
            "status": "failed",
            "classification": classification.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
            "backend_result": {},
            "mesh_metadata": {},
            "artifacts": {},
        }
    recipe = build_recipe(handle, classification, config)
    exec_result = run_with_fallback(recipe, handle, config)
    backend_result = dict(exec_result.get("backend_result") or {})
    artifacts = dict(backend_result.get("artifacts") or {})
    mesh_metadata = {}
    mesh_metadata_path = artifacts.get("mesh_metadata")
    if mesh_metadata_path is not None and Path(mesh_metadata_path).exists():
        mesh_metadata = _json_load(Path(mesh_metadata_path))
    return {
        "status": str(exec_result.get("status") or "failed"),
        "classification": classification.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "recipe": recipe.model_dump(mode="json"),
        "exec_result": exec_result,
        "backend_result": backend_result,
        "mesh_metadata": mesh_metadata,
        "artifacts": artifacts,
    }


def _bounded_mesh_run_artifact_map(mesh_out_dir: Path) -> Dict[str, str]:
    mesh_dir = mesh_out_dir / "artifacts" / "mesh"
    artifacts: Dict[str, str] = {}
    for name in (
        "mesh_metadata.json",
        "mesh3d_watchdog.json",
        "mesh3d_watchdog_sample.txt",
        "mesh2d_watchdog.json",
        "gmsh_log.txt",
        "hotspot_patch_report.json",
        "surface_patch_diagnostics.json",
        "surface_mesh_2d.msh",
    ):
        path = mesh_dir / name
        if path.exists():
            artifacts[path.stem] = str(path)
    return artifacts


def _execute_mesh_run_bounded_worker(payload: Dict[str, Any], result_path_str: str) -> None:
    result_path = Path(result_path_str)
    try:
        source_path = Path(payload["source_path"])
        provider_result = GeometryProviderResult.model_validate(payload["provider_result"])
        config = MeshJobConfig.model_validate(payload["config"])
        handle = _build_geometry_handle_from_provider_result(
            source_path=source_path,
            component=str(payload["component"]),
            provider_result=provider_result,
            metadata=dict(payload.get("handle_metadata") or {}),
        )
        mesh_run = _execute_mesh_run(handle=handle, config=config)
        payload_out = {
            "status": str(mesh_run.get("status") or "failed"),
            "mesh_metadata": mesh_run.get("mesh_metadata"),
            "artifacts": {
                key: str(value) if value is not None else ""
                for key, value in dict(mesh_run.get("artifacts") or {}).items()
            },
            "error": None,
            "traceback": "",
        }
    except Exception as exc:  # pragma: no cover - exercised through bounded parent path
        payload_out = {
            "status": "failed",
            "mesh_metadata": None,
            "artifacts": {},
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
    _write_normalization_report(result_path, payload_out)


def _execute_mesh_run_bounded_subprocess_entry(payload_path_str: str, result_path_str: str) -> None:
    payload = _json_load(Path(payload_path_str))
    _execute_mesh_run_bounded_worker(payload, result_path_str)


def _execute_mesh_run_bounded(
    *,
    source_path: Path,
    component: str,
    provider_result: GeometryProviderResult,
    handle_metadata: Dict[str, Any],
    config: MeshJobConfig,
    timeout_seconds: float = _AUTONOMOUS_CANDIDATE_3D_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    runner_dir = config.out_dir / "_bounded_exec"
    runner_dir.mkdir(parents=True, exist_ok=True)
    payload_path = runner_dir / "bounded_mesh_run_payload.json"
    result_path = runner_dir / "bounded_mesh_run_result.json"
    payload = {
        "source_path": str(source_path),
        "component": component,
        "provider_result": provider_result.model_dump(mode="json"),
        "handle_metadata": dict(handle_metadata),
        "config": config.model_dump(mode="json"),
    }
    _write_normalization_report(payload_path, payload)
    if result_path.exists():
        result_path.unlink()
    command = [
        sys.executable,
        "-c",
        (
            "from hpa_meshing.providers.esp_pipeline import "
            "_execute_mesh_run_bounded_subprocess_entry as _entry; "
            f"_entry(r'''{payload_path}''', r'''{result_path}''')"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=float(timeout_seconds),
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "mesh_metadata": None,
            "artifacts": _bounded_mesh_run_artifact_map(config.out_dir),
            "error": f"bounded_mesh_timeout_after_{float(timeout_seconds):.1f}s",
        }
    if result_path.exists():
        return _json_load(result_path)
    return {
        "status": "failed",
        "mesh_metadata": None,
        "artifacts": _bounded_mesh_run_artifact_map(config.out_dir),
        "error": (
            f"bounded_mesh_worker_exitcode_{completed.returncode}: "
            f"{(completed.stderr or completed.stdout or '').strip()}"
        ),
    }


def _bbox_center(record: Dict[str, Any]) -> tuple[float, float, float]:
    bbox = record.get("bbox") or {}
    return (
        0.5 * (float(bbox.get("x_min", 0.0)) + float(bbox.get("x_max", 0.0))),
        0.5 * (float(bbox.get("y_min", 0.0)) + float(bbox.get("y_max", 0.0))),
        0.5 * (float(bbox.get("z_min", 0.0)) + float(bbox.get("z_max", 0.0))),
    )


def _select_tip_neighborhood_targets(
    *,
    surface_patch_diagnostics: Dict[str, Any],
    rebuild_model: _NativeRebuildModel,
    source_section_index: int,
    component: str = "main_wing",
    max_surface_count: int = 4,
) -> Dict[str, Any]:
    if not isinstance(surface_patch_diagnostics, dict):
        return {"surface_tags": [], "curve_tags": [], "ranked_surfaces": []}
    surface_index = _surface_index_for_component(rebuild_model, component=component)
    surface = rebuild_model.surfaces[surface_index]
    tip_index = min(max(int(source_section_index), 0), len(surface.sections) - 1)
    tip_section = surface.sections[tip_index]
    previous_section = surface.sections[max(tip_index - 1, 0)]
    anchors = [
        (float(tip_section.x_le + tip_section.chord), float(tip_section.y_le), float(tip_section.z_le)),
        (float(previous_section.x_le + previous_section.chord), float(previous_section.y_le), float(previous_section.z_le)),
    ]
    if surface.symmetric_xz and abs(float(tip_section.y_le)) > 1.0e-9:
        anchors.extend(
            [
                (float(tip_section.x_le + tip_section.chord), -float(tip_section.y_le), float(tip_section.z_le)),
                (float(previous_section.x_le + previous_section.chord), -float(previous_section.y_le), float(previous_section.z_le)),
            ]
        )

    ranked_surfaces: list[Dict[str, Any]] = []
    for record in surface_patch_diagnostics.get("surface_records", []):
        if str(record.get("surface_role")) != "aircraft":
            continue
        center = _bbox_center(record)
        distance = min(math.dist(center, anchor) for anchor in anchors)
        suspect_score = float(record.get("suspect_score", 0.0) or 0.0)
        ranked_surfaces.append(
            {
                "tag": int(record.get("tag", -1)),
                "curve_tags": [int(tag) for tag in record.get("curve_tags", [])],
                "distance_to_tip_anchor_m": float(distance),
                "suspect_score": suspect_score,
                "family_hints": list(record.get("family_hints", [])),
            }
        )
    ranked_surfaces = sorted(
        ranked_surfaces,
        key=lambda entry: (
            float(entry["distance_to_tip_anchor_m"]),
            -float(entry["suspect_score"]),
            int(entry["tag"]),
        ),
    )
    selected_surfaces = ranked_surfaces[: max(max_surface_count, 1)]
    selected_curve_tags = _unique_sorted_ints(
        curve_tag for record in selected_surfaces for curve_tag in record.get("curve_tags", [])
    )
    return {
        "surface_tags": [int(record["tag"]) for record in selected_surfaces if int(record["tag"]) > 0],
        "curve_tags": selected_curve_tags,
        "ranked_surfaces": selected_surfaces,
    }


def _minimum_surface_gamma(hotspot_patch_report: Dict[str, Any] | None) -> float | None:
    gamma_values = [
        float((report.get("surface_triangle_quality") or {}).get("gamma", {}).get("min"))
        for report in (hotspot_patch_report or {}).get("surface_reports", [])
        if (report.get("surface_triangle_quality") or {}).get("gamma", {}).get("min") is not None
    ]
    return min(gamma_values) if gamma_values else None


def _collect_candidate_2d_reports(
    *,
    normalized_geometry_path: Path,
    surface_mesh_path: Path,
    surface_patch_diagnostics: Dict[str, Any],
    rebuild_model: _NativeRebuildModel,
    source_section_index: int,
    report_dir: Path,
) -> Dict[str, Any]:
    from ..adapters.gmsh_backend import (
        _collect_brep_hotspot_report,
        _collect_hotspot_patch_report,
    )

    target_selection = _select_tip_neighborhood_targets(
        surface_patch_diagnostics=surface_patch_diagnostics,
        rebuild_model=rebuild_model,
        source_section_index=source_section_index,
    )
    brep_hotspot_report = _collect_brep_hotspot_report(
        step_path=normalized_geometry_path,
        surface_patch_diagnostics=surface_patch_diagnostics,
        requested_surface_tags=target_selection["surface_tags"],
        requested_curve_tags=target_selection["curve_tags"],
    )
    brep_hotspot_report["target_selection"] = target_selection
    candidate_brep_path = report_dir / "candidate_brep_hotspot_report.json"
    _write_normalization_report(candidate_brep_path, brep_hotspot_report)

    hotspot_patch_report: Dict[str, Any]
    gmsh = None
    try:
        gmsh = load_gmsh()
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(surface_mesh_path))
        hotspot_patch_report = _collect_hotspot_patch_report(
            gmsh,
            surface_patch_diagnostics=surface_patch_diagnostics,
            quality_metrics={"worst_20_tets": []},
            requested_surface_tags=target_selection["surface_tags"],
        )
    finally:
        try:
            if gmsh is not None:
                gmsh.finalize()
        except Exception:
            pass
    hotspot_patch_report["target_selection"] = target_selection
    candidate_hotspot_path = report_dir / "candidate_hotspot_patch_report_2d.json"
    _write_normalization_report(candidate_hotspot_path, hotspot_patch_report)
    return {
        "brep_hotspot_report": brep_hotspot_report,
        "candidate_brep_hotspot_report_path": candidate_brep_path,
        "hotspot_patch_report_2d": hotspot_patch_report,
        "candidate_hotspot_patch_report_2d_path": candidate_hotspot_path,
        "target_selection": target_selection,
    }


def _collect_candidate_sliver_cluster_report(
    *,
    baseline: str,
    mesh_metadata: Dict[str, Any],
    hotspot_patch_report: Dict[str, Any] | None,
    focus_surface_tags: Sequence[int],
    report_path: Path,
) -> Dict[str, Any]:
    from ..adapters.gmsh_backend import _collect_sliver_cluster_report

    cluster_report = _collect_sliver_cluster_report(
        baseline=baseline,
        quality_metrics=mesh_metadata.get("quality_metrics"),
        hotspot_patch_report=hotspot_patch_report,
        focus_surface_tags=focus_surface_tags,
    )
    _write_normalization_report(report_path, cluster_report)
    return cluster_report


def _candidate_failure_reason(candidate_summary: Dict[str, Any]) -> str:
    if candidate_summary.get("geometry_filter_passed") is False:
        reasons = candidate_summary.get("hard_reject_reasons", []) or []
        return ", ".join(str(reason) for reason in reasons) if reasons else "geometry_filter_rejected"
    if int(candidate_summary.get("ill_shaped_tet_count", 0) or 0) != 0:
        return "ill_shaped_tets_present"
    timeout_phase = str(candidate_summary.get("timeout_phase_classification") or "").strip()
    if not candidate_summary.get("generate_3d_returned") and timeout_phase:
        return f"generate_3d_timeout_{timeout_phase}"
    if not candidate_summary.get("generate_3d_returned"):
        return "generate_3d_failed"
    if str(candidate_summary.get("timeout_phase_classification") or "") == "volume_insertion":
        return "volume_insertion"
    return ""


def _reclassify_bounded_timeout_phase(mesh3d_watchdog: Dict[str, Any]) -> str | None:
    phase = str(mesh3d_watchdog.get("timeout_phase_classification") or "").strip()
    if phase != "volume_insertion":
        return phase or None
    logger_tail = [str(line) for line in mesh3d_watchdog.get("logger_tail") or []]
    if any("3D refinement terminated" in line for line in logger_tail) and any(
        "tetrahedra created" in line for line in logger_tail
    ):
        return "optimization"
    return phase or None


def _evaluate_topology_repair_candidate(
    *,
    candidate: Dict[str, Any],
    source_path: Path,
    component: str,
    base_config: MeshJobConfig,
    candidate_dir: Path,
    source_section_index: int,
    baseline_reference: Dict[str, Any] | None,
    baseline_artifacts: Dict[str, Any],
    topology_suppression_report: Dict[str, Any],
    run_3d: bool = False,
    existing_evaluation: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_report_path = candidate_dir / "candidate_topology_repair_report.json"
    face_map_path = candidate_dir / "old_face_to_new_face_map.json"
    candidate_provider_metadata_path = candidate_dir / "candidate_provider_metadata.json"
    report_payload = dict(candidate["report"])
    if existing_evaluation is not None and candidate_report_path.exists():
        persisted_report = _json_load(candidate_report_path)
        if isinstance(persisted_report, dict):
            report_payload = {
                **report_payload,
                **persisted_report,
            }
    _write_normalization_report(candidate_report_path, report_payload)
    _write_normalization_report(face_map_path, report_payload.get("old_face_to_new_face_map", {}))

    if existing_evaluation is not None:
        evaluation = dict(existing_evaluation)
    else:
        evaluation = {
            "name": candidate["candidate_name"],
            "repair_type": candidate["repair_type"],
            "geometry_filter_passed": False,
            "geometry_score": float("-inf"),
            "hard_reject_reasons": [],
            "ran_3d": False,
            "generate_2d_returned": False,
            "generate_3d_returned": False,
            "surface_triangle_count": None,
            "volume_element_count": None,
            "ill_shaped_tet_count": None,
            "nodes_created_per_boundary_node": None,
            "brep_valid_default": None,
            "brep_valid_exact": None,
            "physical_groups_preserved": None,
            "physical_group_remap": dict(report_payload.get("physical_group_remap", {})),
            "old_face_to_new_face_map_path": str(face_map_path),
            "failure_reason": "",
            "timeout_phase_classification": None,
            "min_volume": None,
            "minSICN": None,
            "minSIGE": None,
            "geometry_delta_m": float(report_payload.get("changes", {}).get("max_geometry_delta_m", 0.0) or 0.0),
            "artifacts": {},
        }

    if "_provider_result" not in evaluation:
        if candidate["candidate_name"] == "diagnostic_noop_v2_control":
            provider_result = GeometryProviderResult.model_validate(
                baseline_artifacts["baseline_report"]["provider"]
            )
            candidate_model = baseline_artifacts["baseline_rebuild_model"]
            pipeline_result = None
        else:
            pipeline_result = materialize_with_esp(
                source_path=source_path,
                staging_dir=candidate_dir / "artifacts" / "providers" / "esp_rebuilt",
                component=component,
                prebuilt_rebuild_model=candidate["rebuild_model"],
                skip_terminal_strip_suppression=True,
            )
            if pipeline_result.status != "success" or pipeline_result.normalized_geometry_path is None:
                provider_metadata = {
                    "status": pipeline_result.status,
                    "failure_code": pipeline_result.failure_code,
                    "notes": list(pipeline_result.notes),
                    "warnings": list(pipeline_result.warnings),
                    "physical_groups_preserved": bool(report_payload.get("physical_group_remap")),
                    "physical_group_remap": dict(report_payload.get("physical_group_remap", {})),
                    "tip_topology_diagnostics": {},
                }
                _write_normalization_report(candidate_provider_metadata_path, provider_metadata)
                evaluation["failure_reason"] = pipeline_result.failure_code or "provider_materialization_failed"
                return evaluation
            provider_result = _build_provider_result_from_materialization(
                source_path=source_path,
                component=component,
                pipeline_result=pipeline_result,
            )
            candidate_model = candidate["rebuild_model"]

        tip_topology_diagnostics = _build_tip_topology_diagnostics(
            rebuild_model=candidate_model,
            topology_lineage_report=_build_topology_lineage_report(candidate_model),
            topology_suppression_report=topology_suppression_report,
            hotspot_patch_report=baseline_artifacts["hotspot_patch_report"],
            active_hotspot_family=baseline_artifacts["autonomous_repair_context"]["active_hotspot_family"],
        )
        provider_metadata = {
            "status": "materialized",
            "normalized_geometry_path": str(provider_result.normalized_geometry_path) if provider_result.normalized_geometry_path is not None else None,
            "provider_artifacts": {
                key: str(value) for key, value in provider_result.artifacts.items()
            },
            "physical_groups_preserved": True,
            "physical_group_remap": dict(report_payload.get("physical_group_remap", {})),
            "old_face_to_new_face_map": dict(report_payload.get("old_face_to_new_face_map", {})),
            "tip_topology_diagnostics": tip_topology_diagnostics,
            "candidate_topology_repair_report": str(candidate_report_path),
            "old_face_to_new_face_map_path": str(face_map_path),
        }
        _write_normalization_report(candidate_provider_metadata_path, provider_metadata)

        handle = _build_geometry_handle_from_provider_result(
            source_path=source_path,
            component=component,
            provider_result=provider_result,
            metadata=base_config.metadata,
        )
        evaluation.update(
            {
                "_provider_result": provider_result,
                "_provider_metadata": provider_metadata,
                "_candidate_model": candidate_model,
                "_handle": handle,
            }
        )

    if "_mesh2d" not in evaluation:
        if candidate["candidate_name"] == "diagnostic_noop_v2_control":
            mesh2d_metadata = baseline_artifacts["mesh_metadata"]
            surface_patch_diagnostics = baseline_artifacts["surface_patch_diagnostics"]
            surface_mesh_path = baseline_artifacts["surface_mesh_2d_path"]
        else:
            mesh2d_config = base_config.model_copy(deep=True)
            mesh2d_config.mesh_dim = 2
            mesh2d_config.out_dir = candidate_dir / "mesh_2d"
            mesh2d_config.metadata = dict(mesh2d_config.metadata)
            mesh2d_config.metadata["codex_case_name"] = candidate["candidate_name"]
            mesh2d_run = _execute_mesh_run(handle=evaluation["_handle"], config=mesh2d_config)
            mesh2d_metadata = dict(mesh2d_run.get("mesh_metadata") or {})
            surface_patch_path = Path(
                (mesh2d_run.get("artifacts") or {}).get("surface_patch_diagnostics", "")
            )
            surface_patch_diagnostics = (
                _json_load(surface_patch_path) if surface_patch_path.exists() else {}
            )
            surface_mesh_path = Path((mesh2d_run.get("artifacts") or {}).get("surface_mesh_2d", ""))
            evaluation["generate_2d_returned"] = bool(
                mesh2d_run.get("status") == "success" and mesh2d_metadata.get("status") == "success"
            )
            evaluation["surface_triangle_count"] = int(
                ((mesh2d_metadata.get("mesh") or {}).get("surface_element_count", 0) or 0)
            )
            evaluation["_mesh2d_exec"] = mesh2d_run

        report_bundle = _collect_candidate_2d_reports(
            normalized_geometry_path=evaluation["_provider_result"].normalized_geometry_path or source_path,
            surface_mesh_path=surface_mesh_path,
            surface_patch_diagnostics=surface_patch_diagnostics,
            rebuild_model=evaluation["_candidate_model"],
            source_section_index=source_section_index,
            report_dir=candidate_dir,
        )
        if candidate["candidate_name"] == "diagnostic_noop_v2_control":
            evaluation["generate_2d_returned"] = True
            evaluation["surface_triangle_count"] = int(
                ((mesh2d_metadata.get("mesh") or {}).get("surface_element_count", 0) or 0)
            )
        candidate_baseline_reference = dict(
            baseline_reference
            or {
                "surface_triangle_count": int(
                    baseline_artifacts["autonomous_repair_context"]["baseline_metrics"]["surface_triangle_count"]
                ),
                "tip_surface_min_gamma": _minimum_surface_gamma(report_bundle["hotspot_patch_report_2d"]),
                "focus_surface_ids": list(report_bundle["hotspot_patch_report_2d"].get("selected_surface_tags", [])),
                "min_width_length_ratio": min(
                    evaluation["_provider_metadata"]["tip_topology_diagnostics"]["terminal_tip_neighborhood"]["width_length_ratios"]
                    or [0.0]
                ),
                "min_panel_width_m": min(
                    evaluation["_provider_metadata"]["tip_topology_diagnostics"]["terminal_tip_neighborhood"]["panel_widths_m"]
                    or [0.0]
                ),
                "max_consecutive_width_ratio": float(
                    evaluation["_provider_metadata"]["tip_topology_diagnostics"]["terminal_tip_neighborhood"]["consecutive_width_ratio_max"]
                ),
            }
        )
        decision = _geometry_filter_decision(
            candidate_report=report_payload,
            brep_hotspot_report=report_bundle["brep_hotspot_report"],
            provider_metadata=evaluation["_provider_metadata"],
            candidate_hotspot_patch_report_2d=report_bundle["hotspot_patch_report_2d"],
            mesh_metadata=mesh2d_metadata,
            baseline_reference=candidate_baseline_reference,
        )
        report_payload.update(
            {
                "geometry_score": float(decision["geometry_score"]),
                "geometry_filter_passed": bool(decision["passed"]),
                "hard_reject_reasons": list(decision["hard_reject_reasons"]),
            }
        )
        _write_normalization_report(candidate_report_path, report_payload)
        evaluation.update(
            {
                "geometry_filter_passed": bool(decision["passed"]),
                "geometry_score": float(decision["geometry_score"]),
                "hard_reject_reasons": list(decision["hard_reject_reasons"]),
                "generate_2d_returned": bool(decision["generate_2d_returned"]),
                "brep_valid_default": decision["brep_valid_default"],
                "brep_valid_exact": decision["brep_valid_exact"],
                "physical_groups_preserved": bool(decision["physical_groups_preserved"]),
                "_mesh2d": mesh2d_metadata,
                "_surface_patch_diagnostics": surface_patch_diagnostics,
                "_candidate_hotspot_patch_report_2d": report_bundle["hotspot_patch_report_2d"],
                "_candidate_brep_hotspot_report": report_bundle["brep_hotspot_report"],
                "_baseline_reference": candidate_baseline_reference,
                "_tip_focus_surface_tags": list(report_bundle["target_selection"]["surface_tags"]),
                "artifacts": {
                    **dict(evaluation.get("artifacts") or {}),
                    "candidate_topology_repair_report": str(candidate_report_path),
                    "candidate_provider_metadata": str(candidate_provider_metadata_path),
                    "candidate_brep_hotspot_report": str(report_bundle["candidate_brep_hotspot_report_path"]),
                    "candidate_hotspot_patch_report_2d": str(report_bundle["candidate_hotspot_patch_report_2d_path"]),
                },
            }
        )
        evaluation["failure_reason"] = _candidate_failure_reason(evaluation)

    if not run_3d or not evaluation.get("geometry_filter_passed"):
        return evaluation
    if evaluation.get("ran_3d"):
        return evaluation

    if candidate["candidate_name"] == "diagnostic_noop_v2_control":
        mesh3d_metadata = baseline_artifacts["mesh_metadata"]
        hotspot_patch_report = baseline_artifacts["hotspot_patch_report"]
        sliver_report_path = candidate_dir / "sliver_cluster_report.json"
        sliver_cluster_report = _collect_candidate_sliver_cluster_report(
            baseline=str(baseline_artifacts["autonomous_repair_context"]["baseline"]),
            mesh_metadata=mesh3d_metadata,
            hotspot_patch_report=hotspot_patch_report,
            focus_surface_tags=evaluation["_tip_focus_surface_tags"],
            report_path=sliver_report_path,
        )
        mesh3d_watchdog = mesh3d_metadata.get("mesh3d_watchdog", {}) or {}
        quality_metrics = mesh3d_metadata.get("quality_metrics", {}) or {}
        physical_groups = mesh3d_metadata.get("physical_groups", {}) or {}
        evaluation.update(
            {
                "ran_3d": True,
                "generate_3d_returned": True,
                "volume_element_count": int((mesh3d_metadata.get("mesh") or {}).get("volume_element_count", 0) or 0),
                "ill_shaped_tet_count": int(quality_metrics.get("ill_shaped_tet_count", 0) or 0),
                "nodes_created_per_boundary_node": float(
                    mesh3d_watchdog.get("nodes_created_per_boundary_node", 0.0) or 0.0
                ),
                "timeout_phase_classification": mesh3d_watchdog.get("phase_classification_after_return")
                or mesh3d_watchdog.get("timeout_phase_classification"),
                "min_volume": quality_metrics.get("min_volume"),
                "minSICN": quality_metrics.get("min_sicn"),
                "minSIGE": quality_metrics.get("min_sige"),
                "physical_groups_preserved": all(
                    bool(physical_groups.get(name, {}).get("exists"))
                    for name in ("fluid", "aircraft", "farfield")
                ),
                "artifacts": {
                    **dict(evaluation.get("artifacts") or {}),
                    "mesh_metadata": str(baseline_artifacts["mesh_metadata_path"]),
                    "mesh3d_watchdog": str(baseline_artifacts["mesh3d_watchdog_path"]),
                    "hotspot_patch_report": str(baseline_artifacts["hotspot_patch_report_path"]),
                    "sliver_cluster_report": str(sliver_report_path),
                },
            }
        )
        evaluation["failure_reason"] = _candidate_failure_reason(evaluation)
        return evaluation

    mesh3d_config = base_config.model_copy(deep=True)
    mesh3d_config.mesh_dim = 3
    mesh3d_config.out_dir = candidate_dir / "mesh_3d"
    mesh3d_config.metadata = dict(mesh3d_config.metadata)
    mesh3d_config.metadata["codex_case_name"] = candidate["candidate_name"]
    mesh3d_run = _execute_mesh_run_bounded(
        source_path=source_path,
        component=component,
        provider_result=evaluation["_provider_result"],
        handle_metadata=mesh3d_config.metadata,
        config=mesh3d_config,
    )
    mesh3d_metadata = dict(mesh3d_run.get("mesh_metadata") or {})
    if not mesh3d_metadata:
        mesh3d_watchdog_ref = (mesh3d_run.get("artifacts") or {}).get("mesh3d_watchdog")
        mesh3d_watchdog_path = Path(mesh3d_watchdog_ref) if mesh3d_watchdog_ref else None
        mesh3d_watchdog = _json_load(mesh3d_watchdog_path) if mesh3d_watchdog_path is not None and mesh3d_watchdog_path.exists() else {}
        reclassified_phase = _reclassify_bounded_timeout_phase(mesh3d_watchdog)
        if reclassified_phase is not None:
            original_phase = mesh3d_watchdog.get("timeout_phase_classification")
            if original_phase != reclassified_phase:
                mesh3d_watchdog["original_timeout_phase_classification"] = original_phase
            mesh3d_watchdog["timeout_phase_classification"] = reclassified_phase
        physical_groups = {
            "fluid": {"exists": True},
            "aircraft": {"exists": True},
            "farfield": {"exists": True},
        }
        mesh3d_metadata = {
            "status": str(mesh3d_run.get("status") or "failed"),
            "mesh": {
                "surface_element_count": int(
                    ((evaluation.get("_mesh2d") or {}).get("mesh") or {}).get("surface_element_count", 0) or 0
                ),
                "volume_element_count": 0,
            },
            "quality_metrics": {},
            "mesh3d_watchdog": mesh3d_watchdog,
            "physical_groups": physical_groups,
        }
    hotspot_patch_ref = (mesh3d_run.get("artifacts") or {}).get("hotspot_patch_report")
    hotspot_patch_path = Path(hotspot_patch_ref) if hotspot_patch_ref else None
    hotspot_patch_report = _json_load(hotspot_patch_path) if hotspot_patch_path is not None and hotspot_patch_path.exists() else None
    sliver_report_path = candidate_dir / "sliver_cluster_report.json"
    sliver_cluster_report = _collect_candidate_sliver_cluster_report(
        baseline=str(baseline_artifacts["autonomous_repair_context"]["baseline"]),
        mesh_metadata=mesh3d_metadata,
        hotspot_patch_report=hotspot_patch_report,
        focus_surface_tags=evaluation["_tip_focus_surface_tags"],
        report_path=sliver_report_path,
    )
    quality_metrics = mesh3d_metadata.get("quality_metrics", {}) or {}
    mesh3d_watchdog = mesh3d_metadata.get("mesh3d_watchdog", {}) or {}
    physical_groups = mesh3d_metadata.get("physical_groups", {}) or {}
    evaluation.update(
        {
            "ran_3d": True,
            "generate_3d_returned": bool(
                mesh3d_run.get("status") == "success"
                and mesh3d_metadata.get("status") == "success"
                and int((mesh3d_metadata.get("mesh") or {}).get("volume_element_count", 0) or 0) > 0
            ),
            "surface_triangle_count": int((mesh3d_metadata.get("mesh") or {}).get("surface_element_count", 0) or 0),
            "volume_element_count": int((mesh3d_metadata.get("mesh") or {}).get("volume_element_count", 0) or 0),
            "ill_shaped_tet_count": int(quality_metrics.get("ill_shaped_tet_count", 0) or 0),
            "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
            "timeout_phase_classification": mesh3d_watchdog.get("phase_classification_after_return")
            or mesh3d_watchdog.get("timeout_phase_classification"),
            "min_volume": quality_metrics.get("min_volume"),
            "minSICN": quality_metrics.get("min_sicn"),
            "minSIGE": quality_metrics.get("min_sige"),
            "physical_groups_preserved": all(
                bool(physical_groups.get(name, {}).get("exists"))
                for name in ("fluid", "aircraft", "farfield")
            ),
            "artifacts": {
                **dict(evaluation.get("artifacts") or {}),
                "mesh_metadata": str((mesh3d_run.get("artifacts") or {}).get("mesh_metadata")),
                "mesh3d_watchdog": str((mesh3d_run.get("artifacts") or {}).get("mesh3d_watchdog")),
                "hotspot_patch_report": str(hotspot_patch_path) if hotspot_patch_path is not None and hotspot_patch_path.exists() else "",
                "sliver_cluster_report": str(sliver_report_path),
            },
        }
    )
    evaluation["failure_reason"] = _candidate_failure_reason(evaluation)
    return evaluation


def run_autonomous_tip_topology_repair_controller(
    *,
    source_path: Path,
    out_dir: Path,
    component: str = "main_wing",
    baseline_run_dir: Path | None = None,
    sliver_run_dir: Path | None = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _discover_autonomous_repair_artifacts(
        workspace_root=source_path.parent.parent if source_path.parent.name == "data" else source_path.parent,
        baseline_run_dir=baseline_run_dir,
        sliver_run_dir=sliver_run_dir,
    )
    artifacts: Dict[str, Any] = {}
    missing_artifacts: list[str] = []
    for name, path in artifact_paths.items():
        if not path.exists():
            missing_artifacts.append(name)
            continue
        if path.suffix.lower() == ".json":
            artifacts[name] = _json_load(path)
        else:
            artifacts[name] = path

    autonomous_context = _build_autonomous_repair_context(artifacts=artifacts)
    autonomous_context["missing_artifacts"] = sorted(
        set(list(autonomous_context.get("missing_artifacts", [])) + missing_artifacts)
    )
    autonomous_context_path = out_dir / "autonomous_repair_context.json"
    _write_normalization_report(autonomous_context_path, autonomous_context)
    if autonomous_context["missing_artifacts"] or "baseline_report" not in artifacts:
        return {
            "status": "failed",
            "baseline_promoted": False,
            "missing_artifacts": autonomous_context["missing_artifacts"],
            "autonomous_repair_context": str(autonomous_context_path),
        }

    base_config = _build_autonomous_topology_base_config(
        source_path=source_path,
        out_dir=out_dir / "control",
        baseline_report=artifacts["baseline_report"],
    )
    provider_context_dir = out_dir / "provider_context"
    provider_context_dir.mkdir(parents=True, exist_ok=True)
    component_input = _prepare_component_input_model(
        source_path=source_path,
        artifact_dir=provider_context_dir,
        component=component,
    )
    rebuild_model = _build_native_rebuild_model(
        source_path=component_input.input_model_path,
        component=component,
    )
    baseline_rebuild_model, topology_suppression_report = _apply_terminal_strip_suppression(rebuild_model)
    tip_topology_diagnostics = _build_tip_topology_diagnostics(
        rebuild_model=baseline_rebuild_model,
        topology_lineage_report=_build_topology_lineage_report(baseline_rebuild_model),
        topology_suppression_report=topology_suppression_report,
        hotspot_patch_report=artifacts["hotspot_patch_report"],
        active_hotspot_family=autonomous_context["active_hotspot_family"],
    )
    tip_topology_diagnostics_path = out_dir / "tip_topology_diagnostics.json"
    _write_normalization_report(tip_topology_diagnostics_path, tip_topology_diagnostics)

    candidates = _generate_bounded_tip_topology_repair_candidates(
        baseline_rebuild_model=baseline_rebuild_model,
        diagnostics=tip_topology_diagnostics,
        egads_effective_topology_available=False,
    )
    baseline_artifacts = {
        **artifacts,
        "autonomous_repair_context": autonomous_context,
        "baseline_rebuild_model": baseline_rebuild_model,
        "mesh_metadata_path": artifact_paths["mesh_metadata"],
        "mesh3d_watchdog_path": artifact_paths.get("mesh3d_watchdog"),
        "hotspot_patch_report_path": artifact_paths["hotspot_patch_report"],
        "surface_mesh_2d_path": artifact_paths["surface_mesh_2d"],
    }

    evaluated_candidates: list[Dict[str, Any]] = []
    control_candidate = next(
        candidate for candidate in candidates if candidate["candidate_name"] == "diagnostic_noop_v2_control"
    )
    control_eval = _evaluate_topology_repair_candidate(
        candidate=control_candidate,
        source_path=source_path,
        component=component,
        base_config=base_config,
        candidate_dir=out_dir / control_candidate["candidate_name"],
        source_section_index=int(tip_topology_diagnostics["source_section_index"]),
        baseline_reference=None,
        baseline_artifacts=baseline_artifacts,
        topology_suppression_report=topology_suppression_report,
        run_3d=True,
    )
    evaluated_candidates.append(control_eval)
    baseline_reference = control_eval.get("_baseline_reference") or {
        "surface_triangle_count": autonomous_context["baseline_metrics"]["surface_triangle_count"],
        "tip_surface_min_gamma": None,
        "focus_surface_ids": list(control_eval.get("_tip_focus_surface_tags", [])),
        "min_width_length_ratio": min(
            tip_topology_diagnostics["terminal_tip_neighborhood"]["width_length_ratios"] or [0.0]
        ),
        "min_panel_width_m": min(
            tip_topology_diagnostics["terminal_tip_neighborhood"]["panel_widths_m"] or [0.0]
        ),
        "max_consecutive_width_ratio": float(
            tip_topology_diagnostics["terminal_tip_neighborhood"]["consecutive_width_ratio_max"]
        ),
    }

    for candidate in candidates:
        if candidate["candidate_name"] == "diagnostic_noop_v2_control":
            continue
        evaluation = _evaluate_topology_repair_candidate(
            candidate=candidate,
            source_path=source_path,
            component=component,
            base_config=base_config,
            candidate_dir=out_dir / candidate["candidate_name"],
            source_section_index=int(tip_topology_diagnostics["source_section_index"]),
            baseline_reference=baseline_reference,
            baseline_artifacts=baseline_artifacts,
            topology_suppression_report=topology_suppression_report,
            run_3d=False,
        )
        evaluated_candidates.append(evaluation)

    top_geometry_candidates = _select_top_geometry_candidates(evaluated_candidates)
    top_geometry_names = {candidate["name"] for candidate in top_geometry_candidates}
    final_candidates: list[Dict[str, Any]] = []
    for evaluation in evaluated_candidates:
        if evaluation["name"] in top_geometry_names and not evaluation.get("ran_3d"):
            candidate_spec = next(candidate for candidate in candidates if candidate["candidate_name"] == evaluation["name"])
            evaluation = _evaluate_topology_repair_candidate(
                candidate=candidate_spec,
                source_path=source_path,
                component=component,
                base_config=base_config,
                candidate_dir=out_dir / evaluation["name"],
                source_section_index=int(tip_topology_diagnostics["source_section_index"]),
                baseline_reference=baseline_reference,
                baseline_artifacts=baseline_artifacts,
                topology_suppression_report=topology_suppression_report,
                run_3d=True,
                existing_evaluation=evaluation,
            )
        elif bool(evaluation.get("geometry_filter_passed")) and not evaluation.get("ran_3d"):
            evaluation["failure_reason"] = "not_selected_for_3d_geometry_score_rank"
        final_candidates.append(evaluation)

    winner = _select_topology_repair_winner(final_candidates)
    candidate_summaries = [
        {
            "name": candidate["name"],
            "repair_type": candidate["repair_type"],
            "geometry_filter_passed": bool(candidate.get("geometry_filter_passed")),
            "ran_3d": bool(candidate.get("ran_3d")),
            "surface_triangle_count": candidate.get("surface_triangle_count"),
            "volume_element_count": candidate.get("volume_element_count"),
            "ill_shaped_tet_count": candidate.get("ill_shaped_tet_count"),
            "nodes_created_per_boundary_node": candidate.get("nodes_created_per_boundary_node"),
            "brep_valid_default": candidate.get("brep_valid_default"),
            "brep_valid_exact": candidate.get("brep_valid_exact"),
            "physical_groups_preserved": candidate.get("physical_groups_preserved"),
            "old_face_to_new_face_map_path": candidate.get("old_face_to_new_face_map_path", ""),
            "failure_reason": candidate.get("failure_reason", ""),
        }
        for candidate in final_candidates
    ]
    summary_payload = {
        "baseline": str(autonomous_context["baseline"]),
        "controller_version": _AUTONOMOUS_TIP_TOPOLOGY_CONTROLLER_VERSION,
        "mesh_only_no_go_confirmed": True,
        "candidates": candidate_summaries,
        "winner": winner["name"] if winner is not None else None,
        "baseline_promoted": winner is not None,
        "recommended_next": (
            "promoted shell_v3 quality-clean topology repair winner"
            if winner is not None
            else "manual review of rule-loft section pairing or geometry construction contract"
        ),
    }
    summary_path = out_dir / "upstream_topology_repair_summary.json"
    _write_normalization_report(summary_path, summary_payload)

    if winner is not None:
        manifest_payload = {
            "baseline_name": "shell_v3_quality_clean_baseline",
            "source_candidate": winner["name"],
            "old_baseline": str(autonomous_context["baseline"]),
            "surface_triangle_count": int(winner.get("surface_triangle_count", 0) or 0),
            "volume_element_count": int(winner.get("volume_element_count", 0) or 0),
            "nodes_created_per_boundary_node": float(winner.get("nodes_created_per_boundary_node", 0.0) or 0.0),
            "ill_shaped_tet_count": int(winner.get("ill_shaped_tet_count", 0) or 0),
            "min_volume": float(winner.get("min_volume", 0.0) or 0.0),
            "minSICN": float(winner.get("minSICN", 0.0) or 0.0),
            "minSIGE": float(winner.get("minSIGE", 0.0) or 0.0),
            "old_face_to_new_face_map": _json_load(Path(winner["old_face_to_new_face_map_path"])),
            "physical_group_remap": dict(winner.get("physical_group_remap", {})),
            "artifacts": dict(winner.get("artifacts", {})),
        }
        manifest_path = out_dir / "shell_v3_quality_clean_baseline_manifest.json"
        _write_normalization_report(manifest_path, manifest_payload)
        return {
            "status": "success",
            "baseline_promoted": True,
            "winner": winner["name"],
            "summary_path": str(summary_path),
            "manifest_path": str(manifest_path),
        }

    no_go_payload = _build_upstream_pairing_no_go_summary()
    no_go_path = out_dir / "upstream_pairing_no_go_summary.json"
    _write_normalization_report(no_go_path, no_go_payload)
    return {
        "status": "failed",
        "baseline_promoted": False,
        "winner": None,
        "summary_path": str(summary_path),
        "no_go_summary_path": str(no_go_path),
    }
