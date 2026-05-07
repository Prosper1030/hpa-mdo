from types import SimpleNamespace

from scripts.debug_z_state_mass_cliff import feasibility_labels_from_candidate


def test_production_hard_feasible_requires_moment_closure_even_when_inverse_passes() -> None:
    candidate = SimpleNamespace(
        overall_feasible=True,
        geometry_validity_succeeded=True,
        jig_ground_clearance_margin_m=0.010,
        inverse_result=SimpleNamespace(
            feasibility=SimpleNamespace(
                ground_clearance_passed=True,
                geometry_validity_passed=True,
            )
        ),
        production_result=SimpleNamespace(
            feasibility=SimpleNamespace(
                wire_support_validity_passed=True,
            ),
            optimizer=SimpleNamespace(
                numerical_consistency=SimpleNamespace(
                    moment_closure_passed=False,
                )
            ),
        ),
    )

    labels = feasibility_labels_from_candidate(candidate)

    assert labels["inverse_feasible"] is True
    assert labels["clearance_feasible"] is True
    assert labels["wire_feasible"] is True
    assert labels["moment_closure_feasible"] is False
    assert labels["production_hard_feasible"] is False


def test_production_hard_feasible_requires_clearance_even_when_production_passes() -> None:
    candidate = SimpleNamespace(
        overall_feasible=True,
        geometry_validity_succeeded=True,
        jig_ground_clearance_margin_m=-0.001,
        inverse_result=None,
        production_result=SimpleNamespace(
            feasibility=SimpleNamespace(
                wire_support_validity_passed=True,
            ),
            optimizer=SimpleNamespace(
                numerical_consistency=SimpleNamespace(
                    moment_closure_passed=True,
                )
            ),
        ),
    )

    labels = feasibility_labels_from_candidate(candidate)

    assert labels["inverse_feasible"] is True
    assert labels["clearance_feasible"] is False
    assert labels["wire_feasible"] is True
    assert labels["moment_closure_feasible"] is True
    assert labels["geometry_validity"] is True
    assert labels["production_hard_feasible"] is False
