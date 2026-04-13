#!/usr/bin/env python3
"""Convert continuous inverse-design wall thicknesses into discrete ply layups."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from hpa_mdo.utils.discrete_layup import (  # noqa: E402
    build_segment_layup_results,
    enumerate_valid_stacks,
    format_layup_report,
    summarize_layup_results,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to inverse-design summary JSON.",
    )
    parser.add_argument(
        "--ply-material",
        type=str,
        default=None,
        help="Optional override for the ply material key in data/materials.yaml.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to the human-readable layup report (.txt).",
    )
    parser.add_argument(
        "--ply-drop-limit",
        type=int,
        default=2,
        help="Maximum allowed ply-count drop between adjacent segments.",
    )
    return parser.parse_args()


def _load_selected_design(summary_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    iterations = payload.get("iterations")
    if isinstance(iterations, list) and iterations:
        selected = iterations[-1].get("selected")
        if isinstance(selected, dict):
            return payload, selected

    outcome = payload.get("outcome")
    if isinstance(outcome, dict):
        selected = outcome.get("selected")
        if isinstance(selected, dict):
            return payload, selected

    raise ValueError(f"Could not find a selected design in summary: {summary_path}")


def _build_for_spar(
    *,
    label: str,
    spar_cfg,
    segment_lengths_m: list[float],
    radii_mm: list[float],
    thickness_mm: list[float],
    ply_material_key: str,
    materials_db: MaterialDB,
    ply_drop_limit: int,
) -> tuple[str, dict[str, object]]:
    if not radii_mm or not thickness_mm:
        raise ValueError(f"{label} summary is missing radii or thickness arrays.")
    if len(radii_mm) != len(thickness_mm) or len(radii_mm) != len(segment_lengths_m):
        raise ValueError(f"{label} segment array lengths do not match the config definition.")

    ply_mat = materials_db.get_ply(ply_material_key)
    stacks = enumerate_valid_stacks(spar_cfg)
    results = build_segment_layup_results(
        segment_lengths_m=segment_lengths_m,
        continuous_thicknesses_m=[float(value) * 1.0e-3 for value in thickness_mm],
        outer_radii_m=[float(value) * 1.0e-3 for value in radii_mm],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=ply_drop_limit,
    )
    return ply_material_key, {
        "report": format_layup_report(results, ply_mat),
        "summary": summarize_layup_results(results),
    }


def main() -> int:
    args = _parse_args()
    summary_path = args.summary.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path = output_path.with_name("layup_schedule.json")

    payload, selected = _load_selected_design(summary_path)
    config_path = Path(str(payload["config"])).expanduser().resolve()
    cfg = load_config(config_path)
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")

    design_mm = selected.get("design_mm")
    if not isinstance(design_mm, dict):
        raise ValueError(f"Selected design is missing design_mm: {summary_path}")

    main_ply_material = args.ply_material or cfg.main_spar.ply_material
    if main_ply_material is None:
        raise ValueError("No ply material was provided and config.main_spar.ply_material is empty.")

    sections: dict[str, dict[str, object]] = {}
    _, main_section = _build_for_spar(
        label="main_spar",
        spar_cfg=cfg.main_spar,
        segment_lengths_m=list(cfg.spar_segment_lengths(cfg.main_spar)),
        radii_mm=[float(value) for value in design_mm["main_r"]],
        thickness_mm=[float(value) for value in design_mm["main_t"]],
        ply_material_key=str(main_ply_material),
        materials_db=materials_db,
        ply_drop_limit=int(args.ply_drop_limit),
    )
    sections["main_spar"] = main_section

    rear_r = design_mm.get("rear_r")
    rear_t = design_mm.get("rear_t")
    if cfg.rear_spar.enabled and isinstance(rear_r, list) and isinstance(rear_t, list) and rear_r and rear_t:
        rear_ply_material = args.ply_material or cfg.rear_spar.ply_material or main_ply_material
        _, rear_section = _build_for_spar(
            label="rear_spar",
            spar_cfg=cfg.rear_spar,
            segment_lengths_m=list(cfg.spar_segment_lengths(cfg.rear_spar)),
            radii_mm=[float(value) for value in rear_r],
            thickness_mm=[float(value) for value in rear_t],
            ply_material_key=str(rear_ply_material),
            materials_db=materials_db,
            ply_drop_limit=int(args.ply_drop_limit),
        )
        sections["rear_spar"] = rear_section

    total_continuous_mass = sum(
        float(section["summary"]["continuous_mass_full_wing_kg"]) for section in sections.values()
    )
    total_discrete_mass = sum(
        float(section["summary"]["discrete_mass_full_wing_kg"]) for section in sections.values()
    )
    total_mass_penalty = total_discrete_mass - total_continuous_mass

    report_lines = [
        "Discrete Layup Post-Process",
        "=" * 80,
        f"Generated at: {datetime.now().astimezone().isoformat()}",
        f"Summary JSON: {summary_path}",
        f"Config      : {config_path}",
        f"Report path : {output_path}",
        f"Schedule JSON: {schedule_path}",
        "",
        f"Continuous full-wing mass: {total_continuous_mass:.3f} kg",
        f"Discrete full-wing mass  : {total_discrete_mass:.3f} kg",
        f"Mass penalty             : {total_mass_penalty:+.3f} kg",
        "",
    ]
    for name, section in sections.items():
        report_lines.append(name)
        report_lines.append("-" * 80)
        report_lines.append(str(section["report"]).rstrip())
        report_lines.append("")
    output_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    schedule_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(),
                "summary_json": str(summary_path),
                "config": str(config_path),
                "continuous_full_wing_mass_kg": total_continuous_mass,
                "discrete_full_wing_mass_kg": total_discrete_mass,
                "mass_penalty_full_wing_kg": total_mass_penalty,
                "spars": {
                    name: section["summary"]
                    for name, section in sections.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote layup report  : {output_path}")
    print(f"Wrote layup schedule: {schedule_path}")
    print(f"Mass penalty        : {total_mass_penalty:+.3f} kg (full wing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
