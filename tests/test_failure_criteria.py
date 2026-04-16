"""Unit tests for Tsai-Hill and Tsai-Wu failure criteria (F13).

Golden values computed by hand from first principles and cross-checked
against the Tsai (1971) paper reference cases.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from hpa_mdo.structure.failure_criteria import tsai_hill_index, tsai_wu_index

# ── Material strength parameters: conservative M46J HM CFRP (from materials.yaml) ──
F1T = 1500.0e6
F1C = 1000.0e6
F2T = 50.0e6
F2C = 200.0e6
F6_ = 70.0e6


# ---------------------------------------------------------------------------
# Tsai-Hill golden tests
# ---------------------------------------------------------------------------

class TestTsaiHill:
    def test_pure_longitudinal_tension_at_limit_is_zero(self):
        """σ₁ = F1t, σ₂ = τ = 0 → FI = 1 - 1 = 0 (at failure boundary)."""
        fi = tsai_hill_index(
            np.array([F1T]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(0.0, abs=1e-9)

    def test_pure_compression_at_limit(self):
        fi = tsai_hill_index(
            np.array([-F1C]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(0.0, abs=1e-9)

    def test_pure_shear_at_limit(self):
        fi = tsai_hill_index(
            np.zeros(1), np.zeros(1), np.array([F6_]),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(0.0, abs=1e-9)

    def test_safe_state_is_negative(self):
        """Half the longitudinal failure stress → FI = 0.25 - 1 = -0.75."""
        fi = tsai_hill_index(
            np.array([F1T / 2.0]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(-0.75, abs=1e-9)

    def test_failed_state_is_positive(self):
        """σ₁ = 1.1 × F1t → FI = 1.21 - 1 = 0.21."""
        fi = tsai_hill_index(
            np.array([1.1 * F1T]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(0.21, abs=1e-6)

    def test_combined_load_known_value(self):
        """σ₁ = 0.5·F1t, τ = 0.5·F6 → FI = 0.25 + 0.25 - 1 = -0.5."""
        fi = tsai_hill_index(
            np.array([0.5 * F1T]), np.zeros(1), np.array([0.5 * F6_]),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(-0.5, abs=1e-9)

    def test_all_elements_array(self):
        """Vectorised call — shape preserved."""
        s1 = np.array([0.0, F1T, -F1C])
        fi = tsai_hill_index(s1, np.zeros(3), np.zeros(3),
                             F1T, F1C, F2T, F2C, F6_)
        assert fi.shape == (3,)
        assert fi[0] == pytest.approx(-1.0, abs=1e-9)   # zero stress
        assert fi[1] == pytest.approx(0.0, abs=1e-9)    # at tension limit
        assert fi[2] == pytest.approx(0.0, abs=1e-9)    # at compression limit


# ---------------------------------------------------------------------------
# Tsai-Wu golden tests
# ---------------------------------------------------------------------------

class TestTsaiWu:
    def _coeffs(self):
        F11 = 1.0 / (F1T * F1C)
        F22 = 1.0 / (F2T * F2C)
        F66 = 1.0 / (F6_ ** 2)
        F1_lin = 1.0 / F1T - 1.0 / F1C
        F2_lin = 1.0 / F2T - 1.0 / F2C
        return F11, F22, F66, F1_lin, F2_lin

    def test_pure_longitudinal_tension_at_limit(self):
        """FI_TW(σ₁=F1t) = F11·F1t² + F1_lin·F1t - 1.  Verify numerically."""
        F11, _, _, F1_lin, _ = self._coeffs()
        expected = F11 * F1T ** 2 + F1_lin * F1T - 1.0
        fi = tsai_wu_index(
            np.array([F1T]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(expected, abs=1e-9)

    def test_pure_compression_at_limit(self):
        F11, _, _, F1_lin, _ = self._coeffs()
        expected = F11 * F1C ** 2 - F1_lin * F1C - 1.0
        fi = tsai_wu_index(
            np.array([-F1C]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(expected, abs=1e-9)

    def test_pure_shear_at_limit(self):
        """F66·F6² - 1 = 1 - 1 = 0."""
        fi = tsai_wu_index(
            np.zeros(1), np.zeros(1), np.array([F6_]),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(0.0, abs=1e-9)

    def test_zero_stress_is_negative_one(self):
        """FI_TW(0,0,0) = -1 by definition."""
        fi = tsai_wu_index(
            np.zeros(1), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] == pytest.approx(-1.0, abs=1e-9)

    def test_safe_state_is_negative(self):
        """Any sub-critical stress → FI < 0."""
        fi = tsai_wu_index(
            np.array([0.5 * F1T]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] < 0.0

    def test_failed_state_is_positive(self):
        """1.5×F1t should fail Tsai-Wu."""
        fi = tsai_wu_index(
            np.array([1.5 * F1T]), np.zeros(1), np.zeros(1),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi[0] > 0.0

    def test_interaction_term_sign(self):
        """F12 = -0.5*sqrt(F11*F22) < 0 → combined biaxial FI is less critical
        than the same loads without the interaction term (F12=0)."""
        s1 = np.array([0.6 * F1T])
        s2 = np.array([0.6 * F2T])
        tau = np.zeros(1)

        fi_with_interaction = tsai_wu_index(s1, s2, tau, F1T, F1C, F2T, F2C, F6_)

        # Manually compute without F12 interaction term
        F11 = 1.0 / (F1T * F1C)
        F22 = 1.0 / (F2T * F2C)
        F1_lin = 1.0 / F1T - 1.0 / F1C
        F2_lin = 1.0 / F2T - 1.0 / F2C
        fi_no_interaction = (
            F11 * s1 ** 2 + F22 * s2 ** 2 + F1_lin * s1 + F2_lin * s2 - 1.0
        )

        # Negative F12 reduces the failure index under same-sign biaxial loading
        assert fi_with_interaction[0] < fi_no_interaction[0]

    def test_array_shape_preserved(self):
        n = 10
        fi = tsai_wu_index(
            np.random.uniform(0, 0.5 * F1T, n),
            np.zeros(n),
            np.random.uniform(0, 0.5 * F6_, n),
            F1T, F1C, F2T, F2C, F6_,
        )
        assert fi.shape == (n,)
        assert np.all(fi < 0)


# ---------------------------------------------------------------------------
# TsaiWuKSComp OpenMDAO component smoke test
# ---------------------------------------------------------------------------

class TestTsaiWuKSComp:
    def test_component_von_mises_equiv_fallback(self):
        """TsaiWuKSComp with tsai_wu criterion: KS ≤ 0 when all elements safe."""
        import openmdao.api as om
        from hpa_mdo.structure.components.constraints import TsaiWuKSComp

        prob = om.Problem()
        ne = 5
        comp = TsaiWuKSComp(
            n_elements=ne,
            criterion="tsai_wu",
            F1t=F1T, F1c=F1C, F2t=F2T, F2c=F2C, F6=F6_,
            rear_enabled=False,
            rho_ks=100.0,
            msf=1.0,
        )
        prob.model.add_subsystem("tw", comp, promotes=["*"])
        prob.setup(force_alloc_complex=True)

        # Safe: all σ₁ = 0.5·F1t, τ = 0
        prob.set_val("sigma_lon_main", np.full(ne, 0.5 * F1T))
        prob.set_val("tau_main", np.zeros(ne))
        prob.run_model()

        fi = prob.get_val("failure")[0]
        # KS of [-0.75, -0.75, …] should be < 0
        assert fi < 0.0

    def test_component_fails_at_limit(self):
        import openmdao.api as om
        from hpa_mdo.structure.components.constraints import TsaiWuKSComp

        prob = om.Problem()
        ne = 3
        comp = TsaiWuKSComp(
            n_elements=ne,
            criterion="tsai_hill",
            F1t=F1T, F1c=F1C, F2t=F2T, F2c=F2C, F6=F6_,
            rear_enabled=False,
            rho_ks=100.0,
            msf=1.0,
        )
        prob.model.add_subsystem("tw", comp, promotes=["*"])
        prob.setup(force_alloc_complex=True)

        # Exactly at limit: σ₁ = F1t → Tsai-Hill FI = 0 → KS ≈ 0
        prob.set_val("sigma_lon_main", np.full(ne, F1T))
        prob.set_val("tau_main", np.zeros(ne))
        prob.run_model()

        fi = prob.get_val("failure")[0]
        # KS of all-zero FI values → slightly above 0 (log(n)/rho offset)
        assert fi == pytest.approx(np.log(ne) / 100.0, abs=1e-6)

    def test_partials(self):
        """Check analytic (cs) partials against finite-difference."""
        import openmdao.api as om
        from hpa_mdo.structure.components.constraints import TsaiWuKSComp

        prob = om.Problem()
        ne = 4
        comp = TsaiWuKSComp(
            n_elements=ne,
            criterion="tsai_wu",
            F1t=F1T, F1c=F1C, F2t=F2T, F2c=F2C, F6=F6_,
            rear_enabled=False,
            rho_ks=100.0,
            msf=1.5,
        )
        prob.model.add_subsystem("tw", comp, promotes=["*"])
        prob.setup(force_alloc_complex=True)

        rng = np.random.default_rng(42)
        prob.set_val("sigma_lon_main", rng.uniform(0.1e6, 200e6, ne))
        prob.set_val("tau_main", rng.uniform(0.1e6, 30e6, ne))
        prob.run_model()

        data = prob.check_partials(method="cs", compact_print=True, out_stream=None)
        for comp_name, comp_data in data.items():
            for (out, inp), err in comp_data.items():
                rel_err = err["rel error"].forward
                if not math.isnan(rel_err):
                    assert rel_err < 1e-6, (
                        f"Partial {out} wrt {inp}: rel_err={rel_err:.3e}"
                    )
