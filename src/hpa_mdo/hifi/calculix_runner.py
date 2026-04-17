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
    section_thickness: float | None = None,
    step_name: str = "cruise",
) -> Path:
    """Append a minimal CalculiX linear static step to a mesh ``.inp``."""

    mesh = Path(mesh_inp_path)
    out = Path(out_inp_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    mesh_text = mesh.read_text(encoding="utf-8")
    filtered_mesh_text, element_ids, element_dim = _extract_analysis_mesh(mesh_text)
    boundary_entries = _normalise_boundary(boundary)
    material_name = "HPA_MATERIAL"
    elset_name = "EALL"

    parts = [
        filtered_mesh_text.rstrip(),
        "",
        _format_elset(elset_name, element_ids),
        f"*MATERIAL, NAME={material_name}",
        "*ELASTIC",
        f"{material['E']:.9g}, {material['nu']:.9g}",
        "*DENSITY",
        f"{material['rho']:.9g}",
        *_section_card(
            elset_name,
            material_name,
            element_dim,
            section_thickness=section_thickness,
        ),
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


def prepare_buckle_inp(
    mesh_inp_path: str | Path,
    out_inp_path: str | Path,
    material: dict[str, float],
    boundary: BoundaryEntry | Sequence[BoundaryEntry],
    reference_load: Sequence[LoadEntry],
    *,
    section_thickness: float | None = None,
    n_modes: int = 5,
) -> Path:
    """Append a CalculiX reference static step followed by a BUCKLE step."""

    if n_modes < 1:
        raise ValueError("n_modes must be >= 1")

    mesh = Path(mesh_inp_path)
    out = Path(out_inp_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    mesh_text = mesh.read_text(encoding="utf-8")
    filtered_mesh_text, element_ids, element_dim = _extract_analysis_mesh(mesh_text)
    boundary_entries = _normalise_boundary(boundary)
    material_name = "HPA_MATERIAL"
    elset_name = "EALL"

    parts = [
        filtered_mesh_text.rstrip(),
        "",
        _format_elset(elset_name, element_ids),
        f"*MATERIAL, NAME={material_name}",
        "*ELASTIC",
        f"{material['E']:.9g}, {material['nu']:.9g}",
        "*DENSITY",
        f"{material['rho']:.9g}",
        *_section_card(
            elset_name,
            material_name,
            element_dim,
            section_thickness=section_thickness,
        ),
        "*BOUNDARY",
    ]
    for node_id, dofs in boundary_entries:
        for dof in dofs:
            parts.append(f"{int(node_id)}, {int(dof)}, {int(dof)}, 0.0")

    parts.extend(
        [
            "*STEP, NAME=reference_static",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_id, dof, magnitude in reference_load:
        parts.append(f"{int(node_id)}, {int(dof)}, {float(magnitude):.9g}")

    parts.extend(
        [
            "*END STEP",
            "*STEP, NAME=buckle",
            "*BUCKLE",
            str(int(n_modes)),
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
    log = inp.with_suffix(".log")
    _write_solver_log(log, result.stdout, result.stderr)
    payload: dict[str, Any] = {
        "frd": frd,
        "dat": dat,
        "log": log,
        "returncode": int(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        payload["error"] = result.stderr.strip() or result.stdout.strip() or "ccx failed"
    elif not frd.exists():
        payload["error"] = f"ccx did not produce expected FRD output: {frd}"
    return payload


def _write_solver_log(log_path: Path, stdout: str, stderr: str) -> None:
    """Persist combined solver stdout/stderr next to the input deck."""

    text = "\n".join(
        [
            "===== ccx stdout =====",
            (stdout or "").rstrip(),
            "",
            "===== ccx stderr =====",
            (stderr or "").rstrip(),
            "",
        ]
    )
    log_path.write_text(text, encoding="utf-8")


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


def _extract_analysis_mesh(mesh_text: str) -> tuple[str, list[int], int]:
    """Keep only the highest-dimensional supported element blocks.

    Gmsh often writes mixed meshes (for example surface triangles plus edge
    lines).  For standalone validation we analyse the highest-dimensional
    structural manifold present in the mesh and drop lower-dimensional helper
    blocks so CalculiX receives one consistent section definition.
    """

    lines = mesh_text.splitlines()
    element_dims: list[int] = []
    current_type: str | None = None
    in_element_block = False

    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            current_type = _element_type_from_card(line)
            dim = _element_dimension(current_type)
            if dim > 0:
                element_dims.append(dim)
            in_element_block = True
            continue
        if line.startswith("*"):
            in_element_block = False
            current_type = None
            continue
        if in_element_block:
            continue

    if not element_dims:
        raise ValueError("No supported element blocks found in mesh.")

    target_dim = max(element_dims)
    kept_lines: list[str] = []
    element_ids: list[int] = []
    current_keep = False
    in_element_block = False

    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            current_type = _element_type_from_card(line)
            current_keep = _element_dimension(current_type) == target_dim
            in_element_block = True
            if current_keep:
                kept_lines.append(_normalised_element_card(raw, target_dim))
            continue
        if line.startswith("*"):
            current_keep = False
            in_element_block = False
            kept_lines.append(raw)
            continue
        if current_keep:
            kept_lines.append(raw)
            first = line.split(",", 1)[0].strip()
            if first:
                element_ids.append(int(first))
        elif not in_element_block:
            kept_lines.append(raw)

    if not element_ids:
        raise ValueError("Filtered mesh does not contain any analysable elements.")
    return "\n".join(kept_lines), element_ids, target_dim


def _element_type_from_card(card_line: str) -> str:
    for token in card_line.split(","):
        token = token.strip()
        if token.upper().startswith("TYPE="):
            return token.split("=", 1)[1].strip().upper()
    return ""


def _element_dimension(element_type: str) -> int:
    upper = element_type.upper()
    if upper.startswith("C3D"):
        return 3
    if upper.startswith(("CPS", "CPE", "S", "M3D")):
        return 2
    if upper.startswith(("T3D", "B31", "B32")):
        return 1
    return 0


def _section_card(
    elset_name: str,
    material_name: str,
    element_dim: int,
    *,
    section_thickness: float | None,
) -> list[str]:
    if element_dim == 3:
        return [
            f"*SOLID SECTION, ELSET={elset_name}, MATERIAL={material_name}",
            "",
        ]
    if element_dim == 2:
        if section_thickness is None or float(section_thickness) <= 0.0:
            raise ValueError("section_thickness must be provided for 2D element meshes.")
        return [
            f"*SHELL SECTION, ELSET={elset_name}, MATERIAL={material_name}",
            f"{float(section_thickness):.9g}",
        ]
    raise ValueError(f"Unsupported analysis element dimension: {element_dim}")


def _normalised_element_card(card_line: str, target_dim: int) -> str:
    if target_dim != 2:
        return card_line

    element_type = _element_type_from_card(card_line)
    shell_type = {
        "CPS3": "S3",
        "CPS4": "S4",
        "CPE3": "S3",
        "CPE4": "S4",
    }.get(element_type.upper(), element_type.upper())
    if shell_type == element_type.upper():
        return card_line

    tokens = []
    for token in card_line.split(","):
        stripped = token.strip()
        if stripped.upper().startswith("TYPE="):
            prefix = token[: token.upper().find("TYPE=")]
            tokens.append(f"{prefix}TYPE={shell_type}")
        else:
            tokens.append(token)
    return ",".join(tokens)


def root_boundary_from_mesh(
    mesh_inp_path: str | Path,
    *,
    tolerance: float = 1.0e-9,
    prefer_nset: str = "ROOT",
) -> list[BoundaryEntry]:
    """Clamp all nodes at the structural root plane.

    Prefers the ``NSET=<prefer_nset>`` block written by
    :func:`hpa_mdo.hifi.gmsh_runner.annotate_inp_with_named_points`; falls
    back to the ``|y|``-minimum heuristic when the NSET is absent.  This
    keeps the fallback correct for both half-wing meshes (``y >= 0``) and
    full-span meshes centred on the symmetry plane.  A WARN line is printed
    when the heuristic path is taken.
    """

    try:
        from hpa_mdo.hifi.gmsh_runner import parse_nset_from_inp

        nsets = parse_nset_from_inp(mesh_inp_path)
    except Exception:
        nsets = {}
    prefer = prefer_nset.upper()
    if prefer in nsets and nsets[prefer]:
        return [(int(node_id), (1, 2, 3)) for node_id in nsets[prefer]]

    print(
        f"WARN: NSET={prefer} not found in {mesh_inp_path}; "
        "falling back to |y|-min heuristic for root boundary."
    )
    nodes = parse_inp_nodes(mesh_inp_path)
    y_abs_min = float(np.min(np.abs(nodes[:, 2])))
    root_nodes = nodes[np.abs(np.abs(nodes[:, 2]) - y_abs_min) <= tolerance, 0].astype(int)
    return [(int(node_id), (1, 2, 3)) for node_id in root_nodes]


def tip_node_from_mesh(
    mesh_inp_path: str | Path,
    *,
    prefer_nset: str = "TIP",
) -> int:
    """Return the node id at maximum spanwise ``y``.

    Prefers the ``NSET=<prefer_nset>`` single-node block; falls back to
    the y-max heuristic when the NSET is absent (and prints a WARN).
    """

    try:
        from hpa_mdo.hifi.gmsh_runner import parse_nset_from_inp

        nsets = parse_nset_from_inp(mesh_inp_path)
    except Exception:
        nsets = {}
    prefer = prefer_nset.upper()
    if prefer in nsets and nsets[prefer]:
        return int(nsets[prefer][0])

    print(
        f"WARN: NSET={prefer} not found in {mesh_inp_path}; "
        "falling back to y-max heuristic for tip node."
    )
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
