"""Linear CalculiX beam-deck helpers for Phase 14 parity benchmarks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class BeamMaterial:
    """Minimal isotropic beam material payload for CalculiX beam decks."""

    name: str
    young_pa: float
    poisson_ratio: float
    density_kgpm3: float


@dataclass(frozen=True)
class SinglePipeCantileverSpec:
    """One straight pipe beam clamped at the root."""

    name: str
    y_nodes_m: np.ndarray
    outer_radius_m: np.ndarray
    thickness_m: np.ndarray
    material: BeamMaterial
    nodal_fz_n: np.ndarray
    nodal_my_nm: np.ndarray
    wire_node_indices: tuple[int, ...]


@dataclass(frozen=True)
class DualPipeBenchmarkSpec:
    """Two straight pipe beams with optional rib links and wire supports."""

    name: str
    y_nodes_m: np.ndarray
    main_x_m: np.ndarray
    rear_x_m: np.ndarray
    main_z_m: np.ndarray
    rear_z_m: np.ndarray
    main_outer_radius_m: np.ndarray
    main_thickness_m: np.ndarray
    rear_outer_radius_m: np.ndarray
    rear_thickness_m: np.ndarray
    material_main: BeamMaterial
    material_rear: BeamMaterial
    main_nodal_fz_n: np.ndarray
    rear_nodal_fz_n: np.ndarray
    main_nodal_my_nm: np.ndarray
    rear_nodal_my_nm: np.ndarray
    joint_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]
    joint_link_mode: str = "equal_dof"


@dataclass(frozen=True)
class CalculixBeamDeck:
    """Written deck path and named node-set metadata."""

    inp_path: Path
    node_sets: dict[str, tuple[int, ...]]


def cantilever_tip_deflection_point_load(
    *,
    point_load_n: float,
    span_m: float,
    young_pa: float,
    second_moment_m4: float,
) -> float:
    """Return Euler-Bernoulli cantilever tip deflection for a point load."""

    return float(point_load_n) * float(span_m) ** 3 / (
        3.0 * float(young_pa) * float(second_moment_m4)
    )


def cantilever_tip_deflection_uniform_load(
    *,
    uniform_load_npm: float,
    span_m: float,
    young_pa: float,
    second_moment_m4: float,
) -> float:
    """Return Euler-Bernoulli cantilever tip deflection for a uniform load."""

    return float(uniform_load_npm) * float(span_m) ** 4 / (
        8.0 * float(young_pa) * float(second_moment_m4)
    )


def build_single_pipe_cantilever_spec(
    *,
    name: str,
    y_nodes_m: np.ndarray,
    outer_radius_m: np.ndarray,
    thickness_m: np.ndarray,
    material: BeamMaterial,
    nodal_fz_n: np.ndarray,
    nodal_my_nm: np.ndarray | None = None,
    wire_node_indices: tuple[int, ...] = (),
) -> SinglePipeCantileverSpec:
    """Build one straight beam benchmark spec."""

    y_nodes = _as_1d_array(y_nodes_m, "y_nodes_m")
    ne = y_nodes.size - 1
    if ne < 1:
        raise ValueError("At least two nodes are required for a cantilever beam.")
    return SinglePipeCantileverSpec(
        name=name,
        y_nodes_m=y_nodes,
        outer_radius_m=_as_sized_array(outer_radius_m, ne, "outer_radius_m"),
        thickness_m=_as_sized_array(thickness_m, ne, "thickness_m"),
        material=material,
        nodal_fz_n=_as_sized_array(nodal_fz_n, y_nodes.size, "nodal_fz_n"),
        nodal_my_nm=(
            np.zeros(y_nodes.size, dtype=float)
            if nodal_my_nm is None
            else _as_sized_array(nodal_my_nm, y_nodes.size, "nodal_my_nm")
        ),
        wire_node_indices=tuple(int(idx) for idx in wire_node_indices),
    )


def build_dual_pipe_benchmark_spec(
    *,
    name: str,
    y_nodes_m: np.ndarray,
    main_x_m: np.ndarray,
    rear_x_m: np.ndarray,
    main_z_m: np.ndarray,
    rear_z_m: np.ndarray,
    main_outer_radius_m: np.ndarray,
    main_thickness_m: np.ndarray,
    rear_outer_radius_m: np.ndarray,
    rear_thickness_m: np.ndarray,
    material_main: BeamMaterial,
    material_rear: BeamMaterial,
    main_nodal_fz_n: np.ndarray,
    rear_nodal_fz_n: np.ndarray,
    main_nodal_my_nm: np.ndarray | None = None,
    rear_nodal_my_nm: np.ndarray | None = None,
    joint_node_indices: tuple[int, ...] = (),
    wire_node_indices: tuple[int, ...] = (),
    joint_link_mode: str = "equal_dof",
) -> DualPipeBenchmarkSpec:
    """Build one two-beam parity benchmark spec."""

    y_nodes = _as_1d_array(y_nodes_m, "y_nodes_m")
    ne = y_nodes.size - 1
    if ne < 1:
        raise ValueError("At least two nodes are required for a dual-beam benchmark.")
    if joint_link_mode not in {"equal_dof", "offset_rigid"}:
        raise ValueError("joint_link_mode must be 'equal_dof' or 'offset_rigid'.")
    return DualPipeBenchmarkSpec(
        name=name,
        y_nodes_m=y_nodes,
        main_x_m=_as_sized_array(main_x_m, y_nodes.size, "main_x_m"),
        rear_x_m=_as_sized_array(rear_x_m, y_nodes.size, "rear_x_m"),
        main_z_m=_as_sized_array(main_z_m, y_nodes.size, "main_z_m"),
        rear_z_m=_as_sized_array(rear_z_m, y_nodes.size, "rear_z_m"),
        main_outer_radius_m=_as_sized_array(main_outer_radius_m, ne, "main_outer_radius_m"),
        main_thickness_m=_as_sized_array(main_thickness_m, ne, "main_thickness_m"),
        rear_outer_radius_m=_as_sized_array(rear_outer_radius_m, ne, "rear_outer_radius_m"),
        rear_thickness_m=_as_sized_array(rear_thickness_m, ne, "rear_thickness_m"),
        material_main=material_main,
        material_rear=material_rear,
        main_nodal_fz_n=_as_sized_array(main_nodal_fz_n, y_nodes.size, "main_nodal_fz_n"),
        rear_nodal_fz_n=_as_sized_array(rear_nodal_fz_n, y_nodes.size, "rear_nodal_fz_n"),
        main_nodal_my_nm=(
            np.zeros(y_nodes.size, dtype=float)
            if main_nodal_my_nm is None
            else _as_sized_array(main_nodal_my_nm, y_nodes.size, "main_nodal_my_nm")
        ),
        rear_nodal_my_nm=(
            np.zeros(y_nodes.size, dtype=float)
            if rear_nodal_my_nm is None
            else _as_sized_array(rear_nodal_my_nm, y_nodes.size, "rear_nodal_my_nm")
        ),
        joint_node_indices=tuple(int(idx) for idx in joint_node_indices),
        wire_node_indices=tuple(int(idx) for idx in wire_node_indices),
        joint_link_mode=joint_link_mode,
    )


def write_calculix_beam_inp(
    spec: SinglePipeCantileverSpec | DualPipeBenchmarkSpec,
    path: str | Path,
    *,
    analysis_kind: str = "static",
    n_buckle_modes: int = 5,
) -> CalculixBeamDeck:
    """Write one standalone linear-static CalculiX beam deck."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if analysis_kind not in {"static", "buckle"}:
        raise ValueError("analysis_kind must be 'static' or 'buckle'.")
    if n_buckle_modes < 1:
        raise ValueError("n_buckle_modes must be >= 1.")
    if isinstance(spec, SinglePipeCantileverSpec):
        text, node_sets = _single_beam_text(
            spec,
            analysis_kind=analysis_kind,
            n_buckle_modes=n_buckle_modes,
        )
    else:
        text, node_sets = _dual_beam_text(
            spec,
            analysis_kind=analysis_kind,
            n_buckle_modes=n_buckle_modes,
        )
    out_path.write_text(text, encoding="utf-8")
    return CalculixBeamDeck(inp_path=out_path, node_sets=node_sets)


def _single_beam_text(
    spec: SinglePipeCantileverSpec,
    *,
    analysis_kind: str,
    n_buckle_modes: int,
) -> tuple[str, dict[str, tuple[int, ...]]]:
    nn = spec.y_nodes_m.size
    main_topology = _quadratic_chain_topology(
        x_nodes_m=np.zeros(nn, dtype=float),
        y_nodes_m=spec.y_nodes_m,
        z_nodes_m=np.zeros(nn, dtype=float),
        start_node_id=1,
    )
    node_sets: dict[str, tuple[int, ...]] = {
        "ROOT_MAIN": (main_topology.endpoint_node_ids[0],),
        "TIP_MAIN": (main_topology.endpoint_node_ids[-1],),
    }
    if spec.wire_node_indices:
        node_sets["WIRE_MAIN"] = tuple(
            main_topology.endpoint_node_ids[int(idx)] for idx in spec.wire_node_indices
        )
    node_sets["HPA_SUPPORT_ROOT"] = node_sets["ROOT_MAIN"]
    node_sets["HPA_SUPPORT_ALL"] = tuple(
        sorted({*node_sets["ROOT_MAIN"], *node_sets.get("WIRE_MAIN", ())})
    )
    if spec.wire_node_indices:
        node_sets["HPA_SUPPORT_WIRE"] = node_sets["WIRE_MAIN"]

    lines = [
        f"** Phase 14 beam deck: {spec.name}",
        "*NODE",
    ]
    lines.extend(main_topology.node_lines)

    for elem_index, (node_i, node_mid, node_j) in enumerate(main_topology.element_connectivity, start=1):
        lines.extend(
            [
                f"*ELEMENT, TYPE=B32R, ELSET=MAIN_E{elem_index}",
                f"{elem_index}, {node_i}, {node_mid}, {node_j}",
            ]
        )

    lines.extend(_format_node_sets(node_sets))
    lines.extend(_material_block(spec.material))
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.outer_radius_m, spec.thickness_m, strict=True),
        start=1,
    ):
        lines.extend(
            [
                f"*BEAM SECTION,ELSET=MAIN_E{elem_index},MATERIAL={spec.material.name},SECTION=PIPE",
                f"{outer_radius_m:.9g}, {thickness_m:.9g}",
                "1.0, 0.0, 0.0",
            ]
        )

    lines.append("*BOUNDARY")
    lines.append(f"{node_sets['ROOT_MAIN'][0]}, 1, 6")
    for node_id in node_sets.get("WIRE_MAIN", ()):
        lines.append(f"{node_id}, 3, 3, 0.0")

    cload_lines: list[str] = []
    for node_id, fz_n in zip(main_topology.endpoint_node_ids, spec.nodal_fz_n, strict=True):
        if abs(float(fz_n)) > 0.0:
            cload_lines.append(f"{node_id}, 3, {float(fz_n):.9g}")
        station_index = main_topology.endpoint_node_ids.index(node_id)
        my_nm = float(spec.nodal_my_nm[station_index])
        if abs(my_nm) > 0.0:
            cload_lines.append(f"{node_id}, 5, {my_nm:.9g}")

    lines.extend(
        _analysis_step_lines(
            cload_lines,
            node_sets,
            analysis_kind=analysis_kind,
            n_buckle_modes=n_buckle_modes,
        )
    )
    return "\n".join(lines), node_sets


def _dual_beam_text(
    spec: DualPipeBenchmarkSpec,
    *,
    analysis_kind: str,
    n_buckle_modes: int,
) -> tuple[str, dict[str, tuple[int, ...]]]:
    nn = spec.y_nodes_m.size
    main_topology = _quadratic_chain_topology(
        x_nodes_m=spec.main_x_m,
        y_nodes_m=spec.y_nodes_m,
        z_nodes_m=spec.main_z_m,
        start_node_id=1,
    )
    rear_topology = _quadratic_chain_topology(
        x_nodes_m=spec.rear_x_m,
        y_nodes_m=spec.y_nodes_m,
        z_nodes_m=spec.rear_z_m,
        start_node_id=main_topology.last_node_id + 1,
    )
    node_sets: dict[str, tuple[int, ...]] = {
        "ROOT_MAIN": (main_topology.endpoint_node_ids[0],),
        "TIP_MAIN": (main_topology.endpoint_node_ids[-1],),
        "ROOT_REAR": (rear_topology.endpoint_node_ids[0],),
        "TIP_REAR": (rear_topology.endpoint_node_ids[-1],),
    }
    if spec.wire_node_indices:
        node_sets["WIRE_MAIN"] = tuple(
            main_topology.endpoint_node_ids[int(idx)] for idx in spec.wire_node_indices
        )
        wire_rear_link_nodes = tuple(
            rear_topology.endpoint_node_ids[int(idx)]
            for idx in spec.wire_node_indices
            if int(idx) in set(spec.joint_node_indices)
        )
        if wire_rear_link_nodes:
            node_sets["WIRE_REAR_LINK"] = wire_rear_link_nodes
    node_sets["HPA_SUPPORT_ROOT"] = tuple(sorted({*node_sets["ROOT_MAIN"], *node_sets["ROOT_REAR"]}))
    if spec.wire_node_indices:
        node_sets["HPA_SUPPORT_WIRE"] = tuple(
            sorted({*node_sets["WIRE_MAIN"], *node_sets.get("WIRE_REAR_LINK", ())})
        )
    node_sets["HPA_SUPPORT_ALL"] = tuple(
        sorted({*node_sets["HPA_SUPPORT_ROOT"], *node_sets.get("HPA_SUPPORT_WIRE", ())})
    )

    lines = [
        f"** Phase 14 beam deck: {spec.name}",
        f"** joint_link_mode={spec.joint_link_mode}",
        "*NODE",
    ]
    lines.extend(main_topology.node_lines)
    lines.extend(rear_topology.node_lines)

    element_id = 1
    for elem_index, (node_i, node_mid, node_j) in enumerate(main_topology.element_connectivity, start=1):
        lines.extend(
            [
                f"*ELEMENT, TYPE=B32R, ELSET=MAIN_E{elem_index}",
                f"{element_id}, {node_i}, {node_mid}, {node_j}",
            ]
        )
        element_id += 1
    for elem_index, (node_i, node_mid, node_j) in enumerate(rear_topology.element_connectivity, start=1):
        lines.extend(
            [
                f"*ELEMENT, TYPE=B32R, ELSET=REAR_E{elem_index}",
                f"{element_id}, {node_i}, {node_mid}, {node_j}",
            ]
        )
        element_id += 1

    lines.extend(_format_node_sets(node_sets))
    lines.extend(_material_block(spec.material_main))
    lines.extend(_material_block(spec.material_rear))
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.main_outer_radius_m, spec.main_thickness_m, strict=True),
        start=1,
    ):
        lines.extend(
            [
                f"*BEAM SECTION,ELSET=MAIN_E{elem_index},MATERIAL={spec.material_main.name},SECTION=PIPE",
                f"{outer_radius_m:.9g}, {thickness_m:.9g}",
                "1.0, 0.0, 0.0",
            ]
        )
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.rear_outer_radius_m, spec.rear_thickness_m, strict=True),
        start=1,
    ):
        lines.extend(
            [
                f"*BEAM SECTION,ELSET=REAR_E{elem_index},MATERIAL={spec.material_rear.name},SECTION=PIPE",
                f"{outer_radius_m:.9g}, {thickness_m:.9g}",
                "1.0, 0.0, 0.0",
            ]
        )

    wire_node_index_set = {int(idx) for idx in spec.wire_node_indices}
    for node_index in spec.joint_node_indices:
        main_node = main_topology.endpoint_node_ids[int(node_index)]
        rear_node = rear_topology.endpoint_node_ids[int(node_index)]
        if spec.joint_link_mode == "equal_dof":
            for dof in range(1, 7):
                if dof == 3 and int(node_index) in wire_node_index_set:
                    equation_terms = f"{rear_node}, {dof}, 1.0, {main_node}, {dof}, -1.0"
                else:
                    equation_terms = f"{main_node}, {dof}, 1.0, {rear_node}, {dof}, -1.0"
                lines.extend(
                    [
                        "*EQUATION",
                        "2",
                        equation_terms,
                    ]
                )
        elif spec.joint_link_mode == "offset_rigid":
            offset_vector = np.array(
                [
                    float(spec.rear_x_m[int(node_index)] - spec.main_x_m[int(node_index)]),
                    0.0,
                    float(spec.rear_z_m[int(node_index)] - spec.main_z_m[int(node_index)]),
                ],
                dtype=float,
            )
            lines.extend(
                _offset_rigid_equation_lines(
                    main_node=main_node,
                    rear_node=rear_node,
                    offset_vector_m=offset_vector,
                )
            )
        else:
            raise ValueError(f"Unsupported joint_link_mode: {spec.joint_link_mode}.")

    lines.append("*BOUNDARY")
    lines.append(f"{node_sets['ROOT_MAIN'][0]}, 1, 6")
    lines.append(f"{node_sets['ROOT_REAR'][0]}, 1, 6")
    for node_id in node_sets.get("WIRE_MAIN", ()):
        lines.append(f"{node_id}, 3, 3, 0.0")

    cload_lines: list[str] = []
    for node_index in range(nn):
        main_node = main_topology.endpoint_node_ids[node_index]
        rear_node = rear_topology.endpoint_node_ids[node_index]

        main_fz_n = float(spec.main_nodal_fz_n[node_index])
        if abs(main_fz_n) > 0.0:
            cload_lines.append(f"{main_node}, 3, {main_fz_n:.9g}")
        rear_fz_n = float(spec.rear_nodal_fz_n[node_index])
        if abs(rear_fz_n) > 0.0:
            cload_lines.append(f"{rear_node}, 3, {rear_fz_n:.9g}")

        main_my_nm = float(spec.main_nodal_my_nm[node_index])
        if abs(main_my_nm) > 0.0:
            cload_lines.append(f"{main_node}, 5, {main_my_nm:.9g}")
        rear_my_nm = float(spec.rear_nodal_my_nm[node_index])
        if abs(rear_my_nm) > 0.0:
            cload_lines.append(f"{rear_node}, 5, {rear_my_nm:.9g}")

    lines.extend(
        _analysis_step_lines(
            cload_lines,
            node_sets,
            analysis_kind=analysis_kind,
            n_buckle_modes=n_buckle_modes,
        )
    )
    return "\n".join(lines), node_sets


def _analysis_step_lines(
    cload_lines: list[str],
    node_sets: dict[str, tuple[int, ...]],
    *,
    analysis_kind: str,
    n_buckle_modes: int,
) -> list[str]:
    if analysis_kind == "buckle":
        return [
            "*STEP",
            "*BUCKLE",
            str(int(n_buckle_modes)),
            "*CLOAD",
            *cload_lines,
            *_reaction_output_block(node_sets),
            "*NODE FILE, OUTPUT=2D",
            "U",
            "*END STEP",
            "",
        ]

    return [
        "*STEP",
        "*STATIC",
        "1.0, 1.0",
        "*CLOAD",
        *cload_lines,
        *_reaction_output_block(node_sets),
        "*NODE FILE, OUTPUT=2D",
        "U",
        "*END STEP",
        "",
    ]


def _format_node_sets(node_sets: dict[str, tuple[int, ...]]) -> list[str]:
    lines: list[str] = []
    for name, node_ids in node_sets.items():
        lines.append(f"*NSET, NSET={name}")
        lines.append(", ".join(str(int(node_id)) for node_id in node_ids))
    return lines


def _offset_rigid_equation_lines(
    *,
    main_node: int,
    rear_node: int,
    offset_vector_m: np.ndarray,
) -> list[str]:
    """Return CalculiX equations matching the internal offset-rigid rib row basis."""

    dx, dy, dz = np.asarray(offset_vector_m, dtype=float)
    skew = np.array(
        [
            [0.0, -dz, dy],
            [dz, 0.0, -dx],
            [-dy, dx, 0.0],
        ],
        dtype=float,
    )
    equations: list[list[tuple[int, int, float]]] = []
    for axis in range(3):
        terms = [
            (int(rear_node), axis + 1, 1.0),
            (int(main_node), axis + 1, -1.0),
        ]
        for rot_axis in range(3):
            coeff = 0.5 * float(skew[axis, rot_axis])
            if abs(coeff) > 1.0e-14:
                terms.append((int(main_node), 4 + rot_axis, coeff))
                terms.append((int(rear_node), 4 + rot_axis, coeff))
        equations.append(terms)
    for axis in range(3):
        equations.append(
            [
                (int(rear_node), 4 + axis, 1.0),
                (int(main_node), 4 + axis, -1.0),
            ]
        )

    lines: list[str] = []
    for terms in equations:
        lines.extend(["*EQUATION", str(len(terms))])
        lines.extend(_format_equation_term_lines(terms))
    return lines


def _format_equation_term_lines(terms: list[tuple[int, int, float]]) -> list[str]:
    lines: list[str] = []
    for start in range(0, len(terms), 4):
        chunks: list[str] = []
        for node_id, dof, coeff in terms[start : start + 4]:
            chunks.extend([str(int(node_id)), str(int(dof)), _format_float(float(coeff))])
        lines.append(", ".join(chunks))
    return lines


def _format_float(value: float) -> str:
    if abs(float(value) - 1.0) <= 1.0e-14:
        return "1.0"
    if abs(float(value) + 1.0) <= 1.0e-14:
        return "-1.0"
    return f"{float(value):.9g}"


@dataclass(frozen=True)
class _QuadraticChainTopology:
    node_lines: tuple[str, ...]
    endpoint_node_ids: tuple[int, ...]
    element_connectivity: tuple[tuple[int, int, int], ...]
    last_node_id: int


def _quadratic_chain_topology(
    *,
    x_nodes_m: np.ndarray,
    y_nodes_m: np.ndarray,
    z_nodes_m: np.ndarray,
    start_node_id: int,
) -> _QuadraticChainTopology:
    endpoint_node_ids = [int(start_node_id)]
    node_lines = [
        _node_line(
            int(start_node_id),
            float(x_nodes_m[0]),
            float(y_nodes_m[0]),
            float(z_nodes_m[0]),
        )
    ]
    element_connectivity: list[tuple[int, int, int]] = []
    current_endpoint = int(start_node_id)

    for elem_index in range(y_nodes_m.size - 1):
        next_endpoint = current_endpoint + 2
        midpoint_id = current_endpoint + 1
        x_mid = 0.5 * (float(x_nodes_m[elem_index]) + float(x_nodes_m[elem_index + 1]))
        y_mid = 0.5 * (float(y_nodes_m[elem_index]) + float(y_nodes_m[elem_index + 1]))
        z_mid = 0.5 * (float(z_nodes_m[elem_index]) + float(z_nodes_m[elem_index + 1]))
        node_lines.append(_node_line(midpoint_id, x_mid, y_mid, z_mid))
        node_lines.append(
            _node_line(
                next_endpoint,
                float(x_nodes_m[elem_index + 1]),
                float(y_nodes_m[elem_index + 1]),
                float(z_nodes_m[elem_index + 1]),
            )
        )
        element_connectivity.append((current_endpoint, midpoint_id, next_endpoint))
        endpoint_node_ids.append(next_endpoint)
        current_endpoint = next_endpoint

    return _QuadraticChainTopology(
        node_lines=tuple(node_lines),
        endpoint_node_ids=tuple(endpoint_node_ids),
        element_connectivity=tuple(element_connectivity),
        last_node_id=current_endpoint,
    )


def _node_line(node_id: int, x_m: float, y_m: float, z_m: float) -> str:
    return f"{node_id}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}"


def _material_block(material: BeamMaterial) -> list[str]:
    return [
        f"*MATERIAL, NAME={material.name}",
        "*ELASTIC",
        f"{material.young_pa:.9g}, {material.poisson_ratio:.9g}",
        "*DENSITY",
        f"{material.density_kgpm3:.9g}",
    ]


def _reaction_output_block(node_sets: dict[str, tuple[int, ...]]) -> list[str]:
    lines: list[str] = []
    for set_name in ("HPA_SUPPORT_ALL", "HPA_SUPPORT_ROOT", "HPA_SUPPORT_WIRE"):
        if set_name not in node_sets:
            continue
        lines.extend(
            [
                f"*NODE PRINT, NSET={set_name}, TOTALS=ONLY",
                "RF",
            ]
        )
    return lines


def _as_1d_array(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional.")
    return array


def _as_sized_array(values: np.ndarray, expected_size: int, name: str) -> np.ndarray:
    array = _as_1d_array(values, name)
    if array.size != expected_size:
        raise ValueError(f"{name} must have size {expected_size}; got {array.size}.")
    return array
