from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field


GeometryProvenanceStatusType = Literal["provenance_available", "provenance_missing"]


class MainWingSectionProvenance(BaseModel):
    index: int
    span_m: float | None = None
    root_chord_m: float | None = None
    tip_chord_m: float | None = None
    twist_deg: float | None = None
    dihedral_deg: float | None = None
    sweep_deg: float | None = None
    thick_chord: float | None = None
    airfoil_name: str | None = None
    airfoil_max_camber_over_chord: float | None = None
    airfoil_max_thickness_over_chord: float | None = None
    airfoil_point_count: int | None = None


class MainWingGeometryProvenanceProbeReport(BaseModel):
    schema_version: Literal["main_wing_geometry_provenance_probe.v1"] = (
        "main_wing_geometry_provenance_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["vsp3_geometry_provenance_no_solver"] = (
        "vsp3_geometry_provenance_no_solver"
    )
    production_default_changed: bool = False
    geometry_provenance_status: GeometryProvenanceStatusType
    source_path: str
    selected_geom_id: str | None = None
    selected_geom_name: str | None = None
    x_rotation_deg: float | None = None
    y_rotation_deg: float | None = None
    z_rotation_deg: float | None = None
    installation_incidence_deg: float | None = None
    section_count: int = 0
    sections: List[MainWingSectionProvenance] = Field(default_factory=list)
    twist_summary: Dict[str, Any] = Field(default_factory=dict)
    airfoil_summary: Dict[str, Any] = Field(default_factory=dict)
    alpha_zero_interpretation: str = "not_evaluated"
    engineering_assessment: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_source_path() -> Path:
    return _repo_root() / "data" / "blackcat_004_origin.vsp3"


def _float_attr(element: ET.Element | None, child_name: str) -> float | None:
    child = element.find(child_name) if element is not None else None
    if child is None:
        return None
    try:
        return float(child.attrib.get("Value", ""))
    except ValueError:
        return None


def _point_values(text: str | None) -> list[tuple[float, float]]:
    if not text:
        return []
    values: list[float] = []
    for raw in text.replace("\n", " ").split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    points: list[tuple[float, float]] = []
    for index in range(0, len(values) - 2, 3):
        points.append((values[index], values[index + 1]))
    return points


def _airfoil_metrics(file_airfoil: ET.Element | None) -> dict[str, Any]:
    if file_airfoil is None:
        return {}
    upper = _point_values(file_airfoil.findtext("UpperPnts"))
    lower = _point_values(file_airfoil.findtext("LowerPnts"))
    paired_count = min(len(upper), len(lower))
    if paired_count <= 0:
        return {"point_count": 0}
    cambers = [(upper[i][1] + lower[i][1]) * 0.5 for i in range(paired_count)]
    thicknesses = [upper[i][1] - lower[i][1] for i in range(paired_count)]
    return {
        "point_count": paired_count,
        "max_camber_over_chord": max(cambers, key=abs),
        "max_thickness_over_chord": max(thicknesses),
    }


def _find_main_wing(root: ET.Element) -> ET.Element | None:
    for geom in root.findall(".//Geom"):
        name = geom.findtext("./ParmContainer/Name")
        geom_id = geom.findtext("./ParmContainer/ID")
        if name == "Main Wing" or geom_id == "IPAWXFWPQF":
            return geom
    return None


def _section_from_xsec(index: int, xsec: ET.Element) -> MainWingSectionProvenance:
    params = xsec.find("./ParmContainer/XSec")
    file_airfoil = xsec.find(".//FileAirfoil")
    metrics = _airfoil_metrics(file_airfoil)
    curve_params = xsec.find(".//ParmContainer/XSecCurve")
    airfoil_name = file_airfoil.findtext("AirfoilName") if file_airfoil is not None else None
    return MainWingSectionProvenance(
        index=index,
        span_m=_float_attr(params, "Span"),
        root_chord_m=_float_attr(params, "Root_Chord"),
        tip_chord_m=_float_attr(params, "Tip_Chord"),
        twist_deg=_float_attr(params, "Twist"),
        dihedral_deg=_float_attr(params, "Dihedral"),
        sweep_deg=_float_attr(params, "Sweep"),
        thick_chord=_float_attr(params, "ThickChord") or _float_attr(curve_params, "ThickChord"),
        airfoil_name=airfoil_name.strip() if isinstance(airfoil_name, str) else None,
        airfoil_max_camber_over_chord=metrics.get("max_camber_over_chord"),
        airfoil_max_thickness_over_chord=metrics.get("max_thickness_over_chord"),
        airfoil_point_count=metrics.get("point_count"),
    )


def _twist_summary(sections: list[MainWingSectionProvenance]) -> dict[str, Any]:
    values = [section.twist_deg for section in sections if section.twist_deg is not None]
    if not values:
        return {"status": "unavailable"}
    return {
        "status": "available",
        "min_twist_deg": min(values),
        "max_twist_deg": max(values),
        "all_sections_zero_twist": all(abs(value) <= 1.0e-9 for value in values),
    }


def _airfoil_summary(sections: list[MainWingSectionProvenance]) -> dict[str, Any]:
    names = [
        section.airfoil_name.strip()
        for section in sections
        if isinstance(section.airfoil_name, str) and section.airfoil_name.strip()
    ]
    cambers = [
        section.airfoil_max_camber_over_chord
        for section in sections
        if section.airfoil_max_camber_over_chord is not None
    ]
    thicknesses = [
        section.airfoil_max_thickness_over_chord
        for section in sections
        if section.airfoil_max_thickness_over_chord is not None
    ]
    return {
        "unique_airfoil_names": sorted(set(names)),
        "cambered_airfoil_coordinates_observed": any(
            abs(value) > 1.0e-4 for value in cambers
        ),
        "max_abs_camber_over_chord": max((abs(value) for value in cambers), default=None),
        "max_thickness_over_chord": max(thicknesses) if thicknesses else None,
    }


def _alpha_zero_interpretation(
    *,
    installation_incidence_deg: float | None,
    airfoil_summary: dict[str, Any],
) -> str:
    positive_incidence = (
        installation_incidence_deg is not None and installation_incidence_deg > 0.0
    )
    cambered_airfoils = bool(airfoil_summary.get("cambered_airfoil_coordinates_observed"))
    if positive_incidence and cambered_airfoils:
        return "alpha_zero_expected_positive_lift_but_not_acceptance_lift"
    if positive_incidence:
        return "alpha_zero_positive_incidence_observed"
    if cambered_airfoils:
        return "alpha_zero_cambered_airfoils_observed"
    return "alpha_zero_geometry_lift_source_not_observed"


def _engineering_assessment(
    *,
    installation_incidence_deg: float | None,
    twist_summary: dict[str, Any],
    airfoil_summary: dict[str, Any],
) -> list[str]:
    assessment = [
        "This probe reads OpenVSP geometry provenance only and does not execute Gmsh or SU2.",
    ]
    if installation_incidence_deg is not None:
        assessment.append(
            f"Main Wing has Y_Rotation={installation_incidence_deg:.6g} deg, "
            "so SU2 alpha=0 freestream is not necessarily a zero-lift geometry point."
        )
    if twist_summary.get("all_sections_zero_twist") is True:
        assessment.append(
            "All parsed main-wing sections report zero local twist; the alpha-zero lift source is incidence and airfoil camber, not spanwise twist washout."
        )
    if airfoil_summary.get("cambered_airfoil_coordinates_observed"):
        assessment.append(
            "Embedded airfoil coordinates are cambered, supporting a positive alpha-zero CL reading."
        )
    assessment.append(
        "A positive CL around the current smoke value can be physically plausible, but CL below 1 remains an operational lift-acceptance blocker at V=6.5 m/s."
    )
    return assessment


def build_main_wing_geometry_provenance_probe_report(
    *,
    source_path: Path | None = None,
) -> MainWingGeometryProvenanceProbeReport:
    source = _default_source_path() if source_path is None else source_path
    try:
        root = ET.parse(source).getroot()
    except Exception as exc:
        return MainWingGeometryProvenanceProbeReport(
            geometry_provenance_status="provenance_missing",
            source_path=str(source),
            error=str(exc),
            hpa_mdo_guarantees=["production_default_unchanged", "no_solver_execution"],
            limitations=["Source VSP3 geometry could not be parsed."],
        )
    geom = _find_main_wing(root)
    if geom is None:
        return MainWingGeometryProvenanceProbeReport(
            geometry_provenance_status="provenance_missing",
            source_path=str(source),
            error="Main Wing geometry not found",
            hpa_mdo_guarantees=["production_default_unchanged", "no_solver_execution"],
            limitations=["Main Wing geometry could not be found in source VSP3."],
        )
    xform = geom.find("./ParmContainer/XForm")
    xsec_surf = geom.find(".//XSecSurf")
    sections = [
        _section_from_xsec(index, xsec)
        for index, xsec in enumerate(xsec_surf.findall("./XSec") if xsec_surf is not None else [])
    ]
    twist = _twist_summary(sections)
    airfoils = _airfoil_summary(sections)
    y_rotation = _float_attr(xform, "Y_Rotation")
    return MainWingGeometryProvenanceProbeReport(
        geometry_provenance_status="provenance_available",
        source_path=str(source),
        selected_geom_id=geom.findtext("./ParmContainer/ID"),
        selected_geom_name=geom.findtext("./ParmContainer/Name"),
        x_rotation_deg=_float_attr(xform, "X_Rotation"),
        y_rotation_deg=y_rotation,
        z_rotation_deg=_float_attr(xform, "Z_Rotation"),
        installation_incidence_deg=y_rotation,
        section_count=len(sections),
        sections=sections,
        twist_summary=twist,
        airfoil_summary=airfoils,
        alpha_zero_interpretation=_alpha_zero_interpretation(
            installation_incidence_deg=y_rotation,
            airfoil_summary=airfoils,
        ),
        engineering_assessment=_engineering_assessment(
            installation_incidence_deg=y_rotation,
            twist_summary=twist,
            airfoil_summary=airfoils,
        ),
        next_actions=[
            "treat_alpha_zero_solver_smoke_as_geometry_incidence_point_not_trim_validation",
            "run_alpha_trim_sanity_probe_only_after_solver_validation_policy_is_respected",
            "keep_cl_gt_one_acceptance_gate_for_convergence_claims",
        ],
        hpa_mdo_guarantees=[
            "production_default_unchanged",
            "no_gmsh_execution",
            "no_su2_execution",
            "vsp3_source_geometry_provenance",
        ],
        limitations=[
            "This probe reads VSP3 XML and embedded airfoil coordinates; it does not certify aerodynamic performance.",
            "OpenVSP incidence/twist/camber provenance explains why alpha=0 may have positive lift, not whether the current SU2 run is converged.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_markdown(report: MainWingGeometryProvenanceProbeReport) -> str:
    lines = [
        "# Main Wing Geometry Provenance Probe v1",
        "",
        "This report reads OpenVSP geometry provenance only; it does not execute Gmsh or SU2.",
        "",
        f"- geometry_provenance_status: `{report.geometry_provenance_status}`",
        f"- source_path: `{report.source_path}`",
        f"- selected_geom_name: `{_fmt(report.selected_geom_name)}`",
        f"- selected_geom_id: `{_fmt(report.selected_geom_id)}`",
        f"- installation_incidence_deg: `{_fmt(report.installation_incidence_deg)}`",
        f"- section_count: `{report.section_count}`",
        f"- alpha_zero_interpretation: `{report.alpha_zero_interpretation}`",
        "",
        "## Summaries",
        "",
        f"- twist_summary: `{_fmt(report.twist_summary)}`",
        f"- airfoil_summary: `{_fmt(report.airfoil_summary)}`",
        "",
        "## Sections",
        "",
        "| index | span | root_chord | tip_chord | twist | dihedral | sweep | airfoil | max_camber | max_thickness |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for section in report.sections:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(section.index),
                    _fmt(section.span_m),
                    _fmt(section.root_chord_m),
                    _fmt(section.tip_chord_m),
                    _fmt(section.twist_deg),
                    _fmt(section.dihedral_deg),
                    _fmt(section.sweep_deg),
                    _fmt(section.airfoil_name),
                    _fmt(section.airfoil_max_camber_over_chord),
                    _fmt(section.airfoil_max_thickness_over_chord),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Engineering Assessment", ""])
    lines.extend(f"- {item}" for item in report.engineering_assessment)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{item}`" for item in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_geometry_provenance_probe_report(
    out_dir: Path,
    *,
    report: MainWingGeometryProvenanceProbeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_geometry_provenance_probe_report(source_path=source_path)
    json_path = out_dir / "main_wing_geometry_provenance_probe.v1.json"
    markdown_path = out_dir / "main_wing_geometry_provenance_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
