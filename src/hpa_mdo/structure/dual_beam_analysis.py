"""Internal dual-beam structural analysis path (non-optimizer-gating).

This module adds a minimal internal dual-beam analysis route so we can
evaluate the same main/rear spar design variables with a two-beam topology
and rigid rib-link assumptions, without rewriting the optimization loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from hpa_mdo.structure.fem.elements import (
    _cs_norm,
    _rotation_matrix,
    _timoshenko_element_stiffness,
    _transform_12x12,
)
from hpa_mdo.structure.spar_model import tube_area, tube_Ixx, tube_J


@dataclass
class DualBeamAnalysisResult:
    """Outputs from the internal dual-beam analysis path."""

    disp_main: np.ndarray
    disp_rear: np.ndarray
    tip_deflection_main_m: float
    tip_deflection_rear_m: float
    max_vertical_displacement_m: float
    max_vertical_spar: str
    max_vertical_node: int
    spar_mass_half_kg: float
    spar_mass_full_kg: float
    total_applied_fz_n: float
    support_reaction_fz_n: float
    max_vm_main_pa: float
    max_vm_rear_pa: float
    failure_index: float
    loads_main_fz_n: np.ndarray
    loads_rear_fz_n: np.ndarray
    joint_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]


def _assemble_chain_beam(
    k_global: np.ndarray,
    nodes: np.ndarray,
    start_node: int,
    area: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    j_polar: np.ndarray,
    young: float,
    shear: float,
) -> None:
    """Assemble one 6-DOF/node beam chain into the global stiffness matrix."""
    nn = nodes.shape[0]
    ne = nn - 1

    for e in range(ne):
        ni = nodes[e]
        nj = nodes[e + 1]
        dx = nj - ni
        length = _cs_norm(dx)
        if np.real(length) < 1e-12:
            raise ValueError(f"Degenerate beam element length at element {e}.")

        a_e = area[e]
        iy_e = iy[e]
        iz_e = iz[e]
        j_e = j_polar[e]
        if np.real(min(a_e, iy_e, iz_e, j_e)) <= 0.0:
            raise ValueError(
                f"Non-positive section property at element {e}: "
                f"A={a_e}, Iy={iy_e}, Iz={iz_e}, J={j_e}"
            )

        k_local = _timoshenko_element_stiffness(
            length, young, shear, a_e, iy_e, iz_e, j_e
        )
        r3 = _rotation_matrix(ni, nj)
        t12 = _transform_12x12(r3)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            k_elem = t12.T @ k_local @ t12
        if not np.all(np.isfinite(k_elem)):
            raise ValueError(f"Non-finite element stiffness matrix at element {e}.")

        g1 = (start_node + e) * 6
        g2 = (start_node + e + 1) * 6
        dofs = np.concatenate([np.arange(g1, g1 + 6), np.arange(g2, g2 + 6)])
        for ii in range(12):
            gi = int(dofs[ii])
            for jj in range(12):
                gj = int(dofs[jj])
                k_global[gi, gj] += k_elem[ii, jj]


def _apply_equal_dof_penalty(k_global: np.ndarray, dof_a: int, dof_b: int, penalty: float) -> None:
    """Apply penalty-form equation u_a == u_b."""
    k_global[dof_a, dof_a] += penalty
    k_global[dof_b, dof_b] += penalty
    k_global[dof_a, dof_b] -= penalty
    k_global[dof_b, dof_a] -= penalty


def _dual_spar_nodal_fz_loads(exporter) -> tuple[np.ndarray, np.ndarray]:
    """Reproduce dual-spar APDL nodal FZ loads in-memory."""
    nn = exporter.nn
    dy = np.diff(exporter.y)
    fz_main = np.zeros(nn, dtype=float)
    fz_rear = np.zeros(nn, dtype=float)

    # Lift on main spar.
    for j in range(nn):
        if j == 0:
            f_node = exporter.fz_lift[j] * dy[0] / 2.0
        elif j == nn - 1:
            f_node = exporter.fz_lift[j] * dy[-1] / 2.0
        else:
            f_node = exporter.fz_lift[j] * (dy[j - 1] + dy[j]) / 2.0
        fz_main[j] += f_node

    # Aerodynamic torque as a vertical force couple.
    spar_sep = exporter.x_rear - exporter.x_main
    for j in range(nn):
        if j == 0:
            m_node = exporter.my_torque[j] * dy[0] / 2.0
        elif j == nn - 1:
            m_node = exporter.my_torque[j] * dy[-1] / 2.0
        else:
            m_node = exporter.my_torque[j] * (dy[j - 1] + dy[j]) / 2.0

        if abs(m_node) > 1e-12 and abs(spar_sep[j]) > 1e-8:
            fz_couple = m_node / spar_sep[j]
            fz_main[j] += fz_couple
            fz_rear[j] -= fz_couple

    return fz_main, fz_rear


def _beam_von_mises(
    nodes: np.ndarray,
    disp: np.ndarray,
    radius_elem: np.ndarray,
    young: float,
    shear: float,
) -> np.ndarray:
    """Simple beam-fiber von Mises estimate per element."""
    ne = nodes.shape[0] - 1
    vm = np.zeros(ne, dtype=float)
    for e in range(ne):
        dx = nodes[e + 1] - nodes[e]
        length = _cs_norm(dx)
        if np.real(length) < 1e-12:
            continue

        du = disp[e + 1] - disp[e]
        r3 = _rotation_matrix(nodes[e], nodes[e + 1])
        dtheta_local = r3 @ du[3:6]

        kappa = np.sqrt((dtheta_local[1] / length) ** 2 + (dtheta_local[2] / length) ** 2)
        gamma = dtheta_local[0] / length

        sigma_bend = young * radius_elem[e] * kappa
        tau_torsion = shear * radius_elem[e] * gamma
        vm[e] = float(np.sqrt(sigma_bend**2 + 3.0 * tau_torsion**2))

    return vm


def solve_dual_beam_system(
    *,
    nodes_main: np.ndarray,
    nodes_rear: np.ndarray,
    area_main: np.ndarray,
    iy_main: np.ndarray,
    iz_main: np.ndarray,
    j_main: np.ndarray,
    area_rear: np.ndarray,
    iy_rear: np.ndarray,
    iz_rear: np.ndarray,
    j_rear: np.ndarray,
    young_main: float,
    shear_main: float,
    young_rear: float,
    shear_rear: float,
    loads_main_fz_n: np.ndarray,
    loads_rear_fz_n: np.ndarray,
    joint_node_indices: Sequence[int],
    wire_node_indices: Sequence[int],
    bc_penalty: float,
    link_penalty: float | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Solve static dual-beam displacements with rigid rib-link penalties."""
    nn = int(nodes_main.shape[0])
    if nodes_rear.shape != nodes_main.shape:
        raise ValueError("nodes_main and nodes_rear must have the same shape.")
    if nn < 2:
        raise ValueError("Need at least two nodes per spar.")

    ne = nn - 1
    for arr_name, arr in (
        ("area_main", area_main),
        ("iy_main", iy_main),
        ("iz_main", iz_main),
        ("j_main", j_main),
        ("area_rear", area_rear),
        ("iy_rear", iy_rear),
        ("iz_rear", iz_rear),
        ("j_rear", j_rear),
    ):
        if np.asarray(arr).shape != (ne,):
            raise ValueError(f"{arr_name} must have shape ({ne},).")

    loads_main = np.asarray(loads_main_fz_n, dtype=float).reshape(nn)
    loads_rear = np.asarray(loads_rear_fz_n, dtype=float).reshape(nn)
    ndof = 2 * nn * 6

    k_global = np.zeros((ndof, ndof), dtype=float)
    _assemble_chain_beam(
        k_global,
        nodes_main,
        0,
        np.asarray(area_main, dtype=float),
        np.asarray(iy_main, dtype=float),
        np.asarray(iz_main, dtype=float),
        np.asarray(j_main, dtype=float),
        float(young_main),
        float(shear_main),
    )
    _assemble_chain_beam(
        k_global,
        nodes_rear,
        nn,
        np.asarray(area_rear, dtype=float),
        np.asarray(iy_rear, dtype=float),
        np.asarray(iz_rear, dtype=float),
        np.asarray(j_rear, dtype=float),
        float(young_rear),
        float(shear_rear),
    )

    rhs = np.zeros(ndof, dtype=float)
    for i in range(nn):
        rhs[i * 6 + 2] += loads_main[i]
        rhs[(nn + i) * 6 + 2] += loads_rear[i]
    total_applied_fz_n = float(np.sum(loads_main) + np.sum(loads_rear))

    link_penalty_val = float(link_penalty) if link_penalty is not None else float(bc_penalty)
    for idx in joint_node_indices:
        if idx < 0 or idx >= nn:
            continue
        main_base = idx * 6
        rear_base = (nn + idx) * 6
        for dof in range(6):
            _apply_equal_dof_penalty(
                k_global,
                main_base + dof,
                rear_base + dof,
                link_penalty_val,
            )

    constrained_dofs: list[int] = []
    constrained_dofs.extend(range(0, 6))  # main root
    constrained_dofs.extend(range(nn * 6, nn * 6 + 6))  # rear root
    for wn in wire_node_indices:
        if 0 <= wn < nn:
            constrained_dofs.append(wn * 6 + 2)  # main UZ

    for dof in constrained_dofs:
        k_global[dof, dof] += float(bc_penalty)
        rhs[dof] = 0.0

    try:
        u = np.linalg.solve(k_global, rhs)
    except np.linalg.LinAlgError as exc:
        raise RuntimeError("Dual-beam global stiffness matrix is singular.") from exc

    if not np.all(np.isfinite(u)):
        raise RuntimeError("Dual-beam solve produced non-finite displacements.")

    disp_main = u[: nn * 6].reshape((nn, 6))
    disp_rear = u[nn * 6 :].reshape((nn, 6))
    return disp_main, disp_rear, total_applied_fz_n


def run_dual_beam_analysis(
    *,
    cfg,
    aircraft,
    opt_result,
    export_loads: dict,
    materials_db,
    bc_penalty: float | None = None,
    link_penalty: float | None = None,
) -> DualBeamAnalysisResult:
    """Run the internal dual-beam analysis with dual-spar topology assumptions."""
    from hpa_mdo.structure.ansys_export import ANSYSExporter

    exporter = ANSYSExporter(
        cfg,
        aircraft,
        opt_result,
        export_loads,
        materials_db,
        mode="dual_spar",
    )

    nodes_main = np.column_stack((exporter.x_main, exporter.y, exporter.z_main))
    nodes_rear = np.column_stack((exporter.x_rear, exporter.y, exporter.z_rear))

    r_main_elem = 0.5 * (exporter.R_main[:-1] + exporter.R_main[1:])
    t_main_elem = 0.5 * (exporter.t_main[:-1] + exporter.t_main[1:])
    r_rear_elem = 0.5 * (exporter.R_rear[:-1] + exporter.R_rear[1:])
    t_rear_elem = 0.5 * (exporter.t_rear[:-1] + exporter.t_rear[1:])

    area_main = tube_area(r_main_elem, t_main_elem)
    area_rear = tube_area(r_rear_elem, t_rear_elem)
    i_main = tube_Ixx(r_main_elem, t_main_elem)
    i_rear = tube_Ixx(r_rear_elem, t_rear_elem)
    j_main = tube_J(r_main_elem, t_main_elem)
    j_rear = tube_J(r_rear_elem, t_rear_elem)

    loads_main_fz, loads_rear_fz = _dual_spar_nodal_fz_loads(exporter)

    penalty = float(bc_penalty) if bc_penalty is not None else float(cfg.solver.fem_bc_penalty)
    disp_main, disp_rear, total_applied_fz_n = solve_dual_beam_system(
        nodes_main=nodes_main,
        nodes_rear=nodes_rear,
        area_main=area_main,
        iy_main=i_main,
        iz_main=i_main,
        j_main=j_main,
        area_rear=area_rear,
        iy_rear=i_rear,
        iz_rear=i_rear,
        j_rear=j_rear,
        young_main=float(exporter.mat_main.E),
        shear_main=float(exporter.mat_main.G),
        young_rear=float(exporter.mat_rear.E),
        shear_rear=float(exporter.mat_rear.G),
        loads_main_fz_n=loads_main_fz,
        loads_rear_fz_n=loads_rear_fz,
        joint_node_indices=exporter.joint_node_indices,
        wire_node_indices=exporter.wire_nodes,
        bc_penalty=penalty,
        link_penalty=link_penalty,
    )

    tip_main = float(disp_main[-1, 2])
    tip_rear = float(disp_rear[-1, 2])
    main_abs = np.abs(disp_main[:, 2])
    rear_abs = np.abs(disp_rear[:, 2])
    main_max_i = int(np.argmax(main_abs))
    rear_max_i = int(np.argmax(rear_abs))
    main_max = float(main_abs[main_max_i])
    rear_max = float(rear_abs[rear_max_i])
    if rear_max >= main_max:
        max_vertical = rear_max
        max_spar = "rear"
        max_node = rear_max_i + 1
    else:
        max_vertical = main_max
        max_spar = "main"
        max_node = main_max_i + 1

    elem_lengths = np.diff(exporter.y)
    mass_per_length = exporter.mat_main.density * area_main + exporter.mat_rear.density * area_rear
    spar_mass_half = float(np.sum(mass_per_length * elem_lengths))
    spar_mass_full = 2.0 * spar_mass_half

    vm_main = _beam_von_mises(
        nodes_main,
        disp_main,
        r_main_elem,
        float(exporter.mat_main.E),
        float(exporter.mat_main.G),
    )
    vm_rear = _beam_von_mises(
        nodes_rear,
        disp_rear,
        r_rear_elem,
        float(exporter.mat_rear.E),
        float(exporter.mat_rear.G),
    )
    max_vm_main = float(np.max(vm_main)) if vm_main.size else 0.0
    max_vm_rear = float(np.max(vm_rear)) if vm_rear.size else 0.0

    allow_main = min(
        exporter.mat_main.tensile_strength,
        exporter.mat_main.compressive_strength or exporter.mat_main.tensile_strength,
    ) / cfg.safety.material_safety_factor
    allow_rear = min(
        exporter.mat_rear.tensile_strength,
        exporter.mat_rear.compressive_strength or exporter.mat_rear.tensile_strength,
    ) / cfg.safety.material_safety_factor
    failure_index = max(max_vm_main / allow_main, max_vm_rear / allow_rear) - 1.0

    return DualBeamAnalysisResult(
        disp_main=disp_main,
        disp_rear=disp_rear,
        tip_deflection_main_m=tip_main,
        tip_deflection_rear_m=tip_rear,
        max_vertical_displacement_m=max_vertical,
        max_vertical_spar=max_spar,
        max_vertical_node=max_node,
        spar_mass_half_kg=spar_mass_half,
        spar_mass_full_kg=spar_mass_full,
        total_applied_fz_n=total_applied_fz_n,
        support_reaction_fz_n=abs(total_applied_fz_n),
        max_vm_main_pa=max_vm_main,
        max_vm_rear_pa=max_vm_rear,
        failure_index=float(failure_index),
        loads_main_fz_n=loads_main_fz.copy(),
        loads_rear_fz_n=loads_rear_fz.copy(),
        joint_node_indices=tuple(int(i) for i in exporter.joint_node_indices),
        wire_node_indices=tuple(int(i) for i in exporter.wire_nodes),
    )
