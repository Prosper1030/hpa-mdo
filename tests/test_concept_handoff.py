from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_concept_module(module_name: str, relative_path: str):
    package_name = "hpa_mdo.concept"
    if "hpa_mdo" not in sys.modules:
        hpa_pkg = types.ModuleType("hpa_mdo")
        hpa_pkg.__path__ = [str(_REPO_ROOT / "src" / "hpa_mdo")]
        sys.modules["hpa_mdo"] = hpa_pkg
    if package_name not in sys.modules:
        concept_pkg = types.ModuleType(package_name)
        concept_pkg.__path__ = [str(_REPO_ROOT / "src" / "hpa_mdo" / "concept")]
        sys.modules[package_name] = concept_pkg

    module_path = _REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_vsp_export = _load_concept_module(
    "hpa_mdo.concept.vsp_export", "src/hpa_mdo/concept/vsp_export.py"
)
_handoff = _load_concept_module("hpa_mdo.concept.handoff", "src/hpa_mdo/concept/handoff.py")
write_selected_concept_bundle = _handoff.write_selected_concept_bundle


def test_rank_concepts_prefers_feasible_safer_candidate():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="A",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.20,
                mission_objective_mode="max_range",
                mission_score=-41000.0,
                best_range_m=41000.0,
                assembly_penalty=1.0,
            ),
            CandidateConceptResult(
                concept_id="B",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.35,
                mission_objective_mode="max_range",
                mission_score=-42000.0,
                best_range_m=42000.0,
                assembly_penalty=0.5,
            ),
        ]
    )

    assert ranked[0].concept_id == "B"
    assert ranked[0].why_not_higher == ()


def test_rank_concepts_uses_deterministic_tie_break_on_concept_id():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="b-concept",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.20,
                mission_objective_mode="max_range",
                mission_score=-41000.0,
                best_range_m=41000.0,
                assembly_penalty=1.0,
            ),
            CandidateConceptResult(
                concept_id="a-concept",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.20,
                mission_objective_mode="max_range",
                mission_score=-41000.0,
                best_range_m=41000.0,
                assembly_penalty=1.0,
            ),
        ]
    )

    assert [item.concept_id for item in ranked] == ["a-concept", "b-concept"]


def test_rank_concepts_prefers_mission_passing_min_power_case():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="failing",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=False,
                safety_margin=0.30,
                mission_objective_mode="min_power",
                mission_score=170.0,
                best_range_m=39000.0,
                assembly_penalty=0.0,
            ),
            CandidateConceptResult(
                concept_id="passing",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.25,
                mission_objective_mode="min_power",
                mission_score=180.0,
                best_range_m=43000.0,
                assembly_penalty=0.0,
            ),
        ]
    )

    assert ranked[0].concept_id == "passing"
    assert "target_range_not_met" in ranked[1].why_not_higher


def test_rank_concepts_explains_pure_mission_runner_up():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="winner",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.20,
                mission_objective_mode="max_range",
                mission_score=-43000.0,
                best_range_m=43000.0,
                assembly_penalty=1.0,
            ),
            CandidateConceptResult(
                concept_id="runner-up",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                mission_feasible=True,
                safety_margin=0.20,
                mission_objective_mode="max_range",
                mission_score=-42000.0,
                best_range_m=42000.0,
                assembly_penalty=1.0,
            ),
        ]
    )

    assert ranked[0].concept_id == "winner"
    assert ranked[1].concept_id == "runner-up"
    assert "less_range_than_best" in ranked[1].why_not_higher


def test_rank_concepts_prefers_safety_feasible_candidate_over_infeasible_one():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="infeasible-best-range",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=False,
                mission_feasible=True,
                safety_margin=-0.05,
                mission_objective_mode="max_range",
                mission_score=-50000.0,
                best_range_m=50000.0,
                assembly_penalty=0.0,
            ),
            CandidateConceptResult(
                concept_id="safe-runner",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=True,
                mission_feasible=True,
                safety_margin=0.15,
                mission_objective_mode="max_range",
                mission_score=-42000.0,
                best_range_m=42000.0,
                assembly_penalty=0.5,
            ),
        ]
    )

    assert ranked[0].concept_id == "safe-runner"
    assert "local_stall_not_feasible" in ranked[1].why_not_higher


def test_rank_concepts_prioritizes_feasibility_margin_before_extra_range():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="longer-range-but-tight",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=True,
                mission_feasible=True,
                safety_margin=0.06,
                mission_margin_m=1500.0,
                mission_objective_mode="max_range",
                mission_score=-43500.0,
                best_range_m=43500.0,
                assembly_penalty=0.0,
            ),
            CandidateConceptResult(
                concept_id="safer-runner",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=True,
                mission_feasible=True,
                safety_margin=0.16,
                mission_margin_m=1800.0,
                mission_objective_mode="max_range",
                mission_score=-42500.0,
                best_range_m=42500.0,
                assembly_penalty=0.0,
            ),
        ]
    )

    assert ranked[0].concept_id == "safer-runner"
    assert "lower_feasibility_margin_than_best" in ranked[1].why_not_higher


def test_rank_concepts_requires_mission_feasibility_for_selected_status():
    ranked = rank_concepts(
        [
            CandidateConceptResult(
                concept_id="safety_only",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=True,
                mission_feasible=False,
                safety_margin=0.25,
                mission_margin_m=-1200.0,
                mission_objective_mode="max_range",
                mission_score=-45000.0,
                best_range_m=45000.0,
                assembly_penalty=0.0,
            ),
            CandidateConceptResult(
                concept_id="fully_feasible",
                launch_feasible=True,
                turn_feasible=True,
                trim_feasible=True,
                local_stall_feasible=True,
                mission_feasible=True,
                safety_margin=0.12,
                mission_margin_m=800.0,
                mission_objective_mode="max_range",
                mission_score=-42000.0,
                best_range_m=42000.0,
                assembly_penalty=0.0,
            ),
        ]
    )

    assert ranked[0].concept_id == "fully_feasible"
    assert ranked[0].selection_status == "selected"
    assert ranked[1].selection_status == "best_infeasible"
    assert "target_range_not_met" in ranked[1].why_not_higher


def test_write_selected_concept_bundle_writes_expected_artifacts(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={"name": "concept-01"},
        stations_rows=[{"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0}],
        airfoil_templates={"root": {"upper": [0.2], "lower": [-0.1]}},
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={
            "rank": 1,
            "mission": {
                "mission_objective_mode": "max_range",
                "mission_score": -42000.0,
                "mission_score_reason": "maximize_range",
            },
            "ranking": {
                "score": -41.5,
                "why_not_higher": [],
            },
        },
    )

    assert (bundle_dir / "concept_config.yaml").exists()
    assert (bundle_dir / "stations.csv").exists()
    assert (bundle_dir / "airfoil_templates.json").exists()
    assert (bundle_dir / "lofting_guides.json").exists()
    assert (bundle_dir / "prop_assumption.json").exists()
    concept_summary = json.loads((bundle_dir / "concept_summary.json").read_text(encoding="utf-8"))
    assert concept_summary["rank"] == 1
    assert concept_summary["mission"]["mission_objective_mode"] == "max_range"
    assert concept_summary["ranking"]["score"] == pytest.approx(-41.5)


def test_write_selected_concept_bundle_accepts_cst_template_payload(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={"name": "concept-01"},
        stations_rows=[{"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0}],
        airfoil_templates={
            "root": {
                "authority": "cst_candidate",
                "upper_coefficients": [0.22, 0.28, 0.18, 0.10, 0.04],
                "lower_coefficients": [-0.18, -0.14, -0.08, -0.03, -0.01],
                "candidate_role": "base",
            }
        },
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1},
    )

    payload = json.loads((bundle_dir / "airfoil_templates.json").read_text(encoding="utf-8"))
    assert payload["root"]["authority"] == "cst_candidate"


def test_write_selected_concept_bundle_writes_openvsp_handoff_artifacts(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={
            "name": "concept-01",
            "geometry": {
                "span_m": 32.0,
                "root_chord_m": 1.30,
                "tip_chord_m": 0.45,
            },
        },
        stations_rows=[
            {"y_m": 0.0, "chord_m": 1.30, "twist_deg": 2.0},
            {"y_m": 1.5, "chord_m": 1.22, "twist_deg": 1.5},
            {"y_m": 4.5, "chord_m": 1.05, "twist_deg": 0.5},
        ],
        airfoil_templates={
            "root": {"template_id": "root-seed", "point_count": 2},
            "tip": {"template_id": "tip-seed", "point_count": 2},
        },
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1, "selected": True},
    )

    script_path = bundle_dir / "concept_openvsp.vspscript"
    metadata_path = bundle_dir / "concept_openvsp_metadata.json"

    assert script_path.exists()
    assert metadata_path.exists()

    script = script_path.read_text(encoding="utf-8")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert "concept-01" in script
    assert 'AddGeom( "WING" )' in script
    assert 'SetGeomName( wing_id, "concept-01" );' in script
    assert 'SetParmVal( GetXSecParm( seg0_xs, "Root_Chord" ), 1.300000 );' in script
    assert 'SetParmVal( GetXSecParm( seg1_xs, "Tip_Chord" ), 1.050000 );' in script
    assert 'SetParmVal( GetXSecParm( GetXSec( xsec_surf, 0 ), "Twist" ), 2.000000 );' in script
    assert metadata["concept_id"] == "concept-01"
    assert metadata["station_count"] == 3
    assert metadata["script_path"] == "concept_openvsp.vspscript"
    assert metadata["stations"][1]["y_m"] == 1.5
    assert metadata["vsp3_build"]["target_path"].endswith("concept_openvsp.vsp3")
    assert metadata["vsp3_build"]["status"] in {
        "written",
        "openvsp_python_unavailable",
        "openvsp_api_failed",
    }


def test_write_selected_concept_bundle_writes_selected_airfoils_to_openvsp(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-custom-airfoil",
        concept_config={
            "name": "concept-custom-airfoil",
            "geometry": {
                "span_m": 32.0,
                "root_chord_m": 1.30,
                "tip_chord_m": 0.45,
            },
        },
        stations_rows=[
            {"y_m": 0.0, "chord_m": 1.30, "twist_deg": 2.0},
            {"y_m": 4.0, "chord_m": 1.05, "twist_deg": 0.5},
            {"y_m": 16.0, "chord_m": 0.45, "twist_deg": -2.0},
        ],
        airfoil_templates={
            "root": {
                "template_id": "root-custom-cst",
                "geometry_hash": "rootabc123456",
                "coordinates": [[1.0, 0.001], [0.5, 0.080], [0.0, 0.0], [0.5, -0.050], [1.0, -0.001]],
            },
            "tip": {
                "template_id": "tip-custom-cst",
                "geometry_hash": "tipabc123456",
                "coordinates": [[1.0, 0.001], [0.5, 0.055], [0.0, 0.0], [0.5, -0.040], [1.0, -0.001]],
            },
        },
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1, "selected": True},
    )

    script = (bundle_dir / "concept_openvsp.vspscript").read_text(encoding="utf-8")
    metadata = json.loads((bundle_dir / "concept_openvsp_metadata.json").read_text(encoding="utf-8"))
    root_dat = bundle_dir / "selected_airfoils" / "root-rootabc12345.dat"
    tip_dat = bundle_dir / "selected_airfoils" / "tip-tipabc123456.dat"

    assert root_dat.exists()
    assert tip_dat.exists()
    assert root_dat.read_text(encoding="utf-8").splitlines()[0] == "root-custom-cst"
    assert "XS_FILE_AIRFOIL" in script
    assert "ReadFileAirfoil" in script
    assert "root-rootabc12345.dat" in script
    assert "tip-tipabc123456.dat" in script
    assert metadata["openvsp_airfoil_files"]["root"].endswith("root-rootabc12345.dat")
    assert metadata["openvsp_airfoil_files"]["tip"].endswith("tip-tipabc123456.dat")


def test_write_selected_concept_bundle_writes_openvsp_vsp3_when_api_is_available(tmp_path):
    openvsp = pytest.importorskip("openvsp")

    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-vsp3",
        concept_config={
            "name": "concept-vsp3",
            "geometry": {
                "span_m": 35.0,
                "wing_area_m2": 31.5,
                "root_chord_m": 1.25,
                "tip_chord_m": 0.55,
                "mean_aerodynamic_chord_m": 0.92,
                "tail_area_m2": 3.2,
            },
            "tail_model": {
                "tail_arm_to_mac": 4.2,
                "tail_aspect_ratio": 5.0,
            },
        },
        stations_rows=[
            {"y_m": 0.0, "chord_m": 1.25, "twist_deg": 2.0, "dihedral_deg": 0.0},
            {"y_m": 6.0, "chord_m": 1.00, "twist_deg": 0.5, "dihedral_deg": 3.0},
            {"y_m": 17.5, "chord_m": 0.55, "twist_deg": -2.0, "dihedral_deg": 6.0},
        ],
        airfoil_templates={"root": {"template_id": "root-seed"}},
        lofting_guides={"authority": "concept_station_schedule"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1, "selected": True},
    )

    vsp3_path = bundle_dir / "concept_openvsp.vsp3"
    metadata = json.loads((bundle_dir / "concept_openvsp_metadata.json").read_text(encoding="utf-8"))

    assert vsp3_path.exists()
    assert metadata["vsp3_build"]["status"] == "written"
    assert metadata["vsp3_build"]["path"] == str(vsp3_path)
    assert metadata["auxiliary_geometry"]["horizontal_tail_proxy"]["area_m2"] == pytest.approx(3.2)

    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(vsp3_path))
    openvsp.Update()
    geoms = {
        openvsp.GetGeomName(geom_id): geom_id
        for geom_id in openvsp.FindGeoms()
    }
    assert "concept-vsp3" in geoms
    assert "HorizontalTail_proxy" in geoms


def test_write_selected_concept_bundle_rejects_station_schema_mismatch_before_writing(tmp_path):
    with pytest.raises(ValueError, match="stations_rows"):
        write_selected_concept_bundle(
            output_dir=tmp_path,
            concept_id="concept-01",
            concept_config={"name": "concept-01"},
            stations_rows=[
                {"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0},
                {"y_m": 1.0, "chord_m": 1.1},
            ],
            airfoil_templates={"root": {"upper": [0.2], "lower": [-0.1]}},
            lofting_guides={"authority": "cst_coefficients"},
            prop_assumption={"diameter_m": 3.0},
            concept_summary={"rank": 1},
        )

    assert not (tmp_path / "concept-01").exists()
