import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.structure_budgeted_z_state_search import (  # noqa: E402
    DEFAULT_CANONICAL_NON_TUBE_STRUCTURAL_ALLOWANCE_KG,
    ZStateRequest,
    _command_for_case,
    canonical_total_structural_mass_target,
    effective_dihedral_deg,
    shortlist_status,
    target_main_tip_z_for_effective_dihedral,
    unique_z_state_requests,
)


def test_effective_dihedral_targets_convert_to_main_tip_z() -> None:
    semi_span_m = 17.166143

    target_z = target_main_tip_z_for_effective_dihedral(6.0, semi_span_m)

    assert target_z == math.tan(math.radians(6.0)) * semi_span_m
    assert effective_dihedral_deg(target_z, semi_span_m) == 6.0


def test_unique_z_state_requests_preserve_source_labels_and_deduplicate() -> None:
    requests = unique_z_state_requests(
        semi_span_m=17.166143,
        effective_dihedral_deg_values=[5.0],
        target_main_tip_z_m_values=[1.5018429089648957, 2.675],
        include_old_x4_equivalent=True,
    )

    assert [round(request.target_main_tip_z_m, 6) for request in requests] == [
        1.501843,
        2.675,
        4.25,
    ]
    assert requests[0].source == "effective_dihedral_deg"
    assert requests[1].source == "target_main_tip_z_m"
    assert requests[2].source == "old_x4_equivalent"


def test_shortlist_status_requires_mass_and_clearance() -> None:
    request = ZStateRequest(
        label="target_main_tip_z_2p700m",
        target_main_tip_z_m=2.7,
        source="target_main_tip_z_m",
        requested_effective_dihedral_deg=None,
    )

    status = shortlist_status(
        request=request,
        actual_target_main_tip_z_m=2.7,
        semi_span_m=17.166143,
        tube_mass_kg=11.49,
        total_structural_mass_kg=13.99,
        jig_ground_clearance_min_m=0.025,
        loaded_shape_error_m=0.0,
        spar_tube_mass_target_kg=11.5,
        healthy_clearance_m=0.020,
    )

    assert status["meets_tube_mass_target"] is True
    assert status["healthy_clearance"] is True
    assert status["recommended_for_avl_recheck"] is True
    assert status["effective_dihedral_deg"] == effective_dihedral_deg(2.7, 17.166143)


def test_canonical_total_structural_mass_target_keeps_tube_budget_basis_explicit() -> None:
    target = canonical_total_structural_mass_target(
        spar_tube_mass_target_kg=11.5,
        non_tube_structural_allowance_kg=DEFAULT_CANONICAL_NON_TUBE_STRUCTURAL_ALLOWANCE_KG,
    )

    assert target == 14.0


def test_command_for_case_passes_canonical_total_mass_cap_when_available(tmp_path: Path) -> None:
    command = _command_for_case(
        config_path=tmp_path / "config.yaml",
        design_report=tmp_path / "crossval_report.txt",
        case_dir=tmp_path / "case",
        candidate_avl_artifact=tmp_path / "candidate.json",
        target_shape_z_scale=1.25,
        dihedral_exponent=1.0,
        refresh_steps=0,
        skip_local_refine=True,
        skip_step_export=True,
        no_ground_clearance_recovery=True,
        cobyla_maxiter=40,
        rib_zonewise_mode="limited_zonewise",
        canonical_target_mass_kg=14.0,
    )

    assert "--target-mass-kg" in command
    assert command[command.index("--target-mass-kg") + 1] == "14"
