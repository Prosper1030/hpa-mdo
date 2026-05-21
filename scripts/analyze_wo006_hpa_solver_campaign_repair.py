#!/usr/bin/env python3
"""Generate WO-006 HPA solver-campaign repair evidence reports."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
WO006 = ROOT / "output" / "baseline_A_team_release" / "wo006_su2_baseline_validation"
DEFAULT_OUT = WO006 / "cfd_release_v0_hpa_solver_campaign_repair"
DEFAULT_PROBE = (
    WO006
    / "cfd_release_v0_hpa_grid_independence_verification"
    / "coarse_solver_probe"
)
DEFAULT_REFERENCE_CASE = (
    WO006
    / "cfd_release_v0_true_baseline_solver_stability"
    / "openfoam_cases"
    / "fullwing_mirror"
)
DEFAULT_EXTENDED = DEFAULT_OUT / "coarse_extended_current_setup"


FORCE_COLUMNS = (
    "Time",
    "Cd",
    "Cd(f)",
    "Cd(r)",
    "Cl",
    "Cl(f)",
    "Cl(r)",
    "CmPitch",
    "CmRoll",
    "CmYaw",
    "Cs",
    "Cs(f)",
    "Cs(r)",
)

USER_REFERENCE_CL_PRIMARY = 1.130726
USER_REFERENCE_CD_TOTAL_PHYSICAL = 0.031823
REPO_REFERENCE_CL_PRIMARY = 1.133291
REPO_REFERENCE_CD_PRIMARY = 0.03276165
REPO_REFERENCE_CD_TOTAL_PHYSICAL = 0.0327769065


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--coarse-probe-dir", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--reference-case", type=Path, default=DEFAULT_REFERENCE_CASE)
    parser.add_argument("--coarse-extended-dir", type=Path, default=DEFAULT_EXTENDED)
    args = parser.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    probe_case = (
        args.coarse_probe_dir
        / "openfoam_cases"
        / "coarse"
        / "fullwing_artificial_tip_symmetry"
    ).resolve()
    probe_rung = args.coarse_probe_dir / "openfoam_cases" / "coarse" / "rung_result.json"
    reference_case = args.reference_case.resolve()
    extended_case = (
        args.coarse_extended_dir
        / "openfoam_cases"
        / "coarse"
        / "fullwing_artificial_tip_symmetry"
    ).resolve()
    extended_rung = (
        args.coarse_extended_dir / "openfoam_cases" / "coarse" / "rung_result.json"
    )

    probe_primary = read_force_group(probe_case, "primary")
    probe_total_physical = read_force_group(probe_case, "total_physical")
    write_combined_history(
        out / "coarse_160_force_history.csv",
        {
            "primary": probe_primary,
            "total_physical": probe_total_physical,
        },
    )
    write_probe_explanation(
        out / "coarse_160_probe_explanation.md",
        probe_case,
        probe_rung,
        probe_primary,
        probe_total_physical,
    )

    reference_inventory = build_case_inventory(
        reference_case,
        role="successful_reference_repo_artifact",
        include_force_groups=("primary", "total", "te_wall"),
    )
    write_json(out / "reference_case_manifest.json", reference_inventory)
    write_reference_inventory_md(out / "reference_case_inventory.md", reference_inventory)

    coarse_inventory = build_case_inventory(
        probe_case,
        role="new_grid_family_coarse_probe",
        include_force_groups=("primary", "total", "total_physical", "te_wall"),
    )
    diff_rows = build_inventory_diff(reference_inventory, coarse_inventory)
    write_diff_csv(out / "coarse_vs_reference_diff.csv", diff_rows)
    write_diff_md(out / "coarse_vs_reference_diff.md", diff_rows, reference_case, probe_case)

    if extended_case.exists():
        extended_groups = {
            "primary": read_force_group(extended_case, "primary"),
            "total_physical": read_force_group(extended_case, "total_physical"),
            "te_wall": read_force_group(extended_case, "te_wall"),
        }
        write_combined_history(out / "coarse_extended_force_history.csv", extended_groups)
        extended_rung_data = read_json(extended_rung) if extended_rung.exists() else {}
        write_extended_reports(out, extended_case, extended_rung_data, extended_groups)


def write_probe_explanation(
    path: Path,
    case_dir: Path,
    rung_result_path: Path,
    primary: list[dict[str, float]],
    total_physical: list[dict[str, float]],
) -> None:
    rung = read_json(rung_result_path) if rung_result_path.exists() else {}
    commands = rung.get("commands", {})
    simple = commands.get("simpleFoam_200") or {}
    control = parse_simple_dict(case_dir / "system" / "controlDict")
    final100 = stability_window(primary, 100)
    final50 = stability_window(primary, 50)
    trend_rows = sample_trend(primary, (1, 10, 25, 50, 100, 125, 150, 160))
    total_final100 = stability_window(total_physical, 100)
    stopped_by_guard = simple.get("stopped_by_runaway_guard")
    run_cmd = simple.get("command", "simpleFoam")
    lines = [
        "# Coarse 160 Probe Explanation",
        "",
        "Verdict: `coarse_160_is_smoke_probe_not_converged_result`",
        "",
        f"- case: `{case_dir}`",
        f"- controlDict endTime: `{control.get('endTime')}`",
        f"- executed command: `{run_cmd}`",
        f"- simpleFoam returncode: `{simple.get('returncode')}`",
        f"- elapsed seconds: `{simple.get('elapsed_s')}`",
        f"- stopped by runtime timeout: `{simple.get('timed_out')}`",
        f"- stopped by force guard: `{stopped_by_guard}`",
        f"- runaway time: `{simple.get('runaway_time')}`",
        "",
        "The probe stopped at 160 iterations because the run was launched with",
        "`--first-iterations 160 --final-iterations 160`; the workflow therefore",
        "wrote `endTime 160` into `system/controlDict`. It was not stopped by the",
        "force guard or by an OpenFOAM error.",
        "",
        "## Stability Read",
        "",
        f"- rows in primary force history: `{len(primary)}`",
        f"- final-50 primary drift: `{format_window(final50)}`",
        f"- final-100 primary drift: `{format_window(final100)}`",
        f"- final-100 total_physical drift: `{format_window(total_final100)}`",
        "",
        "`CL_primary≈0.858` is not an accepted aerodynamic result. The case has",
        "fewer than 500 iterations and fails the requested final-100 stability gate.",
        "",
        "## CL/CD Trend",
        "",
        "| iteration | CD_primary | CL_primary | CmPitch_primary |",
        "|---:|---:|---:|---:|",
    ]
    for row in trend_rows:
        lines.append(
            f"| {row['Time']:.0f} | {row['Cd']:.8g} | {row['Cl']:.8g} | {row['CmPitch']:.8g} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reference_inventory_md(path: Path, inv: dict[str, Any]) -> None:
    ref = inv["force_summary"].get("primary", {})
    total = inv["force_summary"].get("total", {})
    derived_total_physical_cd = None
    derived_total_physical_cl = None
    if "primary" in inv["force_summary"] and "te_wall" in inv["force_summary"]:
        derived_total_physical_cd = (
            inv["force_summary"]["primary"].get("last_Cd", 0.0)
            + inv["force_summary"]["te_wall"].get("last_Cd", 0.0)
        )
        derived_total_physical_cl = (
            inv["force_summary"]["primary"].get("last_Cl", 0.0)
            + inv["force_summary"]["te_wall"].get("last_Cl", 0.0)
        )
    lines = [
        "# Reference Case Inventory",
        "",
        "Verdict: `repo_reference_found_but_user_supplied_cd_exact_value_not_present`",
        "",
        f"- case path: `{inv['case_path']}`",
        f"- role: `{inv['role']}`",
        f"- cells: `{inv['mesh'].get('cells')}`",
        f"- bounding box min: `{inv['geometry'].get('bbox_min')}`",
        f"- bounding box max: `{inv['geometry'].get('bbox_max')}`",
        f"- Sref/Aref: `{ref.get('Aref')}`",
        f"- Cref/lRef: `{ref.get('lRef')}`",
        f"- magUInf: `{ref.get('magUInf')}`",
        f"- rhoInf: `{ref.get('rhoInf')}`",
        f"- dragDir: `{ref.get('dragDir')}`",
        f"- liftDir: `{ref.get('liftDir')}`",
        f"- inlet/farfield U: `{inv['dictionaries'].get('U_inletValue')}` / `{inv['dictionaries'].get('U_freestreamValue')}`",
        f"- turbulence model: `{inv['dictionaries'].get('simulationType')}` / `{inv['dictionaries'].get('RASModel')}`",
        f"- transport nu: `{inv['dictionaries'].get('nu')}`",
        f"- primary patches: `{ref.get('patches')}`",
        f"- total patches: `{total.get('patches')}`",
        f"- iteration count: `{ref.get('last_Time')}`",
        f"- final primary CD/CL/CmPitch: `{ref.get('last_Cd')}` / `{ref.get('last_Cl')}` / `{ref.get('last_CmPitch')}`",
        f"- final-100 primary drift under current gate: `{format_window(ref.get('final100', {}))}`",
        f"- derived total_physical = primary + te_wall CD/CL: `{derived_total_physical_cd}` / `{derived_total_physical_cl}`",
        "",
        "Search result: the exact user-supplied `CD_primary≈0.031817`,",
        "`CD_total_physical≈0.031823`, `CL_primary≈1.130726` triple is not present",
        "as an OpenFOAM force-history artifact in this checkout. The traceable",
        "successful OpenFOAM reference with force history is the 500-iteration",
        "`fullwing_mirror` case: `CD_primary=0.03276165`, `CL_primary=1.133291`.",
        "The `0.031823` value appears in the drag/power audit as a user-supplied",
        "OpenFOAM-like physical CD, not as the last row of a stored forceCoeffs file.",
        "",
        "## Patch Inventory",
        "",
        "| patch | type | nFaces | startFace | area_m2 |",
        "|---|---|---:|---:|---:|",
    ]
    for patch in inv["boundary_patches"]:
        lines.append(
            f"| `{patch['name']}` | `{patch['type']}` | {patch['nFaces']} | {patch['startFace']} | {patch.get('area_m2')} |"
        )
    lines.extend(
        [
            "",
            "## OpenFOAM Dictionaries",
            "",
            f"- controlDict startFrom/endTime/writeInterval: `{inv['dictionaries'].get('startFrom')}` / `{inv['dictionaries'].get('endTime')}` / `{inv['dictionaries'].get('writeInterval')}`",
            f"- fvSchemes hash: `{inv['dictionary_hashes'].get('fvSchemes')}`",
            f"- fvSolution hash: `{inv['dictionary_hashes'].get('fvSolution')}`",
            f"- boundary hash: `{inv['dictionary_hashes'].get('boundary')}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_diff_md(path: Path, rows: list[dict[str, Any]], reference: Path, coarse: Path) -> None:
    lines = [
        "# Coarse vs Reference Diff",
        "",
        "Verdict: `coarse_setup_not_equivalent_to_reference_until_force_reproduction_passes`",
        "",
        f"- reference case: `{reference}`",
        f"- coarse probe case: `{coarse}`",
        "",
        "Important setup values match: `Sref/Aref`, `Cref/lRef`, `magUInf`,",
        "`dragDir`, `liftDir`, `rhoInf`, inlet/farfield velocity, and primary force patches.",
        "Important differences remain: the mesh is a newly generated coarse family",
        "mesh, the reference has 1.9968M cells while Coarse has 1.335552M cells,",
        "patch face counts differ, Coarse has `total_physical` functionObjects,",
        "Coarse used potentialFoam initialization, and the Coarse probe only ran 160",
        "iterations.",
        "",
        "| category | item | reference | coarse | match |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['category']} | `{row['item']}` | `{row['reference']}` | `{row['coarse']}` | `{row['match']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_extended_reports(
    out: Path,
    case_dir: Path,
    rung: dict[str, Any],
    groups: dict[str, list[dict[str, float]]],
) -> None:
    primary = groups["primary"]
    total_physical = groups["total_physical"]
    primary_500 = stability_window([r for r in primary if r["Time"] <= 500], 100)
    total_500 = stability_window([r for r in total_physical if r["Time"] <= 500], 100)
    primary_final = stability_window(primary, 100)
    total_final = stability_window(total_physical, 100)
    accepted_500 = window_acceptance(primary_500, total_500)
    accepted_final = window_acceptance(primary_final, total_final)
    last = primary[-1] if primary else {}
    last_total = total_physical[-1] if total_physical else {}
    user_cl_error = relative_error(last.get("Cl"), USER_REFERENCE_CL_PRIMARY)
    user_cd_total_error = relative_error(last_total.get("Cd"), USER_REFERENCE_CD_TOTAL_PHYSICAL)
    repo_cl_error = relative_error(last.get("Cl"), REPO_REFERENCE_CL_PRIMARY)
    repo_cd_primary_error = relative_error(last.get("Cd"), REPO_REFERENCE_CD_PRIMARY)
    repo_cd_total_error = relative_error(last_total.get("Cd"), REPO_REFERENCE_CD_TOTAL_PHYSICAL)
    reference_equivalent_user = (
        accepted_final
        and user_cl_error is not None
        and user_cd_total_error is not None
        and abs(user_cl_error) <= 0.03
        and abs(user_cd_total_error) <= 0.05
    )
    if reference_equivalent_user:
        verdict = "coarse_reference_reproduced"
    elif accepted_final:
        verdict = "coarse_stable_but_not_reference_equivalent"
    else:
        verdict = "coarse_not_converged_by_requested_force_window_gate"
    yplus = rung.get("yPlus", {})
    residuals = rung.get("residuals", {})
    commands = rung.get("commands", {})
    extension_command = (
        commands.get("simpleFoam_1000")
        or commands.get("simpleFoam_500")
        or commands.get("simpleFoam_extension")
    )
    end_time = max((row["Time"] for row in primary), default=None)
    lines = [
        "# Coarse Extended Solver Report",
        "",
        f"Verdict: `{verdict}`",
        "",
        f"- case: `{case_dir}`",
        f"- last primary row: Time `{end_time}`, CD `{last.get('Cd')}`, CL `{last.get('Cl')}`, CmPitch `{last.get('CmPitch')}`",
        f"- last total_physical row: CD `{last_total.get('Cd')}`, CL `{last_total.get('Cl')}`, CmPitch `{last_total.get('CmPitch')}`",
        f"- simpleFoam first segment: `{summarize_command(commands.get('simpleFoam_200'))}`",
        f"- simpleFoam extension segment: `{summarize_command(extension_command)}`",
        f"- yPlus status: `{yplus.get('status')}`",
        "",
        "## Stability",
        "",
        f"- final-100 at 500, primary: `{format_window(primary_500)}`",
        f"- final-100 at 500, total_physical: `{format_window(total_500)}`",
        f"- accepted at 500 by requested gate: `{accepted_500}`",
        f"- final-100 at final time, primary: `{format_window(primary_final)}`",
        f"- final-100 at final time, total_physical: `{format_window(total_final)}`",
        f"- accepted at final time by requested gate: `{accepted_final}`",
        "",
        "## Reference Equivalence",
        "",
        f"- user-supplied acceptance target: `CL_primary={USER_REFERENCE_CL_PRIMARY}`, `CD_total_physical={USER_REFERENCE_CD_TOTAL_PHYSICAL}`",
        f"- repo-traceable stored reference: `CL_primary={REPO_REFERENCE_CL_PRIMARY}`, `CD_primary={REPO_REFERENCE_CD_PRIMARY}`, `CD_total_physical={REPO_REFERENCE_CD_TOTAL_PHYSICAL}`",
        f"- CL error vs user target: `{user_cl_error}`",
        f"- CD_total_physical error vs user target: `{user_cd_total_error}`",
        f"- CL error vs repo-stored reference: `{repo_cl_error}`",
        f"- CD_primary error vs repo-stored reference: `{repo_cd_primary_error}`",
        f"- CD_total_physical error vs repo-stored reference: `{repo_cd_total_error}`",
        f"- accepted reference reproduction: `{reference_equivalent_user}`",
        "",
        "Medium/Fine remain gated until this report says the Coarse run is stable",
        "and reference-equivalent.",
    ]
    (out / "coarse_extended_solver_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    stability_lines = [
        "# Coarse Final Window Stability",
        "",
        f"- final time: `{end_time}`",
        f"- primary final-100: `{json.dumps(primary_final, sort_keys=True)}`",
        f"- total_physical final-100: `{json.dumps(total_final, sort_keys=True)}`",
        f"- accepted: `{accepted_final}`",
        f"- accepted reference reproduction: `{reference_equivalent_user}`",
    ]
    (out / "coarse_final_window_stability.md").write_text("\n".join(stability_lines) + "\n", encoding="utf-8")
    y_lines = [
        "# Coarse yPlus Report",
        "",
        f"- status: `{yplus.get('status')}`",
        f"- real-wall summary: `{json.dumps(yplus.get('primary_main_wall_summary'), sort_keys=True)}`",
        "",
        "| patch | mean | p95 | max |",
        "|---|---:|---:|---:|",
    ]
    for patch, stats in yplus.get("patches", {}).items():
        y_lines.append(
            f"| `{patch}` | {stats.get('mean')} | {stats.get('p95')} | {stats.get('max')} |"
        )
    (out / "coarse_yplus_report.md").write_text("\n".join(y_lines) + "\n", encoding="utf-8")
    residual_lines = [
        "# Coarse Residual Summary",
        "",
        f"`{json.dumps(residuals, sort_keys=True)}`",
    ]
    (out / "coarse_residual_summary.md").write_text("\n".join(residual_lines) + "\n", encoding="utf-8")


def build_case_inventory(case_dir: Path, *, role: str, include_force_groups: Iterable[str]) -> dict[str, Any]:
    boundary = parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")
    bbox = point_bbox(case_dir / "constant" / "polyMesh" / "points")
    patch_areas = compute_patch_surface_areas(case_dir, boundary)
    for patch in boundary:
        patch["area_m2"] = patch_areas.get(patch["name"])
    mesh = parse_checkmesh(case_dir / "log.checkMesh")
    control = parse_simple_dict(case_dir / "system" / "controlDict")
    transport = parse_transport(case_dir / "constant" / "transportProperties")
    turbulence = parse_turbulence(case_dir / "constant" / "turbulenceProperties")
    u_field = parse_u_field(case_dir / "0" / "U")
    force_summary: dict[str, Any] = {}
    for group in include_force_groups:
        rows = read_force_group(case_dir, group)
        if rows:
            last = rows[-1]
            meta = read_force_metadata(case_dir, group)
            force_summary[group] = {
                **meta,
                "rows": len(rows),
                "first_Time": rows[0]["Time"],
                "last_Time": last["Time"],
                "last_Cd": last["Cd"],
                "last_Cl": last["Cl"],
                "last_CmPitch": last["CmPitch"],
                "final100": stability_window(rows, 100),
            }
    return {
        "role": role,
        "case_path": str(case_dir),
        "geometry": bbox,
        "mesh": mesh,
        "boundary_patches": boundary,
        "dictionaries": {
            "startFrom": control.get("startFrom"),
            "endTime": control.get("endTime"),
            "writeInterval": control.get("writeInterval"),
            "nu": transport.get("nu"),
            "simulationType": turbulence.get("simulationType"),
            "RASModel": turbulence.get("RASModel"),
            "turbulence_model": "/".join(
                value
                for value in (turbulence.get("simulationType"), turbulence.get("RASModel"))
                if value
            ),
            "U_internalField": u_field.get("internalField"),
            "U_freestreamValue": u_field.get("freestreamValue"),
            "U_inletValue": u_field.get("inletValue"),
        },
        "dictionary_hashes": {
            "U": file_hash(case_dir / "0" / "U"),
            "p": file_hash(case_dir / "0" / "p"),
            "nuTilda": file_hash(case_dir / "0" / "nuTilda"),
            "boundary": file_hash(case_dir / "constant" / "polyMesh" / "boundary"),
            "fvSchemes": file_hash(case_dir / "system" / "fvSchemes"),
            "fvSolution": file_hash(case_dir / "system" / "fvSolution"),
            "controlDict": file_hash(case_dir / "system" / "controlDict"),
        },
        "force_summary": force_summary,
    }


def build_inventory_diff(ref: dict[str, Any], coarse: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(category: str, item: str, rv: Any, cv: Any) -> None:
        rows.append(
            {
                "category": category,
                "item": item,
                "reference": rv,
                "coarse": cv,
                "match": values_match(rv, cv),
            }
        )

    for key in ("cells", "maxNonOrtho", "maxSkew", "failedChecks"):
        add("mesh", key, ref["mesh"].get(key), coarse["mesh"].get(key))
    add("geometry", "bbox_min", ref["geometry"].get("bbox_min"), coarse["geometry"].get("bbox_min"))
    add("geometry", "bbox_max", ref["geometry"].get("bbox_max"), coarse["geometry"].get("bbox_max"))
    for patch in sorted({p["name"] for p in ref["boundary_patches"]} | {p["name"] for p in coarse["boundary_patches"]}):
        rp = next((p for p in ref["boundary_patches"] if p["name"] == patch), {})
        cp = next((p for p in coarse["boundary_patches"] if p["name"] == patch), {})
        add("patch", f"{patch}.type", rp.get("type"), cp.get("type"))
        add("patch", f"{patch}.nFaces", rp.get("nFaces"), cp.get("nFaces"))
        add("patch", f"{patch}.area_m2", rp.get("area_m2"), cp.get("area_m2"))
    for key in (
        "nu",
        "simulationType",
        "RASModel",
        "U_freestreamValue",
        "U_inletValue",
        "startFrom",
        "endTime",
        "writeInterval",
    ):
        add("dictionary", key, ref["dictionaries"].get(key), coarse["dictionaries"].get(key))
    for group_key in ("primary", "total", "total_physical", "te_wall"):
        rg = ref["force_summary"].get(group_key, {})
        cg = coarse["force_summary"].get(group_key, {})
        for key in ("patches", "rhoInf", "Aref", "lRef", "magUInf", "dragDir", "liftDir", "last_Cd", "last_Cl"):
            add("force", f"{group_key}.{key}", rg.get(key), cg.get(key))
    return rows


def read_force_group(case_dir: Path, group: str) -> list[dict[str, float]]:
    rows_by_time: dict[float, dict[str, float]] = {}
    for path in sorted((case_dir / "postProcessing" / f"forceCoeffs_{group}").glob("*/coefficient.dat")):
        for row in parse_force_file(path):
            rows_by_time[row["Time"]] = row
    return [rows_by_time[key] for key in sorted(rows_by_time)]


def parse_force_file(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) < len(FORCE_COLUMNS):
            continue
        try:
            values = [float(value) for value in parts[: len(FORCE_COLUMNS)]]
        except ValueError:
            continue
        rows.append(dict(zip(FORCE_COLUMNS, values)))
    return rows


def read_force_metadata(case_dir: Path, group: str) -> dict[str, Any]:
    files = sorted((case_dir / "postProcessing" / f"forceCoeffs_{group}").glob("*/coefficient.dat"))
    if not files:
        return {}
    text = files[0].read_text(encoding="utf-8", errors="ignore")
    meta: dict[str, Any] = {}
    for key in ("dragDir", "liftDir", "magUInf", "lRef", "Aref"):
        m = re.search(rf"# {re.escape(key)}\s*:\s*(.+)", text)
        if m:
            meta[key] = m.group(1).strip()
    control_text = (case_dir / "system" / "controlDict").read_text(encoding="utf-8", errors="ignore")
    block_match = re.search(
        rf"forceCoeffs_{re.escape(group)}\s*\{{(?P<body>.*?)\n\s*\}}",
        control_text,
        re.DOTALL,
    )
    if block_match:
        block = block_match.group("body")
        for key in ("rhoInf", "rho"):
            m = re.search(rf"\b{key}\s+([^;]+);", block)
            if m:
                meta[key] = " ".join(m.group(1).split())
    patch_match = re.search(
        rf"forceCoeffs_{re.escape(group)}\s*\{{.*?patches\s+\((.*?)\);",
        control_text,
        re.DOTALL,
    )
    if patch_match:
        meta["patches"] = " ".join(patch_match.group(1).split())
    return meta


def write_combined_history(path: Path, groups: dict[str, list[dict[str, float]]]) -> None:
    times = sorted({row["Time"] for rows in groups.values() for row in rows})
    fieldnames = ["Time"]
    for group in groups:
        for key in ("Cd", "Cl", "CmPitch", "Cs"):
            fieldnames.append(f"{group}_{key}")
    rows_by_group = {
        group: {row["Time"]: row for row in rows}
        for group, rows in groups.items()
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for time_value in times:
            payload: dict[str, Any] = {"Time": int(time_value) if time_value.is_integer() else time_value}
            for group in groups:
                row = rows_by_group[group].get(time_value, {})
                for key in ("Cd", "Cl", "CmPitch", "Cs"):
                    payload[f"{group}_{key}"] = row.get(key, "")
            writer.writerow(payload)


def stability_window(rows: list[dict[str, float]], window: int) -> dict[str, Any]:
    if len(rows) < window:
        return {"status": "insufficient_rows", "rows": len(rows), "window": window}
    tail = rows[-window:]
    result: dict[str, Any] = {"status": "available", "rows": len(tail), "window": window}
    for key in ("Cd", "Cl", "CmPitch"):
        values = [row[key] for row in tail if math.isfinite(row.get(key, math.nan))]
        if not values:
            continue
        mean = sum(values) / len(values)
        span = max(values) - min(values)
        result[key] = {
            "last": values[-1],
            "mean": mean,
            "min": min(values),
            "max": max(values),
            "span": span,
            "relative_span": None if abs(mean) < 1.0e-16 else span / abs(mean),
        }
    return result


def window_acceptance(primary: dict[str, Any], total_physical: dict[str, Any]) -> bool:
    if primary.get("status") != "available" or total_physical.get("status") != "available":
        return False
    checks = [
        total_physical.get("Cd", {}).get("relative_span", 1.0) < 0.01,
        primary.get("Cd", {}).get("relative_span", 1.0) < 0.01,
        primary.get("Cl", {}).get("relative_span", 1.0) < 0.005,
    ]
    cm = primary.get("CmPitch", {}).get("relative_span")
    if cm is not None:
        checks.append(cm < 0.01)
    return all(checks)


def sample_trend(rows: list[dict[str, float]], times: Iterable[int]) -> list[dict[str, float]]:
    by_time = {int(row["Time"]): row for row in rows}
    return [by_time[t] for t in times if t in by_time]


def parse_boundary(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    patches: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\n\s*([A-Za-z0-9_]+)\s*\{\s*type\s+([A-Za-z0-9_]+);\s*nFaces\s+([0-9]+);\s*startFace\s+([0-9]+);",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        patches.append(
            {
                "name": match.group(1),
                "type": match.group(2),
                "nFaces": int(match.group(3)),
                "startFace": int(match.group(4)),
            }
        )
    return patches


def point_bbox(path: Path) -> dict[str, Any]:
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    count = 0
    point_re = re.compile(r"\((-?[0-9.eE+\-]+)\s+(-?[0-9.eE+\-]+)\s+(-?[0-9.eE+\-]+)\)")
    if not path.exists():
        return {"point_count": 0, "bbox_min": None, "bbox_max": None}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = point_re.search(line)
        if not m:
            continue
        values = [float(m.group(i)) for i in range(1, 4)]
        for i, value in enumerate(values):
            mins[i] = min(mins[i], value)
            maxs[i] = max(maxs[i], value)
        count += 1
    return {"point_count": count, "bbox_min": mins, "bbox_max": maxs}


def compute_patch_surface_areas(case_dir: Path, boundary: list[dict[str, Any]]) -> dict[str, float]:
    points = read_points(case_dir / "constant" / "polyMesh" / "points")
    faces_path = case_dir / "constant" / "polyMesh" / "faces"
    if not points or not faces_path.exists():
        return {}
    ranges = sorted(
        (patch["startFace"], patch["startFace"] + patch["nFaces"], patch["name"])
        for patch in boundary
    )
    if not ranges:
        return {}
    areas = {name: 0.0 for _, _, name in ranges}
    range_index = 0
    face_index = 0
    face_re = re.compile(r"^\s*[0-9]+\((.*?)\)\s*$")
    for line in faces_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = face_re.match(line)
        if not m:
            continue
        while range_index < len(ranges) and face_index >= ranges[range_index][1]:
            range_index += 1
        if range_index >= len(ranges):
            break
        start, end, name = ranges[range_index]
        if start <= face_index < end:
            indices = [int(value) for value in m.group(1).split()]
            areas[name] += polygon_area(indices, points)
        face_index += 1
    return areas


def read_points(path: Path) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    point_re = re.compile(r"\((-?[0-9.eE+\-]+)\s+(-?[0-9.eE+\-]+)\s+(-?[0-9.eE+\-]+)\)")
    if not path.exists():
        return points
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = point_re.search(line)
        if m:
            points.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return points


def polygon_area(indices: list[int], points: list[tuple[float, float, float]]) -> float:
    if len(indices) < 3:
        return 0.0
    p0 = points[indices[0]]
    area = 0.0
    for i in range(1, len(indices) - 1):
        p1 = points[indices[i]]
        p2 = points[indices[i + 1]]
        ax, ay, az = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        bx, by, bz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        area += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return area


def parse_checkmesh(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    metrics: dict[str, Any] = {}
    for key, pattern in {
        "points": r"points:\s+([0-9]+)",
        "faces": r"faces:\s+([0-9]+)",
        "cells": r"cells:\s+([0-9]+)",
        "maxAspectRatio": r"Max aspect ratio = ([0-9.eE+\-]+)",
        "maxNonOrtho": r"Mesh non-orthogonality Max: ([0-9.eE+\-]+)",
        "maxSkew": r"Max skewness = ([0-9.eE+\-]+)",
        "failedChecks": r"Failed ([0-9]+) mesh checks",
    }.items():
        m = re.search(pattern, text)
        if m:
            value: Any = float(m.group(1)) if "." in m.group(1) or "e" in m.group(1).lower() else int(m.group(1))
            metrics[key] = value
    metrics["mesh_ok"] = "Mesh OK." in text
    metrics.setdefault("failedChecks", 0 if metrics["mesh_ok"] else None)
    return metrics


def parse_simple_dict(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        parts = line.rstrip(";").split(None, 1)
        if len(parts) == 2 and parts[0] in {"startFrom", "endTime", "writeInterval", "application"}:
            result[parts[0]] = parts[1].strip()
    return result


def parse_transport(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    m = re.search(r"nu\s+(?:\[[^\]]*\]\s+)?([0-9.eE+\-]+);", text)
    return {"nu": m.group(1) if m else None}


def parse_turbulence(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    result: dict[str, str] = {}
    for key in ("simulationType", "RASModel"):
        m = re.search(rf"{key}\s+([A-Za-z0-9_]+);", text)
        if m:
            result[key] = m.group(1)
    return result


def parse_u_field(path: Path) -> dict[str, str | None]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    result: dict[str, str | None] = {}
    for key in ("internalField", "freestreamValue", "inletValue"):
        m = re.search(rf"\b{key}\s+(uniform\s+\([^)]+\)|nonuniform\s+List<vector>)", text)
        result[key] = " ".join(m.group(1).split()) if m else None
    return result


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    import hashlib

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def write_diff_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["category", "item", "reference", "coarse", "match"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_window(window: dict[str, Any]) -> str:
    if window.get("status") != "available":
        return json.dumps(window, sort_keys=True)
    compact = {
        key: {
            "last": window.get(key, {}).get("last"),
            "rel_span": window.get(key, {}).get("relative_span"),
        }
        for key in ("Cd", "Cl", "CmPitch")
    }
    return json.dumps(compact, sort_keys=True)


def values_match(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return number_close(float(left), float(right))
    except Exception:
        pass
    left_numbers = extract_numbers(left)
    right_numbers = extract_numbers(right)
    if left_numbers and len(left_numbers) == len(right_numbers):
        return all(number_close(a, b) for a, b in zip(left_numbers, right_numbers))
    return False


def number_close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1.0e-9, 1.0e-4 * max(abs(left), abs(right), 1.0))


def extract_numbers(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        out: list[float] = []
        for item in value:
            out.extend(extract_numbers(item))
        return out
    if not isinstance(value, str):
        return []
    return [float(match.group(0)) for match in re.finditer(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?", value)]


def relative_error(value: Any, target: float) -> float | None:
    try:
        return (float(value) - target) / target
    except Exception:
        return None


def summarize_command(command: Any) -> dict[str, Any] | None:
    if not isinstance(command, dict):
        return None
    return {
        "returncode": command.get("returncode"),
        "timed_out": command.get("timed_out"),
        "stopped_by_runaway_guard": command.get("stopped_by_runaway_guard"),
        "runaway_time": command.get("runaway_time"),
        "elapsed_s": command.get("elapsed_s"),
    }


if __name__ == "__main__":
    main()
