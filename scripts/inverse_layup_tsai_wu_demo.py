#!/usr/bin/env python3
"""Representative inverse-design -> discrete layup -> Tsai-Wu demo artifact."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.api._shared import json_safe, run_pipeline  # noqa: E402
from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from hpa_mdo.utils.discrete_layup import (  # noqa: E402
    build_segment_layup_results,
    enumerate_valid_stacks,
    format_layup_report,
    summarize_layup_results,
)


DEFAULT_SUMMARY = (
    REPO_ROOT
    / "output"
    / "dihedral_sweep_phase9a_extension"
    / "mult_3p600"
    / "inverse_design"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "inverse_layup_tsai_wu_demo"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="Inverse-design summary JSON with a selected design.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the demo report and JSON artifacts.",
    )
    parser.add_argument(
        "--strain-envelope",
        type=Path,
        default=None,
        help="Optional precomputed strain-envelope JSON. If omitted, OpenMDAO analysis is run.",
    )
    parser.add_argument(
        "--skip-structural-analysis",
        action="store_true",
        help="Require a strain envelope from --strain-envelope or the summary instead of running OpenMDAO.",
    )
    parser.add_argument(
        "--aoa-deg",
        type=float,
        default=None,
        help="Optional VSPAero AoA to choose for the OpenMDAO analysis load case.",
    )
    parser.add_argument(
        "--ply-material",
        type=str,
        default=None,
        help="Optional override for the ply material key in data/materials.yaml.",
    )
    return parser.parse_args()


def _load_selected_design(summary_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
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


def _design_array_m(design_mm: dict[str, Any], key: str) -> np.ndarray:
    values = design_mm.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"Selected design is missing design_mm.{key}.")
    return np.asarray([float(value) for value in values], dtype=float) * 1.0e-3


def _load_existing_strain_source(
    *,
    payload: dict[str, Any],
    selected: dict[str, Any],
    strain_envelope_path: Path | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if strain_envelope_path is not None:
        resolved = strain_envelope_path.expanduser().resolve()
        return json.loads(resolved.read_text(encoding="utf-8")), str(resolved)

    selected_env = selected.get("strain_envelope")
    if isinstance(selected_env, dict):
        return selected_env, "selected.strain_envelope"

    payload_env = payload.get("strain_envelope")
    if isinstance(payload_env, dict):
        return payload_env, "summary.strain_envelope"

    return None, None


def _run_structural_strain_envelope(
    *,
    config_path: Path,
    design_mm: dict[str, Any],
    aoa_deg: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg, _aircraft, _mat_db, _loads, opt, best_case = run_pipeline(
        str(config_path),
        aoa_deg=aoa_deg,
    )
    result = opt.analyze(
        main_t_seg=_design_array_m(design_mm, "main_t"),
        main_r_seg=_design_array_m(design_mm, "main_r"),
        rear_t_seg=_design_array_m(design_mm, "rear_t") if cfg.rear_spar.enabled else None,
        rear_r_seg=_design_array_m(design_mm, "rear_r") if cfg.rear_spar.enabled else None,
    )
    metadata = {
        "source": "openmdao_analysis",
        "best_case_aoa_deg": None if best_case is None else float(best_case.aoa_deg),
        "analysis_success": bool(result.success),
        "analysis_message": str(result.message),
        "manufacturing_gates": json_safe(result.manufacturing_gates),
    }
    return json_safe(result.strain_envelope), metadata


def _array_from_envelope(
    envelope: dict[str, Any],
    key: str,
    n_segments: int,
    aliases: tuple[str, ...] = (),
) -> list[float]:
    raw = envelope.get(key)
    for alias in aliases:
        if raw is None:
            raw = envelope.get(alias)
    if raw is None:
        raise ValueError(f"strain envelope is missing '{key}'.")
    if not isinstance(raw, list) or len(raw) != n_segments:
        raise ValueError(f"strain envelope '{key}' must contain {n_segments} values.")
    return [float(value) for value in raw]


def _strain_envelopes_for_spar(
    source: dict[str, Any],
    *,
    label: str,
    n_segments: int,
) -> list[dict[str, float]]:
    candidate: Any = source
    if isinstance(candidate, dict) and "strain_envelope" in candidate:
        candidate = candidate["strain_envelope"]
    if isinstance(candidate, dict) and label in candidate:
        candidate = candidate[label]
    if isinstance(candidate, dict) and "combined" in candidate:
        candidate = candidate["combined"]
    if not isinstance(candidate, dict):
        raise ValueError(f"strain envelope for {label} must be a JSON object.")

    eps = _array_from_envelope(candidate, "epsilon_x_absmax", n_segments)
    kappa = _array_from_envelope(
        candidate,
        "kappa_absmax",
        n_segments,
        aliases=("kappa_absmax_1pm",),
    )
    torsion = _array_from_envelope(
        candidate,
        "torsion_rate_absmax",
        n_segments,
        aliases=("torsion_rate_absmax_1pm", "tau_absmax"),
    )
    return [
        {
            "epsilon_x_absmax": eps[idx],
            "kappa_absmax": kappa[idx],
            "torsion_rate_absmax": torsion[idx],
        }
        for idx in range(n_segments)
    ]


def _build_layup_section(
    *,
    label: str,
    cfg,
    spar_cfg,
    design_mm: dict[str, Any],
    radius_key: str,
    thickness_key: str,
    ply_material_key: str,
    materials_db: MaterialDB,
    strain_source: dict[str, Any],
) -> dict[str, Any]:
    segment_lengths_m = list(cfg.spar_segment_lengths(spar_cfg))
    n_segments = len(segment_lengths_m)
    ply_mat = materials_db.get_ply(ply_material_key)
    stacks = enumerate_valid_stacks(spar_cfg)
    results = build_segment_layup_results(
        segment_lengths_m=segment_lengths_m,
        continuous_thicknesses_m=_design_array_m(design_mm, thickness_key),
        outer_radii_m=_design_array_m(design_mm, radius_key),
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=int(spar_cfg.max_ply_drop_per_segment),
        strain_envelopes=_strain_envelopes_for_spar(
            strain_source,
            label=label,
            n_segments=n_segments,
        ),
    )
    return {
        "ply_material": ply_material_key,
        "report": format_layup_report(
            results,
            ply_mat,
            ply_drop_limit=int(spar_cfg.max_ply_drop_per_segment),
            min_run_length_m=float(spar_cfg.min_layup_run_length_m),
        ),
        "summary": summarize_layup_results(
            results,
            ply_drop_limit=int(spar_cfg.max_ply_drop_per_segment),
            min_run_length_m=float(spar_cfg.min_layup_run_length_m),
        ),
    }


def main() -> int:
    args = _parse_args()
    summary_path = args.summary.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload, selected = _load_selected_design(summary_path)
    config_path = Path(str(payload["config"])).expanduser().resolve()
    cfg = load_config(config_path)
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    design_mm = selected.get("design_mm")
    if not isinstance(design_mm, dict):
        raise ValueError(f"Selected design is missing design_mm: {summary_path}")

    strain_source, strain_source_label = _load_existing_strain_source(
        payload=payload,
        selected=selected,
        strain_envelope_path=args.strain_envelope,
    )
    analysis_metadata: dict[str, Any] = {}
    if strain_source is None:
        if args.skip_structural_analysis:
            raise ValueError(
                "No strain envelope was found. Remove --skip-structural-analysis or pass "
                "--strain-envelope."
            )
        strain_source, analysis_metadata = _run_structural_strain_envelope(
            config_path=config_path,
            design_mm=design_mm,
            aoa_deg=args.aoa_deg,
        )
        strain_source_label = "openmdao_analysis"

    strain_path = output_dir / "openmdao_strain_envelope.json"
    strain_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(),
                "source": strain_source_label,
                "metadata": analysis_metadata,
                "strain_envelope": json_safe(strain_source),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    sections: dict[str, dict[str, Any]] = {}
    main_ply_material = args.ply_material or cfg.main_spar.ply_material
    if main_ply_material is None:
        raise ValueError("No ply material for main spar. Pass --ply-material or set config.")
    sections["main_spar"] = _build_layup_section(
        label="main_spar",
        cfg=cfg,
        spar_cfg=cfg.main_spar,
        design_mm=design_mm,
        radius_key="main_r",
        thickness_key="main_t",
        ply_material_key=str(main_ply_material),
        materials_db=materials_db,
        strain_source=strain_source,
    )

    rear_r = design_mm.get("rear_r")
    rear_t = design_mm.get("rear_t")
    if cfg.rear_spar.enabled and isinstance(rear_r, list) and isinstance(rear_t, list):
        rear_ply_material = args.ply_material or cfg.rear_spar.ply_material or main_ply_material
        sections["rear_spar"] = _build_layup_section(
            label="rear_spar",
            cfg=cfg,
            spar_cfg=cfg.rear_spar,
            design_mm=design_mm,
            radius_key="rear_r",
            thickness_key="rear_t",
            ply_material_key=str(rear_ply_material),
            materials_db=materials_db,
            strain_source=strain_source,
        )

    total_continuous_mass = sum(
        float(section["summary"]["continuous_mass_full_wing_kg"]) for section in sections.values()
    )
    total_discrete_mass = sum(
        float(section["summary"]["discrete_mass_full_wing_kg"]) for section in sections.values()
    )
    total_mass_penalty = total_discrete_mass - total_continuous_mass
    manufacturing_passed = all(
        bool(section["summary"].get("manufacturing_gates", {}).get("passed", True))
        for section in sections.values()
    )

    report_path = output_dir / "representative_layup_tsai_wu_report.txt"
    schedule_path = output_dir / "representative_layup_tsai_wu_summary.json"
    report_lines = [
        "Representative Inverse-Design -> Discrete Layup -> Tsai-Wu",
        "=" * 80,
        f"Generated at: {datetime.now().astimezone().isoformat()}",
        f"Summary JSON: {summary_path}",
        f"Config      : {config_path}",
        f"Strain env  : {strain_source_label}",
        f"Strain JSON : {strain_path}",
        "",
        f"Continuous full-wing mass: {total_continuous_mass:.3f} kg",
        f"Discrete full-wing mass  : {total_discrete_mass:.3f} kg",
        f"Mass penalty             : {total_mass_penalty:+.3f} kg",
        f"Manufacturing gates      : {'PASS' if manufacturing_passed else 'FAIL'}",
        "",
    ]
    for name, section in sections.items():
        report_lines.append(name)
        report_lines.append("-" * 80)
        report_lines.append(str(section["report"]).rstrip())
        report_lines.append("")
    report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    schedule_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(),
                "artifact": "representative_inverse_design_discrete_layup_tsai_wu",
                "summary_json": str(summary_path),
                "config": str(config_path),
                "strain_envelope_source": strain_source_label,
                "strain_envelope_json": str(strain_path),
                "analysis_metadata": analysis_metadata,
                "continuous_full_wing_mass_kg": total_continuous_mass,
                "discrete_full_wing_mass_kg": total_discrete_mass,
                "mass_penalty_full_wing_kg": total_mass_penalty,
                "manufacturing_gates_passed": manufacturing_passed,
                "spars": {
                    name: {
                        "ply_material": section["ply_material"],
                        **section["summary"],
                    }
                    for name, section in sections.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote demo report  : {report_path}")
    print(f"Wrote demo summary : {schedule_path}")
    print(f"Wrote strain JSON  : {strain_path}")
    print(f"Manufacturing gates: {'PASS' if manufacturing_passed else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
