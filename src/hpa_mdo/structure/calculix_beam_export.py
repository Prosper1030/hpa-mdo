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
    """Two straight pipe beams with optional equal-DOF links and wire supports."""

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
) -> DualPipeBenchmarkSpec:
    """Build one two-beam parity benchmark spec."""

    y_nodes = _as_1d_array(y_nodes_m, "y_nodes_m")
    ne = y_nodes.size - 1
    if ne < 1:
        raise ValueError("At least two nodes are required for a dual-beam benchmark.")
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
    )


def write_calculix_beam_inp(
    spec: SinglePipeCantileverSpec | DualPipeBenchmarkSpec,
    path: str | Path,
) -> CalculixBeamDeck:
    """Write one standalone linear-static CalculiX beam deck."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(spec, SinglePipeCantileverSpec):
        text, node_sets = _single_beam_text(spec)
    else:
        text, node_sets = _dual_beam_text(spec)
    out_path.write_text(text, encoding="utf-8")
    return CalculixBeamDeck(inp_path=out_path, node_sets=node_sets)


def _single_beam_text(
    spec: SinglePipeCantileverSpec,
) -> tuple[str, dict[str, tuple[int, ...]]]:
    nn = spec.y_nodes_m.size
    node_sets: dict[str, tuple[int, ...]] = {
        "ROOT_MAIN": (1,),
        "TIP_MAIN": (nn,),
    }
    if spec.wire_node_indices:
        node_sets["WIRE_MAIN"] = tuple(idx + 1 for idx in spec.wire_node_indices)
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
    for idx, y_coord_m in enumerate(spec.y_nodes_m, start=1):
        lines.append(f"{idx}, 0.0, {y_coord_m:.9g}, 0.0")

    for elem_index in range(nn - 1):
        node_i = elem_index + 1
        node_j = elem_index + 2
        lines.extend(
            [
                f"*ELEMENT, TYPE=B31, ELSET=MAIN_E{elem_index + 1}",
                f"{elem_index + 1}, {node_i}, {node_j}",
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
    lines.append("1, 1, 6")
    for node_id in node_sets.get("WIRE_MAIN", ()):
        lines.append(f"{node_id}, 3, 3, 0.0")

    lines.extend(
        [
            "*STEP, NAME=static",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_id, fz_n in enumerate(spec.nodal_fz_n, start=1):
        if abs(float(fz_n)) > 0.0:
            lines.append(f"{node_id}, 3, {float(fz_n):.9g}")
        my_nm = float(spec.nodal_my_nm[node_id - 1])
        if abs(my_nm) > 0.0:
            lines.append(f"{node_id}, 5, {my_nm:.9g}")

    lines.extend(_reaction_output_block(node_sets))
    lines.extend(
        [
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "",
        ]
    )
    return "\n".join(lines), node_sets


def _dual_beam_text(
    spec: DualPipeBenchmarkSpec,
) -> tuple[str, dict[str, tuple[int, ...]]]:
    nn = spec.y_nodes_m.size
    rear_offset = nn
    node_sets: dict[str, tuple[int, ...]] = {
        "ROOT_MAIN": (1,),
        "TIP_MAIN": (nn,),
        "ROOT_REAR": (rear_offset + 1,),
        "TIP_REAR": (rear_offset + nn,),
    }
    if spec.wire_node_indices:
        node_sets["WIRE_MAIN"] = tuple(idx + 1 for idx in spec.wire_node_indices)
    node_sets["HPA_SUPPORT_ROOT"] = tuple(sorted({*node_sets["ROOT_MAIN"], *node_sets["ROOT_REAR"]}))
    node_sets["HPA_SUPPORT_ALL"] = tuple(
        sorted({*node_sets["HPA_SUPPORT_ROOT"], *node_sets.get("WIRE_MAIN", ())})
    )
    if spec.wire_node_indices:
        node_sets["HPA_SUPPORT_WIRE"] = node_sets["WIRE_MAIN"]

    lines = [
        f"** Phase 14 beam deck: {spec.name}",
        "*NODE",
    ]
    for idx, (x_m, y_m, z_m) in enumerate(
        zip(spec.main_x_m, spec.y_nodes_m, spec.main_z_m, strict=True),
        start=1,
    ):
        lines.append(f"{idx}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}")
    for idx, (x_m, y_m, z_m) in enumerate(
        zip(spec.rear_x_m, spec.y_nodes_m, spec.rear_z_m, strict=True),
        start=rear_offset + 1,
    ):
        lines.append(f"{idx}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}")

    element_id = 1
    for elem_index in range(nn - 1):
        lines.extend(
            [
                f"*ELEMENT, TYPE=B31, ELSET=MAIN_E{elem_index + 1}",
                f"{element_id}, {elem_index + 1}, {elem_index + 2}",
            ]
        )
        element_id += 1
    for elem_index in range(nn - 1):
        node_i = rear_offset + elem_index + 1
        node_j = rear_offset + elem_index + 2
        lines.extend(
            [
                f"*ELEMENT, TYPE=B31, ELSET=REAR_E{elem_index + 1}",
                f"{element_id}, {node_i}, {node_j}",
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

    for node_index in spec.joint_node_indices:
        main_node = int(node_index) + 1
        rear_node = rear_offset + int(node_index) + 1
        for dof in range(1, 7):
            lines.extend(
                [
                    "*EQUATION",
                    "2",
                    f"{main_node}, {dof}, 1.0, {rear_node}, {dof}, -1.0",
                ]
            )

    lines.append("*BOUNDARY")
    lines.append("1, 1, 6")
    lines.append(f"{rear_offset + 1}, 1, 6")
    for node_id in node_sets.get("WIRE_MAIN", ()):
        lines.append(f"{node_id}, 3, 3, 0.0")

    lines.extend(
        [
            "*STEP, NAME=static",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_index in range(nn):
        main_node = node_index + 1
        rear_node = rear_offset + node_index + 1

        main_fz_n = float(spec.main_nodal_fz_n[node_index])
        if abs(main_fz_n) > 0.0:
            lines.append(f"{main_node}, 3, {main_fz_n:.9g}")
        rear_fz_n = float(spec.rear_nodal_fz_n[node_index])
        if abs(rear_fz_n) > 0.0:
            lines.append(f"{rear_node}, 3, {rear_fz_n:.9g}")

        main_my_nm = float(spec.main_nodal_my_nm[node_index])
        if abs(main_my_nm) > 0.0:
            lines.append(f"{main_node}, 5, {main_my_nm:.9g}")
        rear_my_nm = float(spec.rear_nodal_my_nm[node_index])
        if abs(rear_my_nm) > 0.0:
            lines.append(f"{rear_node}, 5, {rear_my_nm:.9g}")

    lines.extend(_reaction_output_block(node_sets))
    lines.extend(
        [
            "*NODE FILE, OUTPUT=3D",
            "U",
            "*END STEP",
            "",
        ]
    )
    return "\n".join(lines), node_sets


def _format_node_sets(node_sets: dict[str, tuple[int, ...]]) -> list[str]:
    lines: list[str] = []
    for name, node_ids in node_sets.items():
        lines.append(f"*NSET, NSET={name}")
        lines.append(", ".join(str(int(node_id)) for node_id in node_ids))
    return lines


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
