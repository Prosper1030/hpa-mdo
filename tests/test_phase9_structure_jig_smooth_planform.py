from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "phase9_structure_jig_smooth_planform.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "phase9_structure_jig_smooth_planform",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_smooth_power_law_chords_preserve_area_endpoints_and_monotonicity() -> None:
    module = _load_script_module()
    sections = (
        module.SectionRow(index=0, eta=0.0, y_m=0.0, z_m=0.0, chord_m=1.25, twist_deg=2.0, airfoil_id="root", airfoil_dat_path="/tmp/root.dat"),
        module.SectionRow(index=1, eta=0.35, y_m=3.5, z_m=0.1, chord_m=1.0, twist_deg=1.0, airfoil_id="root", airfoil_dat_path="/tmp/root.dat"),
        module.SectionRow(index=2, eta=0.70, y_m=7.0, z_m=0.4, chord_m=1.0, twist_deg=0.5, airfoil_id="tip", airfoil_dat_path="/tmp/tip.dat"),
        module.SectionRow(index=3, eta=1.0, y_m=10.0, z_m=0.8, chord_m=0.55, twist_deg=0.0, airfoil_id="tip", airfoil_dat_path="/tmp/tip.dat"),
    )
    target_area = module.area_from_sections(sections)

    smoothed, fit = module.smooth_power_law_sections(sections, target_area_m2=target_area)

    chords = [row.chord_m for row in smoothed]
    assert chords[0] == pytest.approx(sections[0].chord_m)
    assert chords[-1] == pytest.approx(sections[-1].chord_m)
    assert all(right <= left for left, right in zip(chords[:-1], chords[1:]))
    assert module.area_from_sections(smoothed) == pytest.approx(target_area, rel=5e-3)
    assert fit["fit_method"] == "smooth_area_matching_power_law"


def test_geometry_quality_penalizes_plateau_and_slope_breaks() -> None:
    module = _load_script_module()
    faceted = (
        module.SectionRow(index=0, eta=0.0, y_m=0.0, z_m=0.0, chord_m=1.25, twist_deg=0.0, airfoil_id="a", airfoil_dat_path="/tmp/a.dat"),
        module.SectionRow(index=1, eta=0.35, y_m=3.5, z_m=0.1, chord_m=1.0, twist_deg=0.0, airfoil_id="a", airfoil_dat_path="/tmp/a.dat"),
        module.SectionRow(index=2, eta=0.70, y_m=7.0, z_m=0.4, chord_m=1.0, twist_deg=0.0, airfoil_id="b", airfoil_dat_path="/tmp/b.dat"),
        module.SectionRow(index=3, eta=1.0, y_m=10.0, z_m=0.8, chord_m=0.55, twist_deg=0.0, airfoil_id="b", airfoil_dat_path="/tmp/b.dat"),
    )
    smooth, _ = module.smooth_power_law_sections(faceted, target_area_m2=module.area_from_sections(faceted))

    faceted_quality = module.geometry_quality_metrics(
        case_id="demo",
        variant="monotone",
        sections=faceted,
        reference_sections=faceted,
    )
    smooth_quality = module.geometry_quality_metrics(
        case_id="demo",
        variant="smooth_monotone",
        sections=smooth,
        reference_sections=faceted,
    )

    assert faceted_quality["near_constant_chord_segment_count"] >= 1
    assert smooth_quality["visual_production_score"] > faceted_quality["visual_production_score"]
    assert smooth_quality["max_slope_change_abs"] < faceted_quality["max_slope_change_abs"]


def test_carbon_tube_catalog_selects_lightest_candidate_meeting_required_ei(tmp_path: Path) -> None:
    module = _load_script_module()
    catalog = tmp_path / "tubes.csv"
    with catalog.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "vendor",
                "product",
                "material_key",
                "outer_diameter_mm",
                "inner_diameter_mm",
                "wall_thickness_mm",
                "mass_per_meter_kg",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "vendor": "demo",
                "product": "small",
                "material_key": "carbon_fiber_hm",
                "outer_diameter_mm": "40",
                "inner_diameter_mm": "38",
                "wall_thickness_mm": "1",
                "mass_per_meter_kg": "0.2",
            }
        )
        writer.writerow(
            {
                "vendor": "demo",
                "product": "large",
                "material_key": "carbon_fiber_hm",
                "outer_diameter_mm": "80",
                "inner_diameter_mm": "76",
                "wall_thickness_mm": "2",
                "mass_per_meter_kg": "0.25",
            }
        )

    rows = module.carbon_tube_candidates(
        catalog_path=catalog,
        half_span_m=10.0,
        required_ei_nm2=150_000.0,
        youngs_pa=120.0e9,
        tube_count_per_wing=2,
        vertical_separation_m=0.10,
        current_spar_tube_mass_target_kg=11.75,
    )

    passing = [row for row in rows if row["ei_pass"]]
    assert passing
    assert passing[0]["product"] == "large"
    assert passing[0]["estimated_full_span_tube_mass_kg"] < 11.75
