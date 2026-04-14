"""Discrete symmetric layup catalog helpers and post-processing utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Sequence

from hpa_mdo.core.config import SparConfig
from hpa_mdo.core.layup_constraints import (
    effective_layup_thickness_step_limit as effective_layup_thickness_step_limit,
    thickness_step_margin_min as thickness_step_margin_min,
)
from hpa_mdo.core.materials import PlyMaterial
from hpa_mdo.structure.laminate import (
    PlyFailureResult,
    PlyStack,
    TubeEquivalentProperties,
    evaluate_laminate_tsai_wu,
    tube_equivalent_from_layup,
)


LOGGER = logging.getLogger(__name__)
_FLOAT_TOL = 1.0e-12


@dataclass(frozen=True)
class SegmentTsaiWuSummary:
    """Worst-ply Tsai-Wu summary for a segment load envelope."""

    max_failure_index: float
    min_strength_ratio: float
    critical_ply_index: int
    critical_ply_angle_deg: float
    critical_z_mid_m: float
    critical_stress_12_pa: tuple[float, float, float]
    critical_midplane_strain: tuple[float, float, float] | None = None
    critical_curvature: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class SegmentStrainEnvelope:
    """Kinematic strain envelope used for laminate recovery in one spar segment."""

    epsilon_x_absmax: float
    kappa_absmax_1pm: float
    torsion_rate_absmax_1pm: float
    surface_epsilon_x_absmax: float
    gamma_xy_absmax: float


@dataclass(frozen=True)
class SegmentLayupResult:
    """Discrete layup selection for one spanwise segment."""

    segment_index: int
    y_start_m: float
    y_end_m: float
    target_thickness_m: float
    outer_radius_m: float
    stack: PlyStack
    equivalent_properties: TubeEquivalentProperties
    continuous_mass_full_wing_kg: float
    discrete_mass_full_wing_kg: float
    catalog_capped: bool
    strain_envelope: SegmentStrainEnvelope | None = None
    tsai_wu_summary: SegmentTsaiWuSummary | None = None

    @property
    def mass_penalty_full_wing_kg(self) -> float:
        return self.discrete_mass_full_wing_kg - self.continuous_mass_full_wing_kg

    @property
    def stack_notation(self) -> str:
        return format_stack_notation(self.stack)


def _stack_sort_key(stack: PlyStack) -> tuple[int, int, int, int]:
    return (stack.total_plies(), stack.n_90, stack.n_45, stack.n_0)


def format_stack_notation(stack: PlyStack) -> str:
    tokens: list[str] = []
    for angle in stack.angle_sequence_half():
        if angle > 0.0:
            tokens.append(f"+{int(angle)}")
        elif angle < 0.0:
            tokens.append(f"{int(angle)}")
        else:
            tokens.append("0")
    return "[" + "/".join(tokens) + "]_s"


def enumerate_valid_stacks(config: SparConfig) -> list[PlyStack]:
    """Enumerate structurally valid symmetric ply stacks from config limits."""
    max_half_plies = max(int(config.max_total_plies) // 2, 1)
    stacks: list[PlyStack] = []
    for n_0 in range(int(config.min_plies_0), max_half_plies + 1):
        for n_45 in range(int(config.min_plies_45_pairs), max_half_plies + 1):
            for n_90 in range(int(config.min_plies_90), max_half_plies + 1):
                stack = PlyStack(n_0=n_0, n_45=n_45, n_90=n_90)
                if stack.total_plies() > int(config.max_total_plies):
                    continue
                if stack.validate():
                    continue
                stacks.append(stack)
    return sorted(stacks, key=_stack_sort_key)


def snap_to_nearest_stack(
    target_thickness: float,
    stacks: Sequence[PlyStack],
    ply_mat: PlyMaterial,
) -> PlyStack:
    """Snap up to the thinnest stack whose wall thickness meets the target."""
    if not stacks:
        raise ValueError("stacks must not be empty.")

    for stack in stacks:
        if stack.wall_thickness(ply_mat.t_ply) >= float(target_thickness) - _FLOAT_TOL:
            return stack

    thickest = max(stacks, key=lambda item: item.wall_thickness(ply_mat.t_ply))
    LOGGER.warning(
        "Target wall thickness %.6f m exceeds catalog max %.6f m; returning the thickest stack.",
        float(target_thickness),
        thickest.wall_thickness(ply_mat.t_ply),
    )
    return thickest


def discretize_layup_per_segment(
    continuous_thicknesses: Sequence[float],
    R_outer_per_seg: Sequence[float],
    stacks: Sequence[PlyStack],
    ply_mat: PlyMaterial,
    ply_drop_limit: int = 2,
) -> list[PlyStack]:
    """Snap each segment thickness to a discrete stack with ply-drop control."""
    if len(continuous_thicknesses) != len(R_outer_per_seg):
        raise ValueError("continuous_thicknesses and R_outer_per_seg must have the same length.")
    if ply_drop_limit < 0:
        raise ValueError("ply_drop_limit must be non-negative.")

    ordered = sorted(
        stacks, key=lambda stack: (stack.wall_thickness(ply_mat.t_ply), _stack_sort_key(stack))
    )
    selected: list[PlyStack] = []

    for idx, target in enumerate(continuous_thicknesses):
        stack = snap_to_nearest_stack(float(target), ordered, ply_mat)
        if idx > 0:
            min_total_plies = max(selected[-1].total_plies() - int(ply_drop_limit), 0)
            if stack.total_plies() < min_total_plies:
                eligible = [
                    candidate
                    for candidate in ordered
                    if candidate.total_plies() >= min_total_plies
                    and candidate.wall_thickness(ply_mat.t_ply) >= float(target) - _FLOAT_TOL
                ]
                if eligible:
                    stack = eligible[0]
                else:
                    stack = ordered[-1]
                    LOGGER.warning(
                        "Segment %d requires at least %d plies to satisfy ply-drop control; "
                        "using the thickest available stack.",
                        idx + 1,
                        min_total_plies,
                    )
        selected.append(stack)

    return selected


def summarize_segment_tsai_wu(
    *,
    stack: PlyStack,
    ply_mat: PlyMaterial,
    midplane_strain: Sequence[float],
    curvature: Sequence[float] = (0.0, 0.0, 0.0),
) -> SegmentTsaiWuSummary:
    """Summarize the critical ply under a CLT strain/curvature state."""
    ply_results = evaluate_laminate_tsai_wu(
        ply_angles_deg=stack.angle_sequence_half(),
        t_ply=ply_mat.t_ply,
        ply_mat=ply_mat,
        midplane_strain=midplane_strain,
        curvature=curvature,
    )
    max_failure = max(ply_results, key=lambda result: float(result.failure_index))
    critical = min(ply_results, key=_strength_ratio_sort_key)
    return SegmentTsaiWuSummary(
        max_failure_index=float(max_failure.failure_index),
        min_strength_ratio=float(critical.strength_ratio),
        critical_ply_index=int(critical.ply_index),
        critical_ply_angle_deg=float(critical.theta_deg),
        critical_z_mid_m=float(critical.z_mid),
        critical_stress_12_pa=critical.stress_12,
        critical_midplane_strain=tuple(float(value) for value in midplane_strain),
        critical_curvature=tuple(float(value) for value in curvature),
    )


def _strength_ratio_sort_key(result: PlyFailureResult) -> tuple[int, float]:
    strength_ratio = float(result.strength_ratio)
    return (0 if strength_ratio == strength_ratio else 1, strength_ratio)


def summarize_segment_tsai_wu_envelope(
    *,
    stack: PlyStack,
    ply_mat: PlyMaterial,
    epsilon_x_absmax: float,
    kappa_absmax: float,
    torsion_rate_absmax: float,
    outer_radius_m: float,
) -> tuple[SegmentTsaiWuSummary, SegmentStrainEnvelope]:
    """Evaluate conservative CLT/Tsai-Wu margins from a beam strain envelope.

    Beam bending curvature is recovered as the critical tube-wall axial strain
    ``epsilon_x +/- R * kappa``.  That cross-section bending effect is not the
    same as laminate through-thickness CLT curvature, so each candidate wall
    state is evaluated with zero CLT curvature and signed axial/shear strain.
    """
    radius = abs(float(outer_radius_m))
    eps_abs = abs(float(epsilon_x_absmax))
    kappa_abs = abs(float(kappa_absmax))
    torsion_abs = abs(float(torsion_rate_absmax))
    surface_eps_abs = eps_abs + radius * kappa_abs
    gamma_abs = radius * torsion_abs
    strain_envelope = SegmentStrainEnvelope(
        epsilon_x_absmax=eps_abs,
        kappa_absmax_1pm=kappa_abs,
        torsion_rate_absmax_1pm=torsion_abs,
        surface_epsilon_x_absmax=surface_eps_abs,
        gamma_xy_absmax=gamma_abs,
    )

    candidate_summaries: list[SegmentTsaiWuSummary] = []
    for eps in _signed_envelope_values(surface_eps_abs):
        for gamma in _signed_envelope_values(gamma_abs):
            candidate_summaries.append(
                summarize_segment_tsai_wu(
                    stack=stack,
                    ply_mat=ply_mat,
                    midplane_strain=(eps, 0.0, gamma),
                    curvature=(0.0, 0.0, 0.0),
                )
            )

    critical = min(candidate_summaries, key=_summary_strength_ratio_sort_key)
    failure_values = [
        float(summary.max_failure_index)
        for summary in candidate_summaries
        if float(summary.max_failure_index) == float(summary.max_failure_index)
    ]
    max_failure = max(failure_values) if failure_values else float("nan")
    summary = SegmentTsaiWuSummary(
        max_failure_index=max_failure,
        min_strength_ratio=critical.min_strength_ratio,
        critical_ply_index=critical.critical_ply_index,
        critical_ply_angle_deg=critical.critical_ply_angle_deg,
        critical_z_mid_m=critical.critical_z_mid_m,
        critical_stress_12_pa=critical.critical_stress_12_pa,
        critical_midplane_strain=critical.critical_midplane_strain,
        critical_curvature=critical.critical_curvature,
    )
    return summary, strain_envelope


def _signed_envelope_values(abs_value: float) -> tuple[float, ...]:
    value = abs(float(abs_value))
    if value <= _FLOAT_TOL:
        return (0.0,)
    return (-value, value)


def _summary_strength_ratio_sort_key(summary: SegmentTsaiWuSummary) -> tuple[int, float, float]:
    strength_ratio = float(summary.min_strength_ratio)
    failure_index = float(summary.max_failure_index)
    return (
        0 if strength_ratio == strength_ratio else 1,
        strength_ratio,
        -failure_index if failure_index == failure_index else 0.0,
    )


def build_segment_layup_results(
    *,
    segment_lengths_m: Sequence[float],
    continuous_thicknesses_m: Sequence[float],
    outer_radii_m: Sequence[float],
    stacks: Sequence[PlyStack],
    ply_mat: PlyMaterial,
    ply_drop_limit: int = 2,
    midplane_strains: Sequence[Sequence[float]] | None = None,
    curvatures: Sequence[Sequence[float]] | None = None,
    strain_envelopes: Sequence[dict[str, float]] | None = None,
) -> list[SegmentLayupResult]:
    """Build per-segment layup selections with geometry and mass annotations."""
    if not (len(segment_lengths_m) == len(continuous_thicknesses_m) == len(outer_radii_m)):
        raise ValueError(
            "segment_lengths_m, continuous_thicknesses_m, and outer_radii_m must match in length."
        )
    if midplane_strains is not None and strain_envelopes is not None:
        raise ValueError("Provide either midplane_strains or strain_envelopes, not both.")
    if midplane_strains is not None and len(midplane_strains) != len(segment_lengths_m):
        raise ValueError("midplane_strains must match the segment count when provided.")
    if curvatures is not None and len(curvatures) != len(segment_lengths_m):
        raise ValueError("curvatures must match the segment count when provided.")
    if strain_envelopes is not None and len(strain_envelopes) != len(segment_lengths_m):
        raise ValueError("strain_envelopes must match the segment count when provided.")

    selected = discretize_layup_per_segment(
        continuous_thicknesses=continuous_thicknesses_m,
        R_outer_per_seg=outer_radii_m,
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=ply_drop_limit,
    )
    results: list[SegmentLayupResult] = []
    y_start = 0.0
    for idx, (length_m, target_t_m, outer_r_m, stack) in enumerate(
        zip(segment_lengths_m, continuous_thicknesses_m, outer_radii_m, selected, strict=True),
        start=1,
    ):
        y_end = y_start + float(length_m)
        equiv = tube_equivalent_from_layup(stack, ply_mat, R_outer=float(outer_r_m))
        continuous_mass = _segment_full_wing_mass(
            segment_length_m=float(length_m),
            outer_radius_m=float(outer_r_m),
            wall_thickness_m=float(target_t_m),
            density_kgpm3=ply_mat.density,
        )
        discrete_mass = _segment_full_wing_mass(
            segment_length_m=float(length_m),
            outer_radius_m=float(outer_r_m),
            wall_thickness_m=equiv.wall_thickness,
            density_kgpm3=ply_mat.density,
        )
        tsai_wu_summary = None
        strain_envelope = None
        if midplane_strains is not None:
            curvature = (0.0, 0.0, 0.0) if curvatures is None else curvatures[idx - 1]
            tsai_wu_summary = summarize_segment_tsai_wu(
                stack=stack,
                ply_mat=ply_mat,
                midplane_strain=midplane_strains[idx - 1],
                curvature=curvature,
            )
        elif strain_envelopes is not None:
            envelope = strain_envelopes[idx - 1]
            tsai_wu_summary, strain_envelope = summarize_segment_tsai_wu_envelope(
                stack=stack,
                ply_mat=ply_mat,
                epsilon_x_absmax=float(envelope["epsilon_x_absmax"]),
                kappa_absmax=float(
                    envelope.get("kappa_absmax", envelope.get("kappa_absmax_1pm", 0.0))
                ),
                torsion_rate_absmax=float(
                    envelope.get(
                        "torsion_rate_absmax",
                        envelope.get(
                            "torsion_rate_absmax_1pm",
                            envelope.get("tau_absmax", 0.0),
                        ),
                    )
                ),
                outer_radius_m=float(outer_r_m),
            )
        results.append(
            SegmentLayupResult(
                segment_index=idx,
                y_start_m=y_start,
                y_end_m=y_end,
                target_thickness_m=float(target_t_m),
                outer_radius_m=float(outer_r_m),
                stack=stack,
                equivalent_properties=equiv,
                continuous_mass_full_wing_kg=continuous_mass,
                discrete_mass_full_wing_kg=discrete_mass,
                catalog_capped=equiv.wall_thickness + _FLOAT_TOL < float(target_t_m),
                strain_envelope=strain_envelope,
                tsai_wu_summary=tsai_wu_summary,
            )
        )
        y_start = y_end

    return results


def format_layup_report(
    segments_stacks: Sequence[SegmentLayupResult],
    ply_mat: PlyMaterial,
) -> str:
    """Format a human-readable layup schedule report."""
    lines = [
        f"Ply material: {ply_mat.name}",
        f"Ply thickness: {ply_mat.t_ply * 1000.0:.3f} mm",
        "",
    ]
    for result in segments_stacks:
        note = " [catalog max reached]" if result.catalog_capped else ""
        lines.append(
            "Segment "
            f"{result.segment_index} (y={result.y_start_m:.1f}-{result.y_end_m:.1f}m): "
            f"{result.stack_notation}{note}"
        )
        lines.append(
            f"  {result.stack.total_plies()} plies, "
            f"h={result.equivalent_properties.wall_thickness * 1000.0:.3f} mm, "
            f"E_eff={result.equivalent_properties.E_axial / 1.0e9:.1f} GPa, "
            f"G_eff={result.equivalent_properties.G_shear / 1.0e9:.1f} GPa"
        )
        lines.append(
            f"  target={result.target_thickness_m * 1000.0:.3f} mm, "
            f"mass_penalty={result.mass_penalty_full_wing_kg:+.3f} kg/full wing"
        )
        if result.tsai_wu_summary is not None:
            summary = result.tsai_wu_summary
            if result.strain_envelope is not None:
                envelope = result.strain_envelope
                lines.append(
                    "  strain envelope "
                    f"eps={envelope.surface_epsilon_x_absmax:.3e}, "
                    f"kappa={envelope.kappa_absmax_1pm:.3e} 1/m, "
                    f"gamma={envelope.gamma_xy_absmax:.3e}"
                )
            lines.append(
                "  Tsai-Wu "
                f"FI={summary.max_failure_index:.3f}, "
                f"SR={_format_strength_ratio(summary.min_strength_ratio)}, "
                f"critical_ply={summary.critical_ply_index} "
                f"({summary.critical_ply_angle_deg:+.0f} deg)"
            )
    return "\n".join(lines) + "\n"


def summarize_layup_results(
    segments_stacks: Sequence[SegmentLayupResult],
) -> dict[str, object]:
    """Return a machine-readable summary for JSON export."""
    return {
        "segment_count": len(segments_stacks),
        "continuous_mass_full_wing_kg": sum(
            result.continuous_mass_full_wing_kg for result in segments_stacks
        ),
        "discrete_mass_full_wing_kg": sum(
            result.discrete_mass_full_wing_kg for result in segments_stacks
        ),
        "mass_penalty_full_wing_kg": sum(
            result.mass_penalty_full_wing_kg for result in segments_stacks
        ),
        "segments": [
            {
                "segment_index": result.segment_index,
                "y_start_m": result.y_start_m,
                "y_end_m": result.y_end_m,
                "target_thickness_m": result.target_thickness_m,
                "outer_radius_m": result.outer_radius_m,
                "stack": asdict(result.stack),
                "stack_notation": result.stack_notation,
                "equivalent_properties": asdict(result.equivalent_properties),
                "continuous_mass_full_wing_kg": result.continuous_mass_full_wing_kg,
                "discrete_mass_full_wing_kg": result.discrete_mass_full_wing_kg,
                "mass_penalty_full_wing_kg": result.mass_penalty_full_wing_kg,
                "catalog_capped": result.catalog_capped,
                "strain_envelope": (
                    None if result.strain_envelope is None else asdict(result.strain_envelope)
                ),
                "tsai_wu_summary": (
                    None if result.tsai_wu_summary is None else asdict(result.tsai_wu_summary)
                ),
            }
            for result in segments_stacks
        ],
    }


def _segment_full_wing_mass(
    *,
    segment_length_m: float,
    outer_radius_m: float,
    wall_thickness_m: float,
    density_kgpm3: float,
) -> float:
    inner_radius_m = max(float(outer_radius_m) - float(wall_thickness_m), 0.0)
    area_m2 = 3.141592653589793 * (float(outer_radius_m) ** 2 - inner_radius_m**2)
    return 2.0 * float(segment_length_m) * float(density_kgpm3) * area_m2


def _format_strength_ratio(value: float) -> str:
    if value == float("inf"):
        return "inf"
    return f"{float(value):.2f}"
