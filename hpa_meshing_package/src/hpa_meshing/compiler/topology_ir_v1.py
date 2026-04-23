from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field


def _default_extrusion_compatibility() -> Dict[str, Any]:
    return {
        "status": "unknown",
        "reason": "pre_plc_audit_required_before_3d_volume",
    }


def _default_truncation_band_role() -> Dict[str, Any]:
    return {
        "status": "not_classified",
    }


class SectionLineageV1(BaseModel):
    source_section_indices: List[int] = Field(default_factory=list)
    rule_section_indices: List[int] = Field(default_factory=list)
    side_labels: List[str] = Field(default_factory=list)


class TopologySeamAdjacencyV1(BaseModel):
    is_seam_adjacent: bool = False
    seam_kind: Optional[str] = None
    seam_curve_ids: List[str] = Field(default_factory=list)
    seam_source_section_indices: List[int] = Field(default_factory=list)


class TopologyClosureAdjacencyV1(BaseModel):
    is_closure_adjacent: bool = False
    closure_kind: Optional[str] = None
    closure_curve_ids: List[str] = Field(default_factory=list)
    closure_source_section_indices: List[int] = Field(default_factory=list)


class LocalTopologyDescriptorsV1(BaseModel):
    collapse_indicators: Dict[str, Any] = Field(default_factory=dict)
    local_clearance_m: Optional[float] = None
    dihedral_consistency: Dict[str, Any] = Field(default_factory=lambda: {"status": "not_evaluated"})
    orientation_consistency: Dict[str, Any] = Field(default_factory=lambda: {"status": "not_evaluated"})
    extrusion_compatibility: Dict[str, Any] = Field(default_factory=_default_extrusion_compatibility)
    truncation_band_role: Dict[str, Any] = Field(default_factory=_default_truncation_band_role)


class TopologyCurveV1(BaseModel):
    curve_id: str
    curve_role: str
    label: str
    source_patch_ids: List[str] = Field(default_factory=list)
    corner_ids: List[str] = Field(default_factory=list)
    section_lineage: SectionLineageV1 = Field(default_factory=SectionLineageV1)
    seam_role: Optional[str] = None
    closure_role: Optional[str] = None
    local_descriptors: LocalTopologyDescriptorsV1 = Field(default_factory=LocalTopologyDescriptorsV1)
    notes: List[str] = Field(default_factory=list)


class TopologyLoopV1(BaseModel):
    loop_id: str
    patch_id: str
    curve_ids: List[str] = Field(default_factory=list)
    is_closed: bool = True
    orientation: str = "artifact_inferred"
    notes: List[str] = Field(default_factory=list)


class TopologyCornerV1(BaseModel):
    corner_id: str
    point_role: str
    xyz: List[float]
    source_patch_ids: List[str] = Field(default_factory=list)
    section_lineage: SectionLineageV1 = Field(default_factory=SectionLineageV1)
    notes: List[str] = Field(default_factory=list)


class TopologyPatchV1(BaseModel):
    patch_id: str
    patch_kind: str
    component: str
    label: str
    source_patch_family: str = "rule_section_strip"
    curve_ids: List[str] = Field(default_factory=list)
    loop_ids: List[str] = Field(default_factory=list)
    corner_ids: List[str] = Field(default_factory=list)
    section_lineage: SectionLineageV1 = Field(default_factory=SectionLineageV1)
    seam_adjacency: TopologySeamAdjacencyV1 = Field(default_factory=TopologySeamAdjacencyV1)
    closure_adjacency: TopologyClosureAdjacencyV1 = Field(default_factory=TopologyClosureAdjacencyV1)
    local_descriptors: LocalTopologyDescriptorsV1 = Field(default_factory=LocalTopologyDescriptorsV1)
    tags: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TopologyAdjacencyEdgeV1(BaseModel):
    edge_id: str
    entity_a: str
    entity_b: str
    relation_kind: str
    shared_entity_id: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class TopologyAdjacencyGraphV1(BaseModel):
    edges: List[TopologyAdjacencyEdgeV1] = Field(default_factory=list)


class TopologyIRV1(BaseModel):
    contract: str = "topology_ir.v1"
    component: str
    geometry_source: str = "esp_rebuilt"
    geometry_provider: Optional[str] = None
    normalized_geometry_path: Optional[Path] = None
    extraction_mode: str = "artifact_inferred_section_strip_decomposition"
    compiler_context: Dict[str, Any] = Field(default_factory=dict)
    topology_counts: Dict[str, Any] = Field(default_factory=dict)
    topology_artifacts: Dict[str, Any] = Field(default_factory=dict)
    patches: List[TopologyPatchV1] = Field(default_factory=list)
    curves: List[TopologyCurveV1] = Field(default_factory=list)
    loops: List[TopologyLoopV1] = Field(default_factory=list)
    corners: List[TopologyCornerV1] = Field(default_factory=list)
    adjacency_graph: TopologyAdjacencyGraphV1 = Field(default_factory=TopologyAdjacencyGraphV1)
    notes: List[str] = Field(default_factory=list)


def _load_payload(payload_or_path: Any) -> Dict[str, Any]:
    if payload_or_path is None:
        return {}
    if isinstance(payload_or_path, Path):
        return json.loads(payload_or_path.read_text(encoding="utf-8"))
    if isinstance(payload_or_path, str):
        path = Path(payload_or_path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return json.loads(payload_or_path)
    if isinstance(payload_or_path, dict):
        return dict(payload_or_path)
    raise TypeError(f"Unsupported topology payload type: {type(payload_or_path)!r}")


def _sorted_rule_sections(surface: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(
        [dict(section) for section in surface.get("rule_sections", [])],
        key=lambda item: int(item.get("rule_section_index", 0)),
    )


def _closure_kind(side_labels: Iterable[str]) -> Optional[str]:
    normalized = [str(label) for label in side_labels if label is not None]
    if any("tip" in label for label in normalized):
        return "tip_endcap"
    if any("center_or_start" in label or "root" in label for label in normalized):
        return "symmetry_or_root"
    return None


def _section_lineage(lhs: Dict[str, Any], rhs: Dict[str, Any]) -> SectionLineageV1:
    return SectionLineageV1(
        source_section_indices=[
            int(lhs.get("source_section_index", 0)),
            int(rhs.get("source_section_index", 0)),
        ],
        rule_section_indices=[
            int(lhs.get("rule_section_index", 0)),
            int(rhs.get("rule_section_index", 0)),
        ],
        side_labels=[str(lhs.get("side", "")), str(rhs.get("side", ""))],
    )


def _section_point(section: Dict[str, Any], point_role: str) -> List[float]:
    x_le = float(section.get("x_le", 0.0))
    y_le = float(section.get("y_le", 0.0))
    z_le = float(section.get("z_le", 0.0))
    chord = float(section.get("chord", 0.0))
    if point_role.endswith("te"):
        return [x_le + chord, y_le, z_le]
    return [x_le, y_le, z_le]


def _dihedral_consistency(lhs: Dict[str, Any], rhs: Dict[str, Any]) -> Dict[str, Any]:
    dy = float(rhs.get("y_le", 0.0)) - float(lhs.get("y_le", 0.0))
    dz = float(rhs.get("z_le", 0.0)) - float(lhs.get("z_le", 0.0))
    if abs(dy) <= 1.0e-9:
        return {"status": "not_evaluated", "reason": "delta_y_too_small"}
    angle_deg = math.degrees(math.atan2(dz, dy))
    return {
        "status": "measured",
        "local_dihedral_deg": float(angle_deg),
        "delta_y_m": float(dy),
        "delta_z_m": float(dz),
    }


def _orientation_consistency(lhs: Dict[str, Any], rhs: Dict[str, Any]) -> Dict[str, Any]:
    lhs_chord = float(lhs.get("chord", 0.0))
    rhs_chord = float(rhs.get("chord", 0.0))
    monotonic_y = float(rhs.get("y_le", 0.0)) >= float(lhs.get("y_le", 0.0))
    return {
        "status": "pass" if monotonic_y and lhs_chord > 0.0 and rhs_chord > 0.0 else "warn",
        "monotonic_y": bool(monotonic_y),
        "positive_chords": bool(lhs_chord > 0.0 and rhs_chord > 0.0),
    }


def _tip_candidate_by_source_section(surface: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    mapping: Dict[int, Dict[str, Any]] = {}
    for candidate in surface.get("terminal_strip_candidates", []) or []:
        source_section_index = int(candidate.get("source_section_index", -1))
        if source_section_index >= 0:
            mapping[source_section_index] = dict(candidate)
    return mapping


def _truncation_connector_band_context(topology_payload: Dict[str, Any]) -> Dict[str, Any]:
    compiler_context = topology_payload.get("compiler_context")
    if not isinstance(compiler_context, dict):
        return {}
    raw = compiler_context.get("truncation_connector_band")
    if not isinstance(raw, dict) or not raw.get("enabled", False):
        return {}
    return {
        "enabled": True,
        "root_y_le_m": (
            float(raw["root_y_le_m"]) if raw.get("root_y_le_m") is not None else None
        ),
        "connector_band_start_y_le_m": (
            float(raw["connector_band_start_y_le_m"])
            if raw.get("connector_band_start_y_le_m") is not None
            else None
        ),
        "truncation_start_y_le_m": (
            float(raw["truncation_start_y_le_m"])
            if raw.get("truncation_start_y_le_m") is not None
            else None
        ),
        "tip_y_le_m": (
            float(raw["tip_y_le_m"]) if raw.get("tip_y_le_m") is not None else None
        ),
        "selected_section_y_le_m": [
            float(value) for value in raw.get("selected_section_y_le_m", []) if value is not None
        ],
        "post_band_transition_guard_y_le_m": (
            float(raw["post_band_transition_guard_y_le_m"])
            if raw.get("post_band_transition_guard_y_le_m") is not None
            else None
        ),
    }


def _close(lhs: Optional[float], rhs: Optional[float], *, tolerance: float = 1.0e-6) -> bool:
    if lhs is None or rhs is None:
        return False
    return abs(float(lhs) - float(rhs)) <= tolerance


def _classify_truncation_band_role(
    *,
    lhs: Dict[str, Any],
    rhs: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    if not context:
        return _default_truncation_band_role()

    lhs_y = float(lhs.get("y_le", 0.0))
    rhs_y = float(rhs.get("y_le", 0.0))
    root_y = context.get("root_y_le_m")
    connector_band_start_y = context.get("connector_band_start_y_le_m")
    truncation_start_y = context.get("truncation_start_y_le_m")
    tip_y = context.get("tip_y_le_m")
    post_band_transition_guard_y = context.get("post_band_transition_guard_y_le_m")
    tolerance = 1.0e-6

    role: Optional[str] = None
    if _close(lhs_y, connector_band_start_y, tolerance=tolerance) and _close(
        rhs_y,
        truncation_start_y,
        tolerance=tolerance,
    ):
        role = "connector_band"
    elif _close(lhs_y, truncation_start_y, tolerance=tolerance) and _close(
        rhs_y,
        tip_y,
        tolerance=tolerance,
    ):
        role = "truncation_transition"
    elif (
        connector_band_start_y is not None
        and root_y is not None
        and lhs_y > float(root_y) + tolerance
        and _close(rhs_y, connector_band_start_y, tolerance=tolerance)
    ):
        role = "pre_band_support"
    elif root_y is not None and _close(lhs_y, root_y, tolerance=tolerance):
        role = "root_to_terminal_support"
    elif (
        post_band_transition_guard_y is not None
        and truncation_start_y is not None
        and _close(lhs_y, truncation_start_y, tolerance=tolerance)
        and _close(rhs_y, post_band_transition_guard_y, tolerance=tolerance)
    ):
        role = "post_band_transition_guard"
    elif (
        post_band_transition_guard_y is not None
        and tip_y is not None
        and _close(lhs_y, post_band_transition_guard_y, tolerance=tolerance)
        and _close(rhs_y, tip_y, tolerance=tolerance)
    ):
        role = "post_band_terminal_transition"

    if role is None:
        return _default_truncation_band_role()

    extra_pre_band_section_y_le_m = [
        float(value)
        for value in context.get("selected_section_y_le_m", [])
        if root_y is not None
        and connector_band_start_y is not None
        and float(value) > float(root_y) + tolerance
        and float(value) < float(connector_band_start_y) - tolerance
    ]

    return {
        "status": "classified",
        "role": role,
        "root_y_le_m": root_y,
        "connector_band_start_y_le_m": connector_band_start_y,
        "truncation_start_y_le_m": truncation_start_y,
        "tip_y_le_m": tip_y,
        "post_band_transition_guard_y_le_m": post_band_transition_guard_y,
        "extra_pre_band_section_y_le_m": extra_pre_band_section_y_le_m,
    }


def build_topology_ir_v1(
    *,
    topology_report: Any,
    topology_lineage_report: Any = None,
    topology_suppression_report: Any = None,
    component: Optional[str] = None,
    normalized_geometry_path: Optional[Path] = None,
) -> TopologyIRV1:
    topology_payload = _load_payload(topology_report)
    lineage_payload = _load_payload(topology_lineage_report)
    suppression_payload = _load_payload(topology_suppression_report)
    truncation_band_context = _truncation_connector_band_context(topology_payload)
    surfaces = [dict(surface) for surface in lineage_payload.get("surfaces", [])]

    curves_by_id: Dict[str, TopologyCurveV1] = {}
    corners_by_id: Dict[str, TopologyCornerV1] = {}
    patches: List[TopologyPatchV1] = []
    loops: List[TopologyLoopV1] = []
    adjacency_edges: List[TopologyAdjacencyEdgeV1] = []
    curve_usage: Dict[str, List[str]] = {}

    resolved_component = component or (
        str(surfaces[0].get("component"))
        if surfaces
        else str(topology_payload.get("component_selection", {}).get("effective_component", "unknown"))
    )

    for surface_index, surface in enumerate(surfaces):
        sections = _sorted_rule_sections(surface)
        tip_candidates = _tip_candidate_by_source_section(surface)
        geom_id = str(surface.get("geom_id", f"surface_{surface_index}"))
        component_name = str(surface.get("component", resolved_component))
        for interval_index, (lhs, rhs) in enumerate(zip(sections[:-1], sections[1:])):
            patch_id = f"patch:{geom_id}:{int(lhs.get('rule_section_index', interval_index))}:{int(rhs.get('rule_section_index', interval_index + 1))}"
            inboard_curve_id = f"curve:{geom_id}:section:{int(lhs.get('rule_section_index', interval_index))}"
            outboard_curve_id = f"curve:{geom_id}:section:{int(rhs.get('rule_section_index', interval_index + 1))}"
            leading_curve_id = f"curve:{geom_id}:leading:{interval_index}"
            trailing_curve_id = f"curve:{geom_id}:trailing:{interval_index}"
            loop_id = f"loop:{patch_id}"

            corner_specs = {
                f"corner:{patch_id}:inboard_le": (lhs, "inboard_le"),
                f"corner:{patch_id}:inboard_te": (lhs, "inboard_te"),
                f"corner:{patch_id}:outboard_te": (rhs, "outboard_te"),
                f"corner:{patch_id}:outboard_le": (rhs, "outboard_le"),
            }
            for corner_id, (section, point_role) in corner_specs.items():
                corners_by_id[corner_id] = TopologyCornerV1(
                    corner_id=corner_id,
                    point_role=point_role,
                    xyz=_section_point(section, point_role),
                    source_patch_ids=[patch_id],
                    section_lineage=SectionLineageV1(
                        source_section_indices=[int(section.get("source_section_index", 0))],
                        rule_section_indices=[int(section.get("rule_section_index", 0))],
                        side_labels=[str(section.get("side", ""))],
                    ),
                )

            shared_curve_specs = {
                inboard_curve_id: {
                    "curve_role": "section_boundary",
                    "label": f"{geom_id} section {lhs.get('rule_section_index')} boundary",
                    "section_lineage": SectionLineageV1(
                        source_section_indices=[int(lhs.get("source_section_index", 0))],
                        rule_section_indices=[int(lhs.get("rule_section_index", 0))],
                        side_labels=[str(lhs.get("side", ""))],
                    ),
                    "corner_ids": [
                        f"corner:{patch_id}:inboard_le",
                        f"corner:{patch_id}:inboard_te",
                    ],
                    "closure_role": _closure_kind([str(lhs.get("side", ""))]),
                },
                outboard_curve_id: {
                    "curve_role": "section_boundary",
                    "label": f"{geom_id} section {rhs.get('rule_section_index')} boundary",
                    "section_lineage": SectionLineageV1(
                        source_section_indices=[int(rhs.get("source_section_index", 0))],
                        rule_section_indices=[int(rhs.get("rule_section_index", 0))],
                        side_labels=[str(rhs.get("side", ""))],
                    ),
                    "corner_ids": [
                        f"corner:{patch_id}:outboard_le",
                        f"corner:{patch_id}:outboard_te",
                    ],
                    "closure_role": _closure_kind([str(rhs.get("side", ""))]),
                },
                leading_curve_id: {
                    "curve_role": "leading_edge_segment",
                    "label": f"{geom_id} leading edge strip {interval_index}",
                    "section_lineage": _section_lineage(lhs, rhs),
                    "corner_ids": [
                        f"corner:{patch_id}:inboard_le",
                        f"corner:{patch_id}:outboard_le",
                    ],
                    "closure_role": None,
                },
                trailing_curve_id: {
                    "curve_role": "trailing_edge_segment",
                    "label": f"{geom_id} trailing edge strip {interval_index}",
                    "section_lineage": _section_lineage(lhs, rhs),
                    "corner_ids": [
                        f"corner:{patch_id}:inboard_te",
                        f"corner:{patch_id}:outboard_te",
                    ],
                    "closure_role": None,
                },
            }

            for curve_id, curve_spec in shared_curve_specs.items():
                curve_usage.setdefault(curve_id, []).append(patch_id)
                if curve_id not in curves_by_id:
                    curves_by_id[curve_id] = TopologyCurveV1(
                        curve_id=curve_id,
                        curve_role=str(curve_spec["curve_role"]),
                        label=str(curve_spec["label"]),
                        source_patch_ids=[patch_id],
                        corner_ids=list(curve_spec["corner_ids"]),
                        section_lineage=curve_spec["section_lineage"],
                        seam_role="trailing_edge_seam" if curve_id == trailing_curve_id else None,
                        closure_role=curve_spec["closure_role"],
                    )
                else:
                    existing = curves_by_id[curve_id]
                    curves_by_id[curve_id] = existing.model_copy(
                        update={
                            "source_patch_ids": [*existing.source_patch_ids, patch_id],
                        }
                    )

            lineage = _section_lineage(lhs, rhs)
            closure_kind = _closure_kind(lineage.side_labels)
            tip_candidate = None
            for source_section_index in lineage.source_section_indices:
                if source_section_index in tip_candidates:
                    tip_candidate = tip_candidates[source_section_index]
                    break
            collapse_indicators: Dict[str, Any] = {
                "tip_terminal_candidate": bool(tip_candidate is not None),
                "suppressed_source_section_indices": (
                    suppression_payload.get("surfaces", [{}])[0].get("suppressed_source_section_indices", [])
                    if suppression_payload.get("surfaces")
                    else []
                ),
            }
            if tip_candidate is not None:
                collapse_indicators.update(
                    {
                        "trailing_edge_gap_m": float(tip_candidate.get("trailing_edge_gap_m", 0.0)),
                        "suppression_threshold_m": float(tip_candidate.get("suppression_threshold_m", 0.0)),
                        "would_suppress": bool(tip_candidate.get("would_suppress", False)),
                        "suppression_reason": str(tip_candidate.get("suppression_reason", "")),
                    }
                )

            truncation_band_role = _classify_truncation_band_role(
                lhs=lhs,
                rhs=rhs,
                context=truncation_band_context,
            )
            source_patch_family = (
                "truncation_connector_band"
                if truncation_band_role.get("role") == "connector_band"
                else "post_band_transition_boundary_recovery"
                if truncation_band_role.get("role")
                in {"post_band_transition_guard", "post_band_terminal_transition"}
                else "rule_section_strip"
            )
            patch_tags = []
            if truncation_band_role.get("role") == "connector_band":
                patch_tags.append("truncation_connector_band")
            elif truncation_band_role.get("role") == "pre_band_support":
                patch_tags.append("truncation_pre_band_support")
            elif truncation_band_role.get("role") == "truncation_transition":
                patch_tags.append("truncation_transition")
            elif truncation_band_role.get("role") == "post_band_transition_guard":
                patch_tags.append("post_band_transition_guard")
            elif truncation_band_role.get("role") == "post_band_terminal_transition":
                patch_tags.append("post_band_terminal_transition")

            patch = TopologyPatchV1(
                patch_id=patch_id,
                patch_kind="rule_section_strip",
                component=component_name,
                label=f"{surface.get('name', component_name)} strip {interval_index}",
                source_patch_family=source_patch_family,
                curve_ids=[inboard_curve_id, leading_curve_id, outboard_curve_id, trailing_curve_id],
                loop_ids=[loop_id],
                corner_ids=list(corner_specs),
                section_lineage=lineage,
                seam_adjacency=TopologySeamAdjacencyV1(
                    is_seam_adjacent=True,
                    seam_kind="trailing_edge_seam",
                    seam_curve_ids=[trailing_curve_id],
                    seam_source_section_indices=list(lineage.source_section_indices),
                ),
                closure_adjacency=TopologyClosureAdjacencyV1(
                    is_closure_adjacent=closure_kind is not None,
                    closure_kind=closure_kind,
                    closure_curve_ids=[
                        curve_id
                        for curve_id in (inboard_curve_id, outboard_curve_id)
                        if curves_by_id[curve_id].closure_role is not None
                    ],
                    closure_source_section_indices=[
                        index
                        for index, side_label in zip(
                            lineage.source_section_indices,
                            lineage.side_labels,
                        )
                        if _closure_kind([side_label]) is not None
                    ],
                ),
                local_descriptors=LocalTopologyDescriptorsV1(
                    collapse_indicators=collapse_indicators,
                    local_clearance_m=(
                        float(tip_candidate.get("trailing_edge_gap_m"))
                        if tip_candidate is not None and tip_candidate.get("trailing_edge_gap_m") is not None
                        else None
                    ),
                    dihedral_consistency=_dihedral_consistency(lhs, rhs),
                    orientation_consistency=_orientation_consistency(lhs, rhs),
                    truncation_band_role=truncation_band_role,
                ),
                tags=patch_tags,
                metadata={
                    "inboard_y_le_m": float(lhs.get("y_le", 0.0)),
                    "outboard_y_le_m": float(rhs.get("y_le", 0.0)),
                    "span_interval_m": abs(float(rhs.get("y_le", 0.0)) - float(lhs.get("y_le", 0.0))),
                    "inboard_chord_m": float(lhs.get("chord", 0.0)),
                    "outboard_chord_m": float(rhs.get("chord", 0.0)),
                    **(
                        {
                            "root_y_le_m": truncation_band_role.get("root_y_le_m"),
                            "connector_band_start_y_le_m": truncation_band_role.get("connector_band_start_y_le_m"),
                            "truncation_start_y_le_m": truncation_band_role.get("truncation_start_y_le_m"),
                            "tip_y_le_m": truncation_band_role.get("tip_y_le_m"),
                            "post_band_transition_guard_y_le_m": truncation_band_role.get(
                                "post_band_transition_guard_y_le_m"
                            ),
                        }
                        if truncation_band_role.get("status") == "classified"
                        else {}
                    ),
                    **(
                        {
                            "terminal_trailing_edge_gap_m": float(tip_candidate.get("trailing_edge_gap_m", 0.0)),
                            "terminal_suppression_threshold_m": float(tip_candidate.get("suppression_threshold_m", 0.0)),
                        }
                        if tip_candidate is not None
                        else {}
                    ),
                },
                notes=[
                    "inferred_from_rule_section_interval",
                    "not_extracted_from_native_brep_faces",
                ],
            )
            patches.append(patch)
            loops.append(
                TopologyLoopV1(
                    loop_id=loop_id,
                    patch_id=patch_id,
                    curve_ids=list(patch.curve_ids),
                    is_closed=True,
                    notes=["artifact_inferred_boundary_cycle"],
                )
            )
            for curve_id in patch.curve_ids:
                adjacency_edges.append(
                    TopologyAdjacencyEdgeV1(
                        edge_id=f"edge:{patch_id}:{curve_id}",
                        entity_a=patch_id,
                        entity_b=curve_id,
                        relation_kind="patch_boundary",
                        shared_entity_id=curve_id,
                    )
                )

    for curve_id, patch_ids in curve_usage.items():
        if len(patch_ids) < 2:
            continue
        adjacency_edges.append(
            TopologyAdjacencyEdgeV1(
                edge_id=f"edge:shared:{curve_id}",
                entity_a=patch_ids[0],
                entity_b=patch_ids[1],
                relation_kind="shared_section_curve",
                shared_entity_id=curve_id,
            )
        )

    topology_counts = {
        "body_count": topology_payload.get("body_count"),
        "surface_count": topology_payload.get("surface_count"),
        "volume_count": topology_payload.get("volume_count"),
        "patch_count": len(patches),
        "curve_count": len(curves_by_id),
        "loop_count": len(loops),
        "corner_count": len(corners_by_id),
    }
    topology_artifacts = {
        "topology_report": topology_payload.get("export_path"),
        "topology_lineage_report": topology_payload.get("topology_lineage_report", {}).get("artifact"),
        "topology_suppression_report": topology_payload.get("topology_suppression_report", {}).get("artifact"),
    }
    if normalized_geometry_path is None and topology_payload.get("export_path"):
        normalized_geometry_path = Path(str(topology_payload["export_path"]))

    return TopologyIRV1(
        component=resolved_component,
        geometry_source="esp_rebuilt",
        geometry_provider="esp_rebuilt",
        normalized_geometry_path=normalized_geometry_path,
        compiler_context=dict(topology_payload.get("compiler_context") or {}),
        topology_counts=topology_counts,
        topology_artifacts=topology_artifacts,
        patches=patches,
        curves=list(curves_by_id.values()),
        loops=loops,
        corners=list(corners_by_id.values()),
        adjacency_graph=TopologyAdjacencyGraphV1(edges=adjacency_edges),
        notes=[
            "topology_ir.v1 is a topology-first classifier layer, not a meshing route",
            "local strips are inferred from esp_rebuilt rule-section lineage artifacts",
        ],
    )
