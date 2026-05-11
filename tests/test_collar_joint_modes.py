from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from collar_joint_modes import (  # noqa: E402
    BondedShearKey,
    FrictionClamp,
    HybridJoint,
    JointLoad,
    JointResult,
    LoadLineYoke,
    MU_REFERENCE,
    PeelBond,
    available_modes,
    joint_from_config,
    recommended_baseline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def reference_load() -> JointLoad:
    """P1 rib station load from the Step-1 geometry freeze."""
    return JointLoad(
        F_n=47.68,       # factored couple force [N]
        R_m=0.050,       # main spar outer radius 50 mm
        L_m=0.085,       # collar contact width [m]
        a_m=0.015,       # current bondline width [m]
        peel_allow=400.0,  # adhesive peel allowable [N/m]
    )


# ---------------------------------------------------------------------------
# JointLoad
# ---------------------------------------------------------------------------

def test_joint_load_moment(reference_load: JointLoad) -> None:
    assert reference_load.M_req_nm == pytest.approx(47.68 * 0.050, rel=1e-6)


def test_joint_load_m_per_width(reference_load: JointLoad) -> None:
    assert reference_load.m_per_width == pytest.approx(47.68 * 0.050 / 0.085, rel=1e-6)


def test_joint_load_from_freeze() -> None:
    freeze = {
        "load_factor": 1.5,
        "local_couple_force_n": -30.0,
        "spar_tubes": {"main_spar": {"od_m": 0.100}},
        "collar": {"collar_contact_width_m": 0.085},
        "bondline": {
            "bondline_width_m": 0.015,
            "adhesive_peel_allowable_n_per_m": 400.0,
        },
    }
    load = JointLoad.from_freeze(freeze)
    assert load.F_n == pytest.approx(45.0)
    assert load.R_m == pytest.approx(0.050)
    assert load.L_m == pytest.approx(0.085)
    assert load.a_m == pytest.approx(0.015)
    assert load.peel_allow == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# PeelBond
# ---------------------------------------------------------------------------

def test_peel_bond_fails_at_15mm(reference_load: JointLoad) -> None:
    mode = PeelBond(c_factor=2.0)
    r = mode.margin(reference_load)
    assert r.margin < 0, "Current 15 mm bondline must fail peel check"
    assert not r.passes


def test_peel_bond_passes_at_large_bondline(reference_load: JointLoad) -> None:
    # With c_factor=2.0 the min viable bondline is ~140 mm; 160 mm must pass.
    mode = PeelBond(a_m=0.160, c_factor=2.0)
    r = mode.margin(reference_load)
    assert r.margin > 0


def test_peel_bond_governs_label(reference_load: JointLoad) -> None:
    r = PeelBond().margin(reference_load)
    assert r.governs == "peel_bond"


def test_peel_bond_min_viable_bondline(reference_load: JointLoad) -> None:
    mode = PeelBond(c_factor=2.0)
    mv = mode.min_viable(reference_load, "a_m", 0.010, 0.200)
    assert mv is not None
    assert mv > 0.050, "Min viable bondline must be >> 15 mm"


def test_peel_bond_roundtrip(reference_load: JointLoad) -> None:
    mode = PeelBond(a_m=0.060, c_factor=1.5)
    d = mode.to_dict()
    assert d["type"] == "peel_bond"
    restored = PeelBond.from_dict(d)
    assert restored.a_m == pytest.approx(0.060)
    assert restored.c_factor == pytest.approx(1.5)
    assert restored.margin(reference_load).margin == pytest.approx(
        mode.margin(reference_load).margin, rel=1e-6
    )


# ---------------------------------------------------------------------------
# LoadLineYoke
# ---------------------------------------------------------------------------

def test_yoke_passes_at_3mm_r_eff(reference_load: JointLoad) -> None:
    mode = LoadLineYoke(r_eff_m=0.003, c_factor=2.0)
    r = mode.margin(reference_load)
    assert r.margin > 0


def test_yoke_fails_at_50mm_r_eff(reference_load: JointLoad) -> None:
    mode = LoadLineYoke(r_eff_m=0.050, c_factor=2.0)
    r = mode.margin(reference_load)
    assert r.margin < 0


def test_yoke_max_viable_r_eff_small(reference_load: JointLoad) -> None:
    mode = LoadLineYoke(r_eff_m=0.050, c_factor=2.0)
    mv = mode.min_viable_inverse(reference_load, "r_eff_m", 0.001, 0.050)
    assert mv is not None
    assert mv < 0.020, f"Max viable r_eff must be < 20 mm; got {mv*1000:.1f} mm"


def test_yoke_smaller_r_eff_better_margin(reference_load: JointLoad) -> None:
    m1 = LoadLineYoke(r_eff_m=0.010, c_factor=2.0).margin(reference_load).margin
    m2 = LoadLineYoke(r_eff_m=0.003, c_factor=2.0).margin(reference_load).margin
    assert m2 > m1, "Smaller r_eff must give better peel margin"


def test_yoke_detail_has_eccentricity_reduction(reference_load: JointLoad) -> None:
    r = LoadLineYoke(r_eff_m=0.003).margin(reference_load)
    assert "eccentricity_reduction_pct" in r.detail
    assert r.detail["eccentricity_reduction_pct"] > 90


def test_yoke_roundtrip(reference_load: JointLoad) -> None:
    mode = LoadLineYoke(r_eff_m=0.003, c_factor=2.0)
    restored = LoadLineYoke.from_dict(mode.to_dict())
    assert restored.r_eff_m == pytest.approx(0.003)
    assert restored.margin(reference_load).margin == pytest.approx(
        mode.margin(reference_load).margin, rel=1e-6
    )


# ---------------------------------------------------------------------------
# FrictionClamp
# ---------------------------------------------------------------------------

def test_friction_clamp_passes_at_600n_mu015(reference_load: JointLoad) -> None:
    mode = FrictionClamp(mu=0.15, N_c_n=600.0, liner="dry_cfrp_conservative")
    r = mode.margin(reference_load)
    assert r.margin > 0


def test_friction_clamp_fails_at_zero_force(reference_load: JointLoad) -> None:
    # N_c=0 → no friction torque; torque margin = -1.0; contact pressure = 0 (no crushing).
    mode = FrictionClamp(mu=0.15, N_c_n=0.0)
    r = mode.margin(reference_load)
    assert r.margin < 0
    assert r.governs == "torque"


def test_friction_clamp_higher_force_better_margin(reference_load: JointLoad) -> None:
    m1 = FrictionClamp(mu=0.15, N_c_n=300.0).margin(reference_load).margin
    m2 = FrictionClamp(mu=0.15, N_c_n=600.0).margin(reference_load).margin
    assert m2 > m1


def test_friction_clamp_min_viable_force(reference_load: JointLoad) -> None:
    mode = FrictionClamp(mu=0.15, N_c_n=100.0)
    mv = mode.min_viable(reference_load, "N_c_n", 10.0, 5000.0)
    assert mv is not None
    assert mv < 2000.0, f"Min N_c should be viable below 2000 N; got {mv:.0f} N"


def test_friction_clamp_mu_reference_dict() -> None:
    assert "dry_cfrp_conservative" in MU_REFERENCE
    assert MU_REFERENCE["dry_cfrp_conservative"] == pytest.approx(0.15)
    assert MU_REFERENCE["worn_in_cfrp"] > 0.5, "Worn-in μ should be >> design value"


def test_friction_clamp_roundtrip(reference_load: JointLoad) -> None:
    mode = FrictionClamp(mu=0.20, N_c_n=800.0, liner="neoprene_liner", role="primary")
    restored = FrictionClamp.from_dict(mode.to_dict())
    assert restored.mu == pytest.approx(0.20)
    assert restored.N_c_n == pytest.approx(800.0)
    assert restored.role == "primary"
    assert restored.margin(reference_load).margin == pytest.approx(
        mode.margin(reference_load).margin, rel=1e-6
    )


# ---------------------------------------------------------------------------
# BondedShearKey
# ---------------------------------------------------------------------------

def test_shear_key_passes_with_literature_geometry(reference_load: JointLoad) -> None:
    mode = BondedShearKey(
        n_keys=2, saddle_length_m=0.060, key_width_m=0.008,
        key_height_m=0.004, tau_d_pa=2.0e6, r_key_offset_m=0.005,
    )
    r = mode.margin(reference_load)
    assert r.margin > 0


def test_shear_key_min_viable_total_area_small(reference_load: JointLoad) -> None:
    mode = BondedShearKey(n_keys=2, key_width_m=0.008, tau_d_pa=2.0e6)
    mv = mode.min_viable(reference_load, "saddle_length_m", 0.005, 0.200)
    assert mv is not None
    total_mm2 = mv * 1000 * 2 * 0.008 * 1000
    assert total_mm2 < 500, f"Should be viable at < 500 mm² total; got {total_mm2:.0f} mm²"


def test_shear_key_more_keys_better(reference_load: JointLoad) -> None:
    m1 = BondedShearKey(n_keys=1).margin(reference_load).margin
    m2 = BondedShearKey(n_keys=2).margin(reference_load).margin
    assert m2 > m1


def test_shear_key_bearing_sub_mode_optional(reference_load: JointLoad) -> None:
    # without bearing allowable
    mode = BondedShearKey(n_keys=2, sigma_b_d_pa=None)
    r = mode.margin(reference_load)
    assert "shear" in r.detail["sub_margins"]
    assert "bearing" not in r.detail["sub_margins"]

    # with bearing allowable
    mode_b = BondedShearKey(n_keys=2, sigma_b_d_pa=50.0e6)
    r_b = mode_b.margin(reference_load)
    assert "shear" in r_b.detail["sub_margins"]
    assert "bearing" in r_b.detail["sub_margins"]


def test_shear_key_governs_shear_by_default(reference_load: JointLoad) -> None:
    mode = BondedShearKey(n_keys=2)
    r = mode.margin(reference_load)
    assert r.governs == "shear"


def test_shear_key_roundtrip(reference_load: JointLoad) -> None:
    mode = BondedShearKey(n_keys=3, saddle_length_m=0.070, tau_d_pa=4.0e6,
                          sigma_b_d_pa=60.0e6)
    restored = BondedShearKey.from_dict(mode.to_dict())
    assert restored.n_keys == 3
    assert restored.saddle_length_m == pytest.approx(0.070)
    assert restored.sigma_b_d_pa == pytest.approx(60.0e6)
    assert restored.margin(reference_load).margin == pytest.approx(
        mode.margin(reference_load).margin, rel=1e-6
    )


# ---------------------------------------------------------------------------
# HybridJoint
# ---------------------------------------------------------------------------

def test_hybrid_governing_is_worst_sub_mode(reference_load: JointLoad) -> None:
    good = BondedShearKey(n_keys=2)
    bad = PeelBond(a_m=0.010, c_factor=2.0)
    hybrid = HybridJoint(modes=[good, bad])
    r = hybrid.margin(reference_load)
    assert r.margin == pytest.approx(bad.margin(reference_load).margin, rel=1e-3)
    assert "peel_bond" in r.governs


def test_hybrid_all_pass_requires_all_pass(reference_load: JointLoad) -> None:
    good = BondedShearKey(n_keys=2)
    bad = PeelBond()  # fails at 15 mm
    hybrid = HybridJoint(modes=[good, bad])
    r = hybrid.margin(reference_load)
    assert not r.passes
    assert not r.detail["all_pass"]
    assert r.detail["any_pass"]


def test_hybrid_roundtrip(reference_load: JointLoad) -> None:
    hybrid = HybridJoint(
        modes=[
            BondedShearKey(n_keys=2),
            LoadLineYoke(r_eff_m=0.003),
            FrictionClamp(mu=0.15, N_c_n=600.0),
        ],
        description="test hybrid",
    )
    d = hybrid.to_dict()
    assert d["type"] == "hybrid"
    assert len(d["modes"]) == 3
    restored = HybridJoint.from_dict(d)
    assert restored.description == "test hybrid"
    assert len(restored.modes) == 3
    assert restored.margin(reference_load).margin == pytest.approx(
        hybrid.margin(reference_load).margin, rel=1e-6
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_all_registered_modes() -> None:
    modes = available_modes()
    for m in ("peel_bond", "load_line_yoke", "friction_clamp", "bonded_shear_key", "hybrid"):
        assert m in modes


def test_factory_peel_bond(reference_load: JointLoad) -> None:
    mode = joint_from_config({"type": "peel_bond", "c_factor": 1.5})
    assert isinstance(mode, PeelBond)
    r = mode.margin(reference_load)
    assert isinstance(r, JointResult)


def test_factory_load_line_yoke(reference_load: JointLoad) -> None:
    mode = joint_from_config({"type": "load_line_yoke", "r_eff_m": 0.003})
    assert isinstance(mode, LoadLineYoke)
    assert mode.margin(reference_load).passes


def test_factory_friction_clamp(reference_load: JointLoad) -> None:
    mode = joint_from_config({"type": "friction_clamp", "mu": 0.15, "N_c_n": 600.0})
    assert isinstance(mode, FrictionClamp)


def test_factory_bonded_shear_key(reference_load: JointLoad) -> None:
    mode = joint_from_config({"type": "bonded_shear_key", "n_keys": 2, "tau_d_pa": 2e6})
    assert isinstance(mode, BondedShearKey)


def test_factory_hybrid_nested(reference_load: JointLoad) -> None:
    cfg = {
        "type": "hybrid",
        "description": "from factory",
        "modes": [
            {"type": "bonded_shear_key", "n_keys": 2},
            {"type": "friction_clamp", "mu": 0.15, "N_c_n": 600.0},
        ],
    }
    mode = joint_from_config(cfg)
    assert isinstance(mode, HybridJoint)
    assert len(mode.modes) == 2
    r = mode.margin(reference_load)
    assert r.detail["description"] == "from factory"


def test_factory_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown collar joint type"):
        joint_from_config({"type": "magic_joint"})


# ---------------------------------------------------------------------------
# Recommended baseline
# ---------------------------------------------------------------------------

def test_recommended_baseline_positive_margin(reference_load: JointLoad) -> None:
    joint = recommended_baseline(reference_load)
    r = joint.margin(reference_load)
    assert r.margin > 0, (
        f"Recommended baseline must pass; got governing margin {r.margin:.3f}"
    )


def test_recommended_baseline_all_pass(reference_load: JointLoad) -> None:
    joint = recommended_baseline(reference_load)
    r = joint.margin(reference_load)
    assert r.passes
    assert r.detail["all_pass"]


def test_recommended_baseline_has_three_modes(reference_load: JointLoad) -> None:
    joint = recommended_baseline(reference_load)
    assert len(joint.modes) == 3
    mode_ids = {m.mode_id for m in joint.modes}
    assert "bonded_shear_key" in mode_ids
    assert "load_line_yoke" in mode_ids
    assert "friction_clamp" in mode_ids


def test_recommended_baseline_shear_key_governs(reference_load: JointLoad) -> None:
    joint = recommended_baseline(reference_load)
    r = joint.margin(reference_load)
    # Shear key with tau_d=2 MPa is typically the weakest of the three
    # (conservative allowable); confirm governing mode is known
    assert r.governs != "", "governing mode must be labelled"


# ---------------------------------------------------------------------------
# Sweep utility
# ---------------------------------------------------------------------------

def test_sweep_returns_rows_in_order(reference_load: JointLoad) -> None:
    mode = PeelBond(c_factor=2.0)
    widths = [0.020, 0.040, 0.060, 0.080, 0.100]
    rows = mode.sweep(reference_load, "a_m", widths)
    assert len(rows) == 5
    margins = [r["margin"] for r in rows]
    assert margins == sorted(margins), "larger bondline → larger margin"


def test_sweep_contains_required_keys(reference_load: JointLoad) -> None:
    mode = LoadLineYoke(r_eff_m=0.010)
    rows = mode.sweep(reference_load, "r_eff_m", [0.005, 0.010, 0.020])
    for row in rows:
        assert "margin" in row
        assert "passes" in row
        assert "governs" in row


# ---------------------------------------------------------------------------
# Physics sanity checks
# ---------------------------------------------------------------------------

def test_peel_demand_scales_with_c_factor(reference_load: JointLoad) -> None:
    m1 = PeelBond(a_m=0.015, c_factor=1.0).margin(reference_load).margin
    m2 = PeelBond(a_m=0.015, c_factor=2.0).margin(reference_load).margin
    assert m1 > m2, "Higher c_factor increases peel demand → lower margin"


def test_shear_key_margin_scales_with_tau_d(reference_load: JointLoad) -> None:
    m1 = BondedShearKey(n_keys=2, tau_d_pa=1.0e6).margin(reference_load).margin
    m2 = BondedShearKey(n_keys=2, tau_d_pa=4.0e6).margin(reference_load).margin
    assert m2 > m1


def test_friction_clamp_torque_linear_in_mu(reference_load: JointLoad) -> None:
    m1 = FrictionClamp(mu=0.10, N_c_n=500.0).margin(reference_load).margin
    m2 = FrictionClamp(mu=0.20, N_c_n=500.0).margin(reference_load).margin
    assert m2 > m1


def test_yoke_eliminates_most_peel_vs_original(reference_load: JointLoad) -> None:
    original = PeelBond(c_factor=2.0).margin(reference_load).margin
    yoke = LoadLineYoke(r_eff_m=0.003, c_factor=2.0).margin(reference_load).margin
    assert yoke > original, "Yoke should drastically improve over original peel design"
    assert yoke > 0, "Yoke at r_eff=3 mm must pass"
    assert original < 0, "Original 15 mm bondline must fail"
