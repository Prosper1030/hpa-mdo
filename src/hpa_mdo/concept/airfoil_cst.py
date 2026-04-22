from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CSTAirfoilTemplate:
    zone_name: str
    upper_coefficients: tuple[float, ...]
    lower_coefficients: tuple[float, ...]
    te_thickness_m: float


def build_lofting_guides(templates: Mapping[str, CSTAirfoilTemplate]) -> dict[str, object]:
    if not templates:
        raise ValueError("templates must not be empty.")

    zone_names = list(templates.keys())
    for key, template in templates.items():
        if key != template.zone_name:
            raise ValueError("template mapping keys must match template.zone_name.")

    for left_name, right_name in zip(zone_names[:-1], zone_names[1:]):
        left_template = templates[left_name]
        right_template = templates[right_name]
        if len(left_template.upper_coefficients) != len(right_template.upper_coefficients):
            raise ValueError("adjacent templates must have the same upper coefficient count.")
        if len(left_template.lower_coefficients) != len(right_template.lower_coefficients):
            raise ValueError("adjacent templates must have the same lower coefficient count.")

    blend_pairs = list(zip(zone_names[:-1], zone_names[1:]))
    return {
        "authority": "cst_coefficients",
        "zones": zone_names,
        "blend_pairs": blend_pairs,
        "interpolation_rule": "linear_in_coeff_space",
    }
