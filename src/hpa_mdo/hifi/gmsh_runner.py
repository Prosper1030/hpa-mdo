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

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Sequence

import numpy as np

from hpa_mdo.core.config import HPAConfig


# Keep retries intentionally bounded: on a 16 GB Mac mini we only allow one
# coarsening step instead of indefinite re-meshing.
_GMSH_COARSE_RETRY_FACTORS = (1.0, 2.0)


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
    match_mode:
        Matching strategy for turning ``xyz`` into a node set.  Supported
        values are ``nearest_xyz`` (default), ``nearest_spanwise_y`` for the
        closest node in spanwise ``y``, and ``spanwise_plane_y`` for the full
        node cluster nearest the requested span station.
    """

    name: str
    xyz: tuple[float, float, float]
    tol_m: float | None = None
    match_mode: str = "nearest_xyz"


@dataclass(frozen=True)
class MeshDiagnostics:
    """Machine-readable diagnostics for one meshed ``.inp`` artifact."""

    mesh_path: Path
    diagnostics_path: Path | None
    element_count: int
    gmsh_returncode: int | None = None
    duplicate_shell_facets: int = 0
    overlapping_boundary_mesh_count: int = 0
    no_elements_in_volume_count: int = 0
    equivalent_triangles_count: int = 0
    invalid_surface_elements_count: int = 0
    duplicate_boundary_facets_count: int = 0
    mesh_size_m: float | None = None
    attempt_index: int | None = None
    attempt_count: int | None = None
    healing_applied: bool = False
    element_type_counts: dict[str, int] = field(default_factory=dict)
    element_family_counts: dict[str, int] = field(default_factory=dict)
    analysis_reality: str = "unknown"
    has_volume_elements: bool = False

    @property
    def issue_hints(self) -> tuple[str, ...]:
        hints: list[str] = []
        if self.overlapping_boundary_mesh_count > 0:
            hints.append(
                f"overlapping_boundary_mesh x{int(self.overlapping_boundary_mesh_count)}"
            )
        if self.no_elements_in_volume_count > 0:
            hints.append(f"no_elements_in_volume x{int(self.no_elements_in_volume_count)}")
        if self.duplicate_boundary_facets_count > 0:
            hints.append(
                f"duplicate_boundary_facets x{int(self.duplicate_boundary_facets_count)}"
            )
        if self.invalid_surface_elements_count > 0:
            hints.append(
                f"invalid_surface_elements x{int(self.invalid_surface_elements_count)}"
            )
        if self.equivalent_triangles_count > 0:
            hints.append(
                f"equivalent_triangles x{int(self.equivalent_triangles_count)}"
            )
        if self.duplicate_shell_facets > 0:
            hints.append(f"duplicate_shell_facets x{int(self.duplicate_shell_facets)}")
        return tuple(hints)

    def to_dict(self) -> dict[str, object]:
        return {
            "mesh_path": str(self.mesh_path),
            "diagnostics_path": None
            if self.diagnostics_path is None
            else str(self.diagnostics_path),
            "element_count": int(self.element_count),
            "gmsh_returncode": self.gmsh_returncode,
            "duplicate_shell_facets": int(self.duplicate_shell_facets),
            "overlapping_boundary_mesh_count": int(self.overlapping_boundary_mesh_count),
            "no_elements_in_volume_count": int(self.no_elements_in_volume_count),
            "equivalent_triangles_count": int(self.equivalent_triangles_count),
            "invalid_surface_elements_count": int(self.invalid_surface_elements_count),
            "duplicate_boundary_facets_count": int(self.duplicate_boundary_facets_count),
            "mesh_size_m": self.mesh_size_m,
            "attempt_index": self.attempt_index,
            "attempt_count": self.attempt_count,
            "healing_applied": self.healing_applied,
            "element_type_counts": dict(sorted(self.element_type_counts.items())),
            "element_family_counts": dict(sorted(self.element_family_counts.items())),
            "analysis_reality": self.analysis_reality,
            "has_volume_elements": self.has_volume_elements,
            "issue_hints": list(self.issue_hints),
        }


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
    attempt_mesh_sizes_m = _mesh_attempt_sizes_m(float(cfg.hi_fidelity.gmsh.mesh_size_m))
    attempt_count = len(attempt_mesh_sizes_m)
    attempt_records: list[tuple[Path, MeshDiagnostics]] = []

    for attempt_index, mesh_size_m in enumerate(attempt_mesh_sizes_m, start=1):
        candidate_out = _attempt_out_path(out, attempt_index, attempt_count=attempt_count)
        result = _run_gmsh_meshing_attempt(
            gmsh=gmsh,
            step=step,
            out=candidate_out,
            order=order,
            clmax_units=float(mesh_size_m) / length_scale_m_per_unit,
        )
        if result is None:
            return None

        if not candidate_out.exists():
            if attempt_index < attempt_count:
                print(
                    "WARN: Gmsh did not write a mesh on attempt "
                    f"{attempt_index}/{attempt_count}; retrying once with a coarser "
                    f"mesh_size_m={attempt_mesh_sizes_m[attempt_index]:.6g}."
                )
                continue
            _report_gmsh_failure(
                result_returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            return None

        element_count = inp_element_count(candidate_out)
        if result.returncode != 0 and element_count <= 0:
            if attempt_index < attempt_count:
                print(
                    "WARN: Gmsh wrote no analysable elements on attempt "
                    f"{attempt_index}/{attempt_count}; retrying once with a coarser "
                    f"mesh_size_m={attempt_mesh_sizes_m[attempt_index]:.6g}."
                )
                continue
            _report_gmsh_failure(
                result_returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            return None

        if result.returncode != 0:
            print(
                "WARN: Gmsh returned a non-zero exit status but wrote a mesh with "
                f"{element_count} elements; continuing with the partial mesh."
            )

        if named_points:
            default_tol = _default_named_point_tolerance_units(
                point_tol_m=float(cfg.hi_fidelity.gmsh.point_tol_m),
                mesh_size_m=float(mesh_size_m),
                length_scale_m_per_unit=length_scale_m_per_unit,
            )
            try:
                annotate_inp_with_named_points(
                    candidate_out,
                    _scaled_named_points(named_points, length_scale_m_per_unit),
                    default_tol_m=default_tol,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"INFO: NSET annotation skipped ({exc}).")

        diagnostics = replace(
            collect_mesh_diagnostics(
                candidate_out,
                gmsh_returncode=result.returncode,
                gmsh_stdout=result.stdout,
                gmsh_stderr=result.stderr,
            ),
            mesh_size_m=float(mesh_size_m),
            attempt_index=attempt_index,
            attempt_count=attempt_count,
            healing_applied=True,
        )
        attempt_records.append((candidate_out, diagnostics))

        if attempt_index < attempt_count and _should_retry_with_coarser_mesh(diagnostics):
            next_mesh_size_m = attempt_mesh_sizes_m[attempt_index]
            print(
                "WARN: Gmsh mesh diagnostics indicate upstream surface issues "
                f"({', '.join(diagnostics.issue_hints) or 'unclassified'}); "
                "retrying once with a coarser mesh_size_m="
                f"{next_mesh_size_m:.6g}."
            )
            continue
        break

    if not attempt_records:
        return None

    selected_out, selected_diagnostics = min(
        attempt_records,
        key=lambda item: _mesh_diagnostics_rank(item[1]),
    )
    attempted_count = max(
        (diagnostics.attempt_index or 0)
        for _candidate_out, diagnostics in attempt_records
    )
    final_diagnostics = replace(
        selected_diagnostics,
        mesh_path=out.resolve(),
        diagnostics_path=mesh_diagnostics_sidecar_path(out).resolve(),
        attempt_count=attempted_count,
    )
    _promote_selected_attempt(
        out=out,
        selected_out=selected_out,
        selected_diagnostics=final_diagnostics,
        attempt_records=attempt_records,
    )
    return out


def mesh_diagnostics_sidecar_path(inp_path: str | Path) -> Path:
    """Return the canonical diagnostics sidecar path for a mesh ``.inp``."""

    return Path(inp_path).with_suffix(".mesh_diagnostics.json")


def _mesh_attempt_sizes_m(base_mesh_size_m: float) -> tuple[float, ...]:
    sizes: list[float] = []
    seen: set[float] = set()
    for factor in _GMSH_COARSE_RETRY_FACTORS:
        candidate = float(base_mesh_size_m) * float(factor)
        rounded = round(candidate, 12)
        if rounded in seen:
            continue
        seen.add(rounded)
        sizes.append(candidate)
    return tuple(sizes)


def _attempt_out_path(out_path: Path, attempt_index: int, *, attempt_count: int) -> Path:
    if attempt_count <= 1 or attempt_index == 1:
        return out_path
    return out_path.with_name(f"{out_path.stem}.attempt{attempt_index}{out_path.suffix}")


def _default_named_point_tolerance_units(
    *,
    point_tol_m: float,
    mesh_size_m: float,
    length_scale_m_per_unit: float,
) -> float:
    tol_m = max(
        float(point_tol_m),
        min(0.05 * float(mesh_size_m), 1.0e-2),
    )
    return tol_m / float(length_scale_m_per_unit)


def _healing_wrapper_geo_path(out_path: Path) -> Path:
    return out_path.with_suffix(".mesh_heal.geo")


def _write_healing_geo_wrapper(wrapper_path: Path, step_path: Path) -> None:
    wrapper_text = "\n".join(
        [
            'SetFactory("OpenCASCADE");',
            "Geometry.OCCFixDegenerated = 1;",
            "Geometry.OCCFixSmallEdges = 1;",
            "Geometry.OCCFixSmallFaces = 1;",
            "Geometry.OCCSewFaces = 1;",
            "Geometry.OCCMakeSolids = 1;",
            f"ShapeFromFile({_geo_string(step_path)});",
            "HealShapes;",
            "Coherence;",
            "",
        ]
    )
    wrapper_path.write_text(wrapper_text, encoding="utf-8")


def _geo_string(path: Path) -> str:
    return json.dumps(str(path.resolve()))


def _run_gmsh_meshing_attempt(
    *,
    gmsh: str,
    step: Path,
    out: Path,
    order: int,
    clmax_units: float,
) -> subprocess.CompletedProcess[str] | None:
    wrapper_geo = _healing_wrapper_geo_path(out)
    _write_healing_geo_wrapper(wrapper_geo, step)
    cmd = [
        gmsh,
        str(wrapper_geo),
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
        return subprocess.run(
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
    finally:
        if wrapper_geo.exists():
            wrapper_geo.unlink()


def _report_gmsh_failure(
    *,
    result_returncode: int | None,
    stdout: str,
    stderr: str,
) -> None:
    message = str(stderr).strip() or str(stdout).strip()
    if message:
        print(f"INFO: Gmsh mesh failed:\n{message}")
        return
    if result_returncode is None:
        print("INFO: Gmsh mesh failed without writing an output mesh.")
        return
    print(f"INFO: Gmsh mesh failed with return code {result_returncode}.")


def _should_retry_with_coarser_mesh(diagnostics: MeshDiagnostics) -> bool:
    return any(
        count > 0
        for count in (
            diagnostics.overlapping_boundary_mesh_count,
            diagnostics.no_elements_in_volume_count,
            diagnostics.invalid_surface_elements_count,
            diagnostics.duplicate_boundary_facets_count,
        )
    )


def _mesh_diagnostics_rank(diagnostics: MeshDiagnostics) -> tuple[int, ...]:
    return (
        int(diagnostics.overlapping_boundary_mesh_count > 0),
        int(diagnostics.no_elements_in_volume_count > 0),
        int(diagnostics.invalid_surface_elements_count > 0),
        int(diagnostics.duplicate_boundary_facets_count > 0),
        int(diagnostics.gmsh_returncode not in {None, 0}),
        int(diagnostics.overlapping_boundary_mesh_count),
        int(diagnostics.no_elements_in_volume_count),
        int(diagnostics.invalid_surface_elements_count),
        int(diagnostics.duplicate_boundary_facets_count),
        int(diagnostics.duplicate_shell_facets),
        int(diagnostics.equivalent_triangles_count),
        int(diagnostics.attempt_index or 0),
    )


def _promote_selected_attempt(
    *,
    out: Path,
    selected_out: Path,
    selected_diagnostics: MeshDiagnostics,
    attempt_records: Sequence[tuple[Path, MeshDiagnostics]],
) -> None:
    selected_sidecar = mesh_diagnostics_sidecar_path(selected_out)
    if selected_out != out:
        selected_out.replace(out)
    write_mesh_diagnostics(selected_diagnostics)
    if selected_out != out and selected_sidecar.exists():
        selected_sidecar.unlink()

    for candidate_out, _diagnostics in attempt_records:
        if candidate_out == selected_out or candidate_out == out:
            continue
        if candidate_out.exists():
            candidate_out.unlink()
        candidate_sidecar = mesh_diagnostics_sidecar_path(candidate_out)
        if candidate_sidecar.exists():
            candidate_sidecar.unlink()


def collect_mesh_diagnostics(
    inp_path: str | Path,
    *,
    gmsh_returncode: int | None = None,
    gmsh_stdout: str = "",
    gmsh_stderr: str = "",
) -> MeshDiagnostics:
    """Collect mesh quality hints from the mesh file and optional Gmsh logs."""

    inp = Path(inp_path).resolve()
    if not inp.exists():
        raise FileNotFoundError(inp)

    log_hints = _parse_gmsh_log_diagnostics(
        "\n".join(part for part in (gmsh_stdout, gmsh_stderr) if part)
    )
    duplicate_shell_facets = _count_duplicate_shell_facets(inp)
    element_type_counts = _count_element_types(inp)
    element_family_counts = _count_element_families(element_type_counts)
    return MeshDiagnostics(
        mesh_path=inp,
        diagnostics_path=None,
        element_count=inp_element_count(inp),
        gmsh_returncode=None if gmsh_returncode is None else int(gmsh_returncode),
        duplicate_shell_facets=duplicate_shell_facets,
        overlapping_boundary_mesh_count=int(log_hints["overlapping_boundary_mesh_count"]),
        no_elements_in_volume_count=int(log_hints["no_elements_in_volume_count"]),
        equivalent_triangles_count=int(log_hints["equivalent_triangles_count"]),
        invalid_surface_elements_count=int(log_hints["invalid_surface_elements_count"]),
        duplicate_boundary_facets_count=int(log_hints["duplicate_boundary_facets_count"]),
        element_type_counts=element_type_counts,
        element_family_counts=element_family_counts,
        analysis_reality=_analysis_reality(element_family_counts),
        has_volume_elements=element_family_counts.get("solid", 0) > 0,
    )


def write_mesh_diagnostics(diagnostics: MeshDiagnostics) -> Path:
    """Persist mesh diagnostics next to the mesh as JSON."""

    out = diagnostics.diagnostics_path or mesh_diagnostics_sidecar_path(diagnostics.mesh_path)
    payload = diagnostics.to_dict()
    payload["diagnostics_path"] = str(out)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def load_mesh_diagnostics(inp_path: str | Path) -> MeshDiagnostics | None:
    """Load persisted mesh diagnostics when a sidecar exists."""

    diagnostics_path = mesh_diagnostics_sidecar_path(inp_path)
    if not diagnostics_path.exists():
        return None

    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    mesh_path = Path(payload["mesh_path"]).resolve()
    return MeshDiagnostics(
        mesh_path=mesh_path,
        diagnostics_path=diagnostics_path.resolve(),
        element_count=int(payload.get("element_count", 0)),
        gmsh_returncode=payload.get("gmsh_returncode"),
        duplicate_shell_facets=int(payload.get("duplicate_shell_facets", 0)),
        overlapping_boundary_mesh_count=int(payload.get("overlapping_boundary_mesh_count", 0)),
        no_elements_in_volume_count=int(payload.get("no_elements_in_volume_count", 0)),
        equivalent_triangles_count=int(payload.get("equivalent_triangles_count", 0)),
        invalid_surface_elements_count=int(payload.get("invalid_surface_elements_count", 0)),
        duplicate_boundary_facets_count=int(payload.get("duplicate_boundary_facets_count", 0)),
        mesh_size_m=payload.get("mesh_size_m"),
        attempt_index=payload.get("attempt_index"),
        attempt_count=payload.get("attempt_count"),
        healing_applied=bool(payload.get("healing_applied", False)),
        element_type_counts={
            str(key): int(value)
            for key, value in dict(payload.get("element_type_counts", {})).items()
        },
        element_family_counts={
            str(key): int(value)
            for key, value in dict(payload.get("element_family_counts", {})).items()
        },
        analysis_reality=str(payload.get("analysis_reality", "unknown")),
        has_volume_elements=bool(payload.get("has_volume_elements", False)),
    )


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
        node_ids, nearest_distance = _match_named_point_node_ids(
            ids,
            coords,
            target,
            tol,
            match_mode=point.match_mode,
        )
        if not node_ids:
            print(
                f"INFO: NamedPoint '{point.name}' unmatched: "
                f"nearest node {ids[int(np.argmin(np.linalg.norm(coords - target[None, :], axis=1)))]} is {nearest_distance:.4g} mesh units away "
                f"(> tol {tol:.4g} mesh units); skipping."
            )
            continue
        nset_name = str(point.name).upper()
        nset_blocks.append(_format_nset_block(nset_name, node_ids))
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


def _match_named_point_node_ids(
    node_ids: np.ndarray,
    coords: np.ndarray,
    target: np.ndarray,
    tolerance: float,
    *,
    match_mode: str,
) -> tuple[list[int], float]:
    xyz_distances = np.linalg.norm(coords - target[None, :], axis=1)
    nearest_xyz_distance = float(np.min(xyz_distances))
    mode = str(match_mode).lower()

    if mode == "nearest_xyz":
        idx = int(np.argmin(xyz_distances))
        if nearest_xyz_distance > tolerance:
            return [], nearest_xyz_distance
        return [int(node_ids[idx])], nearest_xyz_distance

    y_offsets = np.abs(coords[:, 1] - float(target[1]))
    nearest_y_distance = float(np.min(y_offsets))
    if nearest_y_distance > tolerance:
        return [], nearest_y_distance

    if mode == "nearest_spanwise_y":
        idx = int(np.argmin(y_offsets))
        return [int(node_ids[idx])], nearest_y_distance

    if mode == "spanwise_plane_y":
        plane_offsets = np.abs(y_offsets - nearest_y_distance)
        cluster_tolerance = _infer_spanwise_plane_tolerance(plane_offsets, tolerance=tolerance)
        matched = node_ids[plane_offsets <= cluster_tolerance].astype(int).tolist()
        return matched, nearest_y_distance

    raise ValueError(f"Unsupported NamedPoint match_mode: {match_mode}")


def _infer_spanwise_plane_tolerance(plane_offsets: np.ndarray, *, tolerance: float) -> float:
    floor = max(1.0e-12, float(tolerance) * 1.0e-6)
    unique_offsets = np.sort(np.unique(np.round(np.abs(plane_offsets.astype(float)), decimals=12)))
    positive_offsets = unique_offsets[unique_offsets > floor]
    if positive_offsets.size < 2:
        return floor

    for idx in range(len(positive_offsets) - 1):
        current = float(positive_offsets[idx])
        nxt = float(positive_offsets[idx + 1])
        scale = max(current, floor)
        if (nxt / scale) >= 50.0 and ((nxt - current) / scale) >= 10.0:
            return current
    return floor


def _format_nset_block(name: str, node_ids: Sequence[int]) -> str:
    lines = [f"*NSET, NSET={name}"]
    chunk: list[str] = []
    for node_id in node_ids:
        chunk.append(str(int(node_id)))
        if len(chunk) == 16:
            lines.append(", ".join(chunk))
            chunk = []
    if chunk:
        lines.append(", ".join(chunk))
    return "\n".join(lines)


def inp_element_count(inp_path: str | Path) -> int:
    """Return the number of element rows present in a CalculiX ``.inp`` file."""

    count = 0
    in_element_block = False
    for raw in Path(inp_path).read_text(encoding="utf-8", errors="ignore").splitlines():
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
            count += 1
    return count


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
        scaled.append(NamedPoint(point.name, xyz_units, tol_units, point.match_mode))
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


def _parse_gmsh_log_diagnostics(log_text: str) -> dict[str, int]:
    text = str(log_text or "")
    diagnostics = {
        "overlapping_boundary_mesh_count": 0,
        "no_elements_in_volume_count": 0,
        "equivalent_triangles_count": 0,
        "invalid_surface_elements_count": 0,
        "duplicate_boundary_facets_count": 0,
    }
    if not text:
        return diagnostics

    diagnostics["overlapping_boundary_mesh_count"] = len(
        re.findall(
            r"invalid boundary mesh \(overlapping facets\)",
            text,
            flags=re.IGNORECASE,
        )
    )
    diagnostics["no_elements_in_volume_count"] = len(
        re.findall(r"no elements in volume", text, flags=re.IGNORECASE)
    )
    diagnostics["equivalent_triangles_count"] = _sum_regex_group_ints(
        text,
        r"(\d+)\s+triangles are equivalent",
    )
    diagnostics["invalid_surface_elements_count"] = _sum_regex_group_ints(
        text,
        r"(\d+)\s+elements remain invalid in surface",
    )

    duplicate_hits = re.findall(
        r"found\s+([A-Za-z0-9]+)\s+duplicated facets?",
        text,
        flags=re.IGNORECASE,
    )
    diagnostics["duplicate_boundary_facets_count"] = sum(
        _parse_small_count_token(token) for token in duplicate_hits
    )
    return diagnostics


def _sum_regex_group_ints(text: str, pattern: str) -> int:
    return sum(int(token) for token in re.findall(pattern, text, flags=re.IGNORECASE))


def _parse_small_count_token(token: str) -> int:
    token = str(token).strip()
    if token.isdigit():
        return int(token)
    word_map = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    return word_map.get(token.lower(), 1)


def _count_duplicate_shell_facets(inp_path: str | Path) -> int:
    text = Path(inp_path).read_text(encoding="utf-8", errors="ignore")
    facet_counts: dict[tuple[int, ...], int] = {}
    current_type = ""
    in_element_block = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            current_type = _element_type_from_card(line)
            in_element_block = True
            continue
        if line.startswith("*"):
            current_type = ""
            in_element_block = False
            continue
        if not in_element_block or _element_dimension(current_type) != 2:
            continue

        parts = [part.strip() for part in line.split(",") if part.strip()]
        if len(parts) <= 1:
            continue
        key = tuple(sorted(int(token) for token in parts[1:]))
        facet_counts[key] = facet_counts.get(key, 0) + 1

    return sum(count - 1 for count in facet_counts.values() if count > 1)


def _count_element_types(inp_path: str | Path) -> dict[str, int]:
    text = Path(inp_path).read_text(encoding="utf-8", errors="ignore")
    counts: dict[str, int] = {}
    current_type = ""
    in_element_block = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            current_type = _element_type_from_card(line)
            in_element_block = True
            continue
        if line.startswith("*"):
            current_type = ""
            in_element_block = False
            continue
        if not in_element_block:
            continue
        counts[current_type] = counts.get(current_type, 0) + 1

    return counts


def _count_element_families(element_type_counts: dict[str, int]) -> dict[str, int]:
    counts = {"beam": 0, "shell": 0, "solid": 0, "other": 0}
    for element_type, count in element_type_counts.items():
        dimension = _element_dimension(element_type)
        if dimension == 3:
            counts["solid"] += int(count)
        elif dimension == 2:
            counts["shell"] += int(count)
        elif dimension == 1:
            counts["beam"] += int(count)
        else:
            counts["other"] += int(count)
    return counts


def _analysis_reality(element_family_counts: dict[str, int]) -> str:
    beam = int(element_family_counts.get("beam", 0))
    shell = int(element_family_counts.get("shell", 0))
    solid = int(element_family_counts.get("solid", 0))

    if solid > 0 and shell == 0 and beam == 0:
        return "solid_volume_only"
    if solid > 0 and shell == 0 and beam > 0:
        return "solid_plus_beam"
    if solid > 0 and shell > 0:
        return "mixed_solid_and_shell"
    if solid == 0 and shell > 0 and beam == 0:
        return "shell_surface_only"
    if solid == 0 and shell > 0 and beam > 0:
        return "shell_plus_beam"
    if solid == 0 and shell == 0 and beam > 0:
        return "beam_only"
    if solid == 0 and shell == 0 and beam == 0:
        return "no_elements"
    return "unknown"


def _element_type_from_card(card_line: str) -> str:
    for token in card_line.split(","):
        token = token.strip()
        if token.upper().startswith("TYPE="):
            return token.split("=", 1)[1].strip().upper()
    return ""


def _element_dimension(element_type: str) -> int:
    upper = str(element_type).upper()
    if upper.startswith("C3D"):
        return 3
    if upper.startswith(("CPS", "CPE", "S", "M3D")):
        return 2
    if upper.startswith(("T3D", "B31", "B32")):
        return 1
    return 0
