from __future__ import annotations

from pathlib import Path
from typing import Any


def _lines_for_payload(payload: dict[str, Any]) -> list[str]:
    lines = [
        "# hpa_meshing report",
        "",
        f"- status: {payload.get('status', 'unknown')}",
    ]
    failure_code = payload.get("failure_code")
    if failure_code is not None:
        lines.append(f"- failure_code: {failure_code}")

    mesh = payload.get("mesh", {})
    if isinstance(mesh, dict) and mesh:
        lines.extend(
            [
                "",
                "## Mesh",
                "",
                f"- route_stage: {mesh.get('route_stage')}",
                f"- backend: {mesh.get('backend')}",
                f"- node_count: {mesh.get('node_count')}",
                f"- element_count: {mesh.get('element_count')}",
                f"- volume_element_count: {mesh.get('volume_element_count')}",
            ]
        )

    su2 = payload.get("su2", {})
    final_coefficients = su2.get("final_coefficients", {}) if isinstance(su2, dict) else {}
    if final_coefficients:
        lines.extend(
            [
                "",
                "## SU2",
                "",
                f"- run_status: {su2.get('run_status')}",
                f"- CL: {final_coefficients.get('cl')}",
                f"- CD: {final_coefficients.get('cd')}",
                f"- CM: {final_coefficients.get('cm')}",
            ]
        )

    convergence = payload.get("convergence", {})
    if isinstance(convergence, dict) and convergence:
        overall = convergence.get("overall_convergence_gate", {})
        lines.extend(
            [
                "",
                "## Convergence",
                "",
                f"- mesh_gate: {convergence.get('mesh_gate', {}).get('status')}",
                f"- iterative_gate: {convergence.get('iterative_gate', {}).get('status')}",
                f"- overall: {overall.get('status')}",
                f"- comparability_level: {overall.get('comparability_level')}",
            ]
        )

    return lines


def write_markdown_report(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _lines_for_payload(payload if isinstance(payload, dict) else {"payload": payload})
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
