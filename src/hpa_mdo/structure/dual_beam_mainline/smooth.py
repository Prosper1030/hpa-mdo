"""Run-constant smooth diagnostics for the dual-beam mainline kernel."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import (
    DualBeamMainlineModel,
    ReactionRecoveryResult,
    SmoothAggregationResult,
    SmoothScaleConfig,
)


def smooth_abs(values: np.ndarray, eps: float) -> np.ndarray:
    """Smooth absolute value with engineering-scale epsilon."""

    arr = np.asarray(values, dtype=float)
    return np.sqrt(arr**2 + eps**2)


def ks_smooth_max(values: np.ndarray, rho: float) -> float:
    """Smooth maximum using a numerically stable KS/log-sum-exp form."""

    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        return 0.0
    shift = float(np.max(arr))
    return float(shift + (1.0 / rho) * np.log(np.sum(np.exp(rho * (arr - shift)))))


def build_default_smooth_scales(model: DualBeamMainlineModel) -> SmoothScaleConfig:
    """Return run-constant defaults that do not depend on the solved state."""

    u_scale_m = max(float(model.max_tip_deflection_limit_m or 0.0), 1.0e-3)
    return SmoothScaleConfig(
        u_scale_m=u_scale_m,
        lambda_scale_n=1.0,
    )


def build_smooth_aggregation(
    *,
    model: DualBeamMainlineModel,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    reactions: ReactionRecoveryResult,
    scale_config: SmoothScaleConfig,
) -> SmoothAggregationResult:
    """Build smooth displacement and link-force diagnostics with run-constant scales."""

    uz_main = smooth_abs(disp_main_m[:, 2], scale_config.eps_abs_u_m) / scale_config.u_scale_m
    uz_rear = smooth_abs(disp_rear_m[:, 2], scale_config.eps_abs_u_m) / scale_config.u_scale_m
    psi_u_all_m = scale_config.u_scale_m * ks_smooth_max(
        np.concatenate((uz_main, uz_rear)),
        scale_config.rho_u,
    )
    psi_u_rear_m = scale_config.u_scale_m * ks_smooth_max(uz_rear, scale_config.rho_u)

    if model.joint_node_indices:
        outboard_start = max(model.joint_node_indices) + 1
    else:
        outboard_start = 0
    uz_rear_outboard = uz_rear[outboard_start:] if outboard_start < uz_rear.size else uz_rear[-1:]
    psi_u_rear_outboard_m = scale_config.u_scale_m * ks_smooth_max(
        uz_rear_outboard,
        scale_config.rho_u,
    )

    if reactions.link_resultants_n.size:
        link_norms = np.sqrt(
            np.sum(reactions.link_resultants_n**2, axis=1) + scale_config.eps_norm_n**2
        ) / scale_config.lambda_scale_n
        psi_link_n = scale_config.lambda_scale_n * ks_smooth_max(link_norms, scale_config.rho_lambda)
    else:
        psi_link_n = 0.0

    return SmoothAggregationResult(
        u_scale_m=scale_config.u_scale_m,
        lambda_scale_n=scale_config.lambda_scale_n,
        psi_u_all_m=float(psi_u_all_m),
        psi_u_rear_m=float(psi_u_rear_m),
        psi_u_rear_outboard_m=float(psi_u_rear_outboard_m),
        psi_link_n=float(psi_link_n),
    )
