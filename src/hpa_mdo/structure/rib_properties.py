"""Rib family catalog and derived dual-spar warping-knockdown helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from hpa_mdo.core.materials import MaterialDB


_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "rib_properties.yaml"


@dataclass(frozen=True)
class RibStiffnessProxy:
    construction_factor: float
    rotational_fixity_factor: float
    shear_transfer_factor: float


@dataclass(frozen=True)
class RibSpacingGuidance:
    min_m: float
    nominal_m: float
    max_m: float


@dataclass(frozen=True)
class RibFamily:
    key: str
    label: str
    material: str
    thickness_m: float
    description: str
    intended_use: str
    notes: str
    stiffness_proxy: RibStiffnessProxy
    spacing_guidance: RibSpacingGuidance


@dataclass(frozen=True)
class RibDerivationSettings:
    formula: str
    reference_family: str
    reference_spacing_m: float
    bending_weight: float
    shear_weight: float
    spacing_exponent: float
    minimum_knockdown: float
    maximum_knockdown: float


@dataclass(frozen=True)
class DerivedWarpingKnockdown:
    family_key: str
    spacing_m: float
    relative_bending_scale: float
    relative_shear_scale: float
    relative_stiffness: float
    spacing_factor: float
    raw_score: float
    warping_knockdown: float


@dataclass(frozen=True)
class RibPropertiesCatalog:
    description: str
    catalog_version: int
    default_family: str
    default_spacing_m: float
    derivation: RibDerivationSettings
    families: Mapping[str, RibFamily]

    def family(self, key: str) -> RibFamily:
        try:
            return self.families[key]
        except KeyError as exc:
            available = ", ".join(sorted(self.families))
            raise KeyError(f"Unknown rib family '{key}'. Available: {available}") from exc


def _read_yaml(path: Path) -> Mapping[str, object]:
    with open(path, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Rib catalog root must be a mapping: {path}")
    return payload


def _as_float(payload: Mapping[str, object], key: str) -> float:
    return float(payload[key])


def build_default_rib_catalog(path: Path | None = None) -> RibPropertiesCatalog:
    payload = _read_yaml(path or _DEFAULT_CATALOG_PATH)
    metadata = payload.get("metadata") or {}
    families_payload = payload.get("families") or {}
    if not isinstance(metadata, dict) or not isinstance(families_payload, dict):
        raise ValueError("Rib catalog metadata and families must both be mappings.")

    derivation_payload = metadata.get("derivation") or {}
    if not isinstance(derivation_payload, dict):
        raise ValueError("Rib catalog metadata.derivation must be a mapping.")

    derivation = RibDerivationSettings(
        formula=str(derivation_payload["formula"]),
        reference_family=str(derivation_payload["reference_family"]),
        reference_spacing_m=_as_float(derivation_payload, "reference_spacing_m"),
        bending_weight=_as_float(derivation_payload, "bending_weight"),
        shear_weight=_as_float(derivation_payload, "shear_weight"),
        spacing_exponent=_as_float(derivation_payload, "spacing_exponent"),
        minimum_knockdown=_as_float(derivation_payload, "minimum_knockdown"),
        maximum_knockdown=_as_float(derivation_payload, "maximum_knockdown"),
    )
    if derivation.bending_weight < 0.0 or derivation.shear_weight < 0.0:
        raise ValueError("Rib derivation weights must be non-negative.")
    if derivation.bending_weight + derivation.shear_weight <= 0.0:
        raise ValueError("Rib derivation weights must sum to a positive value.")

    families: dict[str, RibFamily] = {}
    for key, raw_family in families_payload.items():
        if not isinstance(raw_family, dict):
            raise ValueError(f"Rib family '{key}' must be a mapping.")
        stiffness_payload = raw_family.get("stiffness_proxy") or {}
        spacing_payload = raw_family.get("spacing_guidance") or {}
        if not isinstance(stiffness_payload, dict) or not isinstance(spacing_payload, dict):
            raise ValueError(f"Rib family '{key}' stiffness_proxy and spacing_guidance must map.")

        families[str(key)] = RibFamily(
            key=str(key),
            label=str(raw_family["label"]),
            material=str(raw_family["material"]),
            thickness_m=_as_float(raw_family, "thickness_m"),
            description=str(raw_family.get("description", "")),
            intended_use=str(raw_family.get("intended_use", "")),
            notes=str(raw_family.get("notes", "")),
            stiffness_proxy=RibStiffnessProxy(
                construction_factor=_as_float(stiffness_payload, "construction_factor"),
                rotational_fixity_factor=_as_float(stiffness_payload, "rotational_fixity_factor"),
                shear_transfer_factor=_as_float(stiffness_payload, "shear_transfer_factor"),
            ),
            spacing_guidance=RibSpacingGuidance(
                min_m=_as_float(spacing_payload, "min_m"),
                nominal_m=_as_float(spacing_payload, "nominal_m"),
                max_m=_as_float(spacing_payload, "max_m"),
            ),
        )

    default_family = str(metadata["default_family"])
    if default_family not in families:
        raise ValueError(f"Rib catalog default_family '{default_family}' is not defined.")
    if derivation.reference_family not in families:
        raise ValueError(
            f"Rib catalog reference_family '{derivation.reference_family}' is not defined."
        )

    return RibPropertiesCatalog(
        description=str(metadata.get("description", "")),
        catalog_version=int(metadata.get("catalog_version", 1)),
        default_family=default_family,
        default_spacing_m=_as_float(metadata, "default_spacing_m"),
        derivation=derivation,
        families=families,
    )


def _family_relative_stiffness(
    family: RibFamily,
    reference_family: RibFamily,
    derivation: RibDerivationSettings,
    material_db: MaterialDB,
) -> tuple[float, float, float]:
    material = material_db.get(family.material)
    reference_material = material_db.get(reference_family.material)

    bending_scale = (
        (material.E / reference_material.E)
        * (family.thickness_m / reference_family.thickness_m) ** 3
        * family.stiffness_proxy.rotational_fixity_factor
    )
    shear_scale = (
        (material.G / reference_material.G)
        * (family.thickness_m / reference_family.thickness_m)
        * family.stiffness_proxy.shear_transfer_factor
    )
    weighted_scale = (
        derivation.bending_weight * bending_scale + derivation.shear_weight * shear_scale
    )
    relative_stiffness = family.stiffness_proxy.construction_factor * weighted_scale
    return bending_scale, shear_scale, relative_stiffness


def derive_warping_knockdown_details(
    family_key: str,
    spacing_m: float,
    *,
    catalog: RibPropertiesCatalog | None = None,
    material_db: MaterialDB | None = None,
) -> DerivedWarpingKnockdown:
    if spacing_m <= 0.0:
        raise ValueError("Rib spacing must be positive.")

    resolved_catalog = catalog or build_default_rib_catalog()
    resolved_material_db = material_db or MaterialDB()
    derivation = resolved_catalog.derivation
    family = resolved_catalog.family(family_key)
    reference_family = resolved_catalog.family(derivation.reference_family)

    bending_scale, shear_scale, relative_stiffness = _family_relative_stiffness(
        family,
        reference_family,
        derivation,
        resolved_material_db,
    )
    spacing_factor = (derivation.reference_spacing_m / spacing_m) ** derivation.spacing_exponent
    raw_score = relative_stiffness * spacing_factor
    raw_knockdown = raw_score / (1.0 + raw_score)
    bounded_knockdown = min(
        derivation.maximum_knockdown,
        max(derivation.minimum_knockdown, raw_knockdown),
    )
    return DerivedWarpingKnockdown(
        family_key=family.key,
        spacing_m=float(spacing_m),
        relative_bending_scale=float(bending_scale),
        relative_shear_scale=float(shear_scale),
        relative_stiffness=float(relative_stiffness),
        spacing_factor=float(spacing_factor),
        raw_score=float(raw_score),
        warping_knockdown=float(bounded_knockdown),
    )


def derive_warping_knockdown(
    family_key: str,
    spacing_m: float,
    *,
    catalog: RibPropertiesCatalog | None = None,
    material_db: MaterialDB | None = None,
) -> float:
    return derive_warping_knockdown_details(
        family_key,
        spacing_m,
        catalog=catalog,
        material_db=material_db,
    ).warping_knockdown


def resolve_rib_warping_knockdown(
    *,
    family_key: str | None = None,
    spacing_m: float | None = None,
    catalog_path: Path | None = None,
    warping_knockdown_override: float | None = None,
) -> float:
    if warping_knockdown_override is not None:
        return float(warping_knockdown_override)

    catalog = build_default_rib_catalog(catalog_path)
    resolved_family_key = family_key or catalog.default_family
    family = catalog.family(resolved_family_key)
    resolved_spacing_m = float(
        spacing_m if spacing_m is not None else family.spacing_guidance.nominal_m
    )
    return derive_warping_knockdown(
        resolved_family_key,
        resolved_spacing_m,
        catalog=catalog,
    )
