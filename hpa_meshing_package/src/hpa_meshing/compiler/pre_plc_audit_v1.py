from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .topology_ir_v1 import TopologyIRV1


PrePLCAuditStatusV1 = Literal["pass", "warn", "fail", "not_evaluated"]
PrePLCAuditAssessmentV1 = Literal["observed", "observed_candidate", "inferred", "placeholder", "unsupported"]
PrePLCEvidenceLevelV1 = Literal["observed", "observed_candidate"]
PlanningPolicyFailKindV1 = Literal["bl_clearance_incompatibility"]
PlanningPolicyRecommendationKindV1 = Literal[
    "shrink_total_thickness",
    "split_region_budget",
    "stage_back_layers",
    "truncate_tip_zone",
]
PrePLCAuditCheckKindV1 = Literal[
    "segment_facet_intersection_risk",
    "facet_facet_overlap_risk",
    "boundary_recovery_error_2_risk",
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
    evidence_level: PrePLCEvidenceLevelV1 = "observed"
    residual_family: Optional[str] = None
    throw_site_label: Optional[str] = None
    throw_site_file: Optional[str] = None
    throw_site_line: Optional[int] = None
    local_surface_tags: List[int] = Field(default_factory=list)
    local_y_band: List[float] = Field(default_factory=list)
    suspicious_window: List[float] = Field(default_factory=list)
    sevent_e_type: Optional[int] = None
    degenerated_prism_seen: Optional[bool] = None
    notes: List[str] = Field(default_factory=list)


class PrePLCAuditConfigV1(BaseModel):
    first_layer_height_m: Optional[float] = None
    total_boundary_layer_thickness_m: Optional[float] = None
    observed_evidence: List[PrePLCAuditObservedEvidenceV1] = Field(default_factory=list)
    planning_budgeting: Optional["PlanningBudgetingV1"] = None


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
    observed_candidate_count: int = 0
    inferred_count: int
    placeholder_count: int
    unsupported_count: int
    observed_topology_fail_count: int = 0
    observed_candidate_topology_fail_count: int = 0
    inferred_topology_fail_count: int = 0
    bl_compatibility_fail_count: int = 0
    planning_policy_fail_count: int = 0
    planning_policy_recommendation_count: int = 0


class BLClearanceCompatibilityV1(BaseModel):
    status: PrePLCAuditStatusV1
    verdict: Literal["compatible", "insufficient_clearance", "unsupported"]
    total_bl_thickness_m: Optional[float] = None
    min_local_clearance_m: Optional[float] = None
    clearance_to_thickness_ratio: Optional[float] = None
    entity_ids: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PlanningBudgetRecommendationV1(BaseModel):
    kind: PlanningPolicyRecommendationKindV1
    direction: str
    span_y_range_m: Dict[str, float] = Field(default_factory=dict)
    delta_total_thickness_m: Optional[float] = None
    delta_total_thickness_ratio: Optional[float] = None
    suggested_truncation_start_y_m: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class PlanningManualEditCandidateV1(BaseModel):
    candidate_id: str
    target_kind: Literal["section", "region"]
    target_id: str
    planning_only: bool = True
    span_y_range_m: Dict[str, float] = Field(default_factory=dict)
    current_total_bl_thickness_m: Optional[float] = None
    min_local_clearance_m: Optional[float] = None
    current_clearance_ratio: Optional[float] = None
    ratio_deficit: Optional[float] = None
    available_budget_ratio_deficit: Optional[float] = None
    suggested_max_total_bl_thickness_m: Optional[float] = None
    suggested_thickness_reduction_m: Optional[float] = None
    suggested_truncation_start_y_m: Optional[float] = None
    suggested_split_boundary_y_m: Optional[float] = None
    suggested_layer_stage_back_direction: Optional[str] = None
    recommendation_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
    recommendation_reason: str = ""
    notes: List[str] = Field(default_factory=list)


class PlanningBudgetSectionV1(BaseModel):
    section_id: str
    span_y_m: float
    span_y_range_m: Dict[str, float] = Field(default_factory=dict)
    region_kind: str
    sample_count: int = 0
    triggered_sample_count: int = 0
    min_local_half_thickness_m: Optional[float] = None
    min_clearance_to_thickness_ratio: Optional[float] = None
    clearance_to_thickness_ratio_deficit: Optional[float] = None
    min_available_budget_ratio: Optional[float] = None
    available_budget_ratio_deficit: Optional[float] = None
    min_required_scale_for_tip_clearance: Optional[float] = None
    min_predicted_bl_top_clearance_m: Optional[float] = None
    clearance_pressure: Optional[float] = None
    recommended_action_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
    recommendations: List[PlanningBudgetRecommendationV1] = Field(default_factory=list)
    manual_edit_candidates: List[PlanningManualEditCandidateV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PlanningBudgetRegionV1(BaseModel):
    region_id: str
    region_kind: str
    section_ids: List[str] = Field(default_factory=list)
    section_count: int = 0
    span_y_range_m: Dict[str, float] = Field(default_factory=dict)
    min_clearance_to_thickness_ratio: Optional[float] = None
    clearance_to_thickness_ratio_deficit: Optional[float] = None
    min_available_budget_ratio: Optional[float] = None
    available_budget_ratio_deficit: Optional[float] = None
    peak_clearance_pressure: Optional[float] = None
    recommended_action_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
    recommendations: List[PlanningBudgetRecommendationV1] = Field(default_factory=list)
    manual_edit_candidates: List[PlanningManualEditCandidateV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PlanningBudgetingV1(BaseModel):
    status: Literal["available", "unsupported"] = "unsupported"
    total_bl_thickness_m: Optional[float] = None
    section_budgets: List[PlanningBudgetSectionV1] = Field(default_factory=list)
    region_budgets: List[PlanningBudgetRegionV1] = Field(default_factory=list)
    tightest_section_ids: List[str] = Field(default_factory=list)
    tightest_region_ids: List[str] = Field(default_factory=list)
    tightest_sections: List[PlanningBudgetSectionV1] = Field(default_factory=list)
    tightest_regions: List[PlanningBudgetRegionV1] = Field(default_factory=list)
    recommendation_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
    manual_edit_candidates: List[PlanningManualEditCandidateV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PlanningPolicyV1(BaseModel):
    status: PrePLCAuditStatusV1
    verdict: Literal["clear_for_topology_planning", "blocked_by_bl_compatibility", "unsupported"]
    blocking_kind: Optional[str] = None
    fail_kinds: List[PlanningPolicyFailKindV1] = Field(default_factory=list)
    recommendation_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PrePLCAuditReportV1(BaseModel):
    contract: str = "pre_plc_audit.v1"
    source_contract: str = "topology_ir.v1"
    config: PrePLCAuditConfigV1 = Field(default_factory=PrePLCAuditConfigV1)
    checks: List[PrePLCAuditCheckV1] = Field(default_factory=list)
    bl_clearance_compatibility: BLClearanceCompatibilityV1
    planning_budgeting: PlanningBudgetingV1 = Field(default_factory=PlanningBudgetingV1)
    planning_policy: PlanningPolicyV1
    summary: PrePLCAuditSummaryV1
    blocking_check_kinds: List[PrePLCAuditCheckKindV1] = Field(default_factory=list)
    blocking_topology_check_kinds: List[PrePLCAuditCheckKindV1] = Field(default_factory=list)
    blocking_bl_compatibility_check_kinds: List[PrePLCAuditCheckKindV1] = Field(default_factory=list)
    planning_policy_fail_kinds: List[PlanningPolicyFailKindV1] = Field(default_factory=list)
    planning_policy_recommendation_kinds: List[PlanningPolicyRecommendationKindV1] = Field(default_factory=list)
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
    evidence_metrics = {
        "evidence_level": primary.evidence_level,
        "residual_family": primary.residual_family,
        "throw_site_label": primary.throw_site_label,
        "throw_site_file": primary.throw_site_file,
        "throw_site_line": primary.throw_site_line,
        "local_surface_tags": list(primary.local_surface_tags),
        "local_y_band": list(primary.local_y_band),
        "suspicious_window": list(primary.suspicious_window),
        "sevent_e_type": primary.sevent_e_type,
        "degenerated_prism_seen": primary.degenerated_prism_seen,
    }
    return PrePLCAuditCheckV1(
        kind=kind,
        status="fail",
        assessment=primary.evidence_level,
        implemented=True,
        summary=summary,
        entity_ids=[evidence.fixture_id for evidence in evidences],
        metrics={
            "observed_fixture_count": len(evidences),
            "selected_section_y_le_m": list(primary.selected_section_y_le_m),
            **{
                key: value
                for key, value in evidence_metrics.items()
                if value is not None and value != []
            },
        },
        notes=[
            primary.error_text,
            *(
                [f"residual_family={primary.residual_family}"]
                if primary.residual_family
                else []
            ),
            *list(primary.notes),
        ],
    )


def _is_topology_check(kind: PrePLCAuditCheckKindV1) -> bool:
    return kind in {
        "segment_facet_intersection_risk",
        "facet_facet_overlap_risk",
        "boundary_recovery_error_2_risk",
        "degenerated_prism_risk",
        "manifold_loop_consistency",
    }


def _is_bl_compatibility_check(kind: PrePLCAuditCheckKindV1) -> bool:
    return kind in {
        "extrusion_self_contact_risk",
        "local_clearance_vs_first_layer_height",
    }


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


def _boundary_recovery_error_2_check(
    ir: TopologyIRV1,
    config: PrePLCAuditConfigV1,
) -> PrePLCAuditCheckV1:
    observed = _observed_evidence_for_kind(config, "boundary_recovery_error_2_risk")
    if observed:
        has_failed_steiner = any(
            evidence.residual_family == "boundary_recovery_error_2_recoversegment_failed_insert_steiner"
            for evidence in observed
        )
        return _observed_check(
            kind="boundary_recovery_error_2_risk",
            evidences=observed,
            summary=(
                "Observed-candidate recoversegment failed-Steiner boundary-recovery `error 2` family "
                "in the shell_v4-derived PLC reproducer fixture."
                if has_failed_steiner
                else (
                    "Observed post-band transition boundary-recovery `error 2` failure in the "
                    "shell_v4-derived PLC reproducer fixture."
                )
            ),
        )
    return PrePLCAuditCheckV1(
        kind="boundary_recovery_error_2_risk",
        status="not_evaluated",
        assessment="placeholder",
        implemented=False,
        summary="No boundary-recovery `error 2` reproducer evidence is available yet.",
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


def _bl_clearance_compatibility_from_check(
    check: PrePLCAuditCheckV1,
) -> BLClearanceCompatibilityV1:
    if check.status == "not_evaluated":
        return BLClearanceCompatibilityV1(
            status="not_evaluated",
            verdict="unsupported",
            notes=list(check.notes),
        )
    ratio = check.metrics.get("min_clearance_to_total_thickness_ratio")
    return BLClearanceCompatibilityV1(
        status=check.status,
        verdict="compatible" if check.status == "pass" else "insufficient_clearance",
        total_bl_thickness_m=check.metrics.get("total_boundary_layer_thickness_m"),
        min_local_clearance_m=check.metrics.get("min_local_clearance_m"),
        clearance_to_thickness_ratio=ratio,
        entity_ids=list(check.entity_ids),
        notes=list(check.notes),
    )


def _planning_policy_from_bl_clearance(
    bl_clearance_compatibility: BLClearanceCompatibilityV1,
    planning_budgeting: PlanningBudgetingV1,
) -> PlanningPolicyV1:
    recommendation_kinds = list(planning_budgeting.recommendation_kinds)
    if bl_clearance_compatibility.verdict == "unsupported":
        return PlanningPolicyV1(
            status="not_evaluated",
            verdict="unsupported",
            recommendation_kinds=recommendation_kinds,
            notes=[
                "Need a BL-thickness versus local-clearance comparison before promoting this into a planning policy verdict.",
                *(
                    ["Budgeting recommendations remain unavailable until sectionwise/regionwise evidence is provided."]
                    if planning_budgeting.status != "available"
                    else ["Available budgeting recommendations are still plan-only and must not mutate geometry."]
                ),
            ],
        )
    if bl_clearance_compatibility.verdict == "insufficient_clearance":
        return PlanningPolicyV1(
            status="fail",
            verdict="blocked_by_bl_compatibility",
            blocking_kind="bl_compatibility_policy_fail",
            fail_kinds=["bl_clearance_incompatibility"],
            recommendation_kinds=recommendation_kinds,
            notes=[
                "BL compatibility is a separate planning-policy block and should not be misread as a topology-operator miss.",
                "Budgeting recommendations remain planning-only guidance and must not be auto-applied to geometry.",
            ],
        )
    return PlanningPolicyV1(
        status="pass",
        verdict="clear_for_topology_planning",
        recommendation_kinds=recommendation_kinds,
        notes=["No BL-compatibility planning-policy block is currently raised."],
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
        _boundary_recovery_error_2_check(ir, resolved_config),
        _extrusion_self_contact_check(ir, resolved_config),
        _degenerated_prism_check(ir, resolved_config),
        _local_clearance_check(ir, resolved_config),
        _manifold_loop_consistency_check(ir),
    ]
    checks_by_kind = {check.kind: check for check in checks}
    highest_status = max((check.status for check in checks), key=_status_rank)
    blocking_check_kinds = [
        check.kind
        for check in checks
        if check.status == "fail"
    ]
    blocking_topology_check_kinds = [
        check.kind for check in checks if check.status == "fail" and _is_topology_check(check.kind)
    ]
    blocking_bl_compatibility_check_kinds = [
        check.kind for check in checks if check.status == "fail" and _is_bl_compatibility_check(check.kind)
    ]
    warning_count = sum(1 for check in checks if check.status == "warn")
    not_evaluated_count = sum(1 for check in checks if check.status == "not_evaluated")
    observed_count = sum(1 for check in checks if check.assessment == "observed")
    observed_candidate_count = sum(1 for check in checks if check.assessment == "observed_candidate")
    inferred_count = sum(1 for check in checks if check.assessment == "inferred")
    placeholder_count = sum(1 for check in checks if check.assessment == "placeholder")
    unsupported_count = sum(1 for check in checks if check.assessment == "unsupported")
    observed_topology_fail_count = sum(
        1
        for check in checks
        if check.status == "fail" and check.assessment == "observed" and _is_topology_check(check.kind)
    )
    observed_candidate_topology_fail_count = sum(
        1
        for check in checks
        if check.status == "fail" and check.assessment == "observed_candidate" and _is_topology_check(check.kind)
    )
    inferred_topology_fail_count = sum(
        1
        for check in checks
        if check.status == "fail" and check.assessment == "inferred" and _is_topology_check(check.kind)
    )
    bl_compatibility_fail_count = sum(
        1
        for check in checks
        if check.status == "fail" and _is_bl_compatibility_check(check.kind)
    )
    planning_budgeting = resolved_config.planning_budgeting or PlanningBudgetingV1(
        status="unsupported",
        notes=[
            "Sectionwise/regionwise budgeting evidence was not supplied for this audit run.",
        ],
    )
    bl_clearance_compatibility = _bl_clearance_compatibility_from_check(
        checks_by_kind["extrusion_self_contact_risk"]
    )
    planning_policy = _planning_policy_from_bl_clearance(
        bl_clearance_compatibility,
        planning_budgeting,
    )
    return PrePLCAuditReportV1(
        config=resolved_config,
        checks=checks,
        bl_clearance_compatibility=bl_clearance_compatibility,
        planning_budgeting=planning_budgeting,
        planning_policy=planning_policy,
        summary=PrePLCAuditSummaryV1(
            highest_status=highest_status,
            blocker_count=len(blocking_check_kinds),
            warning_count=warning_count,
            not_evaluated_count=not_evaluated_count,
            observed_count=observed_count,
            observed_candidate_count=observed_candidate_count,
            inferred_count=inferred_count,
            placeholder_count=placeholder_count,
            unsupported_count=unsupported_count,
            observed_topology_fail_count=observed_topology_fail_count,
            observed_candidate_topology_fail_count=observed_candidate_topology_fail_count,
            inferred_topology_fail_count=inferred_topology_fail_count,
            bl_compatibility_fail_count=bl_compatibility_fail_count,
            planning_policy_fail_count=len(planning_policy.fail_kinds),
            planning_policy_recommendation_count=len(planning_policy.recommendation_kinds),
        ),
        blocking_check_kinds=blocking_check_kinds,
        blocking_topology_check_kinds=blocking_topology_check_kinds,
        blocking_bl_compatibility_check_kinds=blocking_bl_compatibility_check_kinds,
        planning_policy_fail_kinds=list(planning_policy.fail_kinds),
        planning_policy_recommendation_kinds=list(planning_policy.recommendation_kinds),
        notes=[
            "pre_plc_audit.v1 is a front-loaded risk audit, not a claim that PLC repair is implemented",
            "BL thickness / clearance compatibility is reported separately from observed or inferred topology failures.",
            "planning_policy captures route-level blocks that should remain separate from topology-family repair progress.",
            "planning_budgeting carries plan-only sectionwise/regionwise advice and must not be misread as runtime mutation.",
        ],
    )
