"""Gmsh CLI runner for high-fidelity validation meshes.

The runner wraps the Gmsh CLI to mesh STEP geometry to CalculiX-compatible
``.inp``.  On top of the raw mesh we layer named node sets (``*NSET``) so
downstream CalculiX decks can refer to ``NSET=ROOT`` / ``NSET=TIP`` /
``NSET=WIRE_1`` instead of re-deriving them from coordinate heuristics.

The named-NSET pass is implemented as a post-process over the ``.inp``
rather than via the (optional) ``gmsh`` Python API so the dependency
footprint stays limited to the Gmsh binary.  For each :class:`NamedPoint`
we search the meshed node cloud for the closest node within ``tol_m``
and append ``*NSET, NSET=<NAME>\\n<node_id>`` before the ``*ELEMENT``
block — this is what Gmsh itself would emit for a Physical Point with
``Mesh.SaveGroupsOfNodes = -1111``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
from typing import Sequence

import numpy as np

from hpa_mdo.core.config import HPAConfig


@dataclass(frozen=True)
class NamedPoint:
    """A coordinate-tagged node to promote into a CalculiX ``*NSET``.

    Parameters
    ----------
    name:
        ``*NSET, NSET=<name>`` label.  Upper-cased when written.
    xyz:
        Target coordinate in mesh units (meters).  The nearest node in the
        produced ``.inp`` within ``tol_m`` becomes the member of the NSET.
    tol_m:
        Maximum acceptable distance [m] between ``xyz`` and the nearest
        node.  When ``None`` the caller-supplied ``GmshConfig.point_tol_m``
        is applied.
    """

    name: str
    xyz: tuple[float, float, float]
    tol_m: float | None = None


def find_gmsh(cfg: HPAConfig) -> str | None:
    """Return an absolute Gmsh executable path, or ``None`` when unavailable."""

    gmsh_cfg = cfg.hi_fidelity.gmsh
    if not gmsh_cfg.enabled:
        return None

    configured = gmsh_cfg.binary
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        discovered = shutil.which(str(configured))
        if discovered:
            return str(Path(discovered).resolve())
        return None

    discovered = shutil.which("gmsh")
    if discovered:
        return str(Path(discovered).resolve())
    return None


def mesh_step_to_inp(
    step_path: str | Path,
    out_inp_path: str | Path,
    cfg: HPAConfig,
    *,
    order: int = 1,
    named_points: Sequence[NamedPoint] | None = None,
) -> Path | None:
    """Mesh a STEP file to CalculiX-compatible ``.inp`` via the Gmsh CLI.

    When ``named_points`` is provided the produced ``.inp`` is augmented
    with ``*NSET, NSET=<name>`` entries — one per point — whose single
    member is the mesh node closest to the requested coordinate (subject
    to ``tol_m`` / ``GmshConfig.point_tol_m``).

    Named points that cannot be matched within tolerance are reported via
    ``print("INFO: ...")`` and skipped; no exception is raised.
    """

    gmsh = find_gmsh(cfg)
    if gmsh is None:
        print("INFO: Gmsh disabled or not found; skipping STEP mesh.")
        return None

    step = Path(step_path)
    out = Path(out_inp_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    length_scale_m_per_unit = step_length_scale_m_per_unit(step)
    clmax_units = float(cfg.hi_fidelity.gmsh.mesh_size_m) / length_scale_m_per_unit

    cmd = [
        gmsh,
        str(step),
        "-3",
        "-format",
        "inp",
        "-order",
        str(order),
        "-clmax",
        str(clmax_units),
        "-o",
        str(out),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"INFO: Gmsh timed out after {exc.timeout}s while meshing {step}.")
        return None
    except OSError as exc:
        print(f"INFO: Gmsh failed to start: {exc}")
        return None

    if result.returncode != 0 or not out.exists():
        stderr = result.stderr.strip() or result.stdout.strip()
        if stderr:
            print(f"INFO: Gmsh mesh failed:\n{stderr}")
        else:
            print(f"INFO: Gmsh mesh failed with return code {result.returncode}.")
        return None

    if named_points:
        default_tol = float(cfg.hi_fidelity.gmsh.point_tol_m) / length_scale_m_per_unit
        try:
            annotate_inp_with_named_points(
                out,
                _scaled_named_points(named_points, length_scale_m_per_unit),
                default_tol_m=default_tol,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"INFO: NSET annotation skipped ({exc}).")
    return out


def annotate_inp_with_named_points(
    inp_path: str | Path,
    named_points: Sequence[NamedPoint],
    *,
    default_tol_m: float = 1.0e-3,
) -> list[str]:
    """Inject ``*NSET, NSET=<name>`` blocks into an existing ``.inp`` file.

    Returns the list of NSET names that were actually written (in order);
    names whose coordinate could not be matched within tolerance are
    skipped and reported via ``print``.
    """

    inp = Path(inp_path)
    text = inp.read_text(encoding="utf-8")
    # Parse node table from the existing .inp.  The coordinate parser is
    # shared with calculix_runner.parse_inp_nodes but re-implemented here
    # to avoid a circular import.
    nodes = _parse_inp_nodes(text)  # shape (N, 4) => [id, x, y, z]
    if nodes.size == 0:
        raise ValueError(f"No *NODE entries found in {inp}")

    coords = nodes[:, 1:4]
    ids = nodes[:, 0].astype(int)

    nset_blocks: list[str] = []
    written: list[str] = []
    for point in named_points:
        tol = float(point.tol_m) if point.tol_m is not None else float(default_tol_m)
        target = np.asarray(point.xyz, dtype=float)
        d = np.linalg.norm(coords - target[None, :], axis=1)
        idx = int(np.argmin(d))
        if d[idx] > tol:
            print(
                f"INFO: NamedPoint '{point.name}' unmatched: "
                f"nearest node {ids[idx]} is {d[idx]:.4g} m away "
                f"(> tol {tol:.4g} m); skipping."
            )
            continue
        nset_name = str(point.name).upper()
        nset_blocks.append(f"*NSET, NSET={nset_name}\n{ids[idx]}")
        written.append(nset_name)

    if not nset_blocks:
        return written

    # Insert the NSET blocks before the first *ELEMENT to mirror the
    # layout Gmsh itself produces with Mesh.SaveGroupsOfNodes enabled.
    marker = "*ELEMENT"
    lines = text.splitlines()
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.lstrip().upper().startswith(marker):
            insert_at = i
            break
    block = "\n".join(nset_blocks)
    new_text = "\n".join(lines[:insert_at]) + "\n" + block + "\n" + "\n".join(lines[insert_at:])
    if not new_text.endswith("\n"):
        new_text += "\n"
    inp.write_text(new_text, encoding="utf-8")
    return written


def _parse_inp_nodes(text: str) -> np.ndarray:
    rows: list[tuple[float, float, float, float]] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*NODE"):
            in_block = True
            continue
        if line.startswith("*"):
            in_block = False
            continue
        if in_block:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                rows.append(tuple(float(p) for p in parts[:4]))
    if not rows:
        return np.empty((0, 4), dtype=float)
    return np.asarray(rows, dtype=float)


def step_length_scale_m_per_unit(step_path: str | Path) -> float:
    """Return the STEP model length scale in metres per geometric unit.

    Gmsh preserves the CAD model's native coordinate units.  For Open CASCADE
    STEP exported in millimetres we therefore need to scale ``-clmax`` and
    point tolerances from metres into STEP units before meshing.
    """

    text = Path(step_path).read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(
        r"LENGTH_UNIT\(\)\s+NAMED_UNIT\(\*\)\s+SI_UNIT\(\s*(?:\.(?P<prefix>[A-Z]+)\.\s*,)?\s*\.METRE\.\s*\)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return 1.0

    prefix = (match.group("prefix") or "").upper()
    return {
        "": 1.0,
        "MILLI": 1.0e-3,
        "CENTI": 1.0e-2,
        "DECI": 1.0e-1,
        "MICRO": 1.0e-6,
        "NANO": 1.0e-9,
        "KILO": 1.0e3,
    }.get(prefix, 1.0)


def _scaled_named_points(
    named_points: Sequence[NamedPoint],
    length_scale_m_per_unit: float,
) -> list[NamedPoint]:
    scale = float(length_scale_m_per_unit)
    if scale <= 0.0:
        raise ValueError("length_scale_m_per_unit must be > 0")

    scaled: list[NamedPoint] = []
    for point in named_points:
        xyz_units = tuple(float(value) / scale for value in point.xyz)
        tol_units = None if point.tol_m is None else float(point.tol_m) / scale
        scaled.append(NamedPoint(point.name, xyz_units, tol_units))
    return scaled


def parse_nset_from_inp(inp_path: str | Path) -> dict[str, list[int]]:
    """Return a mapping ``{NSET_NAME: [node_ids, ...]}`` parsed from ``.inp``."""

    inp = Path(inp_path)
    nsets: dict[str, list[int]] = {}
    current: str | None = None
    for raw in inp.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*NSET"):
            # Parse "*NSET, NSET=ROOT" or "*NSET, NSET=ROOT, ..."
            current = None
            for token in line.split(","):
                token = token.strip()
                if token.upper().startswith("NSET="):
                    current = token.split("=", 1)[1].strip().upper()
                    break
            if current:
                nsets.setdefault(current, [])
            continue
        if line.startswith("*"):
            current = None
            continue
        if current is not None:
            for token in line.split(","):
                token = token.strip()
                if token:
                    try:
                        nsets[current].append(int(token))
                    except ValueError:
                        pass
    return nsets
