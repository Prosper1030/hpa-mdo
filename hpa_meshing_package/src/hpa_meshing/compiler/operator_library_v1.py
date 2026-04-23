from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .motif_registry_v1 import MotifMatchV1
from .topology_ir_v1 import TopologyIRV1


OperatorNameV1 = Literal[
    "root_closure_from_bl_faces",
    "closure_ring_exact_wire_surface_fill",
    "extbl_termination_fallback_for_collapsed_endcap",
    "local_truncation_protection",
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
            "local_truncation_protection": OperatorContractV1(
                operator_name="local_truncation_protection",
                implementation_status="skeleton",
                supported_motif_kinds=["TRUNCATION_CONNECTOR_BAND"],
                expected_artifact_keys=["local_truncation_protection_plan", "local_truncation_protection_report"],
                report_key="local_truncation_protection",
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
