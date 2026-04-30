from __future__ import annotations

from typing import Dict, Any

from ..schema import MeshJobConfig


def _required_wall_marker(config: MeshJobConfig) -> str:
    if config.component == "fairing_solid":
        return "fairing_solid"
    if config.component in {"main_wing", "tail_wing", "horizontal_tail", "vertical_tail"}:
        return config.component
    return "aircraft"


def quality_check(run_result: Dict[str, Any], config: MeshJobConfig) -> Dict[str, Any]:
    backend_result = run_result.get("backend_result", {})
    mesh_handoff = backend_result.get("mesh_handoff", {})
    route_stage = backend_result.get("route_stage")
    mesh_stats = mesh_handoff.get("mesh_stats", backend_result.get("mesh_stats", {}))
    marker_summary = mesh_handoff.get("marker_summary", backend_result.get("marker_summary", {}))
    wall_marker = _required_wall_marker(config)
    missing_markers = [
        name
        for name in (wall_marker, "farfield")
        if route_stage == "baseline" and not marker_summary.get(name, {}).get("exists", False)
    ]
    element_count = mesh_stats.get("element_count")
    node_count = mesh_stats.get("node_count")
    volume_element_count = mesh_stats.get("volume_element_count")
    max_elements = config.quality_gate.max_elements

    ok = run_result.get("status") == "success"
    if route_stage == "baseline":
        ok = bool(
            ok
            and not missing_markers
            and isinstance(node_count, int)
            and node_count > 0
            and isinstance(volume_element_count, int)
            and volume_element_count > 0
            and (max_elements is None or (isinstance(element_count, int) and element_count <= max_elements))
        )

    notes = [f"max_elements={max_elements}"]
    if route_stage == "baseline":
        notes.extend(
            [
                f"node_count={node_count}",
                f"element_count={element_count}",
                f"volume_element_count={volume_element_count}",
                f"missing_markers={missing_markers}",
            ]
        )
    else:
        notes.append("quality gate is permissive for routes that still use placeholder backend execution")

    return {
        "ok": ok,
        "checked_route": backend_result.get("meshing_route"),
        "checked_backend_capability": backend_result.get("backend_capability"),
        "notes": notes,
    }


def quality_check_stub(run_result: Dict[str, Any], config: MeshJobConfig) -> Dict[str, Any]:
    return quality_check(run_result, config)
