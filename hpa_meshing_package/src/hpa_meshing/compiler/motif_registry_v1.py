from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .topology_ir_v1 import TopologyIRV1


MotifKindV1 = Literal[
    "ROOT_CLOSURE",
    "TRUNCATION_SEAM_REQUIRED_RING",
    "TRIANGULAR_ENDCAP_COLLAPSED_3PATCH",
    "TRUNCATION_CONNECTOR_BAND",
    "CANONICAL_CONNECTOR_BAND_POST_TRANSITION",
    "POST_BAND_TRANSITION_BOUNDARY_RECOVERY",
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
                admissible_operators=["regularize_truncation_connector_band"],
                reject_conditions=["missing_connector_band_descriptors"],
                unsupported_conditions=["connector_band_not_classified"],
                expected_artifact_keys=[
                    "truncation_connector_band_regularization_plan",
                    "truncation_connector_band_regularization_report",
                ],
            ),
            "CANONICAL_CONNECTOR_BAND_POST_TRANSITION": MotifRegistryEntryV1(
                kind="CANONICAL_CONNECTOR_BAND_POST_TRANSITION",
                admissible_operators=["prototype_split_post_band_transition"],
                reject_conditions=[
                    "family_not_canonical_connector_band",
                    "missing_segment_facet_blocker",
                ],
                unsupported_conditions=["post_band_transition_not_localized"],
                expected_artifact_keys=[
                    "post_band_transition_split_plan",
                    "post_band_transition_split_report",
                ],
            ),
            "POST_BAND_TRANSITION_BOUNDARY_RECOVERY": MotifRegistryEntryV1(
                kind="POST_BAND_TRANSITION_BOUNDARY_RECOVERY",
                admissible_operators=["regularize_recoversegment_failed_steiner_post_band"],
                reject_conditions=[
                    "family_not_post_transition_guard_split",
                    "missing_boundary_recovery_error_2_blocker",
                    "overlap_family_still_blocking",
                ],
                unsupported_conditions=["boundary_recovery_contact_locus_not_localized"],
                expected_artifact_keys=[
                    "post_transition_boundary_recovery_regularization_plan",
                    "post_transition_boundary_recovery_regularization_report",
                ],
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
        matches.extend(self._match_canonical_connector_band_post_transition(ir, audit_report=audit_report))
        matches.extend(self._match_post_band_transition_boundary_recovery(ir, audit_report=audit_report))
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
        connector_band_patches = [
            patch
            for patch in ir.patches
            if patch.source_patch_family == "truncation_connector_band"
            or "truncation_connector_band" in patch.tags
            or patch.local_descriptors.truncation_band_role.get("role") == "connector_band"
        ]
        patch_ids = [patch.patch_id for patch in connector_band_patches]
        if not patch_ids:
            return []
        entry = self.describe("TRUNCATION_CONNECTOR_BAND")
        selected_section_y_le_m = (
            ir.compiler_context.get("truncation_connector_band", {}).get("selected_section_y_le_m", [])
            if isinstance(ir.compiler_context, dict)
            else []
        )
        extra_pre_band_support_count = sum(
            1
            for patch in ir.patches
            if patch.local_descriptors.truncation_band_role.get("role") == "pre_band_support"
        )
        return [
            MotifMatchV1(
                motif_id="TRUNCATION_CONNECTOR_BAND:0",
                kind="TRUNCATION_CONNECTOR_BAND",
                entity_ids=patch_ids,
                summary="Topology isolates a connector-band strip family with explicit truncation-band descriptors.",
                predicate_evidence={
                    "connector_band_patch_count": len(patch_ids),
                    "extra_pre_band_support_count": extra_pre_band_support_count,
                    "selected_section_y_le_m": list(selected_section_y_le_m),
                    "connector_band_start_y_le_m": connector_band_patches[0]
                    .local_descriptors.truncation_band_role.get("connector_band_start_y_le_m"),
                    "truncation_start_y_le_m": connector_band_patches[0]
                    .local_descriptors.truncation_band_role.get("truncation_start_y_le_m"),
                },
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
            )
        ]

    def _match_canonical_connector_band_post_transition(
        self,
        ir: TopologyIRV1,
        *,
        audit_report: Optional[Any] = None,
    ) -> List[MotifMatchV1]:
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
        if (
            len(root_support_patches) != 1
            or len(connector_band_patches) != 1
            or len(transition_patches) != 1
            or pre_band_support_patches
            or "segment_facet_intersection_risk" not in blocking_topology_check_kinds
        ):
            return []
        entry = self.describe("CANONICAL_CONNECTOR_BAND_POST_TRANSITION")
        root_support_patch = root_support_patches[0]
        connector_patch = connector_band_patches[0]
        transition_patch = transition_patches[0]
        transition_start_y = transition_patch.metadata.get("inboard_y_le_m")
        tip_y = transition_patch.metadata.get("outboard_y_le_m")
        transition_span_m = None
        if transition_start_y is not None and tip_y is not None:
            transition_span_m = float(tip_y) - float(transition_start_y)
        return [
            MotifMatchV1(
                motif_id="CANONICAL_CONNECTOR_BAND_POST_TRANSITION:0",
                kind="CANONICAL_CONNECTOR_BAND_POST_TRANSITION",
                entity_ids=[
                    root_support_patch.patch_id,
                    connector_patch.patch_id,
                    transition_patch.patch_id,
                ],
                summary=(
                    "Canonical connector-band topology still carries a post-band transition strip under "
                    "observed segment-facet pressure."
                ),
                predicate_evidence={
                    "root_support_patch_count": len(root_support_patches),
                    "connector_band_patch_count": len(connector_band_patches),
                    "transition_patch_count": len(transition_patches),
                    "pre_band_support_patch_count": len(pre_band_support_patches),
                    "blocking_topology_check_kinds": blocking_topology_check_kinds,
                    "transition_start_y_le_m": transition_start_y,
                    "tip_y_le_m": tip_y,
                    "transition_span_m": transition_span_m,
                },
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
                notes=[
                    "This motif is intentionally downstream of overlap-family regularization.",
                    "It only matches already-canonical connector-band families with zero pre-band support strips.",
                ],
            )
        ]

    def _match_post_band_transition_boundary_recovery(
        self,
        ir: TopologyIRV1,
        *,
        audit_report: Optional[Any] = None,
    ) -> List[MotifMatchV1]:
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
        pre_band_support_patches = [
            patch
            for patch in ir.patches
            if patch.local_descriptors.truncation_band_role.get("role") == "pre_band_support"
        ]
        blocking_topology_check_kinds = list(
            getattr(audit_report, "blocking_topology_check_kinds", []) or []
        )
        boundary_recovery_metrics: Dict[str, Any] = {}
        if audit_report is not None:
            for check in getattr(audit_report, "checks", []) or []:
                if getattr(check, "kind", None) == "boundary_recovery_error_2_risk":
                    boundary_recovery_metrics = dict(getattr(check, "metrics", {}) or {})
                    break
        if (
            len(root_support_patches) != 1
            or len(connector_band_patches) != 1
            or len(transition_guard_patches) != 1
            or len(transition_terminal_patches) != 1
            or pre_band_support_patches
            or "boundary_recovery_error_2_risk" not in blocking_topology_check_kinds
            or "facet_facet_overlap_risk" in blocking_topology_check_kinds
        ):
            return []
        entry = self.describe("POST_BAND_TRANSITION_BOUNDARY_RECOVERY")
        guard_patch = transition_guard_patches[0]
        terminal_patch = transition_terminal_patches[0]
        guard_split_y = guard_patch.metadata.get("outboard_y_le_m")
        transition_start_y = guard_patch.metadata.get("inboard_y_le_m")
        tip_y = terminal_patch.metadata.get("outboard_y_le_m")
        return [
            MotifMatchV1(
                motif_id="POST_BAND_TRANSITION_BOUNDARY_RECOVERY:0",
                kind="POST_BAND_TRANSITION_BOUNDARY_RECOVERY",
                entity_ids=[
                    connector_band_patches[0].patch_id,
                    guard_patch.patch_id,
                    terminal_patch.patch_id,
                ],
                summary=(
                    "Canonical connector-band topology now localizes a distinct post-band transition "
                    "boundary-recovery `error 2` family."
                ),
                predicate_evidence={
                    "root_support_patch_count": len(root_support_patches),
                    "connector_band_patch_count": len(connector_band_patches),
                    "transition_guard_patch_count": len(transition_guard_patches),
                    "transition_terminal_patch_count": len(transition_terminal_patches),
                    "pre_band_support_patch_count": len(pre_band_support_patches),
                    "blocking_topology_check_kinds": blocking_topology_check_kinds,
                    "transition_start_y_le_m": transition_start_y,
                    "transition_guard_y_le_m": guard_split_y,
                    "tip_y_le_m": tip_y,
                    "transition_guard_span_m": guard_patch.metadata.get("span_interval_m"),
                    "transition_terminal_span_m": terminal_patch.metadata.get("span_interval_m"),
                    "geometry_contact_locus_kind": "post_band_transition_guard_to_tip",
                    **{
                        key: boundary_recovery_metrics[key]
                        for key in (
                            "residual_family",
                            "evidence_level",
                            "throw_site_label",
                            "throw_site_file",
                            "throw_site_line",
                            "local_surface_tags",
                            "local_y_band",
                            "suspicious_window",
                            "sevent_e_type",
                            "degenerated_prism_seen",
                        )
                        if key in boundary_recovery_metrics
                    },
                },
                admissible_operators=entry.admissible_operators,
                reject_conditions=entry.reject_conditions,
                unsupported_conditions=entry.unsupported_conditions,
                expected_artifact_keys=entry.expected_artifact_keys,
                notes=[
                    "This family is downstream of overlap and segment-facet families after the deterministic guard split.",
                    "It is classified as a boundary-recovery failure localized to the post-band transition contact locus.",
                ],
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
