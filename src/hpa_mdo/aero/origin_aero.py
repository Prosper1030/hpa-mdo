"""Formal origin-VSP aerodynamic sweep workflow."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from hpa_mdo.aero.aero_sweep import (
    AeroSweepPoint,
    build_vspaero_sweep_points,
    load_su2_alpha_sweep,
    sweep_points_to_dataframe,
)
from hpa_mdo.aero.origin_su2 import prepare_origin_su2_alpha_sweep
from hpa_mdo.aero.vsp_builder import VSPBuilder
from hpa_mdo.core.config import load_config

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MPL = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_MPL = False


def _write_placeholder_png(output_path: Path) -> None:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3D9sAAAAASUVORK5CYII="
    )
    output_path.write_bytes(png_bytes)


def _export_dataframe(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    export_df = df.copy()
    if "cl" in export_df.columns and "cd" in export_df.columns:
        export_df["cl_cd"] = export_df["cl"] / export_df["cd"]
    export_df.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(export_df.to_dict(orient="records"), indent=2) + "\n",
        encoding="utf-8",
    )


def _build_solver_markdown(title: str, points: Iterable[AeroSweepPoint]) -> str:
    df = sweep_points_to_dataframe(points)
    lines = [
        f"# {title}",
        "",
        f"- Cases: {len(df)}",
        "",
        "| Alpha (deg) | CL | CD | CM | Lift (N) | Drag (N) |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lift = "n/a" if pd.isna(row["lift_n"]) else f"{float(row['lift_n']):.3f}"
        drag = "n/a" if pd.isna(row["drag_n"]) else f"{float(row['drag_n']):.3f}"
        lines.append(
            f"| {float(row['alpha_deg']):.3f} | "
            f"{float(row['cl']):.6f} | "
            f"{float(row['cd']):.6f} | "
            f"{float(row['cm']):.6f} | "
            f"{lift} | {drag} |"
        )
    return "\n".join(lines) + "\n"


def _plot_groups(
    grouped_points: dict[str, Sequence[AeroSweepPoint]],
    output_path: Path,
    *,
    title: str,
) -> None:
    if not HAS_MPL:
        _write_placeholder_png(output_path)
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle(title, fontsize=13, fontweight="bold")
    ax_cl_alpha, ax_cl_cd, ax_clcd_alpha, ax_cd_alpha = axes.flatten()

    for solver, points in grouped_points.items():
        df = sweep_points_to_dataframe(points)
        if df.empty:
            continue
        df = df.dropna(subset=["alpha_deg", "cl", "cd"]).copy()
        if df.empty:
            continue
        df["cl_cd"] = df["cl"] / df["cd"]
        ax_cl_alpha.plot(df["alpha_deg"], df["cl"], marker="o", linewidth=1.8, label=solver)
        ax_cl_cd.plot(df["cd"], df["cl"], marker="o", linewidth=1.8, label=solver)
        ax_clcd_alpha.plot(df["alpha_deg"], df["cl_cd"], marker="o", linewidth=1.8, label=solver)
        ax_cd_alpha.plot(df["alpha_deg"], df["cd"], marker="o", linewidth=1.8, label=solver)

    ax_cl_alpha.set_title("CL vs Alpha")
    ax_cl_alpha.set_xlabel("Alpha (deg)")
    ax_cl_alpha.set_ylabel("CL")
    ax_cl_cd.set_title("CL vs CD")
    ax_cl_cd.set_xlabel("CD")
    ax_cl_cd.set_ylabel("CL")
    ax_clcd_alpha.set_title("CL/CD vs Alpha")
    ax_clcd_alpha.set_xlabel("Alpha (deg)")
    ax_clcd_alpha.set_ylabel("CL/CD")
    ax_cd_alpha.set_title("CD vs Alpha")
    ax_cd_alpha.set_xlabel("Alpha (deg)")
    ax_cd_alpha.set_ylabel("CD")

    for axis in axes.flatten():
        axis.grid(True, alpha=0.25)
        axis.legend()

    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def write_origin_aero_artifacts(
    *,
    output_dir: str | Path,
    vspaero_points: Sequence[AeroSweepPoint],
    su2_points: Sequence[AeroSweepPoint] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    vspaero_df = sweep_points_to_dataframe(vspaero_points)
    vspaero_csv = out_dir / "vspaero_results.csv"
    vspaero_json = out_dir / "vspaero_results.json"
    vspaero_md = out_dir / "vspaero_results.md"
    vspaero_plot = out_dir / "vspaero_plots.png"
    _export_dataframe(vspaero_df, vspaero_csv, vspaero_json)
    vspaero_md.write_text(
        _build_solver_markdown("Origin VSPAero Sweep", vspaero_points),
        encoding="utf-8",
    )
    _plot_groups({"vspaero": vspaero_points}, vspaero_plot, title="Origin VSPAero Sweep")

    bundle: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "metadata": metadata or {},
        "vspaero": {
            "count": len(vspaero_points),
            "files": {
                "csv": str(vspaero_csv),
                "json": str(vspaero_json),
                "markdown": str(vspaero_md),
                "plot": str(vspaero_plot),
            },
        },
        "su2": None,
    }

    if su2_points:
        su2_df = sweep_points_to_dataframe(su2_points)
        su2_csv = out_dir / "su2_results.csv"
        su2_json = out_dir / "su2_results.json"
        su2_md = out_dir / "su2_results.md"
        comparison_plot = out_dir / "comparison_plots.png"
        _export_dataframe(su2_df, su2_csv, su2_json)
        su2_md.write_text(
            _build_solver_markdown("SU2 Alpha Sweep", su2_points),
            encoding="utf-8",
        )
        _plot_groups(
            {"vspaero": vspaero_points, "su2": su2_points},
            comparison_plot,
            title="Origin Aero Sweep Comparison",
        )
        bundle["su2"] = {
            "count": len(su2_points),
            "files": {
                "csv": str(su2_csv),
                "json": str(su2_json),
                "markdown": str(su2_md),
                "comparison_plot": str(comparison_plot),
            },
        }

    bundle_json = out_dir / "analysis_bundle.json"
    bundle_json.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    bundle["bundle_json"] = str(bundle_json)
    return bundle


def run_origin_aero_sweep(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    aoa_list: Sequence[float],
    su2_sweep_dir: str | Path | None = None,
    prepare_su2: bool = False,
    su2_mesh_path: str | Path | None = None,
    run_su2_cases: bool = False,
    su2_binary: str | None = None,
    su2_mpi_ranks: int | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    origin_vsp_path = getattr(cfg.io, "vsp_model", None)
    if origin_vsp_path is None:
        raise ValueError("config does not define io.vsp_model for the origin .vsp3")

    raw_dir = Path(output_dir).expanduser().resolve() / "vspaero_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    builder = VSPBuilder(cfg)
    run_result = builder.run_vspaero(str(origin_vsp_path), list(aoa_list), str(raw_dir))
    if not run_result.get("success", False):
        raise RuntimeError(run_result.get("error", "VSPAero run failed"))

    lod_path = run_result.get("lod_path")
    polar_path = run_result.get("polar_path")
    if not lod_path or not polar_path:
        raise RuntimeError("VSPAero run did not produce both .lod and .polar outputs")

    vspaero_points = build_vspaero_sweep_points(lod_path=lod_path, polar_path=polar_path)
    resolved_su2_dir = None if su2_sweep_dir is None else Path(su2_sweep_dir).expanduser().resolve()
    su2_preparation = None
    su2_note = None
    if prepare_su2:
        prep_dir = (
            resolved_su2_dir
            if resolved_su2_dir is not None
            else Path(output_dir).expanduser().resolve() / "su2_alpha_sweep"
        )
        su2_preparation = prepare_origin_su2_alpha_sweep(
            config_path=config_path,
            output_dir=prep_dir,
            aoa_list=aoa_list,
            mesh_path=su2_mesh_path,
            run_cases=run_su2_cases,
            su2_binary=su2_binary,
            mpi_ranks=su2_mpi_ranks,
        )
        resolved_su2_dir = Path(su2_preparation["sweep_dir"]).expanduser().resolve()

    su2_points = None
    if resolved_su2_dir is not None:
        try:
            su2_points = load_su2_alpha_sweep(resolved_su2_dir)
        except ValueError as exc:
            if not prepare_su2:
                raise
            su2_note = str(exc)

    bundle = write_origin_aero_artifacts(
        output_dir=output_dir,
        vspaero_points=vspaero_points,
        su2_points=su2_points,
        metadata={
            "config_path": str(Path(config_path).expanduser().resolve()),
            "origin_vsp_path": str(Path(origin_vsp_path).expanduser().resolve()),
            "aoa_list_deg": [float(value) for value in aoa_list],
            "vspaero_run": {
                "analysis_method": run_result.get("analysis_method"),
                "solver_backend": run_result.get("solver_backend"),
                "lod_path": lod_path,
                "polar_path": polar_path,
            },
            "su2_sweep_dir": None if resolved_su2_dir is None else str(resolved_su2_dir),
            "su2_preparation": su2_preparation,
            "su2_analysis_note": su2_note,
        },
    )
    return bundle
