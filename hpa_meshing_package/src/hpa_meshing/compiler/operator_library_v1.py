from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .motif_registry_v1 import MotifMatchV1
from .topology_ir_v1 import TopologyIRV1


OperatorNameV1 = Literal[
    "root_closure_from_bl_faces",
    "closure_ring_exact_wire_surface_fill",
    "extbl_termination_fallback_for_collapsed_endcap",
    "regularize_truncation_connector_band",
    "prototype_split_post_band_transition",
    "prototype_regularize_post_transition_boundary_recovery",
    "reject_unsupported_plc_risk_family",
]


class OperatorContractV1(BaseModel):
    operator_name: OperatorNameV1
    implementation_status: Literal["skeleton", "implemented"]
    supported_motif_kinds: List[str] = Field(default_factory=list)
    expected_artifact_keys: List[str] = Field(default_factory=list)
    report_key: str
    notes: List[str] = Field(default_factory=list)


class OperatorResultV1(BaseModel):
    contract: str = "operator_result.v1"
    operator_name: OperatorNameV1
    motif_kind: str
    status: Literal["not_implemented", "rejected", "applied"]
    applied: bool = False
    report_key: str
    expected_artifact_keys: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class OperatorPlanEntryV1(BaseModel):
    motif_id: str
    motif_kind: str
    admissible_operators: List[str] = Field(default_factory=list)
    selected_operator: Optional[str] = None
    execution_status: str = "plan_only"
    execution_gate: str = "plan_only"
    expected_artifact_keys: List[str] = Field(default_factory=list)


class OperatorPlanV1(BaseModel):
    contract: str = "operator_plan.v1"
    execution_gate: str = "plan_only"
    entries: List[OperatorPlanEntryV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class TruncationConnectorBandRegularizationPlanV1(BaseModel):
    contract: str = "truncation_connector_band_regularization_plan.v1"
    applicable: bool
    reject_reasons: List[str] = Field(default_factory=list)
    connector_band_patch_ids: List[str] = Field(default_factory=list)
    pre_band_support_patch_ids: List[str] = Field(default_factory=list)
    drop_section_y_le_m: List[float] = Field(default_factory=list)
    keep_section_y_le_m: List[float] = Field(default_factory=list)
    root_y_le_m: Optional[float] = None
    connector_band_start_y_le_m: Optional[float] = None
    truncation_start_y_le_m: Optional[float] = None
    tip_y_le_m: Optional[float] = None
    limitation: str = "v1_only_regularizes_one_extra_pre_band_support_section"


class PostBandTransitionSplitPlanV1(BaseModel):
    contract: str = "post_band_transition_split_plan.v1"
    applicable: bool
    reject_reasons: List[str] = Field(default_factory=list)
    blocking_topology_check_kinds: List[str] = Field(default_factory=list)
    root_support_patch_ids: List[str] = Field(default_factory=list)
    connector_band_patch_ids: List[str] = Field(default_factory=list)
    transition_patch_ids: List[str] = Field(default_factory=list)
    transition_start_y_le_m: Optional[float] = None
    tip_y_le_m: Optional[float] = None
    transition_span_m: Optional[float] = None
    split_fraction: float = 1.0 / 3.0
    proposed_split_y_le_m: Optional[float] = None
    limitation: str = "prototype_only_inserts_one_synthetic_post_band_transition_section"


class PostTransitionBoundaryRecoveryRegularizationPlanV1(BaseModel):
    contract: str = "post_transition_boundary_recovery_regularization_plan.v1"
    applicable: bool
    reject_reasons: List[str] = Field(default_factory=list)
    blocking_topology_check_kinds: List[str] = Field(default_factory=list)
    connector_band_patch_ids: List[str] = Field(default_factory=list)
    transition_guard_patch_ids: List[str] = Field(default_factory=list)
    transition_terminal_patch_ids: List[str] = Field(default_factory=list)
    transition_start_y_le_m: Optional[float] = None
    transition_guard_y_le_m: Optional[float] = None
    tip_y_le_m: Optional[float] = None
    transition_guard_span_m: Optional[float] = None
    transition_terminal_span_m: Optional[float] = None
    geometry_contact_locus_kind: Optional[str] = None
    acts_on_interval_role: str = "post_band_transition_guard_to_tip_terminal"
    mutation_kind: str = "insert_transition_terminal_relief_section"
    relief_fraction: float = 0.4
    proposed_relief_y_le_m: Optional[float] = None
    contact_locus_span_m_before: Optional[float] = None
    contact_locus_span_m_after: Optional[float] = None
    limitation: str = (
        "prototype_only_narrows_the_guard_to_tip_contact_locus_without_claiming_full_boundary_recovery_repair"
    )


def _truncation_connector_band_context(ir: TopologyIRV1) -> Dict[str, Any]:
    if not isinstance(ir.compiler_context, dict):
        return {}
    context = ir.compiler_context.get("truncation_connector_band")
    if not isinstance(context, dict):
        return {}
    return context


def _ordered_selected_section_y_le_m(context: Dict[str, Any]) -> List[float]:
    values = [float(value) for value in context.get("selected_section_y_le_m", []) if value is not None]
    ordered: List[float] = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _connector_band_regularization_plan(
    *,
    motif_match: MotifMatchV1,
    ir: TopologyIRV1,
) -> TruncationConnectorBandRegularizationPlanV1:
    context = _truncation_connector_band_context(ir)
    selected_section_y_le_m = _ordered_selected_section_y_le_m(context)
    root_y = float(context["root_y_le_m"]) if context.get("root_y_le_m") is not None else None
    connector_band_start_y = (
        float(context["connector_band_start_y_le_m"])
        if context.get("connector_band_start_y_le_m") is not None
        else None
    )
    truncation_start_y = (
        float(context["truncation_start_y_le_m"])
        if context.get("truncation_start_y_le_m") is not None
        else None
    )
    tip_y = float(context["tip_y_le_m"]) if context.get("tip_y_le_m") is not None else None

    connector_band_patch_ids = [
        patch.patch_id
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "connector_band"
    ]
    pre_band_support_patch_ids = [
        patch.patch_id
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "pre_band_support"
    ]

    reject_reasons: List[str] = []
    if not selected_section_y_le_m:
        reject_reasons.append("missing_selected_section_y_le_m")
    if root_y is None or connector_band_start_y is None or truncation_start_y is None or tip_y is None:
        reject_reasons.append("missing_connector_band_descriptors")
    if len(connector_band_patch_ids) != 1:
        reject_reasons.append("connector_band_patch_count_not_equal_to_one")

    drop_section_y_le_m = [
        float(value)
        for value in selected_section_y_le_m
        if root_y is not None
        and connector_band_start_y is not None
        and float(value) > float(root_y) + 1.0e-6
        and float(value) < float(connector_band_start_y) - 1.0e-6
    ]
    if not reject_reasons:
        if len(drop_section_y_le_m) == 0:
            reject_reasons.append("already_canonical_connector_band_family")
        elif len(drop_section_y_le_m) > 1:
            reject_reasons.append("multiple_pre_band_support_sections_out_of_scope")

    keep_section_y_le_m = [
        float(value)
        for value in selected_section_y_le_m
        if float(value) not in set(drop_section_y_le_m)
    ]
    applicable = not reject_reasons

    return TruncationConnectorBandRegularizationPlanV1(
        applicable=applicable,
        reject_reasons=reject_reasons,
        connector_band_patch_ids=connector_band_patch_ids or list(motif_match.entity_ids),
        pre_band_support_patch_ids=pre_band_support_patch_ids,
        drop_section_y_le_m=drop_section_y_le_m if applicable else [],
        keep_section_y_le_m=keep_section_y_le_m if applicable else selected_section_y_le_m,
        root_y_le_m=root_y,
        connector_band_start_y_le_m=connector_band_start_y,
        truncation_start_y_le_m=truncation_start_y,
        tip_y_le_m=tip_y,
    )


def _post_band_transition_split_plan(
    *,
    motif_match: MotifMatchV1,
    ir: TopologyIRV1,
    audit_report: Optional[Any],
) -> PostBandTransitionSplitPlanV1:
    root_support_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "root_to_terminal_support"
    ]
    connector_band_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "connector_band"
    ]
    transition_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "truncation_transition"
    ]
    pre_band_support_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "pre_band_support"
    ]
    blocking_topology_check_kinds = list(
        getattr(audit_report, "blocking_topology_check_kinds", []) or []
    )
    if not blocking_topology_check_kinds:
        blocking_topology_check_kinds = list(
            motif_match.predicate_evidence.get("blocking_topology_check_kinds", [])
        )

    reject_reasons: List[str] = []
    if len(root_support_patches) != 1:
        reject_reasons.append("root_support_patch_count_not_equal_to_one")
    if len(connector_band_patches) != 1:
        reject_reasons.append("connector_band_patch_count_not_equal_to_one")
    if len(transition_patches) != 1:
        reject_reasons.append("transition_patch_count_not_equal_to_one")
    if pre_band_support_patches:
        reject_reasons.append("family_not_canonical_connector_band")
    if "segment_facet_intersection_risk" not in blocking_topology_check_kinds:
        reject_reasons.append("missing_segment_facet_blocker")

    transition_start_y = None
    tip_y = None
    transition_span_m = None
    proposed_split_y = None
    if len(transition_patches) == 1:
        transition_patch = transition_patches[0]
        if transition_patch.metadata.get("inboard_y_le_m") is not None:
            transition_start_y = float(transition_patch.metadata["inboard_y_le_m"])
        if transition_patch.metadata.get("outboard_y_le_m") is not None:
            tip_y = float(transition_patch.metadata["outboard_y_le_m"])
        if transition_start_y is None or tip_y is None or tip_y <= transition_start_y:
            reject_reasons.append("invalid_transition_span")
        else:
            transition_span_m = float(tip_y - transition_start_y)
            proposed_split_y = float(transition_start_y + transition_span_m / 3.0)

    applicable = not reject_reasons
    return PostBandTransitionSplitPlanV1(
        applicable=applicable,
        reject_reasons=reject_reasons,
        blocking_topology_check_kinds=blocking_topology_check_kinds,
        root_support_patch_ids=[patch.patch_id for patch in root_support_patches],
        connector_band_patch_ids=[patch.patch_id for patch in connector_band_patches],
        transition_patch_ids=[patch.patch_id for patch in transition_patches],
        transition_start_y_le_m=transition_start_y,
        tip_y_le_m=tip_y,
        transition_span_m=transition_span_m,
        proposed_split_y_le_m=proposed_split_y if applicable else None,
    )


def _post_transition_boundary_recovery_regularization_plan(
    *,
    motif_match: MotifMatchV1,
    ir: TopologyIRV1,
    audit_report: Optional[Any],
) -> PostTransitionBoundaryRecoveryRegularizationPlanV1:
    connector_band_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "connector_band"
    ]
    transition_guard_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "post_band_transition_guard"
    ]
    transition_terminal_patches = [
        patch
        for patch in ir.patches
        if patch.local_descriptors.truncation_band_role.get("role") == "post_band_terminal_transition"
    ]
    blocking_topology_check_kinds = list(
        getattr(audit_report, "blocking_topology_check_kinds", []) or []
    )
    if not blocking_topology_check_kinds:
        blocking_topology_check_kinds = list(
            motif_match.predicate_evidence.get("blocking_topology_check_kinds", [])
        )

    reject_reasons: List[str] = []
    if len(connector_band_patches) != 1:
        reject_reasons.append("connector_band_patch_count_not_equal_to_one")
    if len(transition_guard_patches) != 1:
        reject_reasons.append("transition_guard_patch_count_not_equal_to_one")
    if len(transition_terminal_patches) != 1:
        reject_reasons.append("transition_terminal_patch_count_not_equal_to_one")
    if "boundary_recovery_error_2_risk" not in blocking_topology_check_kinds:
        reject_reasons.append("missing_boundary_recovery_error_2_blocker")

    guard_patch = transition_guard_patches[0] if len(transition_guard_patches) == 1 else None
    terminal_patch = transition_terminal_patches[0] if len(transition_terminal_patches) == 1 else None
    transition_start_y = guard_patch.metadata.get("inboard_y_le_m") if guard_patch is not None else None
    transition_guard_y = guard_patch.metadata.get("outboard_y_le_m") if guard_patch is not None else None
    tip_y = terminal_patch.metadata.get("outboard_y_le_m") if terminal_patch is not None else None
    if transition_start_y is None or transition_guard_y is None or tip_y is None:
        reject_reasons.append("boundary_recovery_contact_locus_not_localized")
    transition_terminal_span = None
    proposed_relief_y = None
    narrowed_contact_span = None
    if transition_guard_y is not None and tip_y is not None:
        transition_terminal_span = float(tip_y) - float(transition_guard_y)
        if transition_terminal_span <= 1.0e-6:
            reject_reasons.append("post_transition_terminal_interval_too_small")
        else:
            proposed_relief_y = round(
                float(transition_guard_y) + 0.4 * float(transition_terminal_span),
                2,
            )
            narrowed_contact_span = float(tip_y) - float(proposed_relief_y)

    applicable = not reject_reasons
    return PostTransitionBoundaryRecoveryRegularizationPlanV1(
        applicable=applicable,
        reject_reasons=reject_reasons,
        blocking_topology_check_kinds=blocking_topology_check_kinds,
        connector_band_patch_ids=[patch.patch_id for patch in connector_band_patches],
        transition_guard_patch_ids=[patch.patch_id for patch in transition_guard_patches],
        transition_terminal_patch_ids=[patch.patch_id for patch in transition_terminal_patches],
        transition_start_y_le_m=float(transition_start_y) if transition_start_y is not None else None,
        transition_guard_y_le_m=float(transition_guard_y) if transition_guard_y is not None else None,
        tip_y_le_m=float(tip_y) if tip_y is not None else None,
        transition_guard_span_m=(
            float(guard_patch.metadata.get("span_interval_m"))
            if guard_patch is not None and guard_patch.metadata.get("span_interval_m") is not None
            else None
        ),
        transition_terminal_span_m=(
            float(terminal_patch.metadata.get("span_interval_m"))
            if terminal_patch is not None and terminal_patch.metadata.get("span_interval_m") is not None
            else None
        ),
        geometry_contact_locus_kind=(
            "post_band_transition_guard_to_tip" if applicable else None
        ),
        proposed_relief_y_le_m=float(proposed_relief_y) if proposed_relief_y is not None else None,
        contact_locus_span_m_before=(
            float(transition_terminal_span) if transition_terminal_span is not None else None
        ),
        contact_locus_span_m_after=(
            float(narrowed_contact_span) if narrowed_contact_span is not None else None
        ),
    )


class OperatorLibraryV1:
    def __init__(self) -> None:
        self._contracts: Dict[str, OperatorContractV1] = {
            "root_closure_from_bl_faces": OperatorContractV1(
                operator_name="root_closure_from_bl_faces",
                implementation_status="skeleton",
                supported_motif_kinds=["ROOT_CLOSURE"],
                expected_artifact_keys=["root_closure_plan", "root_closure_report"],
                report_key="root_closure_from_bl_faces",
            ),
            "closure_ring_exact_wire_surface_fill": OperatorContractV1(
                operator_name="closure_ring_exact_wire_surface_fill",
                implementation_status="skeleton",
                supported_motif_kinds=["TRUNCATION_SEAM_REQUIRED_RING"],
                expected_artifact_keys=["closure_ring_fill_plan", "closure_ring_fill_report"],
                report_key="closure_ring_exact_wire_surface_fill",
            ),
            "extbl_termination_fallback_for_collapsed_endcap": OperatorContractV1(
                operator_name="extbl_termination_fallback_for_collapsed_endcap",
                implementation_status="skeleton",
                supported_motif_kinds=["TRIANGULAR_ENDCAP_COLLAPSED_3PATCH"],
                expected_artifact_keys=["collapsed_endcap_fallback_plan", "collapsed_endcap_fallback_report"],
                report_key="extbl_termination_fallback_for_collapsed_endcap",
            ),
            "regularize_truncation_connector_band": OperatorContractV1(
                operator_name="regularize_truncation_connector_band",
                implementation_status="implemented",
                supported_motif_kinds=["TRUNCATION_CONNECTOR_BAND"],
                expected_artifact_keys=[
                    "truncation_connector_band_regularization_plan",
                    "truncation_connector_band_regularization_report",
                ],
                report_key="truncation_connector_band_regularization",
                notes=[
                    "This operator canonicalizes one extra pre-band support strip into the 4-anchor connector-band family.",
                    "It does not claim BL thickness / local clearance compatibility is fixed.",
                ],
            ),
            "prototype_split_post_band_transition": OperatorContractV1(
                operator_name="prototype_split_post_band_transition",
                implementation_status="implemented",
                supported_motif_kinds=["CANONICAL_CONNECTOR_BAND_POST_TRANSITION"],
                expected_artifact_keys=[
                    "post_band_transition_split_plan",
                    "post_band_transition_split_report",
                ],
                report_key="post_band_transition_split",
                notes=[
                    "This is an honest executable prototype for the post-band transition family after connector-band canonicalization.",
                    "It inserts one synthetic transition-guard section but does not claim solver-entry success.",
                ],
            ),
            "prototype_regularize_post_transition_boundary_recovery": OperatorContractV1(
                operator_name="prototype_regularize_post_transition_boundary_recovery",
                implementation_status="implemented",
                supported_motif_kinds=["POST_BAND_TRANSITION_BOUNDARY_RECOVERY"],
                expected_artifact_keys=[
                    "post_transition_boundary_recovery_regularization_plan",
                    "post_transition_boundary_recovery_regularization_report",
                ],
                report_key="post_transition_boundary_recovery_regularization",
                notes=[
                    "This executable prototype applies a bounded post-band transition regularization for the boundary-recovery `error 2` family.",
                    "It narrows the guard-to-tip contact locus without claiming full boundary recovery repair.",
                ],
            ),
            "reject_unsupported_plc_risk_family": OperatorContractV1(
                operator_name="reject_unsupported_plc_risk_family",
                implementation_status="implemented",
                supported_motif_kinds=["VOLUME_ENTRY_PLC_RISK"],
                expected_artifact_keys=["unsupported_plc_risk_family_report"],
                report_key="unsupported_plc_risk_family",
            ),
        }

    def describe(self, operator_name: OperatorNameV1) -> OperatorContractV1:
        return self._contracts[str(operator_name)]

    def plan_for_matches(
        self,
        matches: List[MotifMatchV1],
        *,
        execution_gate: str = "plan_only",
    ) -> OperatorPlanV1:
        entries: List[OperatorPlanEntryV1] = []
        for match in matches:
            selected_operator = match.admissible_operators[0] if match.admissible_operators else None
            expected_artifact_keys: List[str] = []
            if selected_operator is not None:
                expected_artifact_keys = list(self.describe(selected_operator).expected_artifact_keys)
            entries.append(
                OperatorPlanEntryV1(
                    motif_id=match.motif_id,
                    motif_kind=match.kind,
                    admissible_operators=list(match.admissible_operators),
                    selected_operator=selected_operator,
                    execution_status="plan_only",
                    execution_gate=execution_gate,
                    expected_artifact_keys=expected_artifact_keys,
                )
            )
        return OperatorPlanV1(
            execution_gate=execution_gate,
            entries=entries,
            notes=[
                "operator_library.v1 plans operator landing zones but does not silently auto-repair topology families",
            ],
        )

    def execute(
        self,
        operator_name: OperatorNameV1,
        motif_match: MotifMatchV1,
        ir: TopologyIRV1,
        *,
        audit_report: Optional[Any] = None,
    ) -> OperatorResultV1:
        contract = self.describe(operator_name)
        if operator_name == "regularize_truncation_connector_band":
            regularization_plan = _connector_band_regularization_plan(
                motif_match=motif_match,
                ir=ir,
            )
            if regularization_plan.applicable:
                return OperatorResultV1(
                    operator_name=operator_name,
                    motif_kind=motif_match.kind,
                    status="applied",
                    applied=True,
                    report_key=contract.report_key,
                    expected_artifact_keys=list(contract.expected_artifact_keys),
                    details={"regularization_plan": regularization_plan.model_dump(mode="json")},
                    notes=[
                        "The operator regularizes one extra pre-band support strip into the canonical connector-band family.",
                        "Observed topology and BL compatibility remain separate follow-on judgments.",
                    ],
                )
            return OperatorResultV1(
                operator_name=operator_name,
                motif_kind=motif_match.kind,
                status="rejected",
                applied=False,
                report_key=contract.report_key,
                expected_artifact_keys=list(contract.expected_artifact_keys),
                details={"regularization_plan": regularization_plan.model_dump(mode="json")},
                notes=[
                    "The operator rejected this family honestly instead of pretending the local topology was rewritten.",
                ],
            )
        if operator_name == "prototype_split_post_band_transition":
            transition_split_plan = _post_band_transition_split_plan(
                motif_match=motif_match,
                ir=ir,
                audit_report=audit_report,
            )
            if transition_split_plan.applicable:
                return OperatorResultV1(
                    operator_name=operator_name,
                    motif_kind=motif_match.kind,
                    status="applied",
                    applied=True,
                    report_key=contract.report_key,
                    expected_artifact_keys=list(contract.expected_artifact_keys),
                    details={"transition_split_plan": transition_split_plan.model_dump(mode="json")},
                    notes=[
                        "The prototype inserts one deterministic synthetic guard section in the post-band transition interval.",
                        "A changed downstream failure kind is treated as progress evidence, not as proof of a full topology fix.",
                    ],
                )
            return OperatorResultV1(
                operator_name=operator_name,
                motif_kind=motif_match.kind,
                status="rejected",
                applied=False,
                report_key=contract.report_key,
                expected_artifact_keys=list(contract.expected_artifact_keys),
                details={"transition_split_plan": transition_split_plan.model_dump(mode="json")},
                notes=[
                    "The post-band transition prototype rejected this family honestly instead of mutating a non-canonical case.",
                ],
            )
        if operator_name == "prototype_regularize_post_transition_boundary_recovery":
            boundary_recovery_regularization_plan = _post_transition_boundary_recovery_regularization_plan(
                motif_match=motif_match,
                ir=ir,
                audit_report=audit_report,
            )
            if boundary_recovery_regularization_plan.applicable:
                return OperatorResultV1(
                    operator_name=operator_name,
                    motif_kind=motif_match.kind,
                    status="applied",
                    applied=True,
                    report_key=contract.report_key,
                    expected_artifact_keys=list(contract.expected_artifact_keys),
                    details={
                        "boundary_recovery_regularization_plan": boundary_recovery_regularization_plan.model_dump(
                            mode="json"
                        )
                    },
                    notes=[
                        "The executable prototype inserts one deterministic relief section inside the post-band transition terminal interval.",
                        "A narrowed contact locus is progress evidence, not a claim that the PLC boundary recovery path is fully repaired.",
                    ],
                )
            return OperatorResultV1(
                operator_name=operator_name,
                motif_kind=motif_match.kind,
                status="rejected",
                applied=False,
                report_key=contract.report_key,
                expected_artifact_keys=list(contract.expected_artifact_keys),
                details={
                    "boundary_recovery_regularization_plan": boundary_recovery_regularization_plan.model_dump(
                        mode="json"
                    )
                },
                notes=[
                    "The boundary-recovery regularization rejected this family honestly instead of overstating repair progress.",
                ],
            )
        if operator_name == "reject_unsupported_plc_risk_family":
            blocking_check_kinds = [
                check.kind
                for check in getattr(audit_report, "checks", [])
                if getattr(check, "status", None) == "fail"
            ]
            if not blocking_check_kinds:
                blocking_check_kinds = list(
                    motif_match.predicate_evidence.get("blocking_check_kinds", [])
                )
            return OperatorResultV1(
                operator_name=operator_name,
                motif_kind=motif_match.kind,
                status="rejected",
                applied=False,
                report_key=contract.report_key,
                expected_artifact_keys=list(contract.expected_artifact_keys),
                details={
                    "blocking_check_kinds": blocking_check_kinds,
                    "rejected_entity_ids": list(motif_match.entity_ids),
                    "reason": "plc_risk_family_is_out_of_scope_for_v1_skeleton",
                },
                notes=[
                    "This is an explicit deterministic reject, not a silent drop.",
                ],
            )
        return OperatorResultV1(
            operator_name=operator_name,
            motif_kind=motif_match.kind,
            status="not_implemented",
            applied=False,
            report_key=contract.report_key,
            expected_artifact_keys=list(contract.expected_artifact_keys),
            details={
                "supported_motif_kinds": list(contract.supported_motif_kinds),
                "matched_entity_ids": list(motif_match.entity_ids),
                "topology_patch_count": len(ir.patches),
            },
            notes=[
                "v1 exposes the operator contract and artifact landing zone but does not claim the repair is implemented",
            ],
        )
