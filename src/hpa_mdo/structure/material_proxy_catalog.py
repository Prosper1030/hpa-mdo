"""Preliminary grouped/discrete material proxy catalog for dual-beam screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from hpa_mdo.core.materials import Material, MaterialDB


_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "dual_beam_material_packages.yaml"


@dataclass(frozen=True)
class LayupFractions:
    axial_0: float
    shear_pm45: float
    hoop_90: float

    def total(self) -> float:
        return float(self.axial_0) + float(self.shear_pm45) + float(self.hoop_90)


@dataclass(frozen=True)
class PackagePropertySources:
    young: str
    shear: str
    density: str
    allowable: str


@dataclass(frozen=True)
class PackageBucklingRules:
    minimum_hoop_fraction: float
    forbid_outer_pure_axial: bool
    conservative_allowable_knockdown: float
    allowed_region: str
    local_buckling_reserve: str
    equivalent_gate_credit: str


@dataclass(frozen=True)
class MaterialScalePackage:
    key: str
    label: str
    scope: str
    young_scale: float
    shear_scale: float
    density_scale: float
    allowable_scale: float
    description: str
    family_description: str = ""
    intended_role: str = ""
    manufacturing_notes: str = ""
    buckling_note: str = ""
    layup_reference: str = "tube_family_total"
    source_material_grade: str = ""
    promotion_state: str = "preliminary"
    requires_balanced_symmetric: bool = True
    layup_fractions: LayupFractions = field(
        default_factory=lambda: LayupFractions(axial_0=0.0, shear_pm45=0.0, hoop_90=0.0)
    )
    property_sources: PackagePropertySources = field(
        default_factory=lambda: PackagePropertySources(young="", shear="", density="", allowable="")
    )
    buckling_rules: PackageBucklingRules = field(
        default_factory=lambda: PackageBucklingRules(
            minimum_hoop_fraction=0.0,
            forbid_outer_pure_axial=False,
            conservative_allowable_knockdown=1.0,
            allowed_region="unspecified",
            local_buckling_reserve="baseline",
            equivalent_gate_credit="unspecified",
        )
    )
    overlay_layers_equivalent: float | None = None
    overlay_construction: str | None = None

    @property
    def final_allowable_scale(self) -> float:
        return float(self.allowable_scale) * float(self.buckling_rules.conservative_allowable_knockdown)


@dataclass(frozen=True)
class EffectiveMaterialProperties:
    E_eff_pa: float
    G_eff_pa: float
    density_eff_kgpm3: float
    allowable_eff_pa: float


@dataclass(frozen=True)
class ResolvedPackagePropertyRow:
    axis: str
    package: MaterialScalePackage
    base_material_key: str
    base_material_name: str
    effective_properties: EffectiveMaterialProperties


@dataclass(frozen=True)
class AxisMetadata:
    axis: str
    description: str
    integration_mode: str
    promotion_state: str
    default_base_material_key: str


@dataclass(frozen=True)
class MaterialProxyCatalog:
    main_spar_family: tuple[MaterialScalePackage, ...]
    rear_spar_family: tuple[MaterialScalePackage, ...]
    rear_outboard_reinforcement_pkg: tuple[MaterialScalePackage, ...]
    axis_metadata: Mapping[str, AxisMetadata]

    def packages_for_axis(self, axis_name: str) -> tuple[MaterialScalePackage, ...]:
        try:
            return getattr(self, axis_name)
        except AttributeError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"Unknown material proxy axis: {axis_name}") from exc

    def axis_info(self, axis_name: str) -> AxisMetadata:
        try:
            return self.axis_metadata[axis_name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"Unknown material proxy axis: {axis_name}") from exc

    def get_package(self, axis_name: str, package_key: str) -> MaterialScalePackage:
        for package in self.packages_for_axis(axis_name):
            if package.key == package_key:
                return package
        raise KeyError(f"Package '{package_key}' not found on axis '{axis_name}'.")


def _base_strength(material: Material) -> float:
    return float(min(material.tensile_strength, material.compressive_strength or material.tensile_strength))


def effective_properties(
    base_material: Material,
    package: MaterialScalePackage,
    *,
    safety_factor: float,
) -> EffectiveMaterialProperties:
    strength_eff = _base_strength(base_material) * float(package.final_allowable_scale)
    return EffectiveMaterialProperties(
        E_eff_pa=float(base_material.E) * float(package.young_scale),
        G_eff_pa=float(base_material.G) * float(package.shear_scale),
        density_eff_kgpm3=float(base_material.density) * float(package.density_scale),
        allowable_eff_pa=float(strength_eff / float(safety_factor)),
    )


def register_package_material(
    *,
    materials_db: MaterialDB,
    base_material: Material,
    package: MaterialScalePackage,
    key: str,
) -> None:
    materials_db.register(
        key,
        Material(
            name=f"{base_material.name} [{package.label}]",
            E=float(base_material.E) * float(package.young_scale),
            G=float(base_material.G) * float(package.shear_scale),
            density=float(base_material.density) * float(package.density_scale),
            tensile_strength=float(base_material.tensile_strength) * float(package.final_allowable_scale),
            compressive_strength=float(base_material.sigma_c) * float(package.final_allowable_scale),
            shear_strength=base_material.shear_strength,
            tension_only=base_material.tension_only,
            poisson_ratio=float(base_material.poisson_ratio),
            description=f"{base_material.description} | {package.description}",
        ),
    )


def resolve_catalog_property_rows(
    *,
    catalog: MaterialProxyCatalog,
    materials_db: MaterialDB,
    axis_base_material_keys: Mapping[str, str] | None = None,
    safety_factor: float,
) -> dict[str, tuple[ResolvedPackagePropertyRow, ...]]:
    resolved: dict[str, tuple[ResolvedPackagePropertyRow, ...]] = {}
    overrides = dict(axis_base_material_keys or {})
    for axis_name in ("main_spar_family", "rear_spar_family", "rear_outboard_reinforcement_pkg"):
        axis_info = catalog.axis_info(axis_name)
        material_key = overrides.get(axis_name, axis_info.default_base_material_key)
        base_material = materials_db.get(material_key)
        resolved[axis_name] = tuple(
            ResolvedPackagePropertyRow(
                axis=axis_name,
                package=package,
                base_material_key=material_key,
                base_material_name=base_material.name,
                effective_properties=effective_properties(
                    base_material,
                    package,
                    safety_factor=float(safety_factor),
                ),
            )
            for package in catalog.packages_for_axis(axis_name)
        )
    return resolved


def build_default_material_proxy_catalog(path: Path | None = None) -> MaterialProxyCatalog:
    catalog_path = path or _DEFAULT_CATALOG_PATH
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    axes = raw["axes"]

    axis_metadata: dict[str, AxisMetadata] = {}
    axis_packages: dict[str, tuple[MaterialScalePackage, ...]] = {}

    for axis_name, axis_raw in axes.items():
        axis_metadata[axis_name] = AxisMetadata(
            axis=axis_name,
            description=str(axis_raw["description"]),
            integration_mode=str(axis_raw["integration_mode"]),
            promotion_state=str(axis_raw["promotion_state"]),
            default_base_material_key=str(axis_raw["default_base_material_key"]),
        )

        packages: list[MaterialScalePackage] = []
        for pkg_raw in axis_raw["packages"]:
            layup = LayupFractions(
                axial_0=float(pkg_raw["layup_fractions"]["axial_0"]),
                shear_pm45=float(pkg_raw["layup_fractions"]["shear_pm45"]),
                hoop_90=float(pkg_raw["layup_fractions"]["hoop_90"]),
            )
            total = layup.total()
            if total not in (0.0, 1.0):
                if abs(total - 1.0) > 1.0e-9:
                    raise ValueError(
                        f"Package '{pkg_raw['key']}' on axis '{axis_name}' has invalid layup fraction total {total}."
                    )

            buckling_rules = PackageBucklingRules(
                minimum_hoop_fraction=float(pkg_raw["buckling_rules"]["minimum_hoop_fraction"]),
                forbid_outer_pure_axial=bool(pkg_raw["buckling_rules"]["forbid_outer_pure_axial"]),
                conservative_allowable_knockdown=float(
                    pkg_raw["buckling_rules"]["conservative_allowable_knockdown"]
                ),
                allowed_region=str(pkg_raw["buckling_rules"]["allowed_region"]),
                local_buckling_reserve=str(pkg_raw["buckling_rules"]["local_buckling_reserve"]),
                equivalent_gate_credit=str(pkg_raw["buckling_rules"]["equivalent_gate_credit"]),
            )
            if total > 0.0 and layup.hoop_90 + 1.0e-9 < buckling_rules.minimum_hoop_fraction:
                raise ValueError(
                    f"Package '{pkg_raw['key']}' on axis '{axis_name}' violates its minimum hoop fraction rule."
                )

            packages.append(
                MaterialScalePackage(
                    key=str(pkg_raw["key"]),
                    label=str(pkg_raw["label"]),
                    scope=axis_name,
                    young_scale=float(pkg_raw["young_scale"]),
                    shear_scale=float(pkg_raw["shear_scale"]),
                    density_scale=float(pkg_raw["density_scale"]),
                    allowable_scale=float(pkg_raw["allowable_scale"]),
                    description=str(pkg_raw["description"]),
                    family_description=str(pkg_raw["family_description"]),
                    intended_role=str(pkg_raw["intended_role"]),
                    manufacturing_notes=str(pkg_raw["manufacturing_notes"]),
                    buckling_note=str(pkg_raw["buckling_note"]),
                    layup_reference=str(pkg_raw["layup_reference"]),
                    source_material_grade=str(pkg_raw["source_material_grade"]),
                    promotion_state=str(pkg_raw["promotion_state"]),
                    requires_balanced_symmetric=bool(pkg_raw["requires_balanced_symmetric"]),
                    layup_fractions=layup,
                    property_sources=PackagePropertySources(
                        young=str(pkg_raw["property_sources"]["young"]),
                        shear=str(pkg_raw["property_sources"]["shear"]),
                        density=str(pkg_raw["property_sources"]["density"]),
                        allowable=str(pkg_raw["property_sources"]["allowable"]),
                    ),
                    buckling_rules=buckling_rules,
                    overlay_layers_equivalent=(
                        None
                        if pkg_raw.get("overlay_layers_equivalent") is None
                        else float(pkg_raw["overlay_layers_equivalent"])
                    ),
                    overlay_construction=(
                        None
                        if pkg_raw.get("overlay_construction") is None
                        else str(pkg_raw["overlay_construction"])
                    ),
                )
            )
        axis_packages[axis_name] = tuple(packages)

    return MaterialProxyCatalog(
        main_spar_family=axis_packages["main_spar_family"],
        rear_spar_family=axis_packages["rear_spar_family"],
        rear_outboard_reinforcement_pkg=axis_packages["rear_outboard_reinforcement_pkg"],
        axis_metadata=axis_metadata,
    )


__all__ = [
    "AxisMetadata",
    "EffectiveMaterialProperties",
    "LayupFractions",
    "MaterialProxyCatalog",
    "MaterialScalePackage",
    "PackageBucklingRules",
    "PackagePropertySources",
    "ResolvedPackagePropertyRow",
    "build_default_material_proxy_catalog",
    "effective_properties",
    "register_package_material",
    "resolve_catalog_property_rows",
]
