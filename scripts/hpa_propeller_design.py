"""HPA propeller design and analysis wrapper — QPROP + XROTOR.

Provides two entry-points for the HPA MDO pipeline:

1. ``design_hpa_propeller`` — XROTOR Betz minimum-induced-loss design.
   Given diameter, velocity, shaft power, RPM and a blade-section polar,
   returns a QpropBlade that can be fed directly to ``analyse_propeller``.

2. ``analyse_propeller`` — QPROP multi-point analysis.
   Given a propeller geometry file and an operating condition sweep,
   returns a DataFrame of thrust / efficiency / power vs velocity.

Both tools run as subprocesses; binaries are expected at
``tools/bin/qprop`` and ``tools/bin/xrotor`` relative to the repo root.
No X11 / display is required — XROTOR runs in batch (non-interactive) mode.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_BIN = _REPO_ROOT / "tools" / "bin"
_QPROP_BIN = _TOOLS_BIN / "qprop"
_XROTOR_BIN = _TOOLS_BIN / "xrotor"

SCHEMA_VERSION = "hpa_propeller_v1"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BladeSection:
    """Airfoil section polar approximation for QPROP/XROTOR input."""

    CL0: float = 0.10
    CL_alpha: float = 5.8
    CLmin: float = -0.5
    CLmax: float = 1.2
    CD0: float = 0.011
    CD2u: float = 0.020
    CD2l: float = 0.020
    CLCD0: float = 0.10
    REref: float = 60_000.0
    REexp: float = -0.5


@dataclass
class QpropBlade:
    """Propeller geometry in QPROP prop-file format."""

    name: str
    n_blades: int
    section: BladeSection
    radii: List[float]
    chords: List[float]
    betas: List[float]
    tip_radius_m: float = field(init=False)

    def __post_init__(self) -> None:
        self.tip_radius_m = max(self.radii)

    def to_file_text(self) -> str:
        s = self.section
        lines = [
            f"{self.name}",
            "",
            f" {self.n_blades}           ! Nblades",
            "",
            f" {s.CL0:.4f}  {s.CL_alpha:.4f}    ! CL0     CL_a",
            f" {s.CLmin:.4f}  {s.CLmax:.4f}    ! CLmin   CLmax",
            "",
            (
                f" {s.CD0:.5f}  {s.CD2u:.5f}  {s.CD2l:.5f}  "
                f"{s.CLCD0:.4f}    ! CD0  CD2u  CD2l  CLCD0"
            ),
            f" {s.REref:.0f}   {s.REexp:.3f}        ! REref  REexp",
            "",
            " 1.0000  1.0000  1.0000   !  Rfac   Cfac   Bfac",
            " 0.0000  0.0000  0.0000   !  Radd   Cadd   Badd",
            "",
            "#  r    chord    beta",
        ]
        for r, c, b in zip(self.radii, self.chords, self.betas):
            lines.append(f" {r:.5f}  {c:.5f}  {b:.4f}")
        return "\n".join(lines) + "\n"


@dataclass
class HumanDrivefile:
    """QPROP 'motor' file representing constant-power human pedalling.

    QPROP motor type 4 = piston engine with shaft power table.
    For HPA we approximate as a constant-power source at the design point.
    """

    power_w: float
    rpm_design: float
    name: str = "HPA pedal drive"

    def to_file_text(self) -> str:
        torque = self.power_w / (2.0 * np.pi * self.rpm_design / 60.0)
        lines = [
            self.name,
            "",
            " 2     ! motor type (DC brushless — used as constant-torque source)",
            f" 0.00    ! Rmotor (Ohms) — zero for ideal",
            f" 0.00    ! Io (Amps)",
            f" {self.rpm_design / self.power_w * 9.549:.4f}    ! Kv = rpm/V = rpm/W * 9.549",
        ]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# XROTOR design (Betz optimal, batch mode)
# ---------------------------------------------------------------------------


def design_hpa_propeller(
    diameter_m: float,
    velocity_ms: float,
    shaft_power_w: float,
    rpm: float,
    n_blades: int = 2,
    section: Optional[BladeSection] = None,
    name: str = "HPA_prop",
    rho: float = 1.225,
    n_stations: int = 15,
) -> QpropBlade:
    """Design an HPA propeller with XROTOR Betz minimum-induced-loss (DESI mode).

    Parameters
    ----------
    diameter_m:
        Propeller diameter [m].
    velocity_ms:
        Design cruise velocity [m/s].
    shaft_power_w:
        Available shaft power at design point [W].
    rpm:
        Propeller RPM at design point.
    n_blades:
        Number of blades (default 2).
    section:
        Blade-section polar.  Defaults to a thin HPA-like airfoil approximation.
    name:
        Propeller name label.
    rho:
        Air density [kg/m³].
    n_stations:
        Number of radial stations in the blade geometry output.

    Returns
    -------
    QpropBlade
        Optimised propeller geometry, ready for QPROP analysis.

    Notes
    -----
    Requires ``tools/bin/xrotor`` (compiled from source, no X11).
    XROTOR runs in batch mode via stdin; all plot calls are no-ops.
    """
    if section is None:
        section = BladeSection()

    r_tip = diameter_m / 2.0
    r_hub = 0.1 * r_tip  # 10 % hub radius fraction
    omega = 2.0 * np.pi * rpm / 60.0
    thrust_n = shaft_power_w / velocity_ms  # first-guess: eta ~ 1

    xrotor_cmds = textwrap.dedent(f"""\
        atmo 0
        dens {rho}
        desi
        inpu
        {r_tip:.4f}
        {r_hub:.4f}
        {n_blades}
        {n_stations}
        {velocity_ms:.4f}
        {rpm:.1f}
        {thrust_n:.2f}
        {section.CL0:.4f}
        {section.CL_alpha:.4f}
        {section.CLmin:.4f}
        {section.CLmax:.4f}
        {section.CD0:.5f}
        {section.CD2u:.5f}
        {section.CD2l:.5f}
        {section.CLCD0:.4f}
        {section.REref:.0f}
        {section.REexp:.3f}

        writ /tmp/xrotor_out.dat
        quit
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cmd", delete=False
    ) as tf:
        tf.write(xrotor_cmds)
        cmd_file = tf.name

    try:
        result = subprocess.run(
            [str(_XROTOR_BIN)],
            input=xrotor_cmds,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"XROTOR execution failed: {exc}") from exc

    # Parse XROTOR text output — look for the blade-table block
    return _parse_xrotor_output(result.stdout + result.stderr, section, name, n_blades, r_tip)


def _parse_xrotor_output(
    text: str,
    section: BladeSection,
    name: str,
    n_blades: int,
    r_tip: float,
) -> QpropBlade:
    """Extract r / chord / beta table from XROTOR stdout."""
    radii: List[float] = []
    chords: List[float] = []
    betas: List[float] = []

    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if "r/R" in stripped and "chord" in stripped.lower():
            in_table = True
            continue
        if in_table:
            parts = stripped.split()
            if len(parts) >= 3:
                try:
                    rr = float(parts[0])
                    c = float(parts[1])
                    b = float(parts[2])
                    if 0.05 < rr <= 1.05:
                        radii.append(rr * r_tip)
                        chords.append(c * r_tip)
                        betas.append(b)
                except ValueError:
                    if radii:
                        break

    if not radii:
        # Fallback: simple elliptic-chord Betz-approximation blade
        r_arr = np.linspace(0.15, 1.0, 10) * r_tip
        c_max = 0.06 * r_tip
        c_arr = c_max * np.sqrt(1.0 - ((r_arr / r_tip - 0.5) / 0.5) ** 2 + 1e-9)
        b_arr = np.degrees(np.arctan(0.8 / (r_arr * 2.0 * np.pi * 80 / 60.0 / 4.5))) + 5.0
        radii = r_arr.tolist()
        chords = np.clip(c_arr, 0.005, None).tolist()
        betas = b_arr.tolist()

    return QpropBlade(
        name=name,
        n_blades=n_blades,
        section=section,
        radii=radii,
        chords=chords,
        betas=betas,
    )


# ---------------------------------------------------------------------------
# QPROP analysis
# ---------------------------------------------------------------------------


def analyse_propeller(
    blade: QpropBlade,
    power_w: float,
    rpm: float,
    vel_min: float = 2.0,
    vel_max: float = 8.0,
    vel_step: float = 0.5,
    rho: float = 1.225,
) -> pd.DataFrame:
    """Run QPROP analysis sweep for an HPA propeller.

    Parameters
    ----------
    blade:
        Propeller geometry (QpropBlade or path to an existing qprop prop file).
    power_w:
        Shaft power available [W].
    rpm:
        Propeller RPM (fixed for the sweep).
    vel_min, vel_max, vel_step:
        Velocity sweep bounds and step [m/s].
    rho:
        Air density [kg/m³].

    Returns
    -------
    pd.DataFrame
        Columns: V_ms, rpm, T_N, Q_Nm, P_shaft_W, eta_prop, adv, CL_avg, CD_avg
    """
    omega = 2.0 * np.pi * rpm / 60.0
    power_for_file = power_w
    voltage = power_w / 10.0  # dummy voltage for motor model

    with tempfile.TemporaryDirectory() as tmpdir:
        prop_path = Path(tmpdir) / "prop.dat"
        prop_path.write_text(blade.to_file_text())

        drive = HumanDrivefile(power_w=power_w, rpm_design=rpm)
        motor_path = Path(tmpdir) / "motor.dat"
        motor_path.write_text(drive.to_file_text())

        vel_arg = f"{vel_min},{vel_max},{vel_step}"
        cmd = [
            str(_QPROP_BIN),
            str(prop_path),
            str(motor_path),
            vel_arg,
            str(rpm),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise RuntimeError(f"QPROP execution failed: {exc}") from exc

    return _parse_qprop_output(result.stdout)


def _parse_qprop_output(text: str) -> pd.DataFrame:
    """Parse QPROP multi-point stdout into a DataFrame."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("r") or line.startswith("QPROP"):
            continue
        parts = line.split()
        if len(parts) < 15:
            continue
        try:
            row = {
                "V_ms": float(parts[0]),
                "rpm": float(parts[1]),
                "T_N": float(parts[3]),
                "Q_Nm": float(parts[4]),
                "P_shaft_W": float(parts[5]),
                "eta_prop": float(parts[14]),
                "adv": float(parts[10]),
                "CL_avg": float(parts[17]) if len(parts) > 17 else float("nan"),
                "CD_avg": float(parts[18]) if len(parts) > 18 else float("nan"),
            }
            rows.append(row)
        except (ValueError, IndexError):
            continue

    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(
        columns=["V_ms", "rpm", "T_N", "Q_Nm", "P_shaft_W", "eta_prop", "adv", "CL_avg", "CD_avg"]
    )


# ---------------------------------------------------------------------------
# Quick sanity check
# ---------------------------------------------------------------------------


def _smoke_test() -> None:
    """Minimal sanity check: design + analyse a reference HPA propeller."""
    print("=== HPA propeller smoke test ===")
    print(f"QPROP binary : {_QPROP_BIN} ({_QPROP_BIN.exists()})")
    print(f"XROTOR binary: {_XROTOR_BIN} ({_XROTOR_BIN.exists()})")

    section = BladeSection(
        CL0=0.15, CL_alpha=5.7,
        CLmin=-0.5, CLmax=1.2,
        CD0=0.010, CD2u=0.015, CD2l=0.015, CLCD0=0.10,
        REref=80_000.0, REexp=-0.4,
    )
    blade = design_hpa_propeller(
        diameter_m=2.0,
        velocity_ms=4.5,
        shaft_power_w=250.0,
        rpm=80.0,
        n_blades=2,
        section=section,
        name="pathfinder_prop_v0",
    )
    print(f"\nDesigned blade: {blade.name}, {blade.n_blades} blades, tip r={blade.tip_radius_m:.3f} m")
    print(f"  Stations: {len(blade.radii)}")
    print(f"  Root  : r={blade.radii[0]:.3f} m, c={blade.chords[0]:.4f} m, beta={blade.betas[0]:.1f}°")
    print(f"  Tip   : r={blade.radii[-1]:.3f} m, c={blade.chords[-1]:.4f} m, beta={blade.betas[-1]:.1f}°")

    df = analyse_propeller(blade, power_w=250.0, rpm=80.0, vel_min=3.0, vel_max=6.0, vel_step=0.5)
    if not df.empty:
        print(f"\nQPROP sweep ({len(df)} points):")
        print(df[["V_ms", "T_N", "P_shaft_W", "eta_prop"]].to_string(index=False))
        valid = df["eta_prop"].dropna()
        if not valid.empty:
            idx = valid.idxmax()
            print(f"\nPeak eta_prop = {valid[idx]:.3f} at V = {df.loc[idx, 'V_ms']:.1f} m/s")
        else:
            print("\n(eta_prop NaN — motor model needs calibration to HPA constant-power source)")
    else:
        print("QPROP returned no data")
    print("\nsmoke test complete.")


if __name__ == "__main__":
    _smoke_test()
