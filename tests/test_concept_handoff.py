from __future__ import annotations

import json

from hpa_mdo.concept.handoff import write_selected_concept_bundle
from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts


def test_rank_concepts_prefers_feasible_safer_candidate():
    ranked = rank_concepts(
        [
            CandidateConceptResult("A", True, True, True, 0.20, 41000.0, 1.0),
            CandidateConceptResult("B", True, True, True, 0.35, 42000.0, 0.5),
        ]
    )

    assert ranked[0].concept_id == "B"
    assert ranked[0].why_not_higher == ()


def test_write_selected_concept_bundle_writes_expected_artifacts(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={"name": "concept-01"},
        stations_rows=[{"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0}],
        airfoil_templates={"root": {"upper": [0.2], "lower": [-0.1]}},
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1},
    )

    assert (bundle_dir / "concept_config.yaml").exists()
    assert (bundle_dir / "stations.csv").exists()
    assert (bundle_dir / "airfoil_templates.json").exists()
    assert (bundle_dir / "lofting_guides.json").exists()
    assert (bundle_dir / "prop_assumption.json").exists()
    assert json.loads((bundle_dir / "concept_summary.json").read_text(encoding="utf-8"))["rank"] == 1
