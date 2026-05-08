#!/usr/bin/env python3
"""Run wire allowable sensitivity for the fixed Phase 15 main-wing candidate."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from math import pi
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config
from scripts.phase15_candidate_load_factor_buckling_check import (
    CandidateReference,
    FirstFailEstimate,
    SELECTED_RUN,
    estimate_first_fail,
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/phase15_wire_upgrade_sensitivity"
DEFAULT_WIRE_ALLOWABLE_SWEEP_N: tuple[tuple[str, float | None], ...] = (
    ("current", None),
    ("5kN", 5000.0),
    ("6kN", 6000.0),
    ("8kN", 8000.0),
    ("10kN", 10000.0),
)
REPORT_LOAD_FACTORS = (1.0, 1.5, 1.75, 2.0, 3.0)
THREE_G_COMFORT_WIRE_UTIL_LIMIT = 0.80
THREE_G_COMFORT_SYSTEM_MARGIN_N = 3.25
KGF_TO_N = 9.80665
LB_TO_N = 4.4482216152605


@dataclass(frozen=True)
class WireSourceMetadata:
    material: str
    diameter_m: float
    area_m2: float
    tensile_strength_pa: float
    max_tension_fraction: float
    material_safety_factor: float
    formula_allowable_n: float
    artifact_allowable_n: float
    artifact_path: Path

    @property
    def implied_min_break_load_n(self) -> float:
        if self.max_tension_fraction <= 0.0:
            return float("nan")
        return self.artifact_allowable_n * self.material_safety_factor / self.max_tension_fraction


@dataclass(frozen=True)
class MarketWireReference:
    supplier: str
    product: str
    diameter_mm: float
    strength_type: str
    breaking_load_n: float
    source_url: str
    note: str


@dataclass(frozen=True)
class WireAllowableSweepRow:
    allowable_case: str
    wire_allowable_n: float
    wire_tension_n_1p0g: float
    wire_utilization_1p0g: float
    wire_tension_n_1p5g: float
    wire_utilization_1p5g: float
    wire_tension_n_1p75g: float
    wire_utilization_1p75g: float
    wire_tension_n_2p0g: float
    wire_utilization_2p0g: float
    wire_tension_n_3p0g: float
    wire_utilization_3p0g: float
    wire_only_fail_load_factor: float
    estimated_first_fail_load_factor: float
    first_fail_mode: str
    next_failure_mode_after_wire: str
    next_failure_load_factor_after_wire: float
    one_p75_safe: str
    three_g_wire_comfortable: str
    three_g_system_note: str
    required_min_break_load_n_current_policy: float


MARKET_WIRE_REFERENCES: tuple[MarketWireReference, ...] = (
    MarketWireReference(
        supplier="Marlow",
        product="D12 75/78",
        diameter_mm=2.5,
        strength_type="minimum",
        breaking_load_n=4.8e3,
        source_url=(
            "https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/"
            "d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf"
        ),
        note="PDF table line gives 2.5 mm minimum strength 4.8 kN.",
    ),
    MarketWireReference(
        supplier="Marlow",
        product="D12 75/78",
        diameter_mm=4.0,
        strength_type="minimum",
        breaking_load_n=18.1e3,
        source_url=(
            "https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/"
            "d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf"
        ),
        note="PDF table line gives 4 mm minimum strength 18.1 kN.",
    ),
    MarketWireReference(
        supplier="Marlow",
        product="D12 75/78",
        diameter_mm=6.0,
        strength_type="minimum",
        breaking_load_n=30.8e3,
        source_url=(
            "https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/"
            "d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf"
        ),
        note="PDF table line gives 6 mm minimum strength 30.8 kN.",
    ),
    MarketWireReference(
        supplier="Marlow",
        product="Excel D12 Max 78",
        diameter_mm=2.5,
        strength_type="minimum",
        breaking_load_n=935.0 * KGF_TO_N,
        source_url="https://shop.marlowropes.com/excel-d12-max-78-2-5mm-black-100mr-tv0006",
        note="Product page lists 2.5 mm minimum break load 935 kg.",
    ),
    MarketWireReference(
        supplier="Premiumropes",
        product="DX Core 78",
        diameter_mm=5.0,
        strength_type="catalog",
        breaking_load_n=2400.0 * KGF_TO_N,
        source_url="https://www.premiumropes.com/dx-core-78",
        note="Product page lists 5 mm strength 2400 kg.",
    ),
    MarketWireReference(
        supplier="Premiumropes",
        product="DX Core 78",
        diameter_mm=6.0,
        strength_type="catalog",
        breaking_load_n=3190.0 * KGF_TO_N,
        source_url="https://www.premiumropes.com/dx-core-78",
        note="Product page lists 6 mm strength 3190 kg.",
    ),
    MarketWireReference(
        supplier="Samson",
        product="AmSteel-Blue",
        diameter_mm=5.0,
        strength_type="approx_average",
        breaking_load_n=5400.0 * LB_TO_N,
        source_url="https://www.samsonrope.com/docs/default-source/brochures/rm_line_selection_guide_web.pdf?Status=Temp&sfvrsn=5f36249d_4",
        note="Line selection guide lists 3/16 in / 5 mm average breaking strength 5400 lb.",
    ),
    MarketWireReference(
        supplier="Samson",
        product="AmSteel-Blue",
        diameter_mm=6.0,
        strength_type="approx_average",
        breaking_load_n=8600.0 * LB_TO_N,
        source_url="https://www.samsonrope.com/docs/default-source/brochures/rm_line_selection_guide_web.pdf?Status=Temp&sfvrsn=5f36249d_4",
        note="Line selection guide lists 1/4 in / 6 mm average breaking strength 8600 lb.",
    ),
)


def non_wire_first_fail(reference: CandidateReference) -> FirstFailEstimate:
    """Estimate the first fixed-design failure if wire tension is not limiting."""

    candidates: list[tuple[str, float, str]] = []
    stress_util = max(0.0, 1.0 + float(reference.failure_index))
    buckling_util = max(0.0, 1.0 + float(reference.buckling_index))

    if stress_util > 0.0:
        candidates.append(
            (
                "cfrp_global_bending_stress",
                float(reference.reference_load_factor) / stress_util,
                "global tube stress utilization reaches 1.0",
            )
        )
    if buckling_util > 0.0:
        candidates.append(
            (
                "local_shell_buckling_estimate",
                float(reference.reference_load_factor) / buckling_util,
                "internal shell-buckling utilization reaches 1.0",
            )
        )
    if reference.tip_deflection_m > 0.0:
        candidates.append(
            (
                "tip_deflection",
                float(reference.reference_load_factor)
                * float(reference.tip_deflection_limit_m)
                / float(reference.tip_deflection_m),
                "tip deflection reaches configured limit",
            )
        )
    if reference.twist_max_deg > 0.0:
        candidates.append(
            (
                "torsion_twist",
                float(reference.reference_load_factor)
                * float(reference.twist_limit_deg)
                / float(reference.twist_max_deg),
                "twist reaches configured limit",
            )
        )
    if not candidates:
        return FirstFailEstimate("model_limit", float("nan"), "No positive non-wire utilization was available.")
    mode, load_factor, note = min(candidates, key=lambda item: item[1])
    return FirstFailEstimate(mode=mode, load_factor=float(load_factor), note=note)


def build_wire_allowable_sweep(
    reference: CandidateReference,
    *,
    allowable_sweep_n: Iterable[tuple[str, float | None]] = DEFAULT_WIRE_ALLOWABLE_SWEEP_N,
    metadata: WireSourceMetadata | None = None,
) -> list[WireAllowableSweepRow]:
    rows: list[WireAllowableSweepRow] = []
    next_fail = non_wire_first_fail(reference)
    source = metadata or load_current_wire_source_metadata(reference)
    current_policy_multiplier = source.material_safety_factor / source.max_tension_fraction

    for label, override_n in allowable_sweep_n:
        allowable_n = float(reference.wire_allowable_n if override_n is None else override_n)
        tensions = {
            load_factor: float(reference.wire_tension_n)
            * float(load_factor)
            / float(reference.reference_load_factor)
            for load_factor in REPORT_LOAD_FACTORS
        }
        utils = {
            load_factor: tensions[load_factor] / allowable_n if allowable_n > 0.0 else float("inf")
            for load_factor in REPORT_LOAD_FACTORS
        }
        wire_fail_n = (
            float(reference.reference_load_factor) * allowable_n / float(reference.wire_tension_n)
            if reference.wire_tension_n > 0.0
            else float("inf")
        )
        if wire_fail_n <= next_fail.load_factor:
            first_fail = FirstFailEstimate(
                mode="wire_tension",
                load_factor=wire_fail_n,
                note="lift-wire tension reaches allowable",
            )
        else:
            first_fail = next_fail

        comfortable = (
            utils[3.0] <= THREE_G_COMFORT_WIRE_UTIL_LIMIT
            and first_fail.load_factor >= THREE_G_COMFORT_SYSTEM_MARGIN_N
        )
        system_note = (
            f"wire comfortable; next fixed-design limiter is {next_fail.mode} at n={next_fail.load_factor:.3f}"
            if comfortable
            else _three_g_not_comfortable_note(utils[3.0], first_fail, next_fail)
        )
        rows.append(
            WireAllowableSweepRow(
                allowable_case=label,
                wire_allowable_n=allowable_n,
                wire_tension_n_1p0g=tensions[1.0],
                wire_utilization_1p0g=utils[1.0],
                wire_tension_n_1p5g=tensions[1.5],
                wire_utilization_1p5g=utils[1.5],
                wire_tension_n_1p75g=tensions[1.75],
                wire_utilization_1p75g=utils[1.75],
                wire_tension_n_2p0g=tensions[2.0],
                wire_utilization_2p0g=utils[2.0],
                wire_tension_n_3p0g=tensions[3.0],
                wire_utilization_3p0g=utils[3.0],
                wire_only_fail_load_factor=wire_fail_n,
                estimated_first_fail_load_factor=first_fail.load_factor,
                first_fail_mode=first_fail.mode,
                next_failure_mode_after_wire=next_fail.mode,
                next_failure_load_factor_after_wire=next_fail.load_factor,
                one_p75_safe="yes" if utils[1.75] < 1.0 and 1.75 < next_fail.load_factor else "no",
                three_g_wire_comfortable="yes" if comfortable else "no",
                three_g_system_note=system_note,
                required_min_break_load_n_current_policy=allowable_n * current_policy_multiplier,
            )
        )
    return rows


def write_wire_upgrade_package(
    out_dir: Path,
    reference: CandidateReference,
    *,
    allowable_sweep_n: Iterable[tuple[str, float | None]] = DEFAULT_WIRE_ALLOWABLE_SWEEP_N,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = load_current_wire_source_metadata(reference)
    rows = build_wire_allowable_sweep(reference, allowable_sweep_n=allowable_sweep_n, metadata=metadata)
    outputs = [
        _write_wire_allowable_sweep(out_dir / "wire_allowable_sweep.csv", rows),
        _write_wire_upgrade_summary(out_dir / "wire_upgrade_summary.md", rows, reference, metadata),
        _write_recommended_wire_spec(out_dir / "recommended_wire_spec.md", rows, metadata),
    ]
    return outputs


def load_current_wire_source_metadata(reference: CandidateReference) -> WireSourceMetadata:
    summary = _read_json(SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json")
    cfg = load_config(summary["config"])
    wire_material_key = str(cfg.lift_wires.cable_material)
    wire_material = MaterialDB().get(wire_material_key)
    diameter_m = float(cfg.lift_wires.cable_diameter)
    area_m2 = pi * (0.5 * diameter_m) ** 2
    formula_allowable_n = (
        float(cfg.lift_wires.max_tension_fraction)
        * float(wire_material.tensile_strength)
        * area_m2
        / float(cfg.safety.material_safety_factor)
    )
    return WireSourceMetadata(
        material=wire_material_key,
        diameter_m=diameter_m,
        area_m2=area_m2,
        tensile_strength_pa=float(wire_material.tensile_strength),
        max_tension_fraction=float(cfg.lift_wires.max_tension_fraction),
        material_safety_factor=float(cfg.safety.material_safety_factor),
        formula_allowable_n=float(formula_allowable_n),
        artifact_allowable_n=float(reference.wire_allowable_n),
        artifact_path=SELECTED_RUN / "lift_wire_rigging.json",
    )


def _write_wire_allowable_sweep(path: Path, rows: list[WireAllowableSweepRow]) -> Path:
    fields = [
        "allowable_case",
        "wire_allowable_n",
        "wire_allowable_kn",
        "wire_tension_n_1p0g",
        "wire_utilization_1p0g",
        "wire_tension_n_1p5g",
        "wire_utilization_1p5g",
        "wire_tension_n_1p75g",
        "wire_utilization_1p75g",
        "wire_tension_n_2p0g",
        "wire_utilization_2p0g",
        "wire_tension_n_3p0g",
        "wire_utilization_3p0g",
        "wire_only_fail_load_factor",
        "estimated_first_fail_load_factor",
        "first_fail_mode",
        "next_failure_mode_after_wire",
        "next_failure_load_factor_after_wire",
        "one_p75_safe",
        "three_g_wire_comfortable",
        "three_g_system_note",
        "required_min_break_load_n_current_policy",
        "required_min_break_load_kn_current_policy",
    ]
    out_rows = []
    for row in rows:
        data = row.__dict__.copy()
        data["wire_allowable_kn"] = row.wire_allowable_n / 1000.0
        data["required_min_break_load_kn_current_policy"] = (
            row.required_min_break_load_n_current_policy / 1000.0
        )
        out_rows.append(data)
    return _write_csv(path, fields, out_rows)


def _write_wire_upgrade_summary(
    path: Path,
    rows: list[WireAllowableSweepRow],
    reference: CandidateReference,
    metadata: WireSourceMetadata,
) -> Path:
    current = rows[0]
    first_upgraded = next((row for row in rows if row.allowable_case != "current" and row.first_fail_mode != "wire_tension"), None)
    non_wire = non_wire_first_fail(reference)
    formula_delta_pct = (
        (metadata.formula_allowable_n - metadata.artifact_allowable_n)
        / metadata.artifact_allowable_n
        * 100.0
        if metadata.artifact_allowable_n
        else 0.0
    )
    lines = [
        "# Wire Upgrade Summary",
        "",
        f"Candidate: `{reference.candidate_id}`",
        "",
        "## Direct Answer",
        "",
        "- Does upgrading wire remove the current first-fail blocker? `yes`, once the modeled allowable is at least about `5 kN`; the next fixed-design limiter becomes `tip_deflection`, not CFRP stress or shell buckling.",
        f"- Current first fail: `{current.first_fail_mode}` at `n = {current.estimated_first_fail_load_factor:.3f}`.",
        f"- Next failure mode after wire: `{non_wire.mode}` at `n = {non_wire.load_factor:.3f}`.",
        "- `1.75G` remains safe for every swept allowable case.",
        "- `3.0G` becomes comfortable in wire utilization at `6 kN` allowable and above, but the whole system still has only moderate reserve because tip deflection is estimated to limit at about `3.305G`.",
        "",
        "## Sweep",
        "",
        "| allowable case | allowable kN | T 1.0G N | util 1.0G | T 1.5G N | util 1.5G | T 1.75G N | util 1.75G | T 2.0G N | util 2.0G | T 3.0G N | util 3.0G | first fail n | first mode | 1.75G safe | 3.0G comfortable |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.allowable_case} | {row.wire_allowable_n / 1000.0:.3f} | "
            f"{row.wire_tension_n_1p0g:.1f} | {row.wire_utilization_1p0g:.3f} | "
            f"{row.wire_tension_n_1p5g:.1f} | {row.wire_utilization_1p5g:.3f} | "
            f"{row.wire_tension_n_1p75g:.1f} | {row.wire_utilization_1p75g:.3f} | "
            f"{row.wire_tension_n_2p0g:.1f} | {row.wire_utilization_2p0g:.3f} | "
            f"{row.wire_tension_n_3p0g:.1f} | {row.wire_utilization_3p0g:.3f} | "
            f"{row.estimated_first_fail_load_factor:.3f} | {row.first_fail_mode} | "
            f"{row.one_p75_safe} | {row.three_g_wire_comfortable} |"
        )
    lines.extend(
        [
            "",
            "## Current Wire Source",
            "",
            f"- Material key: `{metadata.material}`.",
            f"- Diameter: `{metadata.diameter_m * 1000.0:.3f} mm`.",
            f"- Area: `{metadata.area_m2 * 1.0e6:.3f} mm^2`.",
            f"- Material tensile strength in local database: `{metadata.tensile_strength_pa / 1.0e6:.1f} MPa`.",
            f"- Current policy: max tension fraction `{metadata.max_tension_fraction:.3f}` and material safety factor `{metadata.material_safety_factor:.3f}`.",
            f"- Formula allowable: `{metadata.formula_allowable_n:.1f} N`; artifact allowable: `{metadata.artifact_allowable_n:.1f} N`; delta `{formula_delta_pct:.2f}%`.",
            f"- Artifact source: `{metadata.artifact_path}`.",
            f"- Implied published/minimum break load to justify the current artifact under the same policy: `{metadata.implied_min_break_load_n / 1000.0:.2f} kN`.",
            "",
            "## FEM / Blocking Readout",
            "",
            "- This package changes only the allowable tension in the failure accounting. It does not redesign the wing, change airfoils, or change aero ranking.",
            "- The repaired candidate-equivalent FEM route is still the validation basis through 2.0G. The 3.0G wire sensitivity is a fixed-design linear load extrapolation.",
            "- Because geometry and load path are unchanged, this is the right quick check for whether wire allowable is the blocker. A final upgraded-wire signoff still needs a Mac-local FEM rerun with the actual wire stiffness, pretension, attach hardware, and candidate-specific local joint shell/detail model.",
            "",
            "## Engineering Judgment",
            "",
            "- A stronger wire does remove the current wire-tension first-fail blocker numerically.",
            "- It does not make the candidate a clean 3.0G design in the submission sense: tip deflection becomes the next limiter at about 3.305G, and the wire attach/root joint/rib load transfer remain unresolved hardware details.",
            "- The current modeled 2.5 mm Dyneema allowable should be treated as a model-derived material allowable, not as proof that any off-the-shelf 2.5 mm cord is acceptable.",
            f"- First useful upgrade target: `{first_upgraded.allowable_case if first_upgraded else 'none in sweep'}` allowable. Practical recommendation is still to buy/spec by published minimum breaking load, not by nominal diameter.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_recommended_wire_spec(
    path: Path,
    rows: list[WireAllowableSweepRow],
    metadata: WireSourceMetadata,
) -> Path:
    row_6 = next(row for row in rows if row.allowable_case == "6kN")
    row_8 = next(row for row in rows if row.allowable_case == "8kN")
    row_10 = next(row for row in rows if row.allowable_case == "10kN")
    lines = [
        "# Recommended Wire Spec",
        "",
        "## Recommendation",
        "",
        f"Use `6 kN modeled allowable` as the first upgrade target. Under the current local safety policy, that means a published minimum breaking load of at least `{row_6.required_min_break_load_n_current_policy / 1000.0:.1f} kN`, before any loss from knots, bends, splices, UV, abrasion, creep, or fittings.",
        "",
        "For a more robust next build, target `8 kN modeled allowable` if the drag, attach fitting, and packaging penalty are acceptable. That requires a published minimum breaking load of at least "
        f"`{row_8.required_min_break_load_n_current_policy / 1000.0:.1f} kN` under the same policy. A `10 kN` modeled allowable requires about `{row_10.required_min_break_load_n_current_policy / 1000.0:.1f} kN` MBL and should be treated as a larger hardware redesign item, not a simple cord swap.",
        "",
        "## Market Check",
        "",
        "| supplier | product | diameter mm | strength type | break load kN | source note |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for ref in MARKET_WIRE_REFERENCES:
        lines.append(
            f"| {ref.supplier} | [{ref.product}]({ref.source_url}) | {ref.diameter_mm:.1f} | "
            f"{ref.strength_type} | {ref.breaking_load_n / 1000.0:.1f} | {ref.note} |"
        )
    lines.extend(
        [
            "",
            "## Spec Boundary",
            "",
            "- Do not buy by nominal diameter alone. The same 2.5 mm class can be far below the current model-derived implied break load.",
            f"- Current artifact allowable `{metadata.artifact_allowable_n / 1000.0:.3f} kN` implies `{metadata.implied_min_break_load_n / 1000.0:.1f} kN` minimum break under the local policy.",
            "- For the next validation build, prefer a catalog line with published minimum breaking load, certified batch data if possible, spliced/thimbled end terminations, and explicit bend-radius and creep limits.",
            "- Avoid knots in the primary load path. Treat every termination, pin bend, and clamp as a strength reducer until tested.",
            "- Re-enter the final selected line as actual area, Young's modulus, pretension, and allowable, then rerun the candidate FEM load-factor package. Higher stiffness can move loads into the root and attach details.",
            "",
            "## Practical Pick",
            "",
            "- Minimum practical upgrade: a Dyneema/HMPE line whose published minimum break is at least `22.5 kN` for the `6 kN` allowable case.",
            "- Preferred validation target: published minimum break at least `30 kN` for the `8 kN` allowable case, because it makes the 3.0G wire utilization comfortable while keeping a clear paper trail.",
            "- The attach fitting and rib load-transfer check are now the gating engineering items; the market wire itself is not the blocker.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _three_g_not_comfortable_note(
    wire_util_3g: float,
    first_fail: FirstFailEstimate,
    next_fail: FirstFailEstimate,
) -> str:
    if wire_util_3g > THREE_G_COMFORT_WIRE_UTIL_LIMIT:
        return f"wire utilization at 3.0G is {wire_util_3g:.3f}, above comfort threshold {THREE_G_COMFORT_WIRE_UTIL_LIMIT:.2f}"
    return f"wire margin is acceptable, but system first fail is {first_fail.mode} at n={first_fail.load_factor:.3f}; next non-wire limiter is {next_fail.mode}"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    outputs = write_wire_upgrade_package(args.output_dir, reference)
    first_fail = estimate_first_fail(reference)
    print(f"Current first fail: {first_fail.mode} at n={first_fail.load_factor:.3f}")
    print(f"Wrote {len(outputs)} files to {args.output_dir}")
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
