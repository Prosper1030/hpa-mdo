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

    @property
    def is_candidate_ready(self) -> bool:
        return self.promotion_state == "candidate_ready"

    @property
    def recipe_profile(self) -> "PackageRecipeProfile":
        return classify_package_recipe_profile(self)

    @property
    def recipe_family(self) -> "RecipeFamily":
        return self.recipe_profile.family


@dataclass(frozen=True)
class EffectiveMaterialProperties:
    E_eff_pa: float
    G_eff_pa: float
    density_eff_kgpm3: float
    allowable_eff_pa: float


@dataclass(frozen=True)
class RecipeFamily:
    key: str
    label: str
    structural_action: str
    description: str


@dataclass(frozen=True)
class PackageRecipeProfile:
    family: RecipeFamily
    role_key: str
    role_label: str
    usage_notes: str

    @property
    def is_formal_candidate(self) -> bool:
        return self.role_key == "formal_candidate"

    @property
    def is_local_only(self) -> bool:
        return self.role_key == "local_reinforcement_only"


@dataclass(frozen=True)
class ResolvedPackagePropertyRow:
    axis: str
    package: MaterialScalePackage
    lookup_key: str
    recipe_profile: PackageRecipeProfile
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

    def packages_for_recipe_family(
        self,
        family_key: str,
        *,
        role_key: str | None = None,
        promotion_state: str | None = None,
    ) -> tuple[MaterialScalePackage, ...]:
        matches: list[MaterialScalePackage] = []
        for axis_name in ("main_spar_family", "rear_spar_family", "rear_outboard_reinforcement_pkg"):
            for package in self.packages_for_axis(axis_name):
                profile = package.recipe_profile
                if profile.family.key != family_key:
                    continue
                if role_key is not None and profile.role_key != role_key:
                    continue
                if promotion_state is not None and package.promotion_state != promotion_state:
                    continue
                matches.append(package)
        return tuple(matches)


_RECIPE_FAMILIES: Mapping[str, RecipeFamily] = {
    "reference_baseline": RecipeFamily(
        key="reference_baseline",
        label="Reference baseline",
        structural_action="baseline_reference",
        description="Reference package kept for continuity, diffing, and nearby seed comparisons.",
    ),
    "bending_dominant": RecipeFamily(
        key="bending_dominant",
        label="Bending-dominant",
        structural_action="axial_bending_efficiency",
        description="Axial-leaning family that primarily buys bending efficiency and mass reduction.",
    ),
    "balanced_torsion": RecipeFamily(
        key="balanced_torsion",
        label="Balanced torsion",
        structural_action="torsion_shear_balance",
        description="Balanced family that keeps stronger +/-45 or hoop participation for torsion and reserve.",
    ),
    "joint_hoop_rich_local": RecipeFamily(
        key="joint_hoop_rich_local",
        label="Joint / hoop-rich local",
        structural_action="local_joint_and_hoop_reserve",
        description="Local reinforcement family that adds hoop support or sleeve-style reserve near joints/hotspots.",
    ),
}

_PACKAGE_RECIPE_PROFILES: Mapping[tuple[str, str], PackageRecipeProfile] = {
    ("main_spar_family", "main_ref"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["reference_baseline"],
        role_key="reference_only",
        role_label="Reference only",
        usage_notes="Keep as the existing baseline package for diffing and nearby-seed screening.",
    ),
    ("main_spar_family", "main_light_ud"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["bending_dominant"],
        role_key="formal_candidate",
        role_label="Formal candidate",
        usage_notes="Primary global candidate when the selector wants a lighter, axial-biased main spar family.",
    ),
    ("main_spar_family", "main_balanced_hm"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["balanced_torsion"],
        role_key="formal_candidate",
        role_label="Formal candidate",
        usage_notes="Primary global reserve-side candidate when torsion and local stability matter alongside bending.",
    ),
    ("rear_spar_family", "rear_ref"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["reference_baseline"],
        role_key="reference_only",
        role_label="Reference only",
        usage_notes="Keep as the current rear-spar screening anchor, not a formal promotion target.",
    ),
    ("rear_spar_family", "rear_balanced_shear"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["balanced_torsion"],
        role_key="screening_only",
        role_label="Screening only",
        usage_notes="Represents a balanced torsion-oriented rear family but remains outside formal promotion in this wave.",
    ),
    ("rear_spar_family", "rear_toughened_balance"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["balanced_torsion"],
        role_key="screening_only",
        role_label="Screening only",
        usage_notes="Toughened rear reserve family kept only for limited screening until rear-spar promotion is reopened.",
    ),
    ("rear_outboard_reinforcement_pkg", "ob_none"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["reference_baseline"],
        role_key="reference_only",
        role_label="Reference only",
        usage_notes="No added local overlay; preserves the active rear-spar baseline at the outboard segment.",
    ),
    ("rear_outboard_reinforcement_pkg", "ob_light_wrap"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["joint_hoop_rich_local"],
        role_key="local_reinforcement_only",
        role_label="Local reinforcement only",
        usage_notes="Local sleeve/wrap option for rear outboard reserve; do not treat as a global family candidate.",
    ),
    ("rear_outboard_reinforcement_pkg", "ob_balanced_sleeve"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["joint_hoop_rich_local"],
        role_key="local_reinforcement_only",
        role_label="Local reinforcement only",
        usage_notes="Best first-pass joint / hoop-rich local reinforcement option in the current candidate-ready catalog.",
    ),
    ("rear_outboard_reinforcement_pkg", "ob_torsion_patch"): PackageRecipeProfile(
        family=_RECIPE_FAMILIES["balanced_torsion"],
        role_key="local_reinforcement_only",
        role_label="Local reinforcement only",
        usage_notes="Local torsion hotspot patch; keep it in rear outboard non-joint zones rather than global selection.",
    ),
}


def _default_recipe_role(package: MaterialScalePackage) -> tuple[str, str]:
    if package.is_candidate_ready:
        return ("formal_candidate", "Formal candidate")
    return ("screening_only", "Screening only")


def classify_package_recipe_profile(package: MaterialScalePackage) -> PackageRecipeProfile:
    explicit = _PACKAGE_RECIPE_PROFILES.get((package.scope, package.key))
    if explicit is not None:
        return explicit

    role_key, role_label = _default_recipe_role(package)
    layup = package.layup_fractions
    if package.scope == "rear_outboard_reinforcement_pkg":
        if layup.shear_pm45 >= 0.70:
            return PackageRecipeProfile(
                family=_RECIPE_FAMILIES["balanced_torsion"],
                role_key="local_reinforcement_only",
                role_label="Local reinforcement only",
                usage_notes="Fallback classification for local rear-outboard torsion-oriented reinforcement.",
            )
        if layup.hoop_90 >= 0.20:
            return PackageRecipeProfile(
                family=_RECIPE_FAMILIES["joint_hoop_rich_local"],
                role_key="local_reinforcement_only",
                role_label="Local reinforcement only",
                usage_notes="Fallback classification for local rear-outboard sleeve or hoop-rich reinforcement.",
            )
        return PackageRecipeProfile(
            family=_RECIPE_FAMILIES["reference_baseline"],
            role_key="reference_only",
            role_label="Reference only",
            usage_notes="Fallback classification for the no-overlay local baseline.",
        )

    if layup.axial_0 >= 0.65:
        return PackageRecipeProfile(
            family=_RECIPE_FAMILIES["bending_dominant"],
            role_key=role_key,
            role_label=role_label,
            usage_notes="Fallback classification for an axial-biased global family.",
        )
    if layup.shear_pm45 >= 0.45 or layup.hoop_90 >= 0.15:
        return PackageRecipeProfile(
            family=_RECIPE_FAMILIES["balanced_torsion"],
            role_key=role_key,
            role_label=role_label,
            usage_notes="Fallback classification for a balanced torsion-oriented family.",
        )
    return PackageRecipeProfile(
        family=_RECIPE_FAMILIES["reference_baseline"],
        role_key="reference_only",
        role_label="Reference only",
        usage_notes="Fallback classification for a baseline/reference family.",
    )


def _package_lookup_key(axis_name: str, package_key: str) -> str:
    return f"{axis_name}:{package_key}"


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
                lookup_key=_package_lookup_key(axis_name, package.key),
                recipe_profile=package.recipe_profile,
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


def resolve_catalog_lookup_rows(
    *,
    catalog: MaterialProxyCatalog,
    materials_db: MaterialDB,
    axis_base_material_keys: Mapping[str, str] | None = None,
    safety_factor: float,
    axis_name: str | None = None,
    family_key: str | None = None,
    role_key: str | None = None,
    promotion_state: str | None = None,
) -> tuple[ResolvedPackagePropertyRow, ...]:
    resolved = resolve_catalog_property_rows(
        catalog=catalog,
        materials_db=materials_db,
        axis_base_material_keys=axis_base_material_keys,
        safety_factor=safety_factor,
    )
    rows: list[ResolvedPackagePropertyRow] = []
    for current_axis, axis_rows in resolved.items():
        if axis_name is not None and current_axis != axis_name:
            continue
        for row in axis_rows:
            if family_key is not None and row.recipe_profile.family.key != family_key:
                continue
            if role_key is not None and row.recipe_profile.role_key != role_key:
                continue
            if promotion_state is not None and row.package.promotion_state != promotion_state:
                continue
            rows.append(row)
    return tuple(rows)


def build_catalog_lookup_index(
    *,
    catalog: MaterialProxyCatalog,
    materials_db: MaterialDB,
    axis_base_material_keys: Mapping[str, str] | None = None,
    safety_factor: float,
) -> dict[str, ResolvedPackagePropertyRow]:
    return {
        row.lookup_key: row
        for row in resolve_catalog_lookup_rows(
            catalog=catalog,
            materials_db=materials_db,
            axis_base_material_keys=axis_base_material_keys,
            safety_factor=safety_factor,
        )
    }


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
    "build_catalog_lookup_index",
    "EffectiveMaterialProperties",
    "LayupFractions",
    "MaterialProxyCatalog",
    "MaterialScalePackage",
    "PackageBucklingRules",
    "PackagePropertySources",
    "PackageRecipeProfile",
    "RecipeFamily",
    "ResolvedPackagePropertyRow",
    "build_default_material_proxy_catalog",
    "classify_package_recipe_profile",
    "effective_properties",
    "register_package_material",
    "resolve_catalog_lookup_rows",
    "resolve_catalog_property_rows",
]
