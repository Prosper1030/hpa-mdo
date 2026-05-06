#!/usr/bin/env python3
"""Export Phase 7 sidecar AVL geometries to OpenVSP for manual inspection.

This is a diagnostic/export utility only.  It reuses the loaded-shape AVL
section geometry from the archived sidecar artifacts and swaps only the
zone-level airfoil assignment for already studied Phase 7 policies.

Two export modes are intentionally separate:

* ``avl_parity`` preserves the exact sidecar AVL/body-axis geometry.
* ``production_inspection`` produces a monotone-chord, cruise-normalized copy
  for OpenVSP/SolidWorks/manual layout inspection.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from hpa_mdo.airfoils.polar_builder import seed_airfoil_specs  # noqa: E402


SOURCE_GEOMETRY_DIR = (
    _REPO_ROOT
    / "output"
    / "airfoil_db"
    / "full_polar_archive"
    / "phase6_full_polar_sidecar"
    / "top_candidate_exports"
    / "rank_01_sample_0007"
)
SOURCE_COMBO_DIR = (
    _REPO_ROOT
    / "output"
    / "airfoil_db"
    / "full_polar_archive"
    / "phase6_full_polar_sidecar"
)
PHASE7_SIDECAR_CSV = _REPO_ROOT / "phase7_1_cst_polar_repair" / "sidecar_after_repair.csv"
FULL_POLAR_REPORT_JSON = (
    _REPO_ROOT / "output" / "airfoil_db" / "full_polar_archive" / "full_polar_build_report.json"
)
SCREENING_COORD_DIR = _REPO_ROOT / "output" / "airfoil_db" / "overnight_cst_zone_search" / "coordinates"
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "geometry_exports" / "phase7_sidecar_vsp"
CRUISE_NORMALIZED_EXPORTS_CSV = (
    _REPO_ROOT
    / "output"
    / "geometry_exports"
    / "phase7_avl_vsp_parity"
    / "cruise_normalized_exports.csv"
)
EXPORT_MODES = ("avl_parity", "production_inspection")
EXPORT_MODE_WARNINGS = {
    "avl_parity": (
        "This file is for AVL/VSP parity only. Alpha=0 is not necessarily cruise. "
        "Do not use directly for production layout."
    ),
    "production_inspection": (
        "This file is cruise-normalized and monotone-chord. Use this for "
        "VSP/SolidWorks/fairing/manual geometry inspection."
    ),
}

ZONE_BOUNDS = {
    "root": (0.00, 0.25),
    "mid1": (0.25, 0.55),
    "mid2": (0.55, 0.80),
    "tip": (0.80, 1.00),
}
CASE_DEFINITIONS = {
    "policy_A_performance_candidate": {
        "policy_id": "A",
        "assignment": "root:dae11|mid1:dae11|mid2:clarkysm|tip:clarkysm",
        "source_avl": SOURCE_COMBO_DIR
        / "avl_cases"
        / "airfoil_sidecar_shadow_34.332_0.5132_sample_0007_combo_02"
        / "concept_wing.avl",
        "source_sidecar_report": SOURCE_GEOMETRY_DIR
        / "airfoil_sidecar"
        / "combination_02_summary.json",
    },
    "policy_C_conservative_baseline": {
        "policy_id": "C",
        "assignment": (
            "root:cst_root_nsga2_g05_child_0019_00cc4dca|"
            "mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:clarkysm|tip:clarkysm"
        ),
        "source_avl": SOURCE_GEOMETRY_DIR / "concept_wing.avl",
        "source_sidecar_report": PHASE7_SIDECAR_CSV,
    },
    "case_B_CST_only": {
        "policy_id": "B",
        "assignment": (
            "root:cst_root_nsga2_g05_child_0019_00cc4dca|"
            "mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|"
            "mid2:cst_mid2_nsga2_g04_child_0024_0b55bfc3|"
            "tip:cst_tip_nsga2_g02_child_0085_cb99bc9c"
        ),
        "source_avl": SOURCE_GEOMETRY_DIR / "concept_wing.avl",
        "source_sidecar_report": PHASE7_SIDECAR_CSV,
    },
    "case_F_no_ClarkY": {
        "policy_id": "F",
        "assignment": (
            "root:cst_root_nsga2_g05_child_0019_00cc4dca|"
            "mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:dae31|tip:dae41"
        ),
        "source_avl": SOURCE_GEOMETRY_DIR / "concept_wing.avl",
        "source_sidecar_report": PHASE7_SIDECAR_CSV,
    },
}


@dataclass(frozen=True)
class AvlSection:
    x_m: float
    y_m: float
    z_m: float
    chord_m: float
    twist_deg: float
    afile: str


@dataclass(frozen=True)
class AvlGeometry:
    title: str
    sref_m2: float
    cref_m: float
    bref_m: float
    xref_m: float
    yref_m: float
    zref_m: float
    sections: tuple[AvlSection, ...]


@dataclass(frozen=True)
class ExportedSection:
    section_index: int
    eta: float
    y_m: float
    z_m: float
    chord_m: float
    twist_deg: float
    dihedral_local_z_slope: float | None
    dihedral_local_deg: float | None
    airfoil_id: str
    airfoil_source_quality: str
    airfoil_dat_path: str


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected_case_names = list(CASE_DEFINITIONS) if args.include_optional else [
        "policy_A_performance_candidate",
        "policy_C_conservative_baseline",
    ]
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    phase7_rows = _read_phase7_rows(PHASE7_SIDECAR_CSV)
    airfoil_paths = _airfoil_coordinate_paths(FULL_POLAR_REPORT_JSON)
    reports = []
    for case_name in selected_case_names:
        definition = CASE_DEFINITIONS[case_name]
        report = export_case(
            case_name=case_name,
            definition=definition,
            output_root=output_root,
            phase7_rows=phase7_rows,
            airfoil_paths=airfoil_paths,
            build_vsp=not args.no_vsp,
            export_mode=str(args.export_mode),
            incidence_offset_deg=args.incidence_offset_deg,
        )
        reports.append(report)

    summary_path = output_root / "export_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "phase7_sidecar_vsp_export_summary_v2",
                "export_mode": str(args.export_mode),
                "cases": reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output_root": str(output_root), "case_count": len(reports), "export_mode": str(args.export_mode)},
            sort_keys=True,
        )
    )
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Also export the optional CST-only and no-ClarkY diagnostic cases.",
    )
    parser.add_argument("--no-vsp", action="store_true", help="Write AVL/tables only; skip .vsp3 build.")
    parser.add_argument(
        "--export-mode",
        choices=EXPORT_MODES,
        default="production_inspection",
        help=(
            "VSP geometry mode. production_inspection is the user-facing default; "
            "use avl_parity explicitly for AVL/VSP parity debugging."
        ),
    )
    parser.add_argument(
        "--incidence-offset-deg",
        type=float,
        default=None,
        help=(
            "Optional uniform incidence override for production_inspection. "
            "By default, known Phase 7 case offsets are read from the parity audit."
        ),
    )
    return parser.parse_args(argv)


def _normalize_export_mode(export_mode: str) -> str:
    mode = str(export_mode or "production_inspection").strip()
    if mode not in EXPORT_MODES:
        raise ValueError(f"export_mode must be one of {EXPORT_MODES}: {export_mode!r}")
    return mode


def _resolve_incidence_offset_deg(
    *,
    case_name: str,
    export_mode: str,
    explicit_offset_deg: float | None,
) -> dict[str, Any]:
    if export_mode == "avl_parity":
        return {
            "incidence_offset_deg_added_to_all_sections": 0.0,
            "incidence_offset_source": "avl_body_axis_no_offset",
            "vsp_alpha0_is_cruise": False,
        }
    if explicit_offset_deg is not None:
        return {
            "incidence_offset_deg_added_to_all_sections": float(explicit_offset_deg),
            "incidence_offset_source": "explicit_override",
            "vsp_alpha0_is_cruise": True,
        }
    offset = _load_phase7_cruise_incidence_offset(case_name)
    if offset is not None:
        return {
            "incidence_offset_deg_added_to_all_sections": float(offset),
            "incidence_offset_source": "phase7_avl_alpha0_calibrated_to_CL_req",
            "vsp_alpha0_is_cruise": True,
        }
    raise ValueError(
        f"No cruise-alpha-zero incidence offset is available for {case_name!r}. "
        "Pass --incidence-offset-deg explicitly, or use --export-mode avl_parity."
    )


def _load_phase7_cruise_incidence_offset(case_name: str) -> float | None:
    if not CRUISE_NORMALIZED_EXPORTS_CSV.is_file():
        return None
    with CRUISE_NORMALIZED_EXPORTS_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("case_name") or "") != case_name:
                continue
            value = _finite_float(row.get("incidence_offset_deg_added_to_all_sections"))
            if value is not None:
                return value
    return None


def _export_mode_metadata(export_mode: str, incidence: Mapping[str, Any]) -> dict[str, Any]:
    if export_mode == "avl_parity":
        chord_mode = "original_inverse_chord"
        incidence_mode = "avl_body_axis"
        chord_enforced = False
    else:
        chord_mode = "monotone_normalized"
        incidence_mode = "cruise_alpha_zero"
        chord_enforced = True
    return {
        "export_mode": export_mode,
        "chord_mode": chord_mode,
        "incidence_mode": incidence_mode,
        "source_geometry": "sidecar_avl_loaded_shape",
        "vsp_alpha0_is_cruise": bool(incidence.get("vsp_alpha0_is_cruise")),
        "chord_monotonicity_enforced": chord_enforced,
        "incidence_offset_deg_added_to_all_sections": float(
            incidence.get("incidence_offset_deg_added_to_all_sections") or 0.0
        ),
        "incidence_offset_source": str(incidence.get("incidence_offset_source") or ""),
        "export_mode_warning": EXPORT_MODE_WARNINGS[export_mode],
    }


def export_case(
    *,
    case_name: str,
    definition: Mapping[str, Any],
    output_root: Path,
    phase7_rows: Mapping[str, Mapping[str, str]],
    airfoil_paths: Mapping[str, Path],
    build_vsp: bool = True,
    export_mode: str = "production_inspection",
    incidence_offset_deg: float | None = None,
) -> dict[str, Any]:
    mode = _normalize_export_mode(export_mode)
    incidence = _resolve_incidence_offset_deg(
        case_name=case_name,
        export_mode=mode,
        explicit_offset_deg=incidence_offset_deg,
    )
    case_dir = output_root / mode / case_name
    airfoil_dir = case_dir / "airfoils"
    case_dir.mkdir(parents=True, exist_ok=True)
    airfoil_dir.mkdir(parents=True, exist_ok=True)

    assignment = _parse_assignment(str(definition["assignment"]))
    source_avl = Path(definition["source_avl"])
    source_geometry = parse_avl_geometry(source_avl)
    quality_by_zone = _quality_by_zone(phase7_rows.get(str(definition.get("policy_id", "")), {}))

    staged_airfoils: dict[str, Path] = {}
    for airfoil_id in dict.fromkeys(assignment.values()):
        source_path = _resolve_airfoil_path(airfoil_id, airfoil_paths)
        staged = airfoil_dir / f"{airfoil_id}.dat"
        shutil.copyfile(source_path, staged)
        staged_airfoils[airfoil_id] = staged.resolve()

    exported_sections = _assigned_sections(
        source_geometry,
        assignment=assignment,
        quality_by_zone=quality_by_zone,
        staged_airfoils=staged_airfoils,
    )
    exported_sections = _apply_export_mode_to_sections(
        exported_sections,
        source_geometry=source_geometry,
        export_mode=mode,
        incidence_offset_deg=incidence["incidence_offset_deg_added_to_all_sections"],
    )
    avl_path = case_dir / f"{case_name}.avl"
    write_avl(source_geometry, exported_sections, avl_path)
    section_csv = case_dir / "section_table.csv"
    _write_csv(section_csv, [asdict(section) for section in exported_sections])

    vsp3_path = case_dir / f"{case_name}.vsp3"
    vspscript_path = case_dir / f"{case_name}.vspscript"
    vsp_report = build_vsp3_from_sections(
        exported_sections,
        output_path=vsp3_path,
        script_path=vspscript_path,
        build_vsp=build_vsp,
    )

    parity = _parity_checks(
        source_geometry=source_geometry,
        exported_sections=exported_sections,
        avl_path=avl_path,
    )
    computed_area = _computed_area_m2(exported_sections)
    computed_span = 2.0 * max(section.y_m for section in exported_sections)
    mode_metadata = _export_mode_metadata(mode, incidence)
    manifest = {
        "schema_version": "phase7_sidecar_vsp_geometry_manifest_v2",
        "case_name": case_name,
        **mode_metadata,
        "source_sidecar_report_path": str(Path(definition["source_sidecar_report"])),
        "source_avl_file_path": str(source_avl),
        "Sref": source_geometry.sref_m2,
        "Bref": source_geometry.bref_m,
        "Cref": source_geometry.cref_m,
        "computed_wing_area_m2": computed_area,
        "computed_span_m": computed_span,
        "loaded_tip_z_m": exported_sections[-1].z_m,
        "loaded_shape_mode": "loaded_dihedral_avl",
        "airfoil_assignment": assignment,
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "known_limitations": [
            "Diagnostic manual-inspection export only; no VSPAero or aerodynamic analysis was run.",
            "Main wing planform, twist, and loaded z are reconstructed from the sidecar AVL sections.",
            "OpenVSP wing sections are driven by span/chord/dihedral/twist; exact CST/DAE/ClarkY airfoil import status is recorded in vsp_export.",
            "Reference empennage/fuselage geometry is not included because the sidecar AVL source is wing-only.",
            EXPORT_MODE_WARNINGS[mode],
        ],
        "vsp_export": vsp_report,
        "parity_checks": parity,
    }
    manifest_path = case_dir / "geometry_manifest.json"
    manifest_path.write_text(json.dumps(_json_ready(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = case_dir / "export_report.md"
    report_path.write_text(
        _export_report_markdown(case_name, manifest=manifest, exported_sections=exported_sections),
        encoding="utf-8",
    )
    return {
        "case_name": case_name,
        "case_dir": str(case_dir),
        "avl_path": str(avl_path),
        "vsp3_path": str(vsp3_path) if Path(vsp3_path).is_file() else None,
        "vspscript_path": str(vspscript_path) if Path(vspscript_path).is_file() else None,
        "section_table_csv": str(section_csv),
        "geometry_manifest_json": str(manifest_path),
        "export_report_md": str(report_path),
        "parity_status": _overall_parity_status(parity),
        "vsp_status": vsp_report.get("status"),
        "export_mode": mode,
    }


def parse_avl_geometry(path: Path) -> AvlGeometry:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if len(lines) < 10:
        raise ValueError(f"AVL file is too short: {path}")
    title = lines[0].strip()
    sref = cref = bref = xref = yref = zref = None
    sections: list[AvlSection] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line == "#Sref  Cref  Bref":
            sref, cref, bref = _float_triplet(lines[index + 1])
            index += 2
            continue
        if line == "#Xref  Yref  Zref":
            xref, yref, zref = _float_triplet(lines[index + 1])
            index += 2
            continue
        if line == "SECTION":
            x, y, z, chord, twist = _float_values(lines[index + 1], expected=5)
            afile = ""
            scan = index + 2
            while scan < len(lines):
                if lines[scan].strip() == "AFILE":
                    afile = lines[scan + 1].strip()
                    break
                if lines[scan].strip() == "SECTION":
                    break
                scan += 1
            sections.append(AvlSection(x, y, z, chord, twist, afile))
        index += 1
    if None in {sref, cref, bref, xref, yref, zref} or not sections:
        raise ValueError(f"Could not parse AVL references or sections: {path}")
    return AvlGeometry(
        title=title,
        sref_m2=float(sref),
        cref_m=float(cref),
        bref_m=float(bref),
        xref_m=float(xref),
        yref_m=float(yref),
        zref_m=float(zref),
        sections=tuple(sections),
    )


def write_avl(
    source_geometry: AvlGeometry,
    sections: Sequence[ExportedSection],
    output_path: Path,
) -> Path:
    lines = [
        source_geometry.title,
        "#Mach",
        "0.000000",
        "#IYsym  iZsym  Zsym",
        "1  0  0.000000",
        "#Sref  Cref  Bref",
        f"{source_geometry.sref_m2:.9f}  {source_geometry.cref_m:.9f}  {source_geometry.bref_m:.9f}",
        "#Xref  Yref  Zref",
        f"{source_geometry.xref_m:.9f}  {source_geometry.yref_m:.9f}  {source_geometry.zref_m:.9f}",
        "#CDp",
        "0.000000",
        "#",
        "SURFACE",
        "Wing",
        f"16  1.0  {max(24, 4 * max(len(sections) - 1, 1))}  1.0",
        "#",
    ]
    for section in sections:
        lines.extend(
            [
                "SECTION",
                (
                    f"0.000000000  {section.y_m:.9f}  {section.z_m:.9f}  "
                    f"{section.chord_m:.9f}  {section.twist_deg:.9f}"
                ),
                "AFILE",
                section.airfoil_dat_path,
                "#",
            ]
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def build_vsp3_from_sections(
    sections: Sequence[ExportedSection],
    *,
    output_path: Path,
    script_path: Path,
    build_vsp: bool = True,
) -> dict[str, Any]:
    _write_vspscript(sections, script_path=script_path, vsp3_target=output_path)
    if not build_vsp:
        return {
            "status": "vsp_skipped",
            "vsp3_path": None,
            "vspscript_path": str(script_path),
            "airfoil_import_mode": "not_attempted",
        }
    try:
        import openvsp as vsp  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent.
        return {
            "status": "openvsp_unavailable",
            "vsp3_path": None,
            "vspscript_path": str(script_path),
            "error": repr(exc),
            "airfoil_import_mode": "vspscript_reference_only",
        }
    airfoil_errors: list[str] = []
    try:
        vsp.ClearVSPModel()
        wing_id = vsp.AddGeom("WING")
        vsp.SetGeomName(wing_id, "Phase7SidecarWing")
        xsec_surf = vsp.GetXSecSurf(wing_id, 0)
        n_segments = len(sections) - 1
        for _ in range(n_segments - 1):
            vsp.InsertXSec(wing_id, 1, vsp.XS_FILE_AIRFOIL)

        _assign_file_airfoil(vsp, xsec_surf, 0, Path(sections[0].airfoil_dat_path), airfoil_errors)
        _set_xsec_twist(vsp, xsec_surf, 0, sections[0].twist_deg)
        for seg_idx in range(n_segments):
            out_idx = seg_idx + 1
            inboard = sections[seg_idx]
            outboard = sections[seg_idx + 1]
            seg_span = float(outboard.y_m) - float(inboard.y_m)
            if seg_span <= 0.0:
                raise ValueError("Sections must have strictly increasing y_m.")
            xs = vsp.GetXSec(xsec_surf, out_idx)
            vsp.SetDriverGroup(
                wing_id,
                out_idx,
                vsp.SPAN_WSECT_DRIVER,
                vsp.ROOTC_WSECT_DRIVER,
                vsp.TIPC_WSECT_DRIVER,
            )
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Root_Chord"), float(inboard.chord_m))
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Tip_Chord"), float(outboard.chord_m))
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Span"), seg_span)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep"), 0.0)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep_Location"), 0.25)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Dihedral"), float(outboard.dihedral_local_deg or 0.0))
            _set_xsec_twist(vsp, xsec_surf, out_idx, outboard.twist_deg)
            vsp.Update()
            _assign_file_airfoil(vsp, xsec_surf, out_idx, Path(outboard.airfoil_dat_path), airfoil_errors)
        sym_parm = vsp.FindParm(wing_id, "Sym_Planar_Flag", "Sym")
        if sym_parm:
            vsp.SetParmVal(sym_parm, vsp.SYM_XZ)
        vsp.Update()
        vsp.WriteVSPFile(str(output_path))
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(output_path))
        vsp.Update()
    except Exception as exc:  # pragma: no cover - environment dependent.
        return {
            "status": "vsp_api_failed",
            "vsp3_path": str(output_path) if output_path.is_file() else None,
            "vspscript_path": str(script_path),
            "error": repr(exc),
            "airfoil_errors": airfoil_errors,
            "airfoil_import_mode": "failed_or_partial",
        }
    return {
        "status": "vsp3_written",
        "vsp3_path": str(output_path),
        "vspscript_path": str(script_path),
        "airfoil_errors": airfoil_errors,
        "airfoil_import_mode": "file_airfoil_imported" if not airfoil_errors else "file_airfoil_partial",
        "vsp_uses_airfoil_shapes": not airfoil_errors,
    }


def _assign_file_airfoil(vsp: Any, xsec_surf: str, xsec_idx: int, path: Path, errors: list[str]) -> None:
    try:
        vsp.ChangeXSecShape(xsec_surf, xsec_idx, vsp.XS_FILE_AIRFOIL)
        xs = vsp.GetXSec(xsec_surf, xsec_idx)
        vsp.ReadFileAirfoil(xs, str(path))
    except Exception as exc:  # pragma: no cover - environment dependent.
        errors.append(f"xsec_{xsec_idx}:{path.name}:{type(exc).__name__}:{exc}")


def _set_xsec_twist(vsp: Any, xsec_surf: str, xsec_idx: int, twist_deg: float) -> None:
    try:
        xs = vsp.GetXSec(xsec_surf, xsec_idx)
        parm = vsp.GetXSecParm(xs, "Twist")
        if parm:
            vsp.SetParmVal(parm, float(twist_deg))
    except Exception:
        return


def _write_vspscript(
    sections: Sequence[ExportedSection],
    *,
    script_path: Path,
    vsp3_target: Path,
) -> None:
    lines = [
        f"// Generated by {Path(__file__).name}; diagnostic sidecar export only.",
        "void main()",
        "{",
        "    ClearVSPModel();",
        '    string wing_id = AddGeom( "WING" );',
        '    SetGeomName( wing_id, "Phase7SidecarWing" );',
        "    string xsec_surf = GetXSecSurf( wing_id, 0 );",
    ]
    n_segments = len(sections) - 1
    for _ in range(n_segments - 1):
        lines.append("    InsertXSec( wing_id, 1, XS_FILE_AIRFOIL );")
    lines.extend(_vspscript_airfoil_block(0, Path(sections[0].airfoil_dat_path), sections[0].airfoil_id))
    for seg_idx in range(n_segments):
        out_idx = seg_idx + 1
        inboard = sections[seg_idx]
        outboard = sections[seg_idx + 1]
        seg_span = outboard.y_m - inboard.y_m
        lines.extend(
            [
                f"    // Segment {seg_idx}: eta {inboard.eta:.6f} to {outboard.eta:.6f}",
                f"    string xs_{out_idx} = GetXSec( xsec_surf, {out_idx} );",
                f"    SetDriverGroup( wing_id, {out_idx}, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER );",
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Root_Chord" ), {inboard.chord_m:.9f} );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Tip_Chord" ), {outboard.chord_m:.9f} );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Span" ), {seg_span:.9f} );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Sweep" ), 0.0 );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Sweep_Location" ), 0.25 );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Dihedral" ), {float(outboard.dihedral_local_deg or 0.0):.9f} );',
                f'    SetParmVal( GetXSecParm( xs_{out_idx}, "Twist" ), {outboard.twist_deg:.9f} );',
                "    Update();",
            ]
        )
        lines.extend(_vspscript_airfoil_block(out_idx, Path(outboard.airfoil_dat_path), outboard.airfoil_id))
    lines.extend(
        [
            '    string sym_parm = FindParm( wing_id, "Sym_Planar_Flag", "Sym" );',
            "    SetParmVal( sym_parm, SYM_XZ );",
            "    Update();",
            f'    WriteVSPFile( "{str(vsp3_target).replace(chr(92), "/")}" );',
            "}",
            "",
        ]
    )
    script_path.write_text("\n".join(lines), encoding="utf-8")


def _vspscript_airfoil_block(xsec_idx: int, path: Path, airfoil_id: str) -> list[str]:
    safe_path = str(path).replace("\\", "/")
    return [
        f"    // Airfoil: {airfoil_id}",
        f"    ChangeXSecShape( xsec_surf, {xsec_idx}, XS_FILE_AIRFOIL );",
        f"    string af_xs_{xsec_idx} = GetXSec( xsec_surf, {xsec_idx} );",
        f'    ReadFileAirfoil( af_xs_{xsec_idx}, "{safe_path}" );',
    ]


def _assigned_sections(
    source_geometry: AvlGeometry,
    *,
    assignment: Mapping[str, str],
    quality_by_zone: Mapping[str, str],
    staged_airfoils: Mapping[str, Path],
) -> tuple[ExportedSection, ...]:
    half_span = max(section.y_m for section in source_geometry.sections)
    sections: list[ExportedSection] = []
    for index, source_section in enumerate(source_geometry.sections):
        eta = 0.0 if half_span <= 0.0 else source_section.y_m / half_span
        zone = _zone_for_eta(eta)
        airfoil_id = assignment[zone]
        if index == 0:
            slope = None
            dihedral = None
        else:
            prev = source_geometry.sections[index - 1]
            dy = source_section.y_m - prev.y_m
            dz = source_section.z_m - prev.z_m
            slope = None if abs(dy) <= 1.0e-12 else dz / dy
            dihedral = None if slope is None else math.degrees(math.atan(slope))
        sections.append(
            ExportedSection(
                section_index=index,
                eta=eta,
                y_m=source_section.y_m,
                z_m=source_section.z_m,
                chord_m=source_section.chord_m,
                twist_deg=source_section.twist_deg,
                dihedral_local_z_slope=slope,
                dihedral_local_deg=dihedral,
                airfoil_id=airfoil_id,
                airfoil_source_quality=quality_by_zone.get(zone, "unknown"),
                airfoil_dat_path=str(staged_airfoils[airfoil_id]),
            )
        )
    return tuple(sections)


def _apply_export_mode_to_sections(
    sections: Sequence[ExportedSection],
    *,
    source_geometry: AvlGeometry,
    export_mode: str,
    incidence_offset_deg: float,
) -> tuple[ExportedSection, ...]:
    if export_mode == "avl_parity":
        return tuple(sections)

    monotone_chords = _monotone_area_scaled_chords(
        sections,
        target_area_m2=source_geometry.sref_m2,
    )
    return tuple(
        replace(
            section,
            chord_m=chord,
            twist_deg=float(section.twist_deg) + float(incidence_offset_deg),
        )
        for section, chord in zip(sections, monotone_chords)
    )


def _monotone_area_scaled_chords(
    sections: Sequence[ExportedSection],
    *,
    target_area_m2: float,
) -> tuple[float, ...]:
    if not sections:
        return ()
    chords = [max(float(section.chord_m), 1.0e-9) for section in sections]
    fitted = _pava_nonincreasing(chords)
    fitted_area = _area_from_y_chords(
        [float(section.y_m) for section in sections],
        fitted,
    )
    if fitted_area > 1.0e-12 and math.isfinite(float(target_area_m2)):
        scale = float(target_area_m2) / fitted_area
        fitted = [max(float(chord) * scale, 1.0e-9) for chord in fitted]
    return tuple(fitted)


def _pava_nonincreasing(values: Sequence[float]) -> list[float]:
    blocks: list[dict[str, float]] = []
    for value in values:
        blocks.append({"level": float(value), "weight": 1.0, "count": 1.0})
        while len(blocks) >= 2 and blocks[-2]["level"] < blocks[-1]["level"]:
            left = blocks.pop(-2)
            right = blocks.pop(-1)
            weight = left["weight"] + right["weight"]
            level = (left["level"] * left["weight"] + right["level"] * right["weight"]) / weight
            blocks.append({"level": level, "weight": weight, "count": left["count"] + right["count"]})
    output: list[float] = []
    for block in blocks:
        output.extend([block["level"]] * int(block["count"]))
    return output


def _area_from_y_chords(y_values: Sequence[float], chords: Sequence[float]) -> float:
    half_area = 0.0
    for y_left, y_right, chord_left, chord_right in zip(
        y_values[:-1],
        y_values[1:],
        chords[:-1],
        chords[1:],
    ):
        half_area += 0.5 * (float(chord_left) + float(chord_right)) * (float(y_right) - float(y_left))
    return 2.0 * half_area


def _parity_checks(
    *,
    source_geometry: AvlGeometry,
    exported_sections: Sequence[ExportedSection],
    avl_path: Path,
) -> list[dict[str, Any]]:
    exported_geometry = parse_avl_geometry(avl_path)
    source_sections = source_geometry.sections
    checks = [
        _check_delta("section_count", len(exported_sections), len(source_sections), tolerance=0.0),
        _check_delta("span_difference_m", 2.0 * exported_sections[-1].y_m, source_geometry.bref_m, tolerance=1.0e-6),
        _check_delta(
            "Sref_vs_computed_area_m2",
            _computed_area_m2(exported_sections),
            source_geometry.sref_m2,
            tolerance=0.05,
        ),
        _check_delta("root_chord_difference_m", exported_sections[0].chord_m, source_sections[0].chord_m, tolerance=1.0e-9),
        _check_delta("tip_chord_difference_m", exported_sections[-1].chord_m, source_sections[-1].chord_m, tolerance=1.0e-9),
        _check_delta("loaded_tip_z_difference_m", exported_sections[-1].z_m, source_sections[-1].z_m, tolerance=1.0e-9),
        _check_delta(
            "exported_avl_section_count",
            len(exported_geometry.sections),
            len(exported_sections),
            tolerance=0.0,
        ),
    ]
    max_twist_delta = max(
        abs(float(section.twist_deg) - float(source.twist_deg))
        for section, source in zip(exported_sections, source_sections)
    )
    checks.append(_check_delta("twist_distribution_max_delta_deg", max_twist_delta, 0.0, tolerance=1.0e-9))
    assignment_match = all(section.airfoil_id in Path(section.airfoil_dat_path).stem for section in exported_sections)
    checks.append(
        {
            "name": "airfoil_assignment_match",
            "status": "pass" if assignment_match else "fail",
            "observed": assignment_match,
            "expected": True,
            "delta": 0.0 if assignment_match else 1.0,
            "tolerance": 0.0,
        }
    )
    loaded_z_nonzero = abs(float(exported_sections[-1].z_m)) > 1.0e-6
    checks.append(
        {
            "name": "loaded_z_nonzero",
            "status": "pass" if loaded_z_nonzero else "fail",
            "observed": exported_sections[-1].z_m,
            "expected": "nonzero",
            "delta": None,
            "tolerance": None,
        }
    )
    return checks


def _check_delta(name: str, observed: float, expected: float, *, tolerance: float) -> dict[str, Any]:
    delta = float(observed) - float(expected)
    status = "pass" if abs(delta) <= tolerance else "warn"
    if tolerance == 0.0 and abs(delta) > 0.0:
        status = "fail"
    return {
        "name": name,
        "status": status,
        "observed": observed,
        "expected": expected,
        "delta": delta,
        "tolerance": tolerance,
    }


def _computed_area_m2(sections: Sequence[ExportedSection]) -> float:
    half_area = 0.0
    for left, right in zip(sections[:-1], sections[1:]):
        half_area += 0.5 * (left.chord_m + right.chord_m) * (right.y_m - left.y_m)
    return 2.0 * half_area


def _zone_for_eta(eta: float) -> str:
    eta_float = float(eta)
    for zone, (lo, hi) in ZONE_BOUNDS.items():
        if zone == "tip":
            if lo <= eta_float <= hi:
                return zone
        elif lo <= eta_float < hi:
            return zone
    return "tip"


def _parse_assignment(text: str) -> dict[str, str]:
    assignment: dict[str, str] = {}
    for item in text.split("|"):
        if ":" not in item:
            continue
        zone, airfoil_id = item.split(":", 1)
        assignment[zone.strip()] = airfoil_id.strip()
    missing = sorted(set(ZONE_BOUNDS) - set(assignment))
    if missing:
        raise ValueError(f"Assignment missing zones: {missing}")
    return assignment


def _read_phase7_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {str(row.get("policy_id") or ""): dict(row) for row in csv.DictReader(handle)}


def _quality_by_zone(row: Mapping[str, str]) -> dict[str, str]:
    for key in ("repaired_quality_summary", "original_archive_quality_summary"):
        text = str(row.get(key) or "")
        if not text:
            continue
        output: dict[str, str] = {}
        for item in text.split(";"):
            if ":" not in item:
                continue
            zone, quality = item.split(":", 1)
            output[zone.strip()] = quality.strip()
        if output:
            return output
    return {}


def _airfoil_coordinate_paths(report_path: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    if report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        records = payload.get("records", {})
        if isinstance(records, Mapping):
            for airfoil_id, item in records.items():
                if isinstance(item, Mapping) and item.get("coordinate_path"):
                    output[str(airfoil_id)] = Path(str(item["coordinate_path"]))
    for airfoil_id, spec in seed_airfoil_specs().items():
        output.setdefault(airfoil_id, spec.coordinate_path)
    return output


def _resolve_airfoil_path(airfoil_id: str, airfoil_paths: Mapping[str, Path]) -> Path:
    candidates = [
        airfoil_paths.get(airfoil_id),
        SCREENING_COORD_DIR / f"{airfoil_id}.dat",
        _REPO_ROOT / "data" / "airfoils" / f"{airfoil_id}.dat",
    ]
    for candidate in candidates:
        if candidate is not None and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError(f"Could not resolve airfoil dat for {airfoil_id}")


def _float_triplet(line: str) -> tuple[float, float, float]:
    values = _float_values(line, expected=3)
    return values[0], values[1], values[2]


def _float_values(line: str, *, expected: int) -> tuple[float, ...]:
    values = tuple(float(item) for item in line.split()[:expected])
    if len(values) != expected:
        raise ValueError(f"Expected {expected} float values in line: {line!r}")
    return values


def _finite_float(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(output):
        return None
    return output


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_json_ready(dict(row)) for row in rows)


def _export_report_markdown(
    case_name: str,
    *,
    manifest: Mapping[str, Any],
    exported_sections: Sequence[ExportedSection],
) -> str:
    vsp_export = manifest.get("vsp_export", {})
    parity = manifest.get("parity_checks", [])
    lines = [
        f"# {case_name}",
        "",
        "Diagnostic OpenVSP export from previously evaluated Phase 6/7 sidecar geometry.",
        "",
        f"**Export mode:** `{manifest.get('export_mode')}`",
        "",
        f"**Warning:** {manifest.get('export_mode_warning')}",
        "",
        f"- Source AVL: `{manifest.get('source_avl_file_path')}`",
        f"- Source report: `{manifest.get('source_sidecar_report_path')}`",
        f"- Assignment: `{_assignment_label(manifest.get('airfoil_assignment', {}))}`",
        f"- Chord mode: `{manifest.get('chord_mode')}`",
        f"- Incidence mode: `{manifest.get('incidence_mode')}`",
        f"- VSP alpha=0 is cruise: `{manifest.get('vsp_alpha0_is_cruise')}`",
        f"- Chord monotonicity enforced: `{manifest.get('chord_monotonicity_enforced')}`",
        f"- Incidence offset: {manifest.get('incidence_offset_deg_added_to_all_sections'):.9f} deg "
        f"({manifest.get('incidence_offset_source')})",
        f"- Sref / Bref / Cref: {manifest.get('Sref'):.9f} / {manifest.get('Bref'):.9f} / {manifest.get('Cref'):.9f}",
        f"- Computed area / span: {manifest.get('computed_wing_area_m2'):.9f} / {manifest.get('computed_span_m'):.9f}",
        f"- Loaded tip z: {manifest.get('loaded_tip_z_m'):.9f} m",
        f"- VSP status: `{vsp_export.get('status')}`",
        f"- VSP airfoil mode: `{vsp_export.get('airfoil_import_mode')}`",
        "",
        "## Parity Checks",
        "",
    ]
    for check in parity:
        lines.append(
            f"- {check.get('status')}: {check.get('name')} "
            f"(observed={check.get('observed')}, expected={check.get('expected')}, "
            f"delta={check.get('delta')}, tol={check.get('tolerance')})"
        )
    lines.extend(["", "## Section Table", ""])
    for section in exported_sections:
        lines.append(
            f"- {section.section_index}: eta={section.eta:.6f}, y={section.y_m:.6f}, "
            f"z={section.z_m:.6f}, chord={section.chord_m:.6f}, twist={section.twist_deg:.6f}, "
            f"airfoil={section.airfoil_id}"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- No VSPAero or aerodynamic analysis was run.",
            "- The source is wing-only AVL sidecar geometry, so this export is for wing manual inspection.",
            "- If `vsp_uses_airfoil_shapes` is false in the manifest, inspect the adjacent `airfoils/*.dat` files as the airfoil source of truth.",
            "",
        ]
    )
    return "\n".join(lines)


def _assignment_label(assignment: Mapping[str, Any]) -> str:
    return "|".join(f"{zone}:{assignment.get(zone)}" for zone in ("root", "mid1", "mid2", "tip"))


def _overall_parity_status(checks: Iterable[Mapping[str, Any]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
