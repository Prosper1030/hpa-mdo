"""MCP (Model Context Protocol) server for HPA-MDO v2.

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

from hpa_mdo.api._shared import run_pipeline as _run_pipeline
from hpa_mdo.api._shared import result_to_dict as _result_to_dict

def _error_response(e: Exception) -> str:
    """Standard error JSON for any tool failure."""
    return json.dumps({"error": str(e), "val_weight": 99999}, indent=2)


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

    mcp = FastMCP("hpa-mdo", description="Human-Powered Aircraft MDO Framework v2")

    # ------------------------------------------------------------------
    # Tool: list_materials
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_materials() -> str:
        """List all available structural materials from data/materials.yaml."""
        try:
            from hpa_mdo.core.materials import MaterialDB
            db = MaterialDB()
            result = {}
            for key in db.list_materials():
                m = db.get(key)
                result[key] = {
                    "name": m.name,
                    "E_GPa": round(m.E / 1e9, 1),
                    "G_GPa": round(m.G / 1e9, 1),
                    "density_kg_m3": m.density,
                    "tensile_strength_MPa": round(m.tensile_strength / 1e6, 0),
                    "poisson_ratio": m.poisson_ratio,
                }
            return json.dumps(result, indent=2)
        except Exception as e:
            return _error_response(e)

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
        try:
            from hpa_mdo.aero.vsp_aero import VSPAeroParser
            parser = VSPAeroParser(lod_path)
            cases = parser.parse()
            best = min(cases, key=lambda c: abs(c.aoa_deg - aoa_deg))
            return json.dumps({
                "aoa_deg": best.aoa_deg,
                "n_stations": best.n_stations,
                "n_cases_parsed": len(cases),
                "available_aoa": [c.aoa_deg for c in cases],
                "total_lift_N": round(float(np.trapezoid(best.lift_per_span, best.y)), 3),
                "y_range_m": [round(float(best.y[0]), 3), round(float(best.y[-1]), 3)],
                "cl_range": [round(float(best.cl.min()), 4), round(float(best.cl.max()), 4)],
            }, indent=2)
        except Exception as e:
            return _error_response(e)

    # ------------------------------------------------------------------
    # Tool: optimize_spar
    # ------------------------------------------------------------------
    @mcp.tool()
    def optimize_spar(
        config_yaml_path: str,
        aoa_deg: float = 3.0,
    ) -> str:
        """Run full spar structural optimization from a YAML config.

        Uses the .lod file path from the config's io.vsp_lod field.
        Auto-selects the AoA case closest to trim if aoa_deg is not matched exactly.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            aoa_deg: Angle of attack for the design case [degrees].
        """
        try:
            cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
                config_yaml_path, aoa_deg)
            result = opt.optimize(method="auto")
            out = _result_to_dict(result)
            out["aoa_used_deg"] = best_case.aoa_deg
            return json.dumps(out, indent=2)
        except Exception as e:
            return _error_response(e)

    # ------------------------------------------------------------------
    # Tool: analyze_spar
    # ------------------------------------------------------------------
    @mcp.tool()
    def analyze_spar(
        config_yaml_path: str,
        main_t_mm: str,
        rear_t_mm: str = "",
        aoa_deg: float = 3.0,
    ) -> str:
        """Evaluate a specific spar design (given segment thicknesses) without optimization.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            main_t_mm: Comma-separated main spar segment thicknesses [mm], e.g. "1.5,1.2,1.0".
            rear_t_mm: Comma-separated rear spar segment thicknesses [mm]. Empty string if no rear spar.
            aoa_deg: Angle of attack [degrees].
        """
        try:
            cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
                config_yaml_path, aoa_deg)

            main_t_seg = np.array([float(x) for x in main_t_mm.split(",")]) * 1e-3
            rear_t_seg = None
            if rear_t_mm.strip():
                rear_t_seg = np.array([float(x) for x in rear_t_mm.split(",")]) * 1e-3

            result = opt.analyze(main_t_seg=main_t_seg, rear_t_seg=rear_t_seg)
            out = _result_to_dict(result)
            out["aoa_used_deg"] = best_case.aoa_deg
            return json.dumps(out, indent=2)
        except Exception as e:
            return _error_response(e)

    # ------------------------------------------------------------------
    # Tool: export_ansys
    # ------------------------------------------------------------------
    @mcp.tool()
    def export_ansys(
        config_yaml_path: str,
        output_dir: str,
        aoa_deg: float = 3.0,
        formats: str = "apdl,csv,nastran",
    ) -> str:
        """Run optimization and export results to ANSYS-compatible formats.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
            output_dir: Directory to write exported files.
            aoa_deg: Angle of attack for the design case [degrees].
            formats: Comma-separated list of export formats (apdl, csv, nastran).
        """
        try:
            from hpa_mdo.structure.ansys_export import ANSYSExporter

            cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
                config_yaml_path, aoa_deg)
            result = opt.optimize(method="auto")

            exporter = ANSYSExporter(cfg, ac, result, aero_loads, mat_db)

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

            out_dict = _result_to_dict(result)
            out_dict["exported_files"] = files
            out_dict["aoa_used_deg"] = best_case.aoa_deg
            return json.dumps(out_dict, indent=2)
        except Exception as e:
            return _error_response(e)

    # ------------------------------------------------------------------
    # Tool: get_config
    # ------------------------------------------------------------------
    @mcp.tool()
    def get_config(config_yaml_path: str) -> str:
        """Return the parsed HPA-MDO configuration as JSON.

        Args:
            config_yaml_path: Path to the HPA-MDO YAML configuration file.
        """
        try:
            from hpa_mdo.core.config import load_config
            cfg = load_config(config_yaml_path)
            return cfg.model_dump_json(indent=2)
        except Exception as e:
            return _error_response(e)

    return mcp


def main():
    server = _make_server()
    server.run()


if __name__ == "__main__":
    main()
