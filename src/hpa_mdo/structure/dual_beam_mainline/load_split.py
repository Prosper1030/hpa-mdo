"""Load ownership and torque conversion for the dual-beam mainline kernel."""

from __future__ import annotations

import numpy as np

from hpa_mdo.core.constants import G_STANDARD

from hpa_mdo.structure.dual_beam_mainline.types import (
    AnalysisModeDefinition,
    AnalysisModeName,
    DualBeamMainlineModel,
    LoadSplitResult,
    TorqueReferenceMode,
)


def convert_torque_to_main_spar_reference(
    *,
    lift_per_span_npm: np.ndarray,
    torque_per_span_nmpm: np.ndarray,
    main_spar_x_nodes_m: np.ndarray,
    torque_input,
) -> np.ndarray:
    """Convert any aerodynamic torque input to one signed moment about the main spar."""

    lift = np.asarray(lift_per_span_npm, dtype=float)
    torque = np.asarray(torque_per_span_nmpm, dtype=float)
    x_main = np.asarray(main_spar_x_nodes_m, dtype=float)

    if torque_input.reference_mode == TorqueReferenceMode.ABOUT_MAIN_SPAR:
        return torque.copy()

    if torque_input.reference_x_nodes_m is None or torque_input.center_of_pressure_x_nodes_m is None:
        raise ValueError(
            "Torque inputs referenced away from the main spar require reference_x_nodes_m "
            "and center_of_pressure_x_nodes_m."
        )

    x_ref = np.asarray(torque_input.reference_x_nodes_m, dtype=float)
    x_cp = np.asarray(torque_input.center_of_pressure_x_nodes_m, dtype=float)
    if x_ref.shape != torque.shape or x_cp.shape != torque.shape:
        raise ValueError("torque reference arrays must match torque_per_span shape.")

    # Spec rule: convert once to a single moment about the main spar, then reuse one split path.
    return torque - (x_cp - x_main) * lift


def _beam_line_self_weight_nodal(
    mass_per_length_kgpm: np.ndarray,
    element_lengths_m: np.ndarray,
    gravity_scale: float,
    nn: int,
) -> np.ndarray:
    """Return nodal Fz loads for tube-only self-weight on one beam line."""

    nodal = np.zeros(nn, dtype=float)
    for e, (mpl, length) in enumerate(zip(mass_per_length_kgpm, element_lengths_m, strict=True)):
        element_weight_n = mpl * G_STANDARD * gravity_scale * length
        nodal[e] -= 0.5 * element_weight_n
        nodal[e + 1] -= 0.5 * element_weight_n
    return nodal


def collapse_explicit_rear_weight_to_equivalent_my_n(
    *,
    rear_mass_per_length_kgpm: np.ndarray,
    spar_separation_elem_m: np.ndarray,
    element_lengths_m: np.ndarray,
    gravity_scale: float,
) -> np.ndarray:
    """Collapse explicit rear-beam self-weight into equivalent-beam torsional nodal loads."""

    ne = rear_mass_per_length_kgpm.size
    nodal = np.zeros(ne + 1, dtype=float)
    for e, (mpl, arm, length) in enumerate(
        zip(rear_mass_per_length_kgpm, spar_separation_elem_m, element_lengths_m, strict=True)
    ):
        torque_n_m = mpl * G_STANDARD * gravity_scale * arm * length
        nodal[e] -= 0.5 * torque_n_m
        nodal[e + 1] -= 0.5 * torque_n_m
    return nodal


def build_dual_beam_load_split(
    *,
    model: DualBeamMainlineModel,
    mode_definition: AnalysisModeDefinition,
) -> LoadSplitResult:
    """Build explicit main/rear nodal loads with mode-owned self-weight and torque handling."""

    if mode_definition.mode == AnalysisModeName.EQUIVALENT_VALIDATION:
        raise ValueError("equivalent_validation is owned by the equivalent-beam solver path.")

    nn = model.y_nodes_m.size
    main_loads = np.zeros((nn, 6), dtype=float)
    rear_loads = np.zeros((nn, 6), dtype=float)

    lift_main_fz_n = np.zeros(nn, dtype=float)
    lift_rear_fz_n = np.zeros(nn, dtype=float)
    torque_main_fz_n = np.zeros(nn, dtype=float)
    torque_rear_fz_n = np.zeros(nn, dtype=float)
    torque_main_my_n = np.zeros(nn, dtype=float)
    torque_rear_my_n = np.zeros(nn, dtype=float)
    main_self_weight_fz_n = np.zeros(nn, dtype=float)
    rear_self_weight_fz_n = np.zeros(nn, dtype=float)
    rear_gravity_torque_my_n = np.zeros(nn, dtype=float)

    if mode_definition.ownership.lift != "disabled":
        lift_main_fz_n = model.lift_per_span_npm * model.node_spacings_m

    torque_about_main_per_span_nmpm = convert_torque_to_main_spar_reference(
        lift_per_span_npm=model.lift_per_span_npm,
        torque_per_span_nmpm=model.torque_per_span_nmpm,
        main_spar_x_nodes_m=model.nodes_main_m[:, 0],
        torque_input=model.torque_input,
    )

    if mode_definition.ownership.aerodynamic_torque == "main_rear_vertical_couple_about_main_spar":
        for i, (moment_per_span, spacing, separation) in enumerate(
            zip(
                torque_about_main_per_span_nmpm,
                model.node_spacings_m,
                model.spar_separation_nodes_m,
                strict=True,
            )
        ):
            if abs(moment_per_span) <= 1.0e-14:
                continue
            if abs(separation) <= 1.0e-12:
                raise ValueError("Main/rear spar separation must stay non-zero for torque splitting.")
            moment_n_m = moment_per_span * spacing
            couple_force_n = moment_n_m / separation
            torque_main_fz_n[i] += couple_force_n
            torque_rear_fz_n[i] -= couple_force_n
    elif mode_definition.ownership.aerodynamic_torque == "main_beam_my_about_main_spar":
        torque_main_my_n = torque_about_main_per_span_nmpm * model.node_spacings_m
    else:
        raise ValueError(
            f"Unsupported aerodynamic torque ownership: {mode_definition.ownership.aerodynamic_torque}."
        )

    if mode_definition.ownership.main_spar_self_weight != "disabled":
        main_self_weight_fz_n = _beam_line_self_weight_nodal(
            model.main_mass_per_length_kgpm,
            model.element_lengths_m,
            model.gravity_scale,
            nn,
        )
    if mode_definition.ownership.rear_spar_self_weight != "disabled":
        rear_self_weight_fz_n = _beam_line_self_weight_nodal(
            model.rear_mass_per_length_kgpm,
            model.element_lengths_m,
            model.gravity_scale,
            nn,
        )

    main_loads[:, 2] = lift_main_fz_n + torque_main_fz_n + main_self_weight_fz_n
    rear_loads[:, 2] = lift_rear_fz_n + torque_rear_fz_n + rear_self_weight_fz_n
    main_loads[:, 4] = torque_main_my_n
    rear_loads[:, 4] = torque_rear_my_n + rear_gravity_torque_my_n
    total_applied_fz_n = float(np.sum(main_loads[:, 2]) + np.sum(rear_loads[:, 2]))

    return LoadSplitResult(
        mode_definition=mode_definition,
        main_loads_n=main_loads,
        rear_loads_n=rear_loads,
        lift_main_fz_n=lift_main_fz_n,
        lift_rear_fz_n=lift_rear_fz_n,
        torque_main_fz_n=torque_main_fz_n,
        torque_rear_fz_n=torque_rear_fz_n,
        torque_main_my_n=torque_main_my_n,
        torque_rear_my_n=torque_rear_my_n,
        main_self_weight_fz_n=main_self_weight_fz_n,
        rear_self_weight_fz_n=rear_self_weight_fz_n,
        rear_gravity_torque_my_n=rear_gravity_torque_my_n,
        torque_about_main_per_span_nmpm=torque_about_main_per_span_nmpm,
        total_applied_fz_n=total_applied_fz_n,
    )
