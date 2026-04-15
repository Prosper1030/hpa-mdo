#!/usr/bin/env python3
"""Run a CalculiX BUCKLE validation and write a markdown report."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from hpa_mdo.core.constants import G_STANDARD  # noqa: E402
from hpa_mdo.hifi.calculix_runner import (  # noqa: E402
    prepare_buckle_inp,
    root_boundary_from_mesh,
    run_static,
    tip_node_from_mesh,
)
from hpa_mdo.hifi.frd_parser import parse_buckle_eigenvalues  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="HPA-MDO config with hi_fidelity.calculix settings.",
    )
    parser.add_argument("--mesh", type=Path, required=True, help="Meshed CalculiX .inp file.")
    parser.add_argument(
        "--mdo-buckling-index",
        type=float,
        required=True,
        help="OpenMDAO KS buckling index; <=0 is feasible.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "output" / "blackcat_004" / "hifi" / "buckle_report.md",
        help="Markdown report path.",
    )
    parser.add_argument(
        "--inp-out",
        type=Path,
        default=None,
        help="Prepared CalculiX BUCKLE .inp path.",
    )
    parser.add_argument(
        "--material",
        type=str,
        default="carbon_fiber_hm",
        help="Material key in data/materials.yaml.",
    )
    parser.add_argument("--n-modes", type=int, default=5, help="Number of BUCKLE modes.")
    parser.add_argument(
        "--tip-load-n",
        type=float,
        default=None,
        help="Optional concentrated vertical tip load [N]. Default is half-MTOW downward.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    material = materials_db.get(args.material)
    material_payload = {
        "E": material.E,
        "nu": material.poisson_ratio,
        "rho": material.density,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        root_boundary = root_boundary_from_mesh(args.mesh)
        tip_node = tip_node_from_mesh(args.mesh)
    except Exception as exc:
        _write_report(
            args.out,
            status="WARN",
            message=f"Could not derive root/tip nodes from mesh: {exc}",
            mdo_buckling_index=args.mdo_buckling_index,
            eigenvalues=[],
        )
        print(f"Wrote {args.out}")
        return 0

    tip_load_n = (
        float(args.tip_load_n)
        if args.tip_load_n is not None
        else -0.5 * cfg.weight.max_takeoff_kg * G_STANDARD
    )
    inp_out = args.inp_out or args.mesh.with_name(f"{args.mesh.stem}_buckle.inp")
    prepare_buckle_inp(
        args.mesh,
        inp_out,
        material_payload,
        root_boundary,
        [(tip_node, 3, tip_load_n)],
        n_modes=args.n_modes,
    )
    result = run_static(inp_out, cfg)
    if result.get("error"):
        _write_report(
            args.out,
            status="WARN",
            message=f"CalculiX BUCKLE skipped/failed: {result['error']}",
            mdo_buckling_index=args.mdo_buckling_index,
            eigenvalues=[],
            prepared_inp=inp_out,
        )
        print(f"Wrote {args.out}")
        return 0

    eigenvalues = parse_buckle_eigenvalues(result["dat"])
    if not eigenvalues:
        _write_report(
            args.out,
            status="WARN",
            message=f"No BUCKLE eigenvalues found in {result['dat']}",
            mdo_buckling_index=args.mdo_buckling_index,
            eigenvalues=[],
            prepared_inp=inp_out,
        )
        print(f"Wrote {args.out}")
        return 0

    threshold = buckling_lambda_threshold(args.mdo_buckling_index)
    margin = eigenvalues[0] - threshold
    status = "PASS" if margin >= 0.0 else "WARN"
    _write_report(
        args.out,
        status=status,
        message="CalculiX BUCKLE completed.",
        mdo_buckling_index=args.mdo_buckling_index,
        eigenvalues=eigenvalues,
        prepared_inp=inp_out,
        threshold=threshold,
        margin=margin,
    )
    print(f"Wrote {args.out}")
    return 0


def buckling_lambda_threshold(mdo_buckling_index: float) -> float:
    """Convert KS ``demand/critical - 1`` index into a load-factor threshold."""

    denominator = 1.0 + float(mdo_buckling_index)
    if denominator <= 0.0:
        return math.inf
    return 1.0 / denominator


def _write_report(
    path: Path,
    *,
    status: str,
    message: str,
    mdo_buckling_index: float,
    eigenvalues: list[float],
    prepared_inp: Path | None = None,
    threshold: float | None = None,
    margin: float | None = None,
) -> None:
    lines = [
        "# High-Fidelity Buckling Check",
        "",
        f"- Status: {status}",
        f"- Message: {message}",
        f"- MDO buckling_index: {mdo_buckling_index:.9g}",
        "- Threshold formula: lambda_threshold = 1 / (1 + buckling_index)",
    ]
    if prepared_inp is not None:
        lines.append(f"- Prepared input: {prepared_inp}")
    if threshold is not None:
        lines.append(f"- lambda_threshold: {threshold:.9g}")
    if margin is not None:
        lines.append(f"- margin_lambda: {margin:.9g}")
    if eigenvalues:
        lines.append("")
        lines.append("| mode | lambda |")
        lines.append("| ---: | ---: |")
        for idx, value in enumerate(eigenvalues, start=1):
            lines.append(f"| {idx} | {value:.9g} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
