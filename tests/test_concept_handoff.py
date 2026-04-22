from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

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


from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts


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
