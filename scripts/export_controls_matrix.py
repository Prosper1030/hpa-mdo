#!/usr/bin/env python3
"""Export linearized controls matrices from an AVL ``.st`` trim run.

Pipeline
--------
1. Load the HPA-MDO config and aircraft geometry.
2. (Optional) Build an AVL ``.mass`` file via the M14 mass budget,
   so AVL sees the correct CG / inertia during trim.
3. Call ``avl`` through :func:`hpa_mdo.aero.avl_runner.run_avl_derivatives`
   to trim at the requested CL and emit ``controls_trim.st``.
4. Parse ``.st`` into :class:`StabilityDerivatives`.
5. Dimensionalize into longitudinal + lateral-directional state-space
   matrices following Etkin & Reid body-axes conventions.
6. Write three artefacts:

   - ``stability_derivatives.json``  (all nondim derivatives + trim state)
   - ``state_space_A.csv`` / ``state_space_B.csv``  (combined 9-state form)
   - ``controls_matrix_report.md``  (human-readable summary + stability flags)

This is an **independent post-process**.  It is never invoked from the
structural optimizer; ``examples/blackcat_004_optimize.py`` stays
untouched and ``val_weight`` is unaffected.

Coordinate / sign convention (Etkin, body axes)
-----------------------------------------------
    +X forward, +Y right, +Z down
    State  x = [u, w, q, theta, v, p, r, phi, psi]  (perturbation)
    Input  u = [d_e, d_a, d_r, d_T]  (d_T is placeholder for pilot power)
    Positive elevator deflection produces negative pitching moment
    (pitch-down) — the AVL gain is ``+1`` so we do NOT flip the sign.

All nondimensional derivatives coming out of AVL are in 1/rad.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.aero.avl_runner import run_avl_derivatives  # noqa: E402
from hpa_mdo.aero.avl_stability_parser import (  # noqa: E402
    StabilityDerivatives,
    parse_control_mapping_from_avl,
    parse_st_file,
)
from hpa_mdo.core import load_config  # noqa: E402


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="Path to the HPA-MDO config YAML.",
    )
    parser.add_argument(
        "--avl",
        type=Path,
        default=REPO_ROOT / "data" / "blackcat_004_full.avl",
        help="Path to the baseline full-aircraft AVL geometry.",
    )
    parser.add_argument(
        "--cl",
        type=float,
        default=None,
        help="Trim CL.  Defaults to a CL consistent with cfg weight / V / rho / S.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=None,
        help="Alternatively, trim to a fixed alpha (deg) instead of CL.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory.  Defaults to <cfg.io.output_dir>/controls/.",
    )
    parser.add_argument(
        "--avl-binary",
        type=str,
        default=None,
        help="Override AVL binary path.  Defaults to shutil.which('avl').",
    )
    parser.add_argument(
        "--mass-file",
        type=Path,
        default=None,
        help="Pre-computed AVL .mass file.  If omitted we try to locate "
        "<cfg.io.output_dir>/avl_mass.mass (produced by M14).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="AVL subprocess timeout [s].",
    )
    return parser.parse_args()


# --------------------------------------------------------------------------
# Mass / inertia resolution (soft dependency on M14)
# --------------------------------------------------------------------------


def _resolve_mass_properties(cfg, out_dir: Path) -> Dict[str, Any]:
    """Return {mass_kg, cg_m, I_principal_kgm2, avl_mass_path} from M14 when possible.

    Falls back to cfg defaults so the report still renders when the
    mass package is missing or the budget has no inertia data.
    """

    target_mass = float(cfg.weight.max_takeoff_kg)
    cg = [0.0, 0.0, 0.0]
    inertia = [1.0, 1.0, 1.0]  # placeholder ones if unavailable
    avl_mass_path: Optional[Path] = None

    try:
        from hpa_mdo.core import Aircraft, MaterialDB  # noqa: E402
        from hpa_mdo.mass import build_mass_budget_from_config  # noqa: E402

        aircraft = Aircraft.from_config(cfg)
        materials_db = MaterialDB()
        budget = build_mass_budget_from_config(
            cfg,
            None,  # no optimizer result needed for CG / I
            aircraft=aircraft,
            materials_db=materials_db,
        )
        target_mass = float(budget.total_mass())
        cg = [float(v) for v in budget.center_of_gravity()]
        inertia_tensor = budget.inertia_tensor()
        inertia = [
            float(inertia_tensor[0, 0]),
            float(inertia_tensor[1, 1]),
            float(inertia_tensor[2, 2]),
        ]
        avl_mass_path = budget.to_avl_mass(
            out_dir / "avl_mass.mass",
            rho=float(cfg.flight.air_density),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: mass budget unavailable ({exc}); using cfg.weight fallback.")

    return {
        "mass_kg": float(target_mass),
        "cg_m": cg,
        "I_principal_kgm2": inertia,
        "avl_mass_path": avl_mass_path,
    }


# --------------------------------------------------------------------------
# State-space construction (Etkin body-axes)
# --------------------------------------------------------------------------


def _cl_from_weight(cfg, mass_kg: float) -> float:
    g = 9.80665
    qbar = 0.5 * float(cfg.flight.air_density) * float(cfg.flight.velocity) ** 2
    mean_c = 0.5 * (float(cfg.wing.root_chord) + float(cfg.wing.tip_chord))
    sref = float(cfg.wing.span) * mean_c
    if qbar <= 0.0 or sref <= 0.0:
        return 0.9
    return g * float(mass_kg) / (qbar * sref)


def _build_state_space(
    derivs: StabilityDerivatives,
    *,
    mass_kg: float,
    inertia: List[float],
    velocity: float,
    density: float,
) -> Dict[str, Any]:
    """Return dict with A, B matrices (9x9 and 9x4) plus metadata.

    Etkin & Reid body-axes, decoupled longitudinal / lateral-directional.
    Off-block couplings (e.g. Ixz) are neglected for HPA baseline.
    """

    V = float(velocity)
    rho = float(density)
    m = float(mass_kg)
    qbar = 0.5 * rho * V * V
    S = float(derivs.Sref)
    b = float(derivs.bref)
    c = float(derivs.cref)
    Ixx, Iyy, Izz = (float(inertia[0]), float(inertia[1]), float(inertia[2]))
    g = 9.80665

    # Approx trim pitch — AVL reports alpha, so theta0 = alpha at level flight.
    theta0 = math.radians(float(derivs.alpha_trim_deg) if math.isfinite(derivs.alpha_trim_deg) else 0.0)

    # ---- helpers to convert "missing" NaN to 0 in matrix slots -------
    def val(x: float) -> float:
        try:
            xf = float(x)
        except (TypeError, ValueError):
            return 0.0
        return 0.0 if (not math.isfinite(xf)) else xf

    # ---- longitudinal dimensional derivatives -----------------------
    # AVL reports CL_alpha, Cm_alpha etc. in 1/rad.
    CLa = val(derivs.CL_alpha)
    CDa = val(derivs.CD_alpha)
    Cma = val(derivs.Cm_alpha)
    CLq = val(derivs.CL_q)
    Cmq = val(derivs.Cm_q)
    CLde = val(derivs.CL_de)
    Cmde = val(derivs.Cm_de)
    CL0 = val(derivs.CL_trim)
    CD0 = val(derivs.CD_trim)

    # Stability-axis / body-axis conflation is acceptable for the
    # small-alpha HPA regime; report it in the docs.
    Xu = -(qbar * S / max(m * V, 1e-9)) * (2.0 * CD0)
    Xw = (qbar * S / max(m * V, 1e-9)) * (CL0 - CDa)
    Zu = -(qbar * S / max(m * V, 1e-9)) * (2.0 * CL0)
    Zw = -(qbar * S / max(m * V, 1e-9)) * (CLa + CD0)
    Zq = -(qbar * S * c / max(2.0 * m * V, 1e-9)) * CLq
    Mu = 0.0
    Mw = (qbar * S * c / max(Iyy * V, 1e-9)) * Cma
    Mq = (qbar * S * c * c / max(2.0 * Iyy * V, 1e-9)) * Cmq

    Xde = 0.0
    Zde = -(qbar * S / max(m, 1e-9)) * CLde
    Mde = (qbar * S * c / max(Iyy, 1e-9)) * Cmde

    # ---- lateral-directional dimensional derivatives ----------------
    CYb = val(derivs.CY_beta)
    Clb = val(derivs.Cl_beta)
    Cnb = val(derivs.Cn_beta)
    CYp = val(derivs.CY_p)
    Clp = val(derivs.Cl_p)
    Cnp = val(derivs.Cn_p)
    CYr = val(derivs.CY_r)
    Clr = val(derivs.Cl_r)
    Cnr = val(derivs.Cn_r)
    CYda = val(derivs.CY_da)
    Clda = val(derivs.Cl_da)
    Cnda = val(derivs.Cn_da)
    CYdr = val(derivs.CY_dr)
    Cldr = val(derivs.Cl_dr)
    Cndr = val(derivs.Cn_dr)

    Yv = (qbar * S / max(m * V, 1e-9)) * CYb
    Yp = (qbar * S * b / max(2.0 * m * V, 1e-9)) * CYp
    Yr = (qbar * S * b / max(2.0 * m * V, 1e-9)) * CYr
    Lv = (qbar * S * b / max(Ixx * V, 1e-9)) * Clb
    Lp = (qbar * S * b * b / max(2.0 * Ixx * V, 1e-9)) * Clp
    Lr = (qbar * S * b * b / max(2.0 * Ixx * V, 1e-9)) * Clr
    Nv = (qbar * S * b / max(Izz * V, 1e-9)) * Cnb
    Np = (qbar * S * b * b / max(2.0 * Izz * V, 1e-9)) * Cnp
    Nr = (qbar * S * b * b / max(2.0 * Izz * V, 1e-9)) * Cnr
    Yda = (qbar * S / max(m, 1e-9)) * CYda
    Lda = (qbar * S * b / max(Ixx, 1e-9)) * Clda
    Nda = (qbar * S * b / max(Izz, 1e-9)) * Cnda
    Ydr = (qbar * S / max(m, 1e-9)) * CYdr
    Ldr = (qbar * S * b / max(Ixx, 1e-9)) * Cldr
    Ndr = (qbar * S * b / max(Izz, 1e-9)) * Cndr

    # ---- Assemble 9x9 A and 9x4 B ------------------------------------
    # States : 0:u  1:w  2:q  3:theta  4:v  5:p  6:r  7:phi  8:psi
    # Inputs : 0:de 1:da 2:dr 3:dT
    A = [[0.0] * 9 for _ in range(9)]
    B = [[0.0] * 4 for _ in range(9)]

    # Longitudinal block
    A[0][0] = Xu
    A[0][1] = Xw
    A[0][3] = -g * math.cos(theta0)
    A[1][0] = Zu
    A[1][1] = Zw
    A[1][2] = V + Zq
    A[1][3] = -g * math.sin(theta0)
    A[2][0] = Mu
    A[2][1] = Mw
    A[2][2] = Mq
    A[3][2] = 1.0  # theta_dot = q
    B[0][0] = Xde
    B[1][0] = Zde
    B[2][0] = Mde

    # Lateral-directional block
    A[4][4] = Yv
    A[4][5] = Yp
    A[4][6] = Yr - V
    A[4][7] = g * math.cos(theta0)
    A[5][4] = Lv
    A[5][5] = Lp
    A[5][6] = Lr
    A[6][4] = Nv
    A[6][5] = Np
    A[6][6] = Nr
    A[7][5] = 1.0  # phi_dot = p
    A[8][6] = 1.0  # psi_dot = r  (flat-earth approx)
    B[4][1] = Yda
    B[4][2] = Ydr
    B[5][1] = Lda
    B[5][2] = Ldr
    B[6][1] = Nda
    B[6][2] = Ndr

    return {
        "A": A,
        "B": B,
        "state_names": ["u", "w", "q", "theta", "v", "p", "r", "phi", "psi"],
        "input_names": ["d_elevator", "d_aileron", "d_rudder", "d_throttle"],
        "dim_deriv_lon": {
            "Xu": Xu, "Xw": Xw, "Zu": Zu, "Zw": Zw, "Zq": Zq,
            "Mu": Mu, "Mw": Mw, "Mq": Mq,
            "Xde": Xde, "Zde": Zde, "Mde": Mde,
        },
        "dim_deriv_lat": {
            "Yv": Yv, "Yp": Yp, "Yr": Yr,
            "Lv": Lv, "Lp": Lp, "Lr": Lr,
            "Nv": Nv, "Np": Np, "Nr": Nr,
            "Yda": Yda, "Lda": Lda, "Nda": Nda,
            "Ydr": Ydr, "Ldr": Ldr, "Ndr": Ndr,
        },
    }


# --------------------------------------------------------------------------
# Output writers
# --------------------------------------------------------------------------


def _write_matrix_csv(path: Path, matrix: List[List[float]], col_names: List[str], row_names: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([""] + list(col_names))
        for name, row in zip(row_names, matrix):
            writer.writerow([name] + [f"{float(v):.9e}" for v in row])


def _stability_flags(derivs: StabilityDerivatives) -> List[Dict[str, Any]]:
    def _check(name: str, value: float, predicate: str) -> Dict[str, Any]:
        if not math.isfinite(value):
            status = "UNKNOWN"
        elif predicate == "<0":
            status = "PASS" if value < 0.0 else "WARN"
        elif predicate == ">0":
            status = "PASS" if value > 0.0 else "WARN"
        else:
            status = "UNKNOWN"
        return {"name": name, "value": value, "predicate": predicate, "status": status}

    return [
        _check("Cm_alpha", float(derivs.Cm_alpha), "<0"),
        _check("Cn_beta", float(derivs.Cn_beta), ">0"),
        _check("Cl_beta", float(derivs.Cl_beta), "<0"),
        _check("Cl_p", float(derivs.Cl_p), "<0"),
        _check("Cn_r", float(derivs.Cn_r), "<0"),
    ]


def _write_json(
    path: Path,
    derivs: StabilityDerivatives,
    ss: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    payload = {
        "schema_version": "controls_interface_v1",
        "units": {
            "angle_derivatives": "1/rad",
            "control_derivatives": "1/rad",
            "lengths": "m",
            "masses": "kg",
            "velocities": "m/s",
        },
        "axes": "body (Etkin): +X forward, +Y right, +Z down",
        "trim": {
            "alpha_deg": float(derivs.alpha_trim_deg),
            "beta_deg": float(derivs.beta_trim_deg),
            "CL": float(derivs.CL_trim),
            "CD": float(derivs.CD_trim),
            "Cm": float(derivs.Cm_trim),
            "velocity_mps": context["velocity"],
            "density_kgm3": context["density"],
        },
        "reference": {
            "Sref_m2": float(derivs.Sref),
            "bref_m": float(derivs.bref),
            "cref_m": float(derivs.cref),
            "Xref_m": float(derivs.Xref),
            "Yref_m": float(derivs.Yref),
            "Zref_m": float(derivs.Zref),
        },
        "mass_properties": {
            "mass_kg": context["mass_kg"],
            "cg_m": context["cg_m"],
            "I_principal_kgm2": context["inertia"],
        },
        "control_mapping": derivs.control_mapping,
        "nondim_derivatives": derivs.as_flat_dict(),
        "dim_derivatives_longitudinal": ss["dim_deriv_lon"],
        "dim_derivatives_lateral": ss["dim_deriv_lat"],
        "stability_flags": _stability_flags(derivs),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_report(
    path: Path,
    derivs: StabilityDerivatives,
    ss: Dict[str, Any],
    context: Dict[str, Any],
    avl_summary: Dict[str, Any],
) -> None:
    flags = _stability_flags(derivs)
    lines: List[str] = []
    lines.append("# Controls Matrix Report (M13)")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- AVL geometry : `{avl_summary.get('avl_path', 'n/a')}`")
    lines.append(f"- AVL binary   : `{avl_summary.get('binary', 'n/a')}`")
    lines.append(f"- .mass file   : `{avl_summary.get('mass_path', 'n/a')}`")
    lines.append(f"- returncode   : `{avl_summary.get('returncode', 'n/a')}`")
    if avl_summary.get("error"):
        lines.append(f"- error        : `{avl_summary['error']}`")
    lines.append("")
    lines.append("## Trim state")
    lines.append("")
    lines.append(f"- alpha = {derivs.alpha_trim_deg:.4f} deg")
    lines.append(f"- beta  = {derivs.beta_trim_deg:.4f} deg")
    lines.append(f"- CL    = {derivs.CL_trim:.4f}")
    lines.append(f"- CD    = {derivs.CD_trim:.4f}")
    lines.append(f"- Cm    = {derivs.Cm_trim:.4f}")
    lines.append(f"- V     = {context['velocity']:.3f} m/s")
    lines.append(f"- rho   = {context['density']:.4f} kg/m^3")
    lines.append("")
    lines.append("## Reference geometry")
    lines.append("")
    lines.append(f"- Sref = {derivs.Sref:.4f} m^2")
    lines.append(f"- bref = {derivs.bref:.4f} m")
    lines.append(f"- cref = {derivs.cref:.4f} m")
    lines.append(f"- Xref = {derivs.Xref:.4f} m (moment reference)")
    lines.append("")
    lines.append("## Mass / CG / Inertia (body axes)")
    lines.append("")
    lines.append(f"- mass = {context['mass_kg']:.3f} kg")
    lines.append(f"- CG   = [{context['cg_m'][0]:+.3f}, {context['cg_m'][1]:+.3f}, {context['cg_m'][2]:+.3f}] m")
    lines.append(
        "- I_principal = "
        f"[Ixx={context['inertia'][0]:.3f}, Iyy={context['inertia'][1]:.3f}, "
        f"Izz={context['inertia'][2]:.3f}] kg·m^2"
    )
    lines.append("")
    lines.append("## Control mapping (AVL d-index)")
    lines.append("")
    if derivs.control_mapping:
        for name, idx in derivs.control_mapping.items():
            lines.append(f"- d{idx} = {name}")
    else:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("## Key nondimensional derivatives (1/rad)")
    lines.append("")
    lines.append("| Name | Value | Check | Status |")
    lines.append("|------|-------|-------|--------|")
    for flag in flags:
        v = flag["value"]
        v_str = f"{v:+.6f}" if math.isfinite(v) else "nan"
        lines.append(f"| {flag['name']} | {v_str} | {flag['predicate']} | **{flag['status']}** |")
    lines.append("")
    lines.append("## Control authority (1/rad)")
    lines.append("")
    ctl_rows = [
        ("CL_de", derivs.CL_de), ("Cm_de", derivs.Cm_de),
        ("CY_da", derivs.CY_da), ("Cl_da", derivs.Cl_da), ("Cn_da", derivs.Cn_da),
        ("CY_dr", derivs.CY_dr), ("Cl_dr", derivs.Cl_dr), ("Cn_dr", derivs.Cn_dr),
    ]
    lines.append("| Name | Value |")
    lines.append("|------|-------|")
    for name, val_ in ctl_rows:
        v = float(val_)
        lines.append(f"| {name} | {v:+.6f} |" if math.isfinite(v) else f"| {name} | nan |")
    lines.append("")
    lines.append("## Dimensional derivatives (body axes, SI)")
    lines.append("")
    lines.append("### Longitudinal")
    for k, v in ss["dim_deriv_lon"].items():
        lines.append(f"- {k} = {v:+.6e}")
    lines.append("")
    lines.append("### Lateral-directional")
    for k, v in ss["dim_deriv_lat"].items():
        lines.append(f"- {k} = {v:+.6e}")
    lines.append("")
    lines.append("## State-space layout")
    lines.append("")
    lines.append("- State:  x = [u, w, q, theta, v, p, r, phi, psi]")
    lines.append("- Input:  u = [d_elevator, d_aileron, d_rudder, d_throttle]")
    lines.append("- Axes :  Etkin body axes (+X forward, +Y right, +Z down)")
    lines.append("- Units:  SI throughout; deflections in radians")
    lines.append("- Files:  `state_space_A.csv`, `state_space_B.csv`")
    lines.append("")
    lines.append("> NOTE: d_throttle is a placeholder column (all zeros) — HPA")
    lines.append("> drivetrain authority should be wired in when the pilot-power")
    lines.append("> model is finalized.  Lateral/longitudinal coupling via Ixz is")
    lines.append("> neglected (HPA baseline has near-zero product of inertia).")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)

    base_out = Path(args.out) if args.out is not None else Path(cfg.io.output_dir) / "controls"
    base_out.mkdir(parents=True, exist_ok=True)

    mass_info = _resolve_mass_properties(cfg, base_out)
    mass_file = args.mass_file
    if mass_file is None:
        mass_file = mass_info["avl_mass_path"]
    if mass_file is None:
        fallback = Path(cfg.io.output_dir) / "avl_mass.mass"
        if fallback.exists():
            mass_file = fallback

    velocity = float(cfg.flight.velocity)
    density = float(cfg.flight.air_density)
    cl_target = args.cl
    alpha_deg = args.alpha
    if cl_target is None and alpha_deg is None:
        cl_target = _cl_from_weight(cfg, mass_info["mass_kg"])

    run = run_avl_derivatives(
        avl_path=Path(args.avl),
        out_dir=base_out,
        avl_binary=args.avl_binary,
        mass_path=Path(mass_file) if mass_file is not None else None,
        cl_target=cl_target,
        alpha_deg=alpha_deg,
        velocity=velocity,
        density=density,
        timeout_s=float(args.timeout),
        stem="controls_trim",
    )

    avl_summary = {
        "avl_path": str(args.avl),
        "binary": args.avl_binary or "shutil.which('avl')",
        "mass_path": str(mass_file) if mass_file is not None else None,
        "returncode": run.returncode,
        "error": run.error,
    }

    if run.st_path is None or not run.st_path.exists():
        # Still produce a report shell so downstream CI consumers find a file.
        empty = StabilityDerivatives()
        ss = _build_state_space(
            empty,
            mass_kg=mass_info["mass_kg"],
            inertia=mass_info["I_principal_kgm2"],
            velocity=velocity,
            density=density,
        )
        context = {
            "mass_kg": mass_info["mass_kg"],
            "cg_m": mass_info["cg_m"],
            "inertia": mass_info["I_principal_kgm2"],
            "velocity": velocity,
            "density": density,
        }
        json_path = base_out / "stability_derivatives.json"
        _write_json(json_path, empty, ss, context)
        report_path = base_out / "controls_matrix_report.md"
        _write_report(report_path, empty, ss, context, avl_summary)
        _write_matrix_csv(
            base_out / "state_space_A.csv", ss["A"], ss["state_names"], ss["state_names"]
        )
        _write_matrix_csv(
            base_out / "state_space_B.csv", ss["B"], ss["input_names"], ss["state_names"]
        )
        print(f"WARN: AVL run failed ({run.error}); wrote placeholder reports to {base_out}")
        return 0

    control_mapping = parse_control_mapping_from_avl(Path(args.avl))
    derivs = parse_st_file(run.st_path, control_mapping_override=control_mapping or None)

    ss = _build_state_space(
        derivs,
        mass_kg=mass_info["mass_kg"],
        inertia=mass_info["I_principal_kgm2"],
        velocity=velocity,
        density=density,
    )
    context = {
        "mass_kg": mass_info["mass_kg"],
        "cg_m": mass_info["cg_m"],
        "inertia": mass_info["I_principal_kgm2"],
        "velocity": velocity,
        "density": density,
    }

    json_path = base_out / "stability_derivatives.json"
    _write_json(json_path, derivs, ss, context)
    report_path = base_out / "controls_matrix_report.md"
    _write_report(report_path, derivs, ss, context, avl_summary)
    _write_matrix_csv(
        base_out / "state_space_A.csv", ss["A"], ss["state_names"], ss["state_names"]
    )
    _write_matrix_csv(
        base_out / "state_space_B.csv", ss["B"], ss["input_names"], ss["state_names"]
    )

    print(f"Wrote: {json_path}")
    print(f"Wrote: {report_path}")
    print(f"Wrote: {base_out / 'state_space_A.csv'}")
    print(f"Wrote: {base_out / 'state_space_B.csv'}")
    print(
        f"Trim CL={derivs.CL_trim:.4f} alpha={derivs.alpha_trim_deg:+.3f}deg "
        f"Cm_alpha={derivs.Cm_alpha:+.4f} Cn_beta={derivs.Cn_beta:+.4f} "
        f"Cl_beta={derivs.Cl_beta:+.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
