"""MCP (Model Context Protocol) server for HPA-MDO.

Exposes MDO tools to AI agents (Claude Code, autoresearch, etc.)
via the MCP protocol. Each tool maps to a core framework operation.

Launch:
    python -m hpa_mdo.api.mcp_server

Or add to Claude Code's MCP config:
    {
      "mcpServers": {
        "hpa-mdo": {
          "command": "python",
          "args": ["-m", "hpa_mdo.api.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def _make_server():
    """Build and return the MCP server instance."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP SDK not installed. Run: pip install 'hpa-mdo[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP("hpa-mdo", description="Human-Powered Aircraft MDO Framework")

    # ------------------------------------------------------------------
    # Tool: list_materials
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_materials() -> str:
        """List all available structural materials in the database."""
        from hpa_mdo.core.materials import MaterialDB
        db = MaterialDB()
        result = {}
        for key in db.list_materials():
            m = db.get(key)
            result[key] = {
                "name": m.name,
                "E_GPa": round(m.E / 1e9, 1),
                "density_kg_m3": m.density,
                "tensile_strength_MPa": round(m.tensile_strength / 1e6, 0),
            }
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Tool: parse_vspaero
    # ------------------------------------------------------------------
    @mcp.tool()
    def parse_vspaero(lod_path: str, aoa_deg: float = 3.0) -> str:
        """Parse a VSPAero .lod file and return the spanwise load distribution
        at the specified angle of attack.

        Args:
            lod_path: Path to the VSPAero .lod output file.
            aoa_deg: Angle of attack to extract [degrees].
        """
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        parser = VSPAeroParser(lod_path)
        parser.parse()
        load = parser.get_load_at_aoa(aoa_deg)
        return json.dumps({
            "aoa_deg": load.aoa_deg,
            "n_stations": load.n_stations,
            "total_lift_N": round(load.total_lift, 3),
            "total_drag_N": round(load.total_drag, 3),
            "y_range_m": [round(float(load.y[0]), 3), round(float(load.y[-1]), 3)],
            "cl_range": [round(float(load.cl.min()), 4), round(float(load.cl.max()), 4)],
        }, indent=2)

    # ------------------------------------------------------------------
    # Tool: optimize_spar
    # ------------------------------------------------------------------
    @mcp.tool()
    def optimize_spar(
        config_yaml_path: str,
        lod_path: str,
        aoa_deg: float = 3.0,
    ) -> str:
        """Run spar structural optimization from a YAML config and VSPAero data.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            lod_path: Path to the VSPAero .lod output file.
            aoa_deg: Angle of attack for the design case [degrees].
        """
        from hpa_mdo.core.config import load_config
        from hpa_mdo.core.aircraft import Aircraft
        from hpa_mdo.core.materials import MaterialDB
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        from hpa_mdo.aero.load_mapper import LoadMapper
        from hpa_mdo.structure.beam_model import EulerBernoulliBeam
        from hpa_mdo.structure.spar import TubularSpar
        from hpa_mdo.structure.optimizer import SparOptimizer

        cfg = load_config(config_yaml_path)
        aircraft = Aircraft.from_config(cfg)
        db = MaterialDB()
        material = db.get(cfg.spar.material)

        parser = VSPAeroParser(lod_path)
        parser.parse()
        aero_load = parser.get_load_at_aoa(aoa_deg)

        spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
        mapper = LoadMapper()
        mapped = mapper.map_loads(aero_load, spar.y, scale_factor=cfg.flight.load_factor)

        beam = EulerBernoulliBeam()
        half_span = aircraft.wing.half_span
        target_defl = half_span * np.tan(np.radians(cfg.wing.dihedral_tip_deg))

        opt = SparOptimizer(
            spar=spar, beam_solver=beam, f_ext=mapped["lift_per_span"],
            safety_factor=cfg.spar.safety_factor, max_tip_deflection=target_defl,
        )
        result = opt.optimize(method=cfg.solver.optimizer_method)

        return json.dumps({
            "success": result.success,
            "message": result.message,
            "spar_mass_full_kg": round(result.spar_mass_full_kg, 4),
            "max_stress_MPa": round(result.max_stress_Pa / 1e6, 2),
            "allowable_stress_MPa": round(result.allowable_stress_Pa / 1e6, 2),
            "tip_deflection_m": round(result.tip_deflection_m, 4),
            "d_i_root_mm": round(result.d_i_root * 1000, 2),
            "d_i_tip_mm": round(result.d_i_tip * 1000, 2),
            "stress_margin": round(
                1.0 - result.max_stress_Pa / result.allowable_stress_Pa, 4
            ),
        }, indent=2)

    # ------------------------------------------------------------------
    # Tool: export_ansys
    # ------------------------------------------------------------------
    @mcp.tool()
    def export_ansys(
        config_yaml_path: str,
        lod_path: str,
        output_dir: str,
        aoa_deg: float = 3.0,
        formats: str = "apdl,csv,nastran",
    ) -> str:
        """Run optimization and export results to ANSYS-compatible formats.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            lod_path: Path to the VSPAero .lod output file.
            output_dir: Directory to write exported files.
            aoa_deg: Angle of attack for the design case [degrees].
            formats: Comma-separated list of export formats (apdl, csv, nastran).
        """
        from hpa_mdo.core.config import load_config
        from hpa_mdo.core.aircraft import Aircraft
        from hpa_mdo.core.materials import MaterialDB
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        from hpa_mdo.aero.load_mapper import LoadMapper
        from hpa_mdo.structure.beam_model import EulerBernoulliBeam
        from hpa_mdo.structure.spar import TubularSpar
        from hpa_mdo.structure.optimizer import SparOptimizer
        from hpa_mdo.structure.ansys_export import ANSYSExporter

        cfg = load_config(config_yaml_path)
        aircraft = Aircraft.from_config(cfg)
        db = MaterialDB()
        material = db.get(cfg.spar.material)

        parser = VSPAeroParser(lod_path)
        parser.parse()
        aero_load = parser.get_load_at_aoa(aoa_deg)

        spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
        mapper = LoadMapper()
        mapped = mapper.map_loads(aero_load, spar.y, scale_factor=cfg.flight.load_factor)

        beam = EulerBernoulliBeam()
        half_span = aircraft.wing.half_span
        target_defl = half_span * np.tan(np.radians(cfg.wing.dihedral_tip_deg))

        opt = SparOptimizer(
            spar=spar, beam_solver=beam, f_ext=mapped["lift_per_span"],
            safety_factor=cfg.spar.safety_factor, max_tip_deflection=target_defl,
        )
        result = opt.optimize()

        exporter = ANSYSExporter(spar, result.spar_props, result.beam_result, material)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        files = []
        fmt_list = [f.strip().lower() for f in formats.split(",")]
        if "apdl" in fmt_list:
            p = exporter.write_apdl(out / "spar_model.mac")
            files.append(str(p))
        if "csv" in fmt_list:
            p = exporter.write_workbench_csv(out / "spar_data.csv")
            files.append(str(p))
        if "nastran" in fmt_list:
            p = exporter.write_nastran_bdf(out / "spar_model.bdf")
            files.append(str(p))

        return json.dumps({"exported_files": files}, indent=2)

    # ------------------------------------------------------------------
    # Tool: beam_analysis
    # ------------------------------------------------------------------
    @mcp.tool()
    def beam_analysis(
        config_yaml_path: str,
        lod_path: str,
        d_i_root_mm: float,
        d_i_tip_mm: float,
        aoa_deg: float = 3.0,
    ) -> str:
        """Evaluate a specific spar design (given inner diameters) without optimization.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            lod_path: Path to the VSPAero .lod output file.
            d_i_root_mm: Inner diameter at root [mm].
            d_i_tip_mm: Inner diameter at tip [mm].
            aoa_deg: Angle of attack [degrees].
        """
        from hpa_mdo.core.config import load_config
        from hpa_mdo.core.aircraft import Aircraft
        from hpa_mdo.core.materials import MaterialDB
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        from hpa_mdo.aero.load_mapper import LoadMapper
        from hpa_mdo.structure.beam_model import EulerBernoulliBeam
        from hpa_mdo.structure.spar import TubularSpar

        cfg = load_config(config_yaml_path)
        aircraft = Aircraft.from_config(cfg)
        db = MaterialDB()
        material = db.get(cfg.spar.material)

        parser = VSPAeroParser(lod_path)
        parser.parse()
        aero_load = parser.get_load_at_aoa(aoa_deg)

        spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
        mapper = LoadMapper()
        mapped = mapper.map_loads(aero_load, spar.y, scale_factor=cfg.flight.load_factor)

        props = spar.compute(d_i_root_mm / 1000.0, d_i_tip_mm / 1000.0)

        g = 9.80665
        f_ext = mapped["lift_per_span"] - props["mass_per_length"] * g

        beam = EulerBernoulliBeam()
        result = beam.solve(spar.y, props["EI"], f_ext, props["outer_radius"])

        actual_stress = result.stress * material.E
        sigma_allow = material.tensile_strength / cfg.spar.safety_factor

        return json.dumps({
            "spar_mass_half_kg": round(props["total_mass"], 4),
            "spar_mass_full_kg": round(props["total_mass"] * 2, 4),
            "tip_deflection_m": round(result.tip_deflection, 4),
            "max_stress_MPa": round(float(np.max(np.abs(actual_stress))) / 1e6, 2),
            "allowable_stress_MPa": round(sigma_allow / 1e6, 2),
            "stress_ratio": round(
                float(np.max(np.abs(actual_stress))) / sigma_allow, 4
            ),
        }, indent=2)

    return mcp


def main():
    server = _make_server()
    server.run()


if __name__ == "__main__":
    main()
