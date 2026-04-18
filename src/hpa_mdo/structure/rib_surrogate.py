"""Candidate-level rib bay surrogate metrics for reportable robustness checks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hpa_mdo.structure.inverse_design import StructuralNodeShape
from hpa_mdo.structure.rib_properties import (
    build_default_rib_catalog,
    derive_warping_knockdown,
)


@dataclass(frozen=True)
class RibBayMetric:
    bay_index: int
    y_start_m: float
    y_end_m: float
    y_center_m: float
    bay_length_m: float
    local_chord_m: float
    bay_length_over_chord: float
    main_delta_z_m: float
    rear_delta_z_m: float
    local_delta_over_chord: float
    shape_retention_risk: float


@dataclass(frozen=True)
class RibBaySurrogateSummary:
    enabled: bool
    source_shape: str
    family_key: str | None
    family_label: str | None
    spacing_m: float | None
    effective_warping_knockdown: float | None
    bay_count: int
    max_bay_length_m: float
    max_bay_length_over_chord: float
    max_local_delta_over_chord: float
    mean_shape_retention_risk: float
    max_shape_retention_risk: float
    dominant_bay_index: int | None
    bays: tuple[RibBayMetric, ...] = ()
    notes: tuple[str, ...] = ()


def _shape_component_at_y(nodes_m: np.ndarray, y_query_m: float, component_idx: int) -> float:
    nodes_arr = np.asarray(nodes_m, dtype=float)
    return float(
        np.interp(
            float(y_query_m),
            np.asarray(nodes_arr[:, 1], dtype=float),
            np.asarray(nodes_arr[:, component_idx], dtype=float),
        )
    )


def _build_bay_edges(*, half_span_m: float, spacing_m: float) -> np.ndarray:
    if half_span_m <= 0.0:
        raise ValueError("Half span must be positive to build rib bay edges.")
    if spacing_m <= 0.0:
        raise ValueError("Rib spacing must be positive to build rib bay edges.")

    edges = [0.0]
    while edges[-1] < half_span_m - 1.0e-12:
        edges.append(min(half_span_m, edges[-1] + spacing_m))
    return np.asarray(edges, dtype=float)


def build_rib_bay_surrogate_summary(
    *,
    cfg,
    aircraft,
    loaded_shape: StructuralNodeShape,
    source_shape: str = "predicted_loaded_shape",
) -> RibBaySurrogateSummary:
    """Return nominal rib-bay metrics derived from the current rib contract.

    The current Track M surrogate is intentionally simple:
    - bay edges come from the resolved rib spacing contract,
    - local ``Δ/c`` uses the larger of main- or rear-spar ``Δz`` across a bay,
    - shape-retention risk scales that ``Δ/c`` by bay length and effective
      warping knockdown so longer, twistier bays rank higher.
    """

    wing = aircraft.wing
    y_nodes_m = np.asarray(wing.y, dtype=float).reshape(-1)
    chord_m = np.asarray(wing.chord, dtype=float).reshape(-1)
    if y_nodes_m.size < 2 or chord_m.size != y_nodes_m.size:
        raise ValueError("Wing geometry must provide matching spanwise y/chord arrays.")
    if np.any(np.diff(y_nodes_m) <= 0.0):
        raise ValueError("Wing spanwise stations must be strictly increasing.")

    rib_cfg = getattr(cfg, "rib", None)
    if rib_cfg is None or not bool(getattr(rib_cfg, "enabled", True)):
        return RibBaySurrogateSummary(
            enabled=False,
            source_shape=str(source_shape),
            family_key=None,
            family_label=None,
            spacing_m=None,
            effective_warping_knockdown=None,
            bay_count=0,
            max_bay_length_m=0.0,
            max_bay_length_over_chord=0.0,
            max_local_delta_over_chord=0.0,
            mean_shape_retention_risk=0.0,
            max_shape_retention_risk=0.0,
            dominant_bay_index=None,
            notes=("rib contract disabled; surrogate not evaluated",),
        )

    catalog = build_default_rib_catalog(getattr(rib_cfg, "catalog_path", None))
    family_key = str(getattr(rib_cfg, "family", None) or catalog.default_family)
    family = catalog.family(family_key)
    spacing_m = float(
        getattr(rib_cfg, "spacing_m", None) or family.spacing_guidance.nominal_m
    )
    effective_warping_knockdown = getattr(
        getattr(cfg, "safety", None),
        "dual_spar_warping_knockdown",
        None,
    )
    notes = [
        "local_delta_over_chord uses the larger main/rear spar delta-z across each nominal bay",
    ]
    if effective_warping_knockdown is None:
        effective_warping_knockdown = derive_warping_knockdown(
            family_key,
            spacing_m,
            catalog=catalog,
        )
        notes.append(
            "effective_warping_knockdown was derived from the rib catalog because cfg.safety was unset"
        )
    effective_warping_knockdown = float(effective_warping_knockdown)

    bay_edges_m = _build_bay_edges(half_span_m=float(y_nodes_m[-1]), spacing_m=spacing_m)
    bays: list[RibBayMetric] = []
    risk_scale = max(effective_warping_knockdown, 1.0e-9)
    for bay_index, (y_start_m, y_end_m) in enumerate(
        zip(bay_edges_m[:-1], bay_edges_m[1:], strict=True),
        start=1,
    ):
        y_center_m = 0.5 * (float(y_start_m) + float(y_end_m))
        local_chord_m = float(np.interp(y_center_m, y_nodes_m, chord_m))
        if local_chord_m <= 0.0:
            raise ValueError("Wing chord must stay positive for rib surrogate metrics.")

        main_delta_z_m = abs(
            _shape_component_at_y(loaded_shape.main_nodes_m, float(y_end_m), 2)
            - _shape_component_at_y(loaded_shape.main_nodes_m, float(y_start_m), 2)
        )
        rear_delta_z_m = abs(
            _shape_component_at_y(loaded_shape.rear_nodes_m, float(y_end_m), 2)
            - _shape_component_at_y(loaded_shape.rear_nodes_m, float(y_start_m), 2)
        )
        bay_length_m = float(y_end_m - y_start_m)
        bay_length_over_chord = bay_length_m / local_chord_m
        local_delta_over_chord = max(main_delta_z_m, rear_delta_z_m) / local_chord_m
        shape_retention_risk = bay_length_over_chord * local_delta_over_chord / risk_scale

        bays.append(
            RibBayMetric(
                bay_index=int(bay_index),
                y_start_m=float(y_start_m),
                y_end_m=float(y_end_m),
                y_center_m=float(y_center_m),
                bay_length_m=float(bay_length_m),
                local_chord_m=float(local_chord_m),
                bay_length_over_chord=float(bay_length_over_chord),
                main_delta_z_m=float(main_delta_z_m),
                rear_delta_z_m=float(rear_delta_z_m),
                local_delta_over_chord=float(local_delta_over_chord),
                shape_retention_risk=float(shape_retention_risk),
            )
        )

    dominant_bay = max(bays, key=lambda bay: bay.shape_retention_risk) if bays else None
    return RibBaySurrogateSummary(
        enabled=True,
        source_shape=str(source_shape),
        family_key=family.key,
        family_label=family.label,
        spacing_m=float(spacing_m),
        effective_warping_knockdown=float(effective_warping_knockdown),
        bay_count=len(bays),
        max_bay_length_m=max((bay.bay_length_m for bay in bays), default=0.0),
        max_bay_length_over_chord=max((bay.bay_length_over_chord for bay in bays), default=0.0),
        max_local_delta_over_chord=max((bay.local_delta_over_chord for bay in bays), default=0.0),
        mean_shape_retention_risk=float(
            np.mean([bay.shape_retention_risk for bay in bays]) if bays else 0.0
        ),
        max_shape_retention_risk=max((bay.shape_retention_risk for bay in bays), default=0.0),
        dominant_bay_index=None if dominant_bay is None else int(dominant_bay.bay_index),
        bays=tuple(bays),
        notes=tuple(notes),
    )


__all__ = [
    "RibBayMetric",
    "RibBaySurrogateSummary",
    "build_rib_bay_surrogate_summary",
]
