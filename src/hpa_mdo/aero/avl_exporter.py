"""Export parsed VSP geometry to AVL input format."""

from __future__ import annotations

from pathlib import Path
import re

import numpy as np

from hpa_mdo.aero.vsp_geometry_parser import VSPGeometryModel, VSPSection, VSPSurface


def export_avl(
    geometry: VSPGeometryModel,
    output_path: Path,
    *,
    sref: float | None = None,
    cref: float | None = None,
    bref: float | None = None,
    xref: float = 0.0,
    yref: float = 0.0,
    zref: float = 0.0,
    mach: float = 0.0,
) -> Path:
    """Export VSPGeometryModel to AVL format .avl file."""
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    wing = geometry.get_wing()
    if wing is not None:
        wing_sections = _sections_for_export(wing)
    else:
        wing_sections = []

    sref_out = float(sref) if sref is not None else _auto_sref(geometry=geometry, wing=wing)
    bref_out = float(bref) if bref is not None else _auto_bref(geometry=geometry, wing=wing)
    cref_out = float(cref) if cref is not None else _auto_cref(sref=sref_out, bref=bref_out, wing=wing)
    xref_out = float(xref)
    yref_out = float(yref)
    zref_out = float(zref)
    if wing_sections and xref == 0.0:
        xref_out = 0.25 * float(wing_sections[0].chord)

    has_xz_symmetry = any(surface.symmetry == "xz" for surface in geometry.surfaces)
    ysym = 1 if has_xz_symmetry else 0

    lines: list[str] = [
        "Generated from VSP3 geometry",
        "#Mach",
        f"{float(mach):.6f}",
        "#IYsym  iZsym  Zsym",
        f"{ysym}  0  0.000000",
        "#Sref  Cref  Bref",
        f"{sref_out:.9f}  {cref_out:.9f}  {bref_out:.9f}",
        "#Xref  Yref  Zref",
        f"{xref_out:.9f}  {yref_out:.9f}  {zref_out:.9f}",
        "#CDp",
        "0.000000",
        "#",
    ]

    for surface in geometry.surfaces:
        sections = _sections_for_export(surface)
        if not sections:
            continue
        lines.extend(
            [
                "SURFACE",
                surface.name,
                "12  1.0  30  -2.0",
                "#",
            ]
        )
        if surface.surface_type == "wing":
            lines.extend(["COMPONENT", "1", "#"])
        elif surface.surface_type == "h_stab":
            lines.extend(["COMPONENT", "2", "#"])
        elif surface.surface_type == "v_fin":
            lines.extend(["COMPONENT", "3", "#"])

        for section in sections:
            lines.extend(
                [
                    "SECTION",
                    (
                        f"{section.x_le:.9f}  {section.y_le:.9f}  "
                        f"{section.z_le:.9f}  {section.chord:.9f}  {section.twist:.9f}"
                    ),
                ]
            )
            naca_digits = _naca_digits(section.airfoil)
            if naca_digits is not None:
                lines.extend(["NACA", naca_digits])
            if surface.surface_type == "h_stab":
                lines.extend(
                    [
                        "! elevator command limit is applied externally (e.g. +/-20 deg)",
                        "CONTROL",
                        "elevator  1.0  0.0  0.0 0.0 0.0  1.0",
                    ]
                )
            elif surface.surface_type == "v_fin":
                lines.extend(
                    [
                        "! rudder command limit is applied externally (e.g. +/-25 deg)",
                        "CONTROL",
                        "rudder  1.0  0.0  0.0 0.0 0.0  1.0",
                    ]
                )
            lines.append("#")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _sections_for_export(surface: VSPSurface) -> list[VSPSection]:
    sections = sorted(surface.sections, key=lambda section: float(section.y_le))
    if surface.symmetry != "xz":
        return sections

    non_negative = [section for section in sections if float(section.y_le) >= -1.0e-9]
    if non_negative:
        return non_negative
    mirrored: list[VSPSection] = []
    for section in sections:
        mirrored.append(
            VSPSection(
                x_le=float(section.x_le),
                y_le=abs(float(section.y_le)),
                z_le=float(section.z_le),
                chord=float(section.chord),
                twist=float(section.twist),
                airfoil=str(section.airfoil),
            )
        )
    return sorted(mirrored, key=lambda section: float(section.y_le))


def _auto_sref(*, geometry: VSPGeometryModel, wing: VSPSurface | None) -> float:
    if wing is not None:
        return max(_surface_area(wing), 1.0e-9)
    area = sum(_surface_area(surface) for surface in geometry.surfaces)
    return max(float(area), 1.0e-9)


def _auto_bref(*, geometry: VSPGeometryModel, wing: VSPSurface | None) -> float:
    if wing is not None:
        return max(_surface_span(wing), 1.0e-9)
    spans = [_surface_span(surface) for surface in geometry.surfaces]
    return max(float(max(spans) if spans else 1.0), 1.0e-9)


def _auto_cref(*, sref: float, bref: float, wing: VSPSurface | None) -> float:
    if wing is not None:
        sections = _sections_for_export(wing)
        if sections:
            return max(float(np.mean([section.chord for section in sections])), 1.0e-9)
    return max(float(sref) / max(float(bref), 1.0e-9), 1.0e-9)


def _surface_area(surface: VSPSurface) -> float:
    sections = _sections_for_export(surface)
    if not sections:
        return 0.0
    if len(sections) == 1:
        base_area = float(sections[0].chord)
    else:
        y = np.asarray([float(section.y_le) for section in sections], dtype=float)
        chord = np.asarray([float(section.chord) for section in sections], dtype=float)
        order = np.argsort(y)
        base_area = float(abs(np.trapz(chord[order], y[order])))
    if surface.symmetry == "xz":
        base_area *= 2.0
    return float(base_area)


def _surface_span(surface: VSPSurface) -> float:
    sections = _sections_for_export(surface)
    if not sections:
        return 0.0
    y_vals = np.asarray([float(section.y_le) for section in sections], dtype=float)
    if surface.symmetry == "xz":
        return float(2.0 * max(abs(y_vals.min()), abs(y_vals.max())))
    return float(abs(y_vals.max() - y_vals.min()))


def _naca_digits(airfoil: str) -> str | None:
    match = re.search(r"([0-9]{4,5})", str(airfoil))
    if match is None:
        return None
    return match.group(1)
