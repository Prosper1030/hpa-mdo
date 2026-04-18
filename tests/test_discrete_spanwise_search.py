from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core import MaterialDB  # noqa: E402
from hpa_mdo.structure.laminate import PlyStack  # noqa: E402
from hpa_mdo.utils.discrete_spanwise_search import (  # noqa: E402
    search_spanwise_discrete_stacks,
)


@pytest.fixture(scope="module")
def ply_mat():
    return MaterialDB(REPO_ROOT / "data" / "materials.yaml").get_ply("cfrp_ply_hm")


def test_spanwise_dp_prefers_global_path_that_avoids_shortfall(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies
        PlyStack(n_0=2, n_45=1, n_90=0),  # 8 plies
        PlyStack(n_0=3, n_45=1, n_90=0),  # 10 plies
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies
    ]

    result = search_spanwise_discrete_stacks(
        continuous_thicknesses_m=[0.99e-3, 1.49e-3],
        segment_lengths_m=[1.0, 1.0],
        outer_radii_m=[0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
    )

    assert [stack.total_plies() for stack in result.selected_stacks] == [10, 12]
    assert result.objective.total_shortfall_m == pytest.approx(0.0)
    assert result.objective.total_transition_half_ply_delta == 1


def test_spanwise_dp_returns_manufacturable_transition_chain(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies
        PlyStack(n_0=2, n_45=1, n_90=0),  # 8 plies
        PlyStack(n_0=3, n_45=1, n_90=0),  # 10 plies
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies
    ]

    result = search_spanwise_discrete_stacks(
        continuous_thicknesses_m=[0.99e-3, 1.49e-3, 0.99e-3],
        segment_lengths_m=[1.0, 1.0, 1.0],
        outer_radii_m=[0.03, 0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
    )

    half_counts = [stack.total_plies() // 2 for stack in result.selected_stacks]
    adjacent_jumps = [abs(curr - prev) for prev, curr in zip(half_counts, half_counts[1:])]

    assert [stack.total_plies() for stack in result.selected_stacks] == [10, 12, 10]
    assert max(adjacent_jumps) == 1
    assert result.objective.total_transition_half_ply_delta == 2


def test_spanwise_dp_rejects_mismatched_segment_lengths(ply_mat) -> None:
    stacks = [PlyStack(n_0=1, n_45=1, n_90=0)]

    with pytest.raises(ValueError, match="segment_lengths_m must match"):
        search_spanwise_discrete_stacks(
            continuous_thicknesses_m=[0.99e-3, 1.49e-3],
            segment_lengths_m=[1.0],
            outer_radii_m=[0.03, 0.03],
            stacks=stacks,
            ply_mat=ply_mat,
            ply_drop_limit=1,
        )
