from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.full_wire_rigging_system_phase9e import (  # noqa: E402
    VendorDesignPoint,
    build_full_aircraft_wire_rows,
    build_rigging_bom,
    summarize_design,
)


def _design() -> VendorDesignPoint:
    return VendorDesignPoint(
        role="balanced",
        layout="single",
        dihedral_multiplier=2.0,
        total_mass_kg=14.8,
        ld_ratio=40.2,
        dutch_roll_damping=5.9,
        min_jig_clearance_mm=1.5,
        wire_margin_n=3000.0,
        summary_json_path="test.json",
        source_name="test",
    )


def test_build_full_aircraft_wire_rows_mirrors_port_and_starboard() -> None:
    rows = build_full_aircraft_wire_rows(
        design=_design(),
        positive_half_records=(
            {
                "identifier": "wire-1",
                "attach_label": "wire-1",
                "attach_y_m": 7.5,
                "attach_point_loaded_m": [0.2, 7.5, 0.5],
                "anchor_point_m": [0.2, 0.0, -1.5],
                "L_flight_m": 7.8,
                "delta_L_m": 0.02,
                "L_cut_m": 7.78,
                "tension_force_n": 2000.0,
                "allowable_tension_n": 8000.0,
                "tension_margin_n": 6000.0,
            },
        ),
        cable_material="dyneema_sk75",
        cable_diameter_m=0.0025,
        cable_density_kgpm3=970.0,
    )

    assert len(rows) == 2
    assert {row.side for row in rows} == {"port", "starboard"}
    assert {round(row.attach_y_m, 3) for row in rows} == {-7.5, 7.5}
    assert rows[0].tension_utilization == rows[1].tension_utilization == 0.25


def test_build_rigging_bom_adds_cable_and_placeholder_hardware() -> None:
    bom = build_rigging_bom(
        design=_design(),
        positive_half_records=(
            {
                "identifier": "wire-1",
                "attach_label": "wire-1",
                "L_cut_m": 7.7,
            },
            {
                "identifier": "wire-2",
                "attach_label": "wire-2",
                "L_cut_m": 10.7,
            },
        ),
        cable_material="dyneema_sk75",
        cable_diameter_m=0.0025,
        cable_density_kgpm3=970.0,
    )

    assert len(bom) == 5
    assert sum(1 for row in bom if row.line_kind == "cable") == 2
    hardware_quantities = {row.item_code: row.quantity for row in bom if row.line_kind != "cable"}
    assert hardware_quantities["wing_fitting_placeholder"] == 4
    assert hardware_quantities["fuselage_anchor_placeholder"] == 4
    assert hardware_quantities["turnbuckle_placeholder"] == 4


def test_summarize_design_aggregates_full_aircraft_metrics() -> None:
    rows = build_full_aircraft_wire_rows(
        design=_design(),
        positive_half_records=(
            {
                "identifier": "wire-1",
                "attach_label": "wire-1",
                "attach_y_m": 7.5,
                "attach_point_loaded_m": [0.2, 7.5, 0.5],
                "anchor_point_m": [0.2, 0.0, -1.5],
                "L_flight_m": 7.8,
                "delta_L_m": 0.02,
                "L_cut_m": 7.78,
                "tension_force_n": 2000.0,
                "allowable_tension_n": 8000.0,
                "tension_margin_n": 6000.0,
            },
        ),
        cable_material="dyneema_sk75",
        cable_diameter_m=0.0025,
        cable_density_kgpm3=970.0,
    )

    summary = summarize_design(design=_design(), wire_rows=rows)

    assert summary["wire_count_full_aircraft"] == 2
    assert summary["cable_cut_length_total_m"] > 15.0
    assert summary["max_tension_n"] == 2000.0
    assert summary["max_utilization_pct"] == 25.0
