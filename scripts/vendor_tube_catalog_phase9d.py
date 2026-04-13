#!/usr/bin/env python3
"""Map Pareto representative designs onto a vendor-aware tube catalog."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402


DEFAULT_BASE_CATALOG = REPO_ROOT / "data" / "carbon_tubes.csv"
DEFAULT_PARETO_SUMMARY = (
    REPO_ROOT / "output" / "pareto_front_phase9c" / "pareto_front_phase9c_summary.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "vendor_tube_catalog_phase9d"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "vendor_tube_catalog_phase9d_report.md"
DEFAULT_OD_GRID_MM = "20,25,30,35,40,45,50,55,60,65,70,80,90,100,110,120"
DEFAULT_WALL_GRID_MM = "1,2,3,4,5"


@dataclass(frozen=True)
class TubeProduct:
    vendor: str
    product: str
    material_key: str
    outer_diameter_mm: float
    inner_diameter_mm: float
    wall_thickness_mm: float
    length_mm: int
    mass_per_meter_kg: float
    price_per_meter_usd: float
    note: str
    hypothetical: bool

    @property
    def stock_length_m(self) -> float:
        return float(self.length_mm) * 1.0e-3

    @property
    def key(self) -> tuple[str, float, float, int]:
        return (
            self.material_key,
            round(float(self.outer_diameter_mm), 6),
            round(float(self.wall_thickness_mm), 6),
            int(self.length_mm),
        )


@dataclass(frozen=True)
class VendorDesignPoint:
    role: str
    layout: str
    dihedral_multiplier: float
    total_mass_kg: float
    ld_ratio: float
    dutch_roll_damping: float
    min_jig_clearance_mm: float | None
    wire_margin_n: float | None
    summary_json_path: str
    source_name: str

    @property
    def label(self) -> str:
        return f"{self.role}: {self.layout} x{self.dihedral_multiplier:.3f}"


@dataclass(frozen=True)
class TubeRequirement:
    design_role: str
    design_label: str
    spar: str
    segment_index: int
    material_key: str
    segment_length_m: float
    full_wing_required_length_m: float
    required_outer_diameter_mm: float
    required_wall_thickness_mm: float
    required_mass_per_meter_kg: float
    continuous_full_wing_mass_kg: float


@dataclass(frozen=True)
class TubeMatch:
    requirement: TubeRequirement
    product: TubeProduct
    procurement_pieces_full_wing: int
    procurement_length_full_wing_m: float
    vendor_full_wing_mass_kg: float
    vendor_full_wing_cost_usd: float
    outer_diameter_margin_mm: float
    wall_margin_mm: float


def _parse_float_list(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Expected at least one numeric value.")
    return values


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def load_tube_products(path: Path) -> tuple[TubeProduct, ...]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    products = [
        TubeProduct(
            vendor=str(row["vendor"]).strip(),
            product=str(row["product"]).strip(),
            material_key=str(row["material_key"]).strip(),
            outer_diameter_mm=float(row["outer_diameter_mm"]),
            inner_diameter_mm=float(row["inner_diameter_mm"]),
            wall_thickness_mm=float(row["wall_thickness_mm"]),
            length_mm=int(float(row["length_mm"])),
            mass_per_meter_kg=float(row["mass_per_meter_kg"]),
            price_per_meter_usd=float(row["price_per_meter_usd"]),
            note=str(row.get("note") or "").strip(),
            hypothetical=False,
        )
        for row in rows
    ]
    return tuple(products)


def synthesize_hypothetical_products(
    *,
    base_products: Iterable[TubeProduct],
    materials_db: MaterialDB,
    material_keys: Iterable[str],
    outer_diameter_grid_mm: Iterable[float],
    wall_thickness_grid_mm: Iterable[float],
    stock_length_mm: int = 3000,
) -> tuple[TubeProduct, ...]:
    existing = {product.key for product in base_products}
    synthetic: list[TubeProduct] = []
    for material_key in sorted(set(str(key) for key in material_keys)):
        density = float(materials_db.get(material_key).density)
        material_tag = material_key.replace("carbon_fiber_", "").upper()
        for od_mm in outer_diameter_grid_mm:
            for wall_mm in wall_thickness_grid_mm:
                if 2.0 * float(wall_mm) >= float(od_mm):
                    continue
                key = (
                    material_key,
                    round(float(od_mm), 6),
                    round(float(wall_mm), 6),
                    int(stock_length_mm),
                )
                if key in existing:
                    continue
                id_mm = float(od_mm) - 2.0 * float(wall_mm)
                area_m2 = 0.25 * math.pi * (
                    (float(od_mm) * 1.0e-3) ** 2 - (float(id_mm) * 1.0e-3) ** 2
                )
                mass_per_meter_kg = density * area_m2
                price_per_meter_usd = round(
                    5.0
                    + 0.70 * float(od_mm)
                    + 10.0 * float(wall_mm)
                    + 10.0 * mass_per_meter_kg,
                    2,
                )
                synthetic.append(
                    TubeProduct(
                        vendor="generic_hypothetical",
                        product=f"CF-{material_tag}-{int(round(float(od_mm)))}x{int(round(id_mm))}",
                        material_key=material_key,
                        outer_diameter_mm=float(od_mm),
                        inner_diameter_mm=float(id_mm),
                        wall_thickness_mm=float(wall_mm),
                        length_mm=int(stock_length_mm),
                        mass_per_meter_kg=float(mass_per_meter_kg),
                        price_per_meter_usd=float(price_per_meter_usd),
                        note="Phase 9d hypothetical infill row derived from material density.",
                        hypothetical=True,
                    )
                )
    return tuple(
        sorted(
            synthetic,
            key=lambda item: (
                item.material_key,
                item.outer_diameter_mm,
                item.wall_thickness_mm,
                item.length_mm,
            ),
        )
    )


def _parse_vendor_point(role: str, payload: dict[str, object]) -> VendorDesignPoint:
    summary_json_path = payload.get("summary_json_path")
    if not summary_json_path:
        raise ValueError(f"Representative '{role}' is missing summary_json_path.")
    return VendorDesignPoint(
        role=role,
        layout=str(payload["layout"]),
        dihedral_multiplier=float(payload["dihedral_multiplier"]),
        total_mass_kg=float(payload["total_mass_kg"]),
        ld_ratio=float(payload["ld_ratio"]),
        dutch_roll_damping=float(payload["dutch_roll_damping"]),
        min_jig_clearance_mm=_safe_float(payload.get("min_jig_clearance_mm")),
        wire_margin_n=_safe_float(payload.get("wire_margin_n")),
        summary_json_path=str(summary_json_path),
        source_name=str(payload["source_name"]),
    )


def load_representative_designs(path: Path) -> tuple[VendorDesignPoint, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    representatives = payload.get("representatives")
    frontier = payload.get("pareto_frontier")
    if not isinstance(representatives, dict):
        raise ValueError("Pareto summary is missing representatives.")
    if not isinstance(frontier, list):
        raise ValueError("Pareto summary is missing pareto_frontier.")

    selected: list[VendorDesignPoint] = []
    for role in ("mass_first", "balanced", "aero_first"):
        rep_payload = representatives.get(role)
        if not isinstance(rep_payload, dict):
            raise ValueError(f"Representative '{role}' missing from Pareto summary.")
        selected.append(_parse_vendor_point(role, rep_payload))

    dual_payload = next(
        (
            item
            for item in frontier
            if isinstance(item, dict) and str(item.get("layout")).strip().lower() == "dual"
        ),
        None,
    )
    if dual_payload is not None:
        selected.append(_parse_vendor_point("dual_anchor", dual_payload))

    deduped: dict[str, VendorDesignPoint] = {}
    for item in selected:
        deduped[item.role] = item
    return tuple(deduped.values())


def _load_selected_design(summary_json_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    payload = json.loads(summary_json_path.read_text(encoding="utf-8"))
    iterations = payload.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        raise ValueError(f"Summary has no iterations: {summary_json_path}")
    selected = iterations[-1].get("selected")
    if not isinstance(selected, dict):
        raise ValueError(f"Summary has no selected design: {summary_json_path}")
    return payload, selected


def build_tube_requirements(
    *,
    design: VendorDesignPoint,
    summary_json_path: Path,
    materials_db: MaterialDB,
) -> tuple[TubeRequirement, ...]:
    summary_payload, selected = _load_selected_design(summary_json_path)
    config_path = Path(str(summary_payload["config"])).expanduser().resolve()
    cfg = load_config(config_path)
    design_mm = selected.get("design_mm")
    if not isinstance(design_mm, dict):
        raise ValueError(f"Selected design is missing design_mm: {summary_json_path}")

    def _build_for_spar(
        spar: str,
        material_key: str,
        segment_lengths_m: Iterable[float],
        radii_mm: Iterable[float],
        thickness_mm: Iterable[float],
    ) -> list[TubeRequirement]:
        density = float(materials_db.get(material_key).density)
        requirements: list[TubeRequirement] = []
        for idx, (segment_length_m, radius_mm, wall_mm) in enumerate(
            zip(segment_lengths_m, radii_mm, thickness_mm, strict=True),
            start=1,
        ):
            od_mm = 2.0 * float(radius_mm)
            area_m2 = math.pi * (
                (float(radius_mm) * 1.0e-3) ** 2
                - max(float(radius_mm) - float(wall_mm), 0.0) ** 2 * 1.0e-6
            )
            required_mass_per_meter_kg = density * area_m2
            full_wing_required_length_m = 2.0 * float(segment_length_m)
            requirements.append(
                TubeRequirement(
                    design_role=design.role,
                    design_label=design.label,
                    spar=spar,
                    segment_index=idx,
                    material_key=material_key,
                    segment_length_m=float(segment_length_m),
                    full_wing_required_length_m=float(full_wing_required_length_m),
                    required_outer_diameter_mm=float(od_mm),
                    required_wall_thickness_mm=float(wall_mm),
                    required_mass_per_meter_kg=float(required_mass_per_meter_kg),
                    continuous_full_wing_mass_kg=float(
                        required_mass_per_meter_kg * full_wing_required_length_m
                    ),
                )
            )
        return requirements

    requirements = _build_for_spar(
        "main",
        str(cfg.main_spar.material),
        cfg.main_spar.segments,
        design_mm["main_r"],
        design_mm["main_t"],
    ) + _build_for_spar(
        "rear",
        str(cfg.rear_spar.material),
        cfg.rear_spar.segments,
        design_mm["rear_r"],
        design_mm["rear_t"],
    )
    return tuple(requirements)


def select_best_vendor_tube(
    requirement: TubeRequirement,
    products: Iterable[TubeProduct],
) -> TubeMatch:
    feasible = [
        product
        for product in products
        if product.material_key == requirement.material_key
        and product.outer_diameter_mm >= requirement.required_outer_diameter_mm - 1.0e-9
        and product.wall_thickness_mm >= requirement.required_wall_thickness_mm - 1.0e-9
        and product.length_mm >= int(math.ceil(requirement.segment_length_m * 1000.0 - 1.0e-9))
    ]
    if not feasible:
        raise ValueError(
            "No vendor product satisfies "
            f"{requirement.design_label} {requirement.spar} seg {requirement.segment_index} "
            f"(OD>={requirement.required_outer_diameter_mm:.3f} mm, "
            f"t>={requirement.required_wall_thickness_mm:.3f} mm)."
        )

    selected = min(
        feasible,
        key=lambda product: (
            product.mass_per_meter_kg,
            product.price_per_meter_usd,
            product.outer_diameter_mm,
            product.wall_thickness_mm,
            product.hypothetical,
        ),
    )
    procurement_pieces_full_wing = int(
        math.ceil(
            requirement.full_wing_required_length_m / max(selected.stock_length_m, 1.0e-12)
            - 1.0e-12
        )
    )
    procurement_length_full_wing_m = procurement_pieces_full_wing * selected.stock_length_m
    vendor_full_wing_mass_kg = selected.mass_per_meter_kg * requirement.full_wing_required_length_m
    vendor_full_wing_cost_usd = (
        selected.price_per_meter_usd * requirement.full_wing_required_length_m
    )
    return TubeMatch(
        requirement=requirement,
        product=selected,
        procurement_pieces_full_wing=procurement_pieces_full_wing,
        procurement_length_full_wing_m=float(procurement_length_full_wing_m),
        vendor_full_wing_mass_kg=float(vendor_full_wing_mass_kg),
        vendor_full_wing_cost_usd=float(vendor_full_wing_cost_usd),
        outer_diameter_margin_mm=float(
            selected.outer_diameter_mm - requirement.required_outer_diameter_mm
        ),
        wall_margin_mm=float(
            selected.wall_thickness_mm - requirement.required_wall_thickness_mm
        ),
    )


def _write_catalog_csv(path: Path, products: Iterable[TubeProduct]) -> None:
    fieldnames = [
        "vendor",
        "product",
        "material_key",
        "outer_diameter_mm",
        "inner_diameter_mm",
        "wall_thickness_mm",
        "length_mm",
        "mass_per_meter_kg",
        "price_per_meter_usd",
        "note",
        "hypothetical",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            writer.writerow(asdict(product))


def _write_match_csv(path: Path, matches: Iterable[TubeMatch]) -> None:
    fieldnames = [
        "design_role",
        "design_label",
        "spar",
        "segment_index",
        "material_key",
        "segment_length_m",
        "full_wing_required_length_m",
        "required_outer_diameter_mm",
        "required_wall_thickness_mm",
        "required_mass_per_meter_kg",
        "continuous_full_wing_mass_kg",
        "vendor",
        "product",
        "hypothetical",
        "selected_outer_diameter_mm",
        "selected_inner_diameter_mm",
        "selected_wall_thickness_mm",
        "selected_length_mm",
        "selected_mass_per_meter_kg",
        "selected_price_per_meter_usd",
        "outer_diameter_margin_mm",
        "wall_margin_mm",
        "procurement_pieces_full_wing",
        "procurement_length_full_wing_m",
        "vendor_full_wing_mass_kg",
        "vendor_full_wing_cost_usd",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            writer.writerow(
                {
                    "design_role": match.requirement.design_role,
                    "design_label": match.requirement.design_label,
                    "spar": match.requirement.spar,
                    "segment_index": match.requirement.segment_index,
                    "material_key": match.requirement.material_key,
                    "segment_length_m": match.requirement.segment_length_m,
                    "full_wing_required_length_m": match.requirement.full_wing_required_length_m,
                    "required_outer_diameter_mm": match.requirement.required_outer_diameter_mm,
                    "required_wall_thickness_mm": match.requirement.required_wall_thickness_mm,
                    "required_mass_per_meter_kg": match.requirement.required_mass_per_meter_kg,
                    "continuous_full_wing_mass_kg": match.requirement.continuous_full_wing_mass_kg,
                    "vendor": match.product.vendor,
                    "product": match.product.product,
                    "hypothetical": match.product.hypothetical,
                    "selected_outer_diameter_mm": match.product.outer_diameter_mm,
                    "selected_inner_diameter_mm": match.product.inner_diameter_mm,
                    "selected_wall_thickness_mm": match.product.wall_thickness_mm,
                    "selected_length_mm": match.product.length_mm,
                    "selected_mass_per_meter_kg": match.product.mass_per_meter_kg,
                    "selected_price_per_meter_usd": match.product.price_per_meter_usd,
                    "outer_diameter_margin_mm": match.outer_diameter_margin_mm,
                    "wall_margin_mm": match.wall_margin_mm,
                    "procurement_pieces_full_wing": match.procurement_pieces_full_wing,
                    "procurement_length_full_wing_m": match.procurement_length_full_wing_m,
                    "vendor_full_wing_mass_kg": match.vendor_full_wing_mass_kg,
                    "vendor_full_wing_cost_usd": match.vendor_full_wing_cost_usd,
                }
            )


def _summarize_design(
    design: VendorDesignPoint,
    matches: Iterable[TubeMatch],
) -> dict[str, object]:
    match_list = list(matches)
    continuous_mass = sum(item.requirement.continuous_full_wing_mass_kg for item in match_list)
    vendor_mass = sum(item.vendor_full_wing_mass_kg for item in match_list)
    vendor_cost = sum(item.vendor_full_wing_cost_usd for item in match_list)
    total_procurement_pieces = sum(item.procurement_pieces_full_wing for item in match_list)
    hypothetical_pieces = sum(1 for item in match_list if item.product.hypothetical)
    return {
        "role": design.role,
        "label": design.label,
        "layout": design.layout,
        "dihedral_multiplier": design.dihedral_multiplier,
        "flight_total_mass_kg": design.total_mass_kg,
        "ld_ratio": design.ld_ratio,
        "dutch_roll_damping": design.dutch_roll_damping,
        "min_jig_clearance_mm": design.min_jig_clearance_mm,
        "wire_margin_n": design.wire_margin_n,
        "tube_continuous_full_wing_mass_kg": float(continuous_mass),
        "tube_vendor_full_wing_mass_kg": float(vendor_mass),
        "tube_vendor_mass_delta_kg": float(vendor_mass - continuous_mass),
        "tube_vendor_mass_delta_pct": (
            None
            if continuous_mass <= 0.0
            else float(100.0 * (vendor_mass - continuous_mass) / continuous_mass)
        ),
        "tube_vendor_cost_usd": float(vendor_cost),
        "procurement_pieces_full_wing": int(total_procurement_pieces),
        "hypothetical_segments": int(hypothetical_pieces),
    }


def build_report(
    *,
    catalog_path: Path,
    base_product_count: int,
    synthetic_product_count: int,
    design_summaries: Iterable[dict[str, object]],
    matches: Iterable[TubeMatch],
) -> str:
    design_list = list(design_summaries)
    match_list = list(matches)
    lines: list[str] = []
    lines.append("# Phase 9d Vendor-Aware Tube Catalog Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "- Starting from the existing `data/carbon_tubes.csv` seed catalog, Phase 9d augments missing SKUs with explicitly flagged hypothetical generic vendor rows so that the current Pareto representatives can all be discretized."
    )
    lines.append(
        f"- Catalog used for this run: `{catalog_path}` ({base_product_count} base rows + {synthetic_product_count} hypothetical infill rows)."
    )
    lines.append(
        "- Selection rule: same material key, conservative snap-up on OD and wall thickness, then minimize vendor mass per meter, then vendor cost."
    )
    lines.append("")
    lines.append("## Design Summary")
    lines.append("")
    lines.append(
        "| Role | Layout | Mult | Flight Mass (kg) | Tube Mass Cont. (kg) | Tube Mass Vendor (kg) | Delta (kg) | Delta (%) | Tube Cost (USD) | Clearance (mm) | Wire Margin (N) |"
    )
    lines.append(
        "|------|--------|------|------------------|-----------------------|------------------------|------------|-----------|-----------------|----------------|-----------------|"
    )
    for item in design_list:
        clearance = item["min_jig_clearance_mm"]
        wire_margin = item["wire_margin_n"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["role"]),
                    str(item["layout"]),
                    f"{float(item['dihedral_multiplier']):.3f}",
                    f"{float(item['flight_total_mass_kg']):.3f}",
                    f"{float(item['tube_continuous_full_wing_mass_kg']):.3f}",
                    f"{float(item['tube_vendor_full_wing_mass_kg']):.3f}",
                    f"{float(item['tube_vendor_mass_delta_kg']):+.3f}",
                    f"{float(item['tube_vendor_mass_delta_pct']):+.2f}",
                    f"{float(item['tube_vendor_cost_usd']):.1f}",
                    "n/a" if clearance is None else f"{float(clearance):.3f}",
                    "n/a" if wire_margin is None else f"{float(wire_margin):.1f}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Segment Selections")
    lines.append("")
    lines.append(
        "| Role | Spar | Seg | Req OD (mm) | Req t (mm) | Selected SKU | Selected OD x t (mm) | Hypothetical | Margin OD / t (mm) | Full-Wing Qty | Full-Wing Cost (USD) |"
    )
    lines.append(
        "|------|------|-----|-------------|------------|--------------|----------------------|--------------|--------------------|---------------|----------------------|"
    )
    for match in match_list:
        lines.append(
            "| "
            + " | ".join(
                [
                    match.requirement.design_role,
                    match.requirement.spar,
                    str(match.requirement.segment_index),
                    f"{match.requirement.required_outer_diameter_mm:.3f}",
                    f"{match.requirement.required_wall_thickness_mm:.3f}",
                    match.product.product,
                    f"{match.product.outer_diameter_mm:.1f} x {match.product.wall_thickness_mm:.1f}",
                    "yes" if match.product.hypothetical else "no",
                    f"{match.outer_diameter_margin_mm:+.3f} / {match.wall_margin_mm:+.3f}",
                    str(match.procurement_pieces_full_wing),
                    f"{match.vendor_full_wing_cost_usd:.1f}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if design_list:
        lowest_delta = min(design_list, key=lambda item: abs(float(item["tube_vendor_mass_delta_kg"])))
        cheapest = min(design_list, key=lambda item: float(item["tube_vendor_cost_usd"]))
        heaviest_penalty = max(design_list, key=lambda item: float(item["tube_vendor_mass_delta_kg"]))
        lines.append(
            f"- The smallest catalog discretization penalty is `{lowest_delta['role']}` at {float(lowest_delta['tube_vendor_mass_delta_kg']):+.3f} kg versus the continuous tube ideal."
        )
        lines.append(
            f"- The cheapest full-wing tube BOM is `{cheapest['role']}` at {float(cheapest['tube_vendor_cost_usd']):.1f} USD."
        )
        lines.append(
            f"- The largest vendor penalty appears on `{heaviest_penalty['role']}` at {float(heaviest_penalty['tube_vendor_mass_delta_kg']):+.3f} kg, which is the main warning sign if we later tighten the catalog to real SKUs."
        )
    lines.append(
        "- Hypothetical rows are concentrated in the smaller / thicker tubes that the current seed catalog does not cover, especially rear-spar heavy-wall segments and the 65-70 mm main-spar plateau region."
    )
    lines.append(
        "- This means the Phase 9 mainline can now reason about procurement-level discreteness without blocking on a real vendor scrape, while keeping every synthetic SKU explicitly traceable."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Phase 9d vendor-aware tube catalog mapping."
    )
    parser.add_argument("--base-catalog", default=str(DEFAULT_BASE_CATALOG))
    parser.add_argument("--pareto-summary", default=str(DEFAULT_PARETO_SUMMARY))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--od-grid-mm", default=DEFAULT_OD_GRID_MM)
    parser.add_argument("--wall-grid-mm", default=DEFAULT_WALL_GRID_MM)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    base_catalog_path = Path(args.base_catalog).expanduser().resolve()
    pareto_summary_path = Path(args.pareto_summary).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    materials_db = MaterialDB()
    base_products = load_tube_products(base_catalog_path)
    representative_designs = load_representative_designs(pareto_summary_path)

    all_requirements: list[TubeRequirement] = []
    used_materials: set[str] = set()
    for design in representative_designs:
        summary_json_path = Path(design.summary_json_path).expanduser().resolve()
        requirements = build_tube_requirements(
            design=design,
            summary_json_path=summary_json_path,
            materials_db=materials_db,
        )
        all_requirements.extend(requirements)
        used_materials.update(req.material_key for req in requirements)

    synthetic_products = synthesize_hypothetical_products(
        base_products=base_products,
        materials_db=materials_db,
        material_keys=used_materials,
        outer_diameter_grid_mm=_parse_float_list(args.od_grid_mm),
        wall_thickness_grid_mm=_parse_float_list(args.wall_grid_mm),
    )
    full_catalog = tuple(base_products) + tuple(synthetic_products)

    matches = tuple(
        select_best_vendor_tube(requirement, full_catalog)
        for requirement in all_requirements
    )
    grouped: dict[str, list[TubeMatch]] = {design.role: [] for design in representative_designs}
    for match in matches:
        grouped.setdefault(match.requirement.design_role, []).append(match)
    design_summaries = [
        _summarize_design(design, grouped.get(design.role, ()))
        for design in representative_designs
    ]

    catalog_output_path = output_dir / "hypothetical_vendor_catalog.csv"
    match_csv_path = output_dir / "vendor_tube_catalog_phase9d_segments.csv"
    summary_json_path = output_dir / "vendor_tube_catalog_phase9d_summary.json"
    _write_catalog_csv(catalog_output_path, full_catalog)
    _write_match_csv(match_csv_path, matches)
    summary_json_path.write_text(
        json.dumps(
            {
                "base_catalog_path": str(base_catalog_path),
                "pareto_summary_path": str(pareto_summary_path),
                "catalog_output_path": str(catalog_output_path),
                "base_product_count": len(base_products),
                "synthetic_product_count": len(synthetic_products),
                "design_summaries": design_summaries,
                "segment_matches": [
                    {
                        "requirement": asdict(match.requirement),
                        "product": asdict(match.product),
                        "procurement_pieces_full_wing": match.procurement_pieces_full_wing,
                        "procurement_length_full_wing_m": match.procurement_length_full_wing_m,
                        "vendor_full_wing_mass_kg": match.vendor_full_wing_mass_kg,
                        "vendor_full_wing_cost_usd": match.vendor_full_wing_cost_usd,
                        "outer_diameter_margin_mm": match.outer_diameter_margin_mm,
                        "wall_margin_mm": match.wall_margin_mm,
                    }
                    for match in matches
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        build_report(
            catalog_path=catalog_output_path,
            base_product_count=len(base_products),
            synthetic_product_count=len(synthetic_products),
            design_summaries=design_summaries,
            matches=matches,
        ),
        encoding="utf-8",
    )

    print(f"Wrote catalog : {catalog_output_path}")
    print(f"Wrote matches : {match_csv_path}")
    print(f"Wrote summary : {summary_json_path}")
    print(f"Wrote report  : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
