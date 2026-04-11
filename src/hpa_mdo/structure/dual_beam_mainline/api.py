"""Public API for the physics-first dual-beam mainline analysis kernel."""

from __future__ import annotations

from hpa_mdo.structure.dual_beam_mainline.builder import build_dual_beam_mainline_model
from hpa_mdo.structure.dual_beam_mainline.constraints import build_constraint_assembly
from hpa_mdo.structure.dual_beam_mainline.load_split import build_dual_beam_load_split
from hpa_mdo.structure.dual_beam_mainline.recovery import (
    build_report_metrics,
    recover_reactions,
    recover_structural_response,
)
from hpa_mdo.structure.dual_beam_mainline.smooth import (
    build_default_smooth_scales,
    build_smooth_aggregation,
)
from hpa_mdo.structure.dual_beam_mainline.solver import solve_dual_beam_state
from hpa_mdo.structure.dual_beam_mainline.types import (
    AnalysisModeName,
    DualBeamConstraintMode,
    DualBeamMainlineModel,
    DualBeamMainlineResult,
    LinkMode,
    RootBCMode,
    SmoothScaleConfig,
    WireBCMode,
    get_analysis_mode_definition,
)


def _resolve_constraint_mode(
    *,
    model: DualBeamMainlineModel,
    mode: AnalysisModeName | str,
    root_bc: RootBCMode | None,
    wire_bc: WireBCMode | None,
    link_mode: LinkMode | None,
) -> tuple:
    mode_definition = get_analysis_mode_definition(mode)
    if mode_definition.analysis_family != "dual_beam":
        raise ValueError(
            f"{mode_definition.mode.value} belongs to the equivalent-beam validation path, not the dual-beam kernel."
        )

    resolved_link_mode = link_mode or mode_definition.default_link_mode
    if resolved_link_mode is None:
        raise ValueError(f"{mode_definition.mode.value} requires an explicit link_mode.")
    if resolved_link_mode not in mode_definition.allowed_link_modes:
        raise ValueError(
            f"link_mode={resolved_link_mode.value} is not allowed for {mode_definition.mode.value}."
        )

    constraint_mode = DualBeamConstraintMode(
        root_bc=root_bc or mode_definition.root_bc,
        wire_bc=wire_bc if wire_bc is not None else mode_definition.wire_bc,
        link_mode=resolved_link_mode,
    )
    return mode_definition, constraint_mode


def run_dual_beam_mainline_kernel(
    *,
    model: DualBeamMainlineModel,
    mode: AnalysisModeName | str = AnalysisModeName.DUAL_BEAM_PRODUCTION,
    root_bc: RootBCMode | None = None,
    wire_bc: WireBCMode | None = None,
    link_mode: LinkMode | None = None,
    smooth_scales: SmoothScaleConfig | None = None,
) -> DualBeamMainlineResult:
    """Run the new dual-beam mainline analysis kernel for one prepared model."""

    mode_definition, constraint_mode = _resolve_constraint_mode(
        model=model,
        mode=mode,
        root_bc=root_bc,
        wire_bc=wire_bc,
        link_mode=link_mode,
    )

    load_split = build_dual_beam_load_split(model=model, mode_definition=mode_definition)
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    disp_main_m, disp_rear_m, multipliers, _ = solve_dual_beam_state(
        model=model,
        main_loads_n=load_split.main_loads_n,
        rear_loads_n=load_split.rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
    )
    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
    )
    smooth = build_smooth_aggregation(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
        scale_config=smooth_scales or build_default_smooth_scales(model),
    )
    report = build_report_metrics(
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
    )
    return DualBeamMainlineResult(
        mode_definition=mode_definition,
        constraint_mode=constraint_mode,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=reactions,
        recovery=recovery,
        smooth=smooth,
        report=report,
    )


def run_dual_beam_mainline_analysis(
    *,
    cfg,
    aircraft,
    opt_result,
    export_loads,
    materials_db,
    mode: AnalysisModeName | str = AnalysisModeName.DUAL_BEAM_PRODUCTION,
    root_bc: RootBCMode | None = None,
    wire_bc: WireBCMode | None = None,
    link_mode: LinkMode | None = None,
    smooth_scales: SmoothScaleConfig | None = None,
    torque_input=None,
) -> DualBeamMainlineResult:
    """Build and run the physics-first dual-beam mainline analysis kernel."""

    model = build_dual_beam_mainline_model(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        torque_input=torque_input,
    )
    return run_dual_beam_mainline_kernel(
        model=model,
        mode=mode,
        root_bc=root_bc,
        wire_bc=wire_bc,
        link_mode=link_mode,
        smooth_scales=smooth_scales,
    )
