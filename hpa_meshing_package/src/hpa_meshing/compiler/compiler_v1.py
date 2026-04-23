from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .motif_registry_v1 import MotifRegistryReportV1, MotifRegistryV1
from .operator_library_v1 import OperatorLibraryV1, OperatorPlanV1
from .pre_plc_audit_v1 import PrePLCAuditConfigV1, PrePLCAuditReportV1, run_pre_plc_audit_v1
from .topology_ir_v1 import TopologyIRV1, build_topology_ir_v1


class ShellRolePolicyV1(BaseModel):
    role_name: str
    is_frozen_geometry_baseline: bool
    allows_near_wall_mainline: bool
    allows_geometry_baseline_mutation: bool
    allows_topology_compiler_planning: bool = True
    notes: list[str] = Field(default_factory=list)


class TopologyCompilerArtifactsV1(BaseModel):
    topology_ir: Path
    motif_registry: Path
    operator_plan: Path
    pre_plc_audit: Path
    summary: Path


class TopologyCompilerResultV1(BaseModel):
    contract: str = "topology_compiler.v1"
    shell_role_policy: ShellRolePolicyV1
    topology_ir: TopologyIRV1
    motif_registry: MotifRegistryReportV1
    operator_plan: OperatorPlanV1
    pre_plc_audit: PrePLCAuditReportV1
    artifacts: TopologyCompilerArtifactsV1
    notes: list[str] = Field(default_factory=list)


def resolve_shell_role_policy_v1(shell_role: str) -> ShellRolePolicyV1:
    normalized = str(shell_role).strip().lower()
    if normalized in {"shell_v3", "shell_v3_frozen_baseline"}:
        return ShellRolePolicyV1(
            role_name="shell_v3_frozen_baseline",
            is_frozen_geometry_baseline=True,
            allows_near_wall_mainline=False,
            allows_geometry_baseline_mutation=False,
            notes=[
                "shell_v3 stays frozen as geometry/coarse-CFD regression reference",
                "compiler outputs are inspection/planning only for shell_v3",
            ],
        )
    if normalized in {"shell_v4", "shell_v4_active_bl_validation"}:
        return ShellRolePolicyV1(
            role_name="shell_v4_active_bl_validation",
            is_frozen_geometry_baseline=False,
            allows_near_wall_mainline=True,
            allows_geometry_baseline_mutation=False,
            notes=[
                "shell_v4 is the active BL / solver-validation consumer of compiler outputs",
                "shell_v4 does not replace the frozen shell_v3 geometry-baseline role",
            ],
        )
    raise ValueError(f"Unsupported shell role for topology compiler v1: {shell_role}")


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        serializable = payload.model_dump(mode="json")
    else:
        serializable = payload
    path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")


def compile_topology_family_v1(
    *,
    topology_report: Any,
    topology_lineage_report: Any = None,
    topology_suppression_report: Any = None,
    component: Optional[str] = None,
    shell_role: str,
    out_dir: Path,
    audit_config: Optional[PrePLCAuditConfigV1] = None,
) -> TopologyCompilerResultV1:
    policy = resolve_shell_role_policy_v1(shell_role)
    topology_ir = build_topology_ir_v1(
        topology_report=topology_report,
        topology_lineage_report=topology_lineage_report,
        topology_suppression_report=topology_suppression_report,
        component=component,
    )
    pre_plc_audit = run_pre_plc_audit_v1(topology_ir, config=audit_config)
    motif_registry = MotifRegistryV1().detect(topology_ir, audit_report=pre_plc_audit)
    operator_plan = OperatorLibraryV1().plan_for_matches(
        motif_registry.matches,
        execution_gate="plan_only",
    )

    artifacts = TopologyCompilerArtifactsV1(
        topology_ir=out_dir / "topology_ir.v1.json",
        motif_registry=out_dir / "motif_registry.v1.json",
        operator_plan=out_dir / "operator_plan.v1.json",
        pre_plc_audit=out_dir / "pre_plc_audit.v1.json",
        summary=out_dir / "topology_compiler.v1.json",
    )

    result = TopologyCompilerResultV1(
        shell_role_policy=policy,
        topology_ir=topology_ir,
        motif_registry=motif_registry,
        operator_plan=operator_plan,
        pre_plc_audit=pre_plc_audit,
        artifacts=artifacts,
        notes=[
            "topology_compiler.v1 is a planning/artifact layer before PLC generation",
            "operator execution remains plan-only in v1",
        ],
    )

    _json_write(artifacts.topology_ir, topology_ir)
    _json_write(artifacts.motif_registry, motif_registry)
    _json_write(artifacts.operator_plan, operator_plan)
    _json_write(artifacts.pre_plc_audit, pre_plc_audit)
    _json_write(artifacts.summary, result)
    return result
