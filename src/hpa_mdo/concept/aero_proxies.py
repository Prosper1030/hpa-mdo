from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import (
        OswaldEfficiencyProxyConfig,
        ParasiteDragProxyConfig,
    )
    from hpa_mdo.concept.geometry import GeometryConcept


def oswald_efficiency_proxy(
    *,
    concept: "GeometryConcept",
    proxy_cfg: "OswaldEfficiencyProxyConfig",
) -> float:
    """Return Oswald-efficiency proxy for the concept.

    Linear knockdown around ``proxy_cfg.base_efficiency`` driven by:
    - dihedral spread (tip - root, only positive part)
    - twist spread (|tip - root|)
    Clamped to ``[efficiency_floor, efficiency_ceiling]``.
    """
    dihedral_delta = max(
        0.0, float(concept.dihedral_tip_deg) - float(concept.dihedral_root_deg)
    )
    twist_delta = abs(float(concept.twist_tip_deg) - float(concept.twist_root_deg))
    efficiency = (
        float(proxy_cfg.base_efficiency)
        - float(proxy_cfg.dihedral_delta_slope_per_deg) * dihedral_delta
        - float(proxy_cfg.twist_delta_slope_per_deg) * twist_delta
    )
    return max(
        float(proxy_cfg.efficiency_floor),
        min(float(proxy_cfg.efficiency_ceiling), efficiency),
    )


def misc_cd_proxy(
    *,
    profile_cd: float,
    tail_area_ratio: float,
    proxy_cfg: "ParasiteDragProxyConfig",
) -> float:
    """Return the lumped fuselage + tail-coupling parasite drag coefficient.

    misc_cd = fuselage_misc_cd + tail_profile_coupling_factor
              * tail_area_ratio * profile_cd
    """
    return (
        float(proxy_cfg.fuselage_misc_cd)
        + float(proxy_cfg.tail_profile_coupling_factor)
        * float(tail_area_ratio)
        * float(profile_cd)
    )


__all__ = ["oswald_efficiency_proxy", "misc_cd_proxy"]
