"""ASWING seed-file exporter from AVL geometry and HPA-MDO config."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Sequence

import numpy as np

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.spar_model import (
    compute_dual_spar_section,
    compute_outer_radius,
    tube_area,
    tube_Ixx,
    tube_J,
)


@dataclass
class AVLSection:
    """Single AVL SECTION entry."""

    x: float
    y: float
    z: float
    chord: float
    ainc: float
    airfoil: str | None = None
    controls: tuple[str, ...] = ()


@dataclass
class AVLSurface:
    """AVL SURFACE with its section stations and symmetry flag."""

    name: str
    sections: list[AVLSection] = field(default_factory=list)
    yduplicate: float | None = None

    @property
    def symmetric(self) -> bool:
        return self.yduplicate is not None


@dataclass
class AVLModel:
    """Minimal AVL geometry needed by the ASWING exporter."""

    title: str
    mach: float
    sref: float
    cref: float
    bref: float
    xref: float
    yref: float
    zref: float
    surfaces: list[AVLSurface]


@dataclass(frozen=True)
class ASWINGExportOptions:
    """Knobs for generated ASWING seed-file metadata.

    Values should normally be sourced from `cfg.aswing` via
    :meth:`from_config`; the dataclass defaults here match the
    Pydantic defaults in `ASWINGExportConfig` and exist only as a
    safety net if the exporter is called without a config (e.g. a
    unit-test that constructs an AVL model in-memory).
    """

    sonic_speed_mps: float = 343.0
    cl_alpha_per_rad: float = 2.0 * math.pi
    cl_max: float = 1.35
    cl_min: float = -1.10
    tail_stiffness_eicc: float = 5.0e3
    tail_stiffness_einn: float = 2.0e3
    tail_stiffness_gj: float = 1.0e3
    tail_axial_stiffness_ea: float = 5.0e5
    tail_weight_per_length_npm: float = 0.35

    @classmethod
    def from_config(cls, cfg: HPAConfig) -> "ASWINGExportOptions":
        """Build options by reading from ``cfg.aswing`` — the single source of truth."""
        a = cfg.aswing
        return cls(
            sonic_speed_mps=float(a.sonic_speed_mps),
            cl_alpha_per_rad=float(a.cl_alpha_per_rad),
            cl_max=float(a.cl_max),
            cl_min=float(a.cl_min),
            tail_stiffness_eicc=float(a.tail_stiffness_eicc_n_m2),
            tail_stiffness_einn=float(a.tail_stiffness_einn_n_m2),
            tail_stiffness_gj=float(a.tail_stiffness_gj_n_m2),
            tail_axial_stiffness_ea=float(a.tail_axial_stiffness_ea_n),
            tail_weight_per_length_npm=float(a.tail_weight_per_length_npm),
        )


def parse_avl(path: str | Path) -> AVLModel:
    """Parse the subset of an AVL file required to seed an ASWING model."""

    lines = _clean_avl_lines(Path(path).read_text(encoding="utf-8"))
    if not lines:
        raise ValueError(f"AVL file is empty: {path}")

    title = lines[0]
    mach = 0.0
    sref = cref = bref = 0.0
    xref = yref = zref = 0.0

    idx = 1
    while idx < len(lines):
        token = lines[idx].upper()
        if token == "SURFACE":
            break
        if token.startswith("#MACH"):
            mach = float(lines[idx + 1].split()[0])
            idx += 2
        elif token.startswith("#SREF"):
            sref, cref, bref = _float_values(lines[idx + 1], 3)
            idx += 2
        elif token.startswith("#XREF"):
            xref, yref, zref = _float_values(lines[idx + 1], 3)
            idx += 2
        else:
            idx += 1

    surfaces: list[AVLSurface] = []
    while idx < len(lines):
        if lines[idx].upper() != "SURFACE":
            idx += 1
            continue

        idx += 1
        if idx >= len(lines):
            raise ValueError("AVL SURFACE block is missing a surface name.")
        surface = AVLSurface(name=lines[idx].strip())
        idx += 1

        while idx < len(lines) and lines[idx].upper() != "SURFACE":
            token = lines[idx].upper()
            if token == "YDUPLICATE":
                surface.yduplicate = float(lines[idx + 1].split()[0])
                idx += 2
            elif token == "SECTION":
                section, idx = _parse_section(lines, idx + 1)
                surface.sections.append(section)
            else:
                idx += 1

        if not surface.sections:
            raise ValueError(f"AVL surface '{surface.name}' has no SECTION entries.")
        surfaces.append(surface)

    return AVLModel(
        title=title,
        mach=mach,
        sref=sref,
        cref=cref,
        bref=bref,
        xref=xref,
        yref=yref,
        zref=zref,
        surfaces=surfaces,
    )


def export_aswing(
    avl_path: str | Path,
    cfg: HPAConfig,
    output_path: str | Path,
    *,
    materials_db: MaterialDB | None = None,
    options: ASWINGExportOptions | None = None,
) -> Path:
    """Write an ASWING ``.asw`` seed file from AVL geometry and config loads."""

    model = parse_avl(avl_path)
    materials = materials_db or MaterialDB()
    opts = options or ASWINGExportOptions.from_config(cfg)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        _render_aswing(model, cfg, materials, opts, source_avl=Path(avl_path)),
        encoding="utf-8",
    )
    return out


def _clean_avl_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.split("!", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _float_values(line: str, count: int) -> tuple[float, ...]:
    values = tuple(float(value) for value in line.split()[:count])
    if len(values) != count:
        raise ValueError(f"Expected {count} numeric values, got: {line!r}")
    return values


def _parse_section(lines: Sequence[str], idx: int) -> tuple[AVLSection, int]:
    x, y, z, chord, ainc = _float_values(lines[idx], 5)
    section = AVLSection(x=x, y=y, z=z, chord=chord, ainc=ainc)
    idx += 1
    controls: list[str] = []

    while idx < len(lines) and lines[idx].upper() not in {"SECTION", "SURFACE"}:
        token = lines[idx].upper()
        if token == "NACA":
            section.airfoil = f"NACA {lines[idx + 1].strip()}"
            idx += 2
        elif token == "AFILE":
            section.airfoil = lines[idx + 1].strip()
            idx += 2
        elif token == "CONTROL":
            controls.append(lines[idx + 1].split()[0])
            idx += 2
        else:
            idx += 1

    section.controls = tuple(controls)
    return section, idx


def _render_aswing(
    model: AVLModel,
    cfg: HPAConfig,
    materials_db: MaterialDB,
    options: ASWINGExportOptions,
    *,
    source_avl: Path,
) -> str:
    lines: list[str] = [
        "#============",
        "Name",
        f"{model.title} - ASWING seed",
        "End",
        "#============",
        "Units",
        "L 1.0 m",
        "T 1.0 s",
        "F 1.0 N",
        "End",
        "#============",
        "Constant",
        f"{_fmt(G_STANDARD)} {_fmt(cfg.flight.air_density)} {_fmt(options.sonic_speed_mps)}",
        "End",
        "#============",
        "Reference",
        "# Sref Cref Bref",
        f"{_fmt(model.sref)} {_fmt(model.cref)} {_fmt(model.bref)}",
        "# Xmom Ymom Zmom",
        f"{_fmt(model.xref)} {_fmt(model.yref)} {_fmt(model.zref)}",
        "End",
        "#============",
        f"! Source AVL: {source_avl}",
        f"! Config project: {cfg.project_name}",
        "! Structural load cases from config:",
    ]

    for load_case in cfg.structural_load_cases():
        lines.append(
            "! load_case "
            f"{load_case.name}: "
            f"aero_scale={_fmt(load_case.aero_scale)} "
            f"nz={_fmt(load_case.nz)} "
            f"V={_fmt(load_case.velocity or cfg.flight.velocity)} "
            f"rho={_fmt(load_case.air_density or cfg.flight.air_density)}"
        )

    lines.extend(_weight_block(cfg))
    lines.extend(_strut_block(model, cfg, materials_db))

    for beam_index, surface in enumerate(model.surfaces, start=1):
        lines.extend(
            _beam_block(
                beam_index,
                surface,
                cfg,
                materials_db,
                options,
            )
        )

    return "\n".join(lines) + "\n"


def _weight_block(cfg: HPAConfig) -> list[str]:
    return [
        "#============",
        "Weight",
        "# Nbeam t Xp Yp Zp Mg CDA Vol Hx Hy Hz",
        "* 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0",
        "! MTOW lumped at the wing-root reference point.",
        f"1 0.0 0.0 0.0 0.0 {_fmt(cfg.weight.max_takeoff_kg * G_STANDARD)} "
        "0.0 0.0 0.0 0.0 0.0",
        "End",
    ]


def _strut_block(
    model: AVLModel,
    cfg: HPAConfig,
    materials_db: MaterialDB,
) -> list[str]:
    if not (cfg.lift_wires.enabled and cfg.lift_wires.attachments):
        return []

    wing_entry = next(
        (
            (idx, surface)
            for idx, surface in enumerate(model.surfaces, start=1)
            if _is_wing_surface(surface)
        ),
        None,
    )
    if wing_entry is None:
        return []

    beam_index, wing = wing_entry
    cable = materials_db.get(cfg.lift_wires.cable_material)
    area = math.pi * (0.5 * cfg.lift_wires.cable_diameter) ** 2
    eaw = cable.E * area

    lines = [
        "#============",
        "Strut",
        "# Nbeam t Xp Yp Zp Xw Yw Zw dL EAw",
    ]
    for attachment in cfg.lift_wires.attachments:
        x, z = _interpolate_xz_at_y(wing, attachment.y)
        for sign in (1.0, -1.0):
            y = sign * attachment.y
            lines.append(
                f"{beam_index:d} {_fmt(y)} {_fmt(x)} {_fmt(y)} {_fmt(z)} "
                f"0.0 0.0 {_fmt(attachment.fuselage_z)} 0.0 {_fmt(eaw)}"
            )
    lines.append("End")
    return lines


def _beam_block(
    beam_index: int,
    surface: AVLSurface,
    cfg: HPAConfig,
    materials_db: MaterialDB,
    options: ASWINGExportOptions,
) -> list[str]:
    t_values = _surface_t_values(surface)
    c_cg = 0.25 if _is_wing_surface(surface) else 0.30
    x_ax = cfg.wing.spar_location_xc if _is_wing_surface(surface) else 0.25
    cd_friction = cfg.aero_gates.cd_profile_estimate

    lines = [
        "#============",
        f"Beam {beam_index:d} {surface.name}",
        "# t chord x y z Ccg",
        "* 1.0 1.0 1.0 1.0 1.0 1.0",
    ]
    for t, section in zip(t_values, surface.sections):
        lines.append(
            f"{_fmt(t)} {_fmt(section.chord)} {_fmt(section.x)} "
            f"{_fmt(section.y)} {_fmt(section.z)} {_fmt(c_cg)}"
        )

    lines.extend(
        _distribution_block(
            "t alpha Cm Cdf Cdp",
            [1.0, 1.0, 1.0, 1.0, 1.0],
            (
                (
                    t,
                    0.0,
                    0.0,
                    cd_friction,
                    0.0,
                )
                for t in t_values
            ),
        )
    )
    lines.extend(
        _distribution_block(
            "t dCLda",
            [1.0, 1.0],
            ((t, options.cl_alpha_per_rad) for t in t_values),
        )
    )
    lines.extend(
        _distribution_block(
            "t CLmax CLmin",
            [1.0, 1.0, 1.0],
            ((t, options.cl_max, options.cl_min) for t in t_values),
        )
    )
    lines.extend(
        _distribution_block(
            "t twist",
            [1.0, 1.0],
            ((t, section.ainc) for t, section in zip(t_values, surface.sections)),
        )
    )
    lines.extend(
        _distribution_block(
            "t Xax",
            [1.0, 1.0],
            ((t, x_ax) for t in t_values),
        )
    )

    for control_name, control_index in _control_indices(surface):
        sign = -1.0 if "rudd" in control_name.lower() else 1.0
        lines.extend(
            _distribution_block(
                f"t dCLdF{control_index:d} dCMdF{control_index:d}",
                [1.0, sign * math.pi / 180.0, math.pi / 180.0],
                ((t, options.cl_alpha_per_rad, -0.6) for t in t_values),
            )
        )

    stiffness = _surface_stiffness(surface, cfg, materials_db, options)
    lines.extend(
        _distribution_block(
            "t EIcc EInn GJ",
            [1.0, 1.0, 1.0, 1.0],
            zip(t_values, stiffness["EIcc"], stiffness["EInn"], stiffness["GJ"]),
        )
    )
    lines.extend(
        _distribution_block(
            "t EA mg",
            [1.0, 1.0, 1.0],
            zip(t_values, stiffness["EA"], stiffness["mg"]),
        )
    )
    lines.append("End")
    return lines


def _distribution_block(
    header: str,
    scales: Sequence[float],
    rows,
) -> list[str]:
    lines = [
        f"# {header}",
        "* " + " ".join(_fmt(scale) for scale in scales),
    ]
    for row in rows:
        lines.append(" ".join(_fmt(float(value)) for value in row))
    return lines


def _surface_stiffness(
    surface: AVLSurface,
    cfg: HPAConfig,
    materials_db: MaterialDB,
    options: ASWINGExportOptions,
) -> dict[str, np.ndarray]:
    n = len(surface.sections)
    if not _is_wing_surface(surface):
        return {
            "EIcc": np.full(n, options.tail_stiffness_eicc),
            "EInn": np.full(n, options.tail_stiffness_einn),
            "GJ": np.full(n, options.tail_stiffness_gj),
            "EA": np.full(n, options.tail_axial_stiffness_ea),
            "mg": np.full(n, options.tail_weight_per_length_npm),
        }

    y = np.asarray([section.y for section in surface.sections], dtype=float)
    chord = np.asarray([section.chord for section in surface.sections], dtype=float)
    eta = _eta(y)
    airfoil_tc = cfg.wing.airfoil_root_tc + eta * (
        cfg.wing.airfoil_tip_tc - cfg.wing.airfoil_root_tc
    )

    main = materials_db.get(cfg.main_spar.material)
    r_main = compute_outer_radius(y, chord, airfoil_tc, cfg.main_spar)
    t_main = _wall_thickness_seed(r_main, cfg.main_spar.min_wall_thickness)

    if cfg.rear_spar.enabled:
        rear = materials_db.get(cfg.rear_spar.material)
        r_rear = compute_outer_radius(y, chord, airfoil_tc, cfg.rear_spar)
        t_rear = _wall_thickness_seed(r_rear, cfg.rear_spar.min_wall_thickness)
        separation = (cfg.rear_spar.location_xc - cfg.main_spar.location_xc) * chord
        section = compute_dual_spar_section(
            R_main=r_main,
            t_main=t_main,
            R_rear=r_rear,
            t_rear=t_rear,
            z_main=np.zeros_like(y),
            z_rear=np.zeros_like(y),
            d_chord=separation,
            E_main=main.E,
            G_main=main.G,
            rho_main=main.density,
            E_rear=rear.E,
            G_rear=rear.G,
            rho_rear=rear.density,
            warping_knockdown=cfg.safety.dual_spar_warping_knockdown,
        )
        ea = main.E * section.A_main + rear.E * section.A_rear
        return {
            "EIcc": section.EI_flap,
            "EInn": section.EI_chord,
            "GJ": section.GJ,
            "EA": ea,
            "mg": section.mass_per_length * G_STANDARD,
        }

    area = tube_area(r_main, t_main)
    inertia = tube_Ixx(r_main, t_main)
    torsion = tube_J(r_main, t_main)
    return {
        "EIcc": main.E * inertia,
        "EInn": main.E * inertia,
        "GJ": main.G * torsion,
        "EA": main.E * area,
        "mg": main.density * area * G_STANDARD,
    }


def _wall_thickness_seed(radius: np.ndarray, requested_t: float) -> np.ndarray:
    return np.minimum(np.full_like(radius, requested_t), 0.8 * radius)


def _surface_t_values(surface: AVLSurface) -> np.ndarray:
    y = np.asarray([section.y for section in surface.sections], dtype=float)
    z = np.asarray([section.z for section in surface.sections], dtype=float)
    if np.ptp(y) > 1.0e-9:
        return y
    return z


def _eta(values: np.ndarray) -> np.ndarray:
    span = float(values[-1] - values[0])
    if abs(span) <= 1.0e-12:
        return np.zeros_like(values)
    return (values - values[0]) / span


def _is_wing_surface(surface: AVLSurface) -> bool:
    name = surface.name.lower().replace(" ", "")
    return name in {"wing", "mainwing"}


def _control_indices(surface: AVLSurface) -> list[tuple[str, int]]:
    controls = [
        control.lower()
        for section in surface.sections
        for control in section.controls
    ]
    if not controls:
        return []

    ordered_unique = list(dict.fromkeys(controls))
    index_by_name = {
        "aileron": 1,
        "elevator": 2,
        "rudder": 3,
        "flap": 4,
        "spoiler": 5,
    }
    next_generic_index = 6
    resolved: list[tuple[str, int]] = []
    for control in ordered_unique:
        control_key = control.lower()
        if "ail" in control_key:
            resolved.append((control, index_by_name["aileron"]))
            continue
        if "elev" in control_key:
            resolved.append((control, index_by_name["elevator"]))
            continue
        if "rudd" in control_key:
            resolved.append((control, index_by_name["rudder"]))
            continue
        if "flap" in control_key:
            resolved.append((control, index_by_name["flap"]))
            continue
        if "spoil" in control_key:
            resolved.append((control, index_by_name["spoiler"]))
            continue
        resolved.append((control, next_generic_index))
        next_generic_index += 1
    return resolved


def _interpolate_xz_at_y(surface: AVLSurface, y_target: float) -> tuple[float, float]:
    sections = sorted(surface.sections, key=lambda section: section.y)
    y = np.asarray([section.y for section in sections], dtype=float)
    x = np.asarray([section.x for section in sections], dtype=float)
    z = np.asarray([section.z for section in sections], dtype=float)
    return float(np.interp(y_target, y, x)), float(np.interp(y_target, y, z))


def _fmt(value: float) -> str:
    return f"{value:.9g}"
