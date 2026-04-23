from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .topology_ir_v1 import TopologyIRV1


MotifKindV1 = Literal[
    "ROOT_CLOSURE",
    "TRUNCATION_SEAM_REQUIRED_RING",
    "TRIANGULAR_ENDCAP_COLLAPSED_3PATCH",
    "TRUNCATION_CONNECTOR_BAND",
    "VOLUME_ENTRY_PLC_RISK",
]


class MotifRegistryEntryV1(BaseModel):
    kind: MotifKindV1
    admissible_operators: List[str] = Field(default_factory=list)
    reject_conditions: List[str] = Field(default_factory=list)
    unsupported_conditions: List[str] = Field(default_factory=list)
    expected_artifact_keys: List[str] = Field(default_factory=list)


class MotifMatchV1(BaseModel):
    motif_id: str
    kind: MotifKindV1
    entity_ids: List[str] = Field(default_factory=list)
    summary: str
    predicate_evidence: Dict[str, Any] = Field(default_factory=dict)
    admissible_operators: List[str] = Field(default_factory=list)
    reject_conditions: List[str] = Field(default_factory=list)
    unsupported_conditions: List[str] = Field(default_factory=list)
    expected_artifact_keys: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MotifRegistryReportV1(BaseModel):
    contract: str = "motif_registry.v1"
    matches: List[MotifMatchV1] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MotifRegistryV1:
    def __init__(self) -> None:
        self._entries: Dict[MotifKindV1, MotifRegistryEntryV1] = {
            "ROOT_CLOSURE": MotifRegistryEntryV1(
                kind="ROOT_CLOSURE",
                admissible_operators=["root_closure_from_bl_faces"],
                reject_conditions=["missing_root_closure_faces"],
                unsupported_conditions=["no_half_wing_root_split_available"],
                expected_artifact_keys=["root_closure_plan", "root_closure_report"],
            ),
            "TRUNCATION_SEAM_REQUIRED_RING": MotifRegistryEntryV1(
                kind="TRUNCATION_SEAM_REQUIRED_RING",
                admissible_operators=["closure_ring_exact_wire_surface_fill"],
                reject_conditions=["missing_truncation_seam_inputs"],
                unsupported_conditions=["truncation_loop_family_not_classified"],
                expected_artifact_keys=["closure_ring_fill_plan", "closure_ring_fill_report"],
            ),
            "TRIANGULAR_ENDCAP_COLLAPSED_3PATCH": MotifRegistryEntryV1(
                kind="TRIANGULAR_ENDCAP_COLLAPSED_3PATCH",
                admissible_operators=["extbl_termination_fallback_for_collapsed_endcap"],
                reject_conditions=["collapsed_patch_count_not_equal_to_three"],
                unsupported_conditions=["collapsed_family_not_localized"],
                expected_artifact_keys=["collapsed_endcap_fallback_plan", "collapsed_endcap_fallback_report"],
            ),
            "TRUNCATION_CONNECTOR_BAND": MotifRegistryEntryV1(
                kind="TRUNCATION_CONNECTOR_BAND",
                admissible_operators=["local_truncation_protection"],
                reject_conditions=["missing_connector_band_span"],
                unsupported_conditions=["connector_band_not_classified"],
                expected_artifact_keys=["local_truncation_protection_plan", "local_truncation_protection_report"],
            ),
            "VOLUME_ENTRY_PLC_RISK": MotifRegistryEntryV1(
                kind="VOLUME_ENTRY_PLC_RISK",
                admissible_operators=["reject_unsupported_plc_risk_family"],
                reject_conditions=["missing_pre_plc_audit"],
                unsupported_conditions=["plc_reproducer_not_implemented_in_v1"],
                expected_artifact_keys=["unsupported_plc_risk_family_report"],
            ),
        }

    def describe(self, kind: MotifKindV1) -> MotifRegistryEntryV1:
        return self._entries[kind]

    def detect(
        self,
        ir: TopologyIRV1,
        audit_report: Optional[Any] = None,
    ) -> MotifRegistryReportV1:
        matches: List[MotifMatchV1] = []
        matches.extend(self._match_root_closure(ir))
        matches.extend(self._match_truncation_seam_required_ring(ir))
        matches.extend(self._match_triangular_endcap_collapsed_3patch(ir))
        matches.extend(self._match_truncation_connector_band(ir))
        matches.extend(self._match_volume_entry_plc_risk(audit_report))
        return MotifRegistryReportV1(
            matches=matches,
            notes=["motif_registry.v1 is topology-family classification, not surface-tag patching"],
        )

    def _match_root_closure(self, ir: TopologyIRV1) -> List[MotifMatchV1]:
        patch_ids = [
            patch.patch_id
            for patch in ir.patches
            if patch.closure_adjacency.closure_kind == "symmetry_or_root"
        ]
        if not patch_ids:
            return []
        entry = self.describe("ROOT_CLOSURE")
        return [
            MotifMatchV1(
                motif_id="ROOT_CLOSURE:0",
                kind="ROOT_CLOSURE",
                entity_ids=patch_ids,
                summary="Local strip topology includes a symmetry/root-adjacent closure family.",
                predicate_evidence={"patch_count": len(patch_ids)},
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]

    def _match_truncation_seam_required_ring(self, ir: TopologyIRV1) -> List[MotifMatchV1]:
        patch_ids = [
            patch.patch_id
            for patch in ir.patches
            if patch.local_descriptors.collapse_indicators.get("tip_terminal_candidate") is True
        ]
        if not patch_ids:
            return []
        entry = self.describe("TRUNCATION_SEAM_REQUIRED_RING")
        return [
            MotifMatchV1(
                motif_id="TRUNCATION_SEAM_REQUIRED_RING:0",
                kind="TRUNCATION_SEAM_REQUIRED_RING",
                entity_ids=patch_ids,
                summary="Tip-adjacent seam strips require a truncation closure-ring treatment family.",
                predicate_evidence={"tip_terminal_candidate_count": len(patch_ids)},
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]

    def _match_triangular_endcap_collapsed_3patch(self, ir: TopologyIRV1) -> List[MotifMatchV1]:
        patch_ids = [
            patch.patch_id
            for patch in ir.patches
            if patch.source_patch_family == "tip_endcap_patch"
            and patch.local_descriptors.collapse_indicators.get("collapsed_patch") is True
        ]
        if len(patch_ids) != 3:
            return []
        entry = self.describe("TRIANGULAR_ENDCAP_COLLAPSED_3PATCH")
        return [
            MotifMatchV1(
                motif_id="TRIANGULAR_ENDCAP_COLLAPSED_3PATCH:0",
                kind="TRIANGULAR_ENDCAP_COLLAPSED_3PATCH",
                entity_ids=patch_ids,
                summary="Exactly three collapsed endcap strips define a triangular collapsed-endcap family.",
                predicate_evidence={"collapsed_patch_count": len(patch_ids)},
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]

    def _match_truncation_connector_band(self, ir: TopologyIRV1) -> List[MotifMatchV1]:
        patch_ids = [
            patch.patch_id
            for patch in ir.patches
            if patch.source_patch_family == "truncation_connector_band"
            or "truncation_connector_band" in patch.tags
        ]
        if not patch_ids:
            return []
        entry = self.describe("TRUNCATION_CONNECTOR_BAND")
        return [
            MotifMatchV1(
                motif_id="TRUNCATION_CONNECTOR_BAND:0",
                kind="TRUNCATION_CONNECTOR_BAND",
                entity_ids=patch_ids,
                summary="Topology already isolates a connector-band strip family for truncation protection.",
                predicate_evidence={"connector_band_patch_count": len(patch_ids)},
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]

    def _match_volume_entry_plc_risk(self, audit_report: Optional[Any]) -> List[MotifMatchV1]:
        if audit_report is None:
            return []
        risky_checks = [
            check
            for check in getattr(audit_report, "checks", [])
            if getattr(check, "status", None) in {"warn", "fail"}
        ]
        if not risky_checks:
            return []
        entry = self.describe("VOLUME_ENTRY_PLC_RISK")
        entity_ids = [entity_id for check in risky_checks for entity_id in getattr(check, "entity_ids", [])]
        return [
            MotifMatchV1(
                motif_id="VOLUME_ENTRY_PLC_RISK:0",
                kind="VOLUME_ENTRY_PLC_RISK",
                entity_ids=entity_ids or [check.kind for check in risky_checks],
                summary="pre_plc_audit.v1 already reports a blocking or warning-level volume-entry risk family.",
                predicate_evidence={
                    "blocking_check_kinds": [check.kind for check in risky_checks],
                },
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]
