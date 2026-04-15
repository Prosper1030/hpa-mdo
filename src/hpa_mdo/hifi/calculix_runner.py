"""CalculiX CLI runner for standalone high-fidelity validation."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
import shutil
import subprocess
from typing import Any

import numpy as np

from hpa_mdo.core.config import HPAConfig

BoundaryEntry = tuple[int, Sequence[int]]
LoadEntry = tuple[int, int, float]


def find_ccx(cfg: HPAConfig) -> str | None:
    """Return an absolute CalculiX ``ccx`` path, or ``None`` when unavailable."""

    ccx_cfg = cfg.hi_fidelity.calculix
    if not ccx_cfg.enabled:
        return None

    configured = ccx_cfg.ccx_binary
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        discovered = shutil.which(str(configured))
        if discovered:
            return str(Path(discovered).resolve())
        return None

    discovered = shutil.which("ccx")
    if discovered:
        return str(Path(discovered).resolve())
    return None


def prepare_static_inp(
    mesh_inp_path: str | Path,
    out_inp_path: str | Path,
    material: dict[str, float],
    boundary: BoundaryEntry | Sequence[BoundaryEntry],
    load: Sequence[LoadEntry],
    *,
    step_name: str = "cruise",
) -> Path:
    """Append a minimal CalculiX linear static step to a mesh ``.inp``."""

    mesh = Path(mesh_inp_path)
    out = Path(out_inp_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    mesh_text = mesh.read_text(encoding="utf-8")
    element_ids = parse_inp_element_ids(mesh)
    boundary_entries = _normalise_boundary(boundary)
    material_name = "HPA_MATERIAL"
    elset_name = "EALL"

    parts = [
        mesh_text.rstrip(),
        "",
        _format_elset(elset_name, element_ids),
        f"*MATERIAL, NAME={material_name}",
        "*ELASTIC",
        f"{material['E']:.9g}, {material['nu']:.9g}",
        "*DENSITY",
        f"{material['rho']:.9g}",
        f"*SOLID SECTION, ELSET={elset_name}, MATERIAL={material_name}",
        "",
        "*BOUNDARY",
    ]
    for node_id, dofs in boundary_entries:
        for dof in dofs:
            parts.append(f"{int(node_id)}, {int(dof)}, {int(dof)}, 0.0")

    parts.extend(
        [
            f"*STEP, NAME={step_name}",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_id, dof, magnitude in load:
        parts.append(f"{int(node_id)}, {int(dof)}, {float(magnitude):.9g}")

    parts.extend(
        [
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "",
        ]
    )
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def run_static(
    inp_path: str | Path,
    cfg: HPAConfig,
    *,
    timeout_s: int = 1200,
) -> dict[str, Any]:
    """Run a CalculiX static input file without raising on solver failures."""

    ccx = find_ccx(cfg)
    inp = Path(inp_path)
    if ccx is None:
        return {"error": "CalculiX disabled or ccx not found", "returncode": None}

    try:
        result = subprocess.run(
            [ccx, inp.stem],
            cwd=inp.parent,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"error": f"ccx timed out after {exc.timeout}s", "returncode": None}
    except OSError as exc:
        return {"error": f"ccx failed to start: {exc}", "returncode": None}

    frd = inp.with_suffix(".frd")
    dat = inp.with_suffix(".dat")
    payload: dict[str, Any] = {
        "frd": frd,
        "dat": dat,
        "returncode": int(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        payload["error"] = result.stderr.strip() or result.stdout.strip() or "ccx failed"
    elif not frd.exists():
        payload["error"] = f"ccx did not produce expected FRD output: {frd}"
    return payload


def parse_inp_nodes(mesh_inp_path: str | Path) -> np.ndarray:
    """Return ``(n, 4)`` array rows ``[node_id, x, y, z]`` from an INP file."""

    nodes: list[tuple[float, float, float, float]] = []
    in_node_block = False
    for raw in Path(mesh_inp_path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*NODE"):
            in_node_block = True
            continue
        if line.startswith("*"):
            in_node_block = False
            continue
        if in_node_block:
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4:
                nodes.append(tuple(float(part) for part in parts[:4]))

    if not nodes:
        raise ValueError(f"No *NODE entries found in {mesh_inp_path}")
    return np.asarray(nodes, dtype=float)


def parse_inp_element_ids(mesh_inp_path: str | Path) -> list[int]:
    """Extract element ids from every ``*ELEMENT`` block in an INP file."""

    ids: list[int] = []
    in_element_block = False
    for raw in Path(mesh_inp_path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            in_element_block = True
            continue
        if line.startswith("*"):
            in_element_block = False
            continue
        if in_element_block:
            first = line.split(",", 1)[0].strip()
            if first:
                ids.append(int(first))
    if not ids:
        raise ValueError(f"No *ELEMENT entries found in {mesh_inp_path}")
    return ids


def root_boundary_from_mesh(
    mesh_inp_path: str | Path,
    *,
    tolerance: float = 1.0e-9,
) -> list[BoundaryEntry]:
    """Clamp all nodes at the minimum spanwise ``y`` station."""

    nodes = parse_inp_nodes(mesh_inp_path)
    y_min = float(np.min(nodes[:, 2]))
    root_nodes = nodes[np.abs(nodes[:, 2] - y_min) <= tolerance, 0].astype(int)
    return [(int(node_id), (1, 2, 3)) for node_id in root_nodes]


def tip_node_from_mesh(mesh_inp_path: str | Path) -> int:
    """Return the node id at maximum spanwise ``y``."""

    nodes = parse_inp_nodes(mesh_inp_path)
    idx = int(np.argmax(nodes[:, 2]))
    return int(nodes[idx, 0])


def _normalise_boundary(boundary: BoundaryEntry | Sequence[BoundaryEntry]) -> list[BoundaryEntry]:
    node_id, maybe_dofs = boundary[0], boundary[1]  # type: ignore[index]
    if isinstance(node_id, int) and _is_dof_sequence(maybe_dofs):
        return [(int(node_id), tuple(int(dof) for dof in maybe_dofs))]
    entries = boundary  # type: ignore[assignment]
    return [
        (int(entry[0]), tuple(int(dof) for dof in entry[1]))
        for entry in entries  # type: ignore[union-attr]
    ]


def _is_dof_sequence(value: object) -> bool:
    if isinstance(value, (str, bytes)):
        return False
    if not isinstance(value, Iterable):
        return False
    return all(isinstance(item, int) for item in value)


def _format_elset(name: str, element_ids: Sequence[int]) -> str:
    lines = [f"*ELSET, ELSET={name}"]
    chunk: list[str] = []
    for element_id in element_ids:
        chunk.append(str(int(element_id)))
        if len(chunk) == 16:
            lines.append(", ".join(chunk))
            chunk = []
    if chunk:
        lines.append(", ".join(chunk))
    return "\n".join(lines)
