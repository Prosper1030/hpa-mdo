"""Export parsed VSP geometry to AVL input format."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil

import numpy as np

from hpa_mdo.aero.vsp_geometry_parser import (
    VSPControl,
    VSPGeometryModel,
    VSPSection,
    VSPSurface,
)


@dataclass(frozen=True)
class _AVLExportSection:
    section: VSPSection
    controls: tuple[VSPControl, ...] = ()
    position: float = 0.0


def export_avl(
    geometry: VSPGeometryModel,
    output_path: Path,
    *,
    title: str | None = None,
    sref: float | None = None,
    cref: float | None = None,
    bref: float | None = None,
    xref: float = 0.0,
    yref: float = 0.0,
    zref: float = 0.0,
    mach: float = 0.0,
    airfoil_dir: Path | str | None = None,
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

    # Always use IYsym=0 so AVL can compute lateral/directional stability
    # derivatives (CYb, Cnb, Clb).  Symmetric surfaces (wing, h_stab) get
    # YDUPLICATE instead.  The vertical fin sits on the centerline and must
    # NOT be duplicated.

    lines: list[str] = [
        title or "Generated from geometry",
        "#Mach",
        f"{float(mach):.6f}",
        "#IYsym  iZsym  Zsym",
        "0  0  0.000000",
        "#Sref  Cref  Bref",
        f"{sref_out:.9f}  {cref_out:.9f}  {bref_out:.9f}",
        "#Xref  Yref  Zref",
        f"{xref_out:.9f}  {yref_out:.9f}  {zref_out:.9f}",
        "#CDp",
        "0.000000",
        "#",
    ]

    for surface in geometry.surfaces:
        export_sections = _sections_with_controls(surface)
        if not export_sections:
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
            lines.extend(["COMPONENT", "1"])
            if surface.symmetry == "xz":
                lines.extend(["YDUPLICATE", "0.0"])
            lines.append("#")
        elif surface.surface_type == "h_stab":
            lines.extend(["COMPONENT", "2"])
            if surface.symmetry == "xz":
                lines.extend(["YDUPLICATE", "0.0"])
            lines.append("#")
        elif surface.surface_type == "v_fin":
            lines.extend(["COMPONENT", "3", "#"])

        for export_section in export_sections:
            section = export_section.section
            lines.extend(
                [
                    "SECTION",
                    (
                        f"{section.x_le:.9f}  {section.y_le:.9f}  "
                        f"{section.z_le:.9f}  {section.chord:.9f}  {section.twist:.9f}"
                    ),
                ]
            )
            if section.airfoil_points:
                lines.extend(_render_inline_airfoil(section.airfoil_points))
            else:
                dat_path = _resolve_airfoil_dat(section.airfoil, airfoil_dir)
                if dat_path is not None:
                    lines.extend(["AFILE", str(dat_path)])
                else:
                    naca_digits = _naca_digits(section.airfoil)
                    if naca_digits is not None:
                        lines.extend(["NACA", naca_digits])
            for control in export_section.controls:
                comment = _control_comment(control)
                if comment is not None:
                    lines.append(comment)
                lines.extend(
                    [
                        "CONTROL",
                        _format_control_line(surface, control, export_section.position),
                    ]
                )
            lines.append("#")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def stage_avl_airfoil_files(
    avl_path: Path | str,
    *,
    airfoil_dir: Path | str | None = None,
) -> list[Path]:
    """Copy referenced AFILE coordinates into the AVL case directory.

    AVL resolves ``AFILE`` paths relative to the working directory.  Campaign
    scripts that rewrite ``case.avl`` in per-case folders therefore need the
    referenced ``.dat`` files staged next to the case file, otherwise AVL
    silently falls back to its default zero-camber airfoil.

    Returns the list of staged file paths inside ``avl_path.parent``.  Any
    successfully resolved ``AFILE`` entry is rewritten to the staged filename.
    Unresolved entries are left untouched so the caller can still inspect the
    original reference.
    """

    case_path = Path(avl_path).expanduser().resolve()
    case_dir = case_path.parent
    lines = case_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    staged: list[Path] = []
    rewritten = False
    staged_sources_by_name: dict[str, Path] = {}

    idx = 0
    while idx < len(lines):
        if lines[idx].strip().upper() != "AFILE":
            idx += 1
            continue
        if idx + 1 >= len(lines):
            break
        target_line = lines[idx + 1]
        raw_target, comment = _split_avl_data_line(target_line)
        resolved = _resolve_airfoil_dat(raw_target, airfoil_dir)
        if resolved is None:
            idx += 2
            continue
        stage_name = _unique_staged_airfoil_name(
            resolved=resolved,
            staged_sources_by_name=staged_sources_by_name,
        )
        staged_path = case_dir / stage_name
        if not staged_path.exists():
            shutil.copy2(resolved, staged_path)
        elif staged_path.resolve() != resolved.resolve() and staged_path.read_bytes() != resolved.read_bytes():
            # Different source with the same staged name should not silently
            # reuse stale contents.
            shutil.copy2(resolved, staged_path)
        staged_sources_by_name[stage_name] = resolved.resolve()
        lines[idx + 1] = f"{stage_name}{comment}"
        staged.append(staged_path)
        rewritten = True
        idx += 2

    if rewritten:
        case_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return staged


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


def _sections_with_controls(surface: VSPSurface) -> list[_AVLExportSection]:
    sections = _sections_for_export(surface)
    if not sections:
        return []

    controls = surface.controls or _default_surface_controls(surface)
    if not controls:
        return [
            _AVLExportSection(section=section, controls=(), position=position)
            for section, position in zip(sections, _normalized_span_positions(sections), strict=False)
        ]

    base_positions = _normalized_span_positions(sections)
    sample_positions = list(base_positions)
    control_intervals = [_control_interval(control) for control in controls]
    for start, end in control_intervals:
        sample_positions.extend((start, end))
    sample_positions = _merge_positions(sample_positions)

    export_sections: list[_AVLExportSection] = []
    for position in sample_positions:
        section = _interpolate_section_at_position(sections, base_positions, position)
        active_controls = tuple(
            control
            for control, (start, end) in zip(controls, control_intervals, strict=False)
            if start - 1.0e-9 <= position <= end + 1.0e-9
        )
        export_sections.append(
            _AVLExportSection(
                section=section,
                controls=active_controls,
                position=position,
            )
        )
    return export_sections


def _normalized_span_positions(sections: list[VSPSection]) -> list[float]:
    if len(sections) == 1:
        return [0.0]

    cumulative = [0.0]
    for left, right in zip(sections[:-1], sections[1:], strict=False):
        ds = float(
            np.linalg.norm(
                [
                    float(right.x_le) - float(left.x_le),
                    float(right.y_le) - float(left.y_le),
                    float(right.z_le) - float(left.z_le),
                ]
            )
        )
        cumulative.append(cumulative[-1] + max(ds, 0.0))

    total = cumulative[-1]
    if total <= 1.0e-12:
        return [0.0 for _ in sections]
    return [value / total for value in cumulative]


def _merge_positions(values: list[float], tol: float = 1.0e-9) -> list[float]:
    merged: list[float] = []
    for value in sorted(min(max(float(v), 0.0), 1.0) for v in values):
        if not merged or abs(value - merged[-1]) > tol:
            merged.append(value)
    return merged


def _render_inline_airfoil(
    points: tuple[tuple[float, float], ...],
) -> list[str]:
    lines = ["AIRFOIL"]
    for x_c, y_c in points:
        lines.append(f"{float(x_c):.9f}  {float(y_c):.9f}")
    return lines


def _split_avl_data_line(line: str) -> tuple[str, str]:
    content, bang, tail = line.partition("!")
    token = content.strip()
    comment = f"{bang}{tail}" if bang else ""
    if bang and content.endswith(" "):
        comment = f" {comment}"
    return token, comment


def _unique_staged_airfoil_name(
    *,
    resolved: Path,
    staged_sources_by_name: dict[str, Path],
) -> str:
    basename = resolved.name
    existing = staged_sources_by_name.get(basename)
    if existing is None or existing.resolve() == resolved.resolve():
        return basename
    digest = hashlib.sha1(str(resolved.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{resolved.stem}_{digest}{resolved.suffix}"


def _interpolate_section_at_position(
    sections: list[VSPSection],
    positions: list[float],
    position: float,
) -> VSPSection:
    for existing, existing_position in zip(sections, positions, strict=False):
        if abs(position - existing_position) <= 1.0e-9:
            return existing

    idx = int(np.searchsorted(np.asarray(positions, dtype=float), position, side="right"))
    hi = min(max(idx, 1), len(sections) - 1)
    lo = hi - 1
    start = positions[lo]
    end = positions[hi]
    span = max(end - start, 1.0e-12)
    weight = min(max((position - start) / span, 0.0), 1.0)

    left = sections[lo]
    right = sections[hi]

    def _lerp(a: float, b: float) -> float:
        return (1.0 - weight) * float(a) + weight * float(b)

    airfoil = left.airfoil if weight <= 0.5 else right.airfoil
    return VSPSection(
        x_le=_lerp(left.x_le, right.x_le),
        y_le=_lerp(left.y_le, right.y_le),
        z_le=_lerp(left.z_le, right.z_le),
        chord=_lerp(left.chord, right.chord),
        twist=_lerp(left.twist, right.twist),
        airfoil=str(airfoil),
    )


def _default_surface_controls(surface: VSPSurface) -> list[VSPControl]:
    if surface.surface_type == "h_stab":
        return [
            VSPControl(
                name="elevator",
                control_type="elevator",
                eta_start=0.0,
                eta_end=1.0,
                chord_fraction_start=1.0,
                chord_fraction_end=1.0,
            )
        ]
    if surface.surface_type == "v_fin":
        return [
            VSPControl(
                name="rudder",
                control_type="rudder",
                eta_start=0.0,
                eta_end=1.0,
                chord_fraction_start=1.0,
                chord_fraction_end=1.0,
            )
        ]
    return []


def _control_interval(control: VSPControl) -> tuple[float, float]:
    start = 0.0 if control.eta_start is None else float(control.eta_start)
    end = 1.0 if control.eta_end is None else float(control.eta_end)
    start = min(max(start, 0.0), 1.0)
    end = min(max(end, 0.0), 1.0)
    if end < start:
        start, end = end, start
    return start, end


def _control_comment(control: VSPControl) -> str | None:
    control_type = str(control.control_type).lower()
    if control_type == "elevator":
        return "! elevator command limit is applied externally"
    if control_type == "rudder":
        return "! rudder command limit is applied externally"
    return None


def _format_control_line(
    surface: VSPSurface,
    control: VSPControl,
    position: float,
) -> str:
    xhinge = _control_xhinge(surface, control, position)
    hx, hy, hz = _control_hinge_vector(surface, control)
    sign_dup = _control_sign_dup(surface, control)
    return (
        f"{control.name}  1.0  {xhinge:.6f}  "
        f"{hx:.1f} {hy:.1f} {hz:.1f}  {sign_dup:.1f}"
    )


def _control_xhinge(surface: VSPSurface, control: VSPControl, position: float) -> float:
    chord_fraction = _control_chord_fraction(surface, control, position)
    edge = str(control.edge or "trailing").lower()
    if edge == "leading":
        return min(max(chord_fraction, 0.0), 1.0)
    return min(max(1.0 - chord_fraction, 0.0), 1.0)


def _control_chord_fraction(
    surface: VSPSurface,
    control: VSPControl,
    position: float,
) -> float:
    c0 = control.chord_fraction_start
    c1 = control.chord_fraction_end
    if c0 is None and c1 is None:
        if surface.surface_type in {"h_stab", "v_fin"} and control.control_type in {"elevator", "rudder"}:
            return 1.0
        return 0.25
    if c0 is None:
        c0 = c1
    if c1 is None:
        c1 = c0
    start, end = _control_interval(control)
    if end - start <= 1.0e-12:
        fraction = float(c0)
    else:
        blend = min(max((position - start) / (end - start), 0.0), 1.0)
        fraction = (1.0 - blend) * float(c0) + blend * float(c1)
    return min(max(float(fraction), 0.0), 1.0)


def _control_hinge_vector(surface: VSPSurface, control: VSPControl) -> tuple[float, float, float]:
    control_type = str(control.control_type).lower()
    if surface.surface_type == "v_fin" or control_type == "rudder":
        return (0.0, 0.0, 1.0)
    return (0.0, 0.0, 0.0)


def _control_sign_dup(surface: VSPSurface, control: VSPControl) -> float:
    if surface.symmetry != "xz":
        return 1.0
    if str(control.control_type).lower() == "aileron":
        return -1.0
    return 1.0


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
        base_area = float(abs(np.trapezoid(chord[order], y[order])))
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
    # Only treat the name as NACA if it begins with "naca" (case-insensitive).
    # Plain digit substrings in names like "fx76mp140" must not trigger NACA.
    match = re.match(r"\s*naca[\s_-]*([0-9]{4,5})", str(airfoil), flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1)


def _resolve_airfoil_dat(
    airfoil: str,
    airfoil_dir: Path | str | None,
) -> Path | None:
    """Locate an airfoil .dat coordinate file for AVL's AFILE directive.

    Searches, in order: the provided airfoil_dir, the repo's data/airfoils,
    the configured SyncFile path, and any absolute path given as the name.
    Returns None if no file is found or the name is clearly a NACA series
    (which AVL handles natively via the NACA directive).
    """
    name = str(airfoil).strip()
    if not name:
        return None
    if _naca_digits(name) is not None:
        # NACA takes precedence — AVL handles it natively.
        return None

    candidates: list[Path] = []
    as_path = Path(name)
    if as_path.is_absolute() and as_path.exists():
        return as_path.resolve()

    search_dirs: list[Path] = []
    if airfoil_dir is not None:
        search_dirs.append(Path(airfoil_dir).expanduser())
    # Repo-local fallback locations.
    repo_guess = Path(__file__).resolve().parents[3]
    search_dirs.extend(
        [
            repo_guess / "data" / "airfoils",
            repo_guess / "Aerodynamics" / "airfoil",
        ]
    )
    # SyncFile location used elsewhere in the project.
    search_dirs.append(Path("/Volumes/Samsung SSD/SyncFile/Aerodynamics/airfoil"))

    stem = as_path.stem or name
    for directory in search_dirs:
        if not directory.exists():
            continue
        for suffix in (".dat", ".txt"):
            candidate = directory / f"{stem}{suffix}"
            if candidate.exists():
                candidates.append(candidate)
        # Case-insensitive match as a last resort.
        try:
            for entry in directory.iterdir():
                if entry.is_file() and entry.stem.lower() == stem.lower():
                    candidates.append(entry)
        except OSError:
            continue
        if candidates:
            return candidates[0].resolve()
    return None
