"""Backward-compat shim for the legacy oas_structural import path.

The structural OpenMDAO stack used to live in this single file. It has
been split across hpa_mdo.structure.{fem,components,groups} modules.
This module re-exports every public name so that existing imports
continue to work without modification.

New code should import directly from the package layout:

    from hpa_mdo.structure.fem import SpatialBeamFEM
    from hpa_mdo.structure.components import DualSparPropertiesComp
    from hpa_mdo.structure.groups import build_structural_problem
"""
from __future__ import annotations

# FEM primitives (kept module-private; re-exported for tests)
from hpa_mdo.structure.fem.elements import (
    _timoshenko_element_stiffness,
    _cs_norm,
    _has_only_finite_values,
    _rotation_matrix,
    _transform_12x12,
)
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM

# OpenMDAO components
from hpa_mdo.structure.components.spar_props import (
    SegmentToElementComp,
    DualSparPropertiesComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.components.constraints import (
    VonMisesStressComp,
    KSFailureComp,
    StructuralMassComp,
    TwistConstraintComp,
    TipDeflectionConstraintComp,
)

# Groups and entry points
from hpa_mdo.structure.groups.load_case import StructuralLoadCaseGroup
from hpa_mdo.structure.groups.main import (
    _is_single_mapped_load,
    _normalise_load_case_inputs,
    _elem_to_seg_mean,
    HPAStructuralGroup,
    compute_outer_radius_from_wing,
    build_structural_problem,
    run_analysis,
    run_optimization,
    _extract_results,
)

__all__ = [
    "SegmentToElementComp",
    "DualSparPropertiesComp",
    "SpatialBeamFEM",
    "VonMisesStressComp",
    "KSFailureComp",
    "StructuralMassComp",
    "ExternalLoadsComp",
    "TwistConstraintComp",
    "TipDeflectionConstraintComp",
    "StructuralLoadCaseGroup",
    "HPAStructuralGroup",
    "build_structural_problem",
    "run_analysis",
    "run_optimization",
    "compute_outer_radius_from_wing",
    "_timoshenko_element_stiffness",
    "_cs_norm",
    "_has_only_finite_values",
    "_rotation_matrix",
    "_transform_12x12",
    "_is_single_mapped_load",
    "_normalise_load_case_inputs",
    "_elem_to_seg_mean",
    "_extract_results",
]
