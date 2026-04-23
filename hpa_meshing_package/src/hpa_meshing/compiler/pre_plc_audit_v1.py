from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .topology_ir_v1 import TopologyIRV1


PrePLCAuditStatusV1 = Literal["pass", "warn", "fail", "not_evaluated"]
PrePLCAuditAssessmentV1 = Literal["observed", "inferred", "placeholder", "unsupported"]
PrePLCAuditCheckKindV1 = Literal[
    "segment_facet_intersection_risk",
    "facet_facet_overlap_risk",
    "extrusion_self_contact_risk",
    "degenerated_prism_risk",
    "local_clearance_vs_first_layer_height",
    "manifold_loop_consistency",
]


class PrePLCAuditObservedEvidenceV1(BaseModel):
    fixture_id: str
    check_kind: PrePLCAuditCheckKindV1
    error_text: str
    selected_section_y_le_m: List[float] = Field(default_factory=list)
    report_path: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class PrePLCAuditConfigV1(BaseModel):
    first_layer_height_m: Optional[float] = None
    total_boundary_layer_thickness_m: Optional[float] = None
    observed_evidence: List[PrePLCAuditObservedEvidenceV1] = Field(default_factory=list)


class PrePLCAuditCheckV1(BaseModel):
    kind: PrePLCAuditCheckKindV1
    status: PrePLCAuditStatusV1
    assessment: PrePLCAuditAssessmentV1
    implemented: bool
    summary: str
    entity_ids: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class PrePLCAuditSummaryV1(BaseModel):
    highest_status: PrePLCAuditStatusV1
    blocker_count: int
    warning_count: int
    not_evaluated_count: int
    observed_count: int
    inferred_count: int
    placeholder_count: int
    unsupported_count: int


class PrePLCAuditReportV1(BaseModel):
    contract: str = "pre_plc_audit.v1"
    source_contract: str = "topology_ir.v1"
    config: PrePLCAuditConfigV1 = Field(default_factory=PrePLCAuditConfigV1)
    checks: List[PrePLCAuditCheckV1] = Field(default_factory=list)
    summary: PrePLCAuditSummaryV1
    blocking_check_kinds: List[PrePLCAuditCheckKindV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


def _status_rank(status: PrePLCAuditStatusV1) -> int:
    return {
        "fail": 3,
        "warn": 2,
        "pass": 1,
        "not_evaluated": 0,
    }[status]


def _observed_evidence_for_kind(
    config: PrePLCAuditConfigV1,
    kind: PrePLCAuditCheckKindV1,
) -> List[PrePLCAuditObservedEvidenceV1]:
    return [evidence for evidence in config.observed_evidence if evidence.check_kind == kind]


def _observed_check(
    *,
    kind: PrePLCAuditCheckKindV1,
    evidences: List[PrePLCAuditObservedEvidenceV1],
    summary: str,
) -> PrePLCAuditCheckV1:
    primary = evidences[0]
    return PrePLCAuditCheckV1(
        kind=kind,
        status="fail",
        assessment="observed",
        implemented=True,
        summary=summary,
        entity_ids=[evidence.fixture_id for evidence in evidences],
        metrics={
            "observed_fixture_count": len(evidences),
            "selected_section_y_le_m": list(primary.selected_section_y_le_m),
        },
        notes=[primary.error_text, *list(primary.notes)],
    )


def _segment_facet_intersection_check(
    ir: TopologyIRV1,
    config: PrePLCAuditConfigV1,
) -> PrePLCAuditCheckV1:
    observed = _observed_evidence_for_kind(config, "segment_facet_intersection_risk")
    if observed:
        return _observed_check(
            kind="segment_facet_intersection_risk",
            evidences=observed,
            summary="Observed segment-facet intersection failure in the shell_v4-derived PLC reproducer fixture.",
        )
    risky_patches = [
        patch.patch_id
        for patch in ir.patches
        if patch.metadata.get("segment_facet_intersection_risk") is True
    ]
    if risky_patches:
        return PrePLCAuditCheckV1(
            kind="segment_facet_intersection_risk",
            status="fail",
            assessment="inferred",
            implemented=True,
            summary="Segment-facet intersection risk is inferred from topology descriptors already flagged on this family.",
            entity_ids=risky_patches,
        )
    return PrePLCAuditCheckV1(
        kind="segment_facet_intersection_risk",
        status="not_evaluated",
        assessment="placeholder",
        implemented=False,
        summary="No segment-facet reproducer evidence or descriptor-level inference is available yet.",
    )


def _facet_facet_overlap_check(
    ir: TopologyIRV1,
    config: PrePLCAuditConfigV1,
) -> PrePLCAuditCheckV1:
    observed = _observed_evidence_for_kind(config, "facet_facet_overlap_risk")
    if observed:
        return _observed_check(
            kind="facet_facet_overlap_risk",
            evidences=observed,
            summary="Observed facet-facet overlap failure in the shell_v4-derived PLC reproducer fixture.",
        )
    risky_patches = [
        patch.patch_id
        for patch in ir.patches
        if patch.metadata.get("facet_facet_overlap_risk") is True
    ]
    if risky_patches:
        return PrePLCAuditCheckV1(
            kind="facet_facet_overlap_risk",
            status="fail",
            assessment="inferred",
            implemented=True,
            summary="Facet-facet overlap risk is inferred from topology descriptors already flagged on this family.",
            entity_ids=risky_patches,
        )
    return PrePLCAuditCheckV1(
        kind="facet_facet_overlap_risk",
        status="not_evaluated",
        assessment="placeholder",
        implemented=False,
        summary="No facet-facet overlap evidence or descriptor-level inference is available yet.",
    )


def _extrusion_self_contact_check(
    ir: TopologyIRV1,
    config: PrePLCAuditConfigV1,
) -> PrePLCAuditCheckV1:
    clearance_payloads = [
        (patch.patch_id, patch.local_descriptors.local_clearance_m)
        for patch in ir.patches
        if patch.local_descriptors.local_clearance_m is not None
    ]
    if config.total_boundary_layer_thickness_m is None or not clearance_payloads:
        return PrePLCAuditCheckV1(
            kind="extrusion_self_contact_risk",
            status="not_evaluated",
            assessment="unsupported",
            implemented=False,
            summary="Need total boundary-layer thickness and local clearance descriptors to infer extrusion self-contact risk.",
            notes=[
                *(["missing_total_boundary_layer_thickness_m"] if config.total_boundary_layer_thickness_m is None else []),
                *(["missing_local_clearance_descriptors"] if not clearance_payloads else []),
            ],
        )
    total_thickness_m = float(config.total_boundary_layer_thickness_m)
    risky_patches = [
        patch_id
        for patch_id, clearance_m in clearance_payloads
        if float(clearance_m) < total_thickness_m
    ]
    min_clearance = min(float(clearance_m) for _, clearance_m in clearance_payloads)
    if risky_patches:
        return PrePLCAuditCheckV1(
            kind="extrusion_self_contact_risk",
            status="fail",
            assessment="inferred",
            implemented=True,
            summary="Extrusion self-contact risk is inferred because local clearance falls below the requested total BL thickness.",
            entity_ids=risky_patches,
            metrics={
                "total_boundary_layer_thickness_m": total_thickness_m,
                "min_local_clearance_m": min_clearance,
                "min_clearance_to_total_thickness_ratio": (
                    float(min_clearance / total_thickness_m) if total_thickness_m > 0.0 else None
                ),
            },
        )
    return PrePLCAuditCheckV1(
        kind="extrusion_self_contact_risk",
        status="pass",
        assessment="inferred",
        implemented=True,
        summary="Available local clearance estimates stay above the requested total BL thickness.",
        metrics={
            "total_boundary_layer_thickness_m": total_thickness_m,
            "min_local_clearance_m": min_clearance,
            "min_clearance_to_total_thickness_ratio": (
                float(min_clearance / total_thickness_m) if total_thickness_m > 0.0 else None
            ),
        },
    )


def _degenerated_prism_check(
    ir: TopologyIRV1,
    config: PrePLCAuditConfigV1,
) -> PrePLCAuditCheckV1:
    observed = _observed_evidence_for_kind(config, "degenerated_prism_risk")
    if observed:
        return _observed_check(
            kind="degenerated_prism_risk",
            evidences=observed,
            summary="Observed degenerated-prism warnings in the shell_v4-derived PLC reproducer fixture.",
        )
    risky_patches = [
        patch.patch_id
        for patch in ir.patches
        if patch.local_descriptors.collapse_indicators.get("collapsed_patch") is True
    ]
    if risky_patches:
        return PrePLCAuditCheckV1(
            kind="degenerated_prism_risk",
            status="warn",
            assessment="inferred",
            implemented=True,
            summary="Collapsed patch indicators suggest prism degeneration risk under BL extrusion.",
            entity_ids=risky_patches,
        )
    return PrePLCAuditCheckV1(
        kind="degenerated_prism_risk",
        status="not_evaluated",
        assessment="placeholder",
        implemented=False,
        summary="No prism-degeneration evidence or collapse indicators are available yet.",
    )


def _local_clearance_check(ir: TopologyIRV1, config: PrePLCAuditConfigV1) -> PrePLCAuditCheckV1:
    clearance_payloads = [
        (patch.patch_id, patch.local_descriptors.local_clearance_m)
        for patch in ir.patches
        if patch.local_descriptors.local_clearance_m is not None
    ]
    if config.first_layer_height_m is None or not clearance_payloads:
        return PrePLCAuditCheckV1(
            kind="local_clearance_vs_first_layer_height",
            status="not_evaluated",
            assessment="unsupported",
            implemented=False,
            summary="Need both first-layer height and local clearance descriptors before evaluating this guard.",
        )

    failing_patch_ids = [
        patch_id
        for patch_id, clearance_m in clearance_payloads
        if float(clearance_m) < float(config.first_layer_height_m)
    ]
    min_clearance = min(float(clearance_m) for _, clearance_m in clearance_payloads)
    if failing_patch_ids:
        return PrePLCAuditCheckV1(
            kind="local_clearance_vs_first_layer_height",
            status="fail",
            assessment="inferred",
            implemented=True,
            summary="At least one local clearance estimate is smaller than the requested first-layer height.",
            entity_ids=failing_patch_ids,
            metrics={
                "first_layer_height_m": float(config.first_layer_height_m),
                "min_local_clearance_m": float(min_clearance),
            },
        )
    return PrePLCAuditCheckV1(
        kind="local_clearance_vs_first_layer_height",
        status="pass",
        assessment="inferred",
        implemented=True,
        summary="Available local clearance estimates stay above the requested first-layer height.",
        metrics={
            "first_layer_height_m": float(config.first_layer_height_m),
            "min_local_clearance_m": float(min_clearance),
        },
    )


def _manifold_loop_consistency_check(ir: TopologyIRV1) -> PrePLCAuditCheckV1:
    curve_ids = {curve.curve_id for curve in ir.curves}
    invalid_loops = [
        loop.loop_id
        for loop in ir.loops
        if not loop.is_closed or len(loop.curve_ids) < 3 or any(curve_id not in curve_ids for curve_id in loop.curve_ids)
    ]
    if invalid_loops:
        return PrePLCAuditCheckV1(
            kind="manifold_loop_consistency",
            status="fail",
            assessment="inferred",
            implemented=True,
            summary="At least one loop is open or references missing curves.",
            entity_ids=invalid_loops,
        )
    return PrePLCAuditCheckV1(
        kind="manifold_loop_consistency",
        status="pass",
        assessment="inferred",
        implemented=True,
        summary="All inferred loops are closed and reference known curves.",
        entity_ids=[loop.loop_id for loop in ir.loops],
    )


def run_pre_plc_audit_v1(
    ir: TopologyIRV1,
    *,
    config: Optional[PrePLCAuditConfigV1] = None,
) -> PrePLCAuditReportV1:
    resolved_config = config or PrePLCAuditConfigV1()
    checks = [
        _segment_facet_intersection_check(ir, resolved_config),
        _facet_facet_overlap_check(ir, resolved_config),
        _extrusion_self_contact_check(ir, resolved_config),
        _degenerated_prism_check(ir, resolved_config),
        _local_clearance_check(ir, resolved_config),
        _manifold_loop_consistency_check(ir),
    ]
    highest_status = max((check.status for check in checks), key=_status_rank)
    blocking_check_kinds = [
        check.kind
        for check in checks
        if check.status == "fail"
    ]
    warning_count = sum(1 for check in checks if check.status == "warn")
    not_evaluated_count = sum(1 for check in checks if check.status == "not_evaluated")
    observed_count = sum(1 for check in checks if check.assessment == "observed")
    inferred_count = sum(1 for check in checks if check.assessment == "inferred")
    placeholder_count = sum(1 for check in checks if check.assessment == "placeholder")
    unsupported_count = sum(1 for check in checks if check.assessment == "unsupported")
    return PrePLCAuditReportV1(
        config=resolved_config,
        checks=checks,
        summary=PrePLCAuditSummaryV1(
            highest_status=highest_status,
            blocker_count=len(blocking_check_kinds),
            warning_count=warning_count,
            not_evaluated_count=not_evaluated_count,
            observed_count=observed_count,
            inferred_count=inferred_count,
            placeholder_count=placeholder_count,
            unsupported_count=unsupported_count,
        ),
        blocking_check_kinds=blocking_check_kinds,
        notes=[
            "pre_plc_audit.v1 is a front-loaded risk audit, not a claim that PLC repair is implemented",
        ],
    )
