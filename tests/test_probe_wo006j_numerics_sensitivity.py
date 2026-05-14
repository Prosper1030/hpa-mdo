from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006j_numerics_sensitivity.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("probe_wo006j_numerics_sensitivity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_wo006j_numerics_sensitivity"] = module
    spec.loader.exec_module(module)
    return module


def test_force_single_su2_key_replaces_duplicate_muscl_setting() -> None:
    module = _load_module()
    cfg = "\n".join(
        [
            "SOLVER= INC_EULER",
            "CONV_NUM_METHOD_FLOW= FDS",
            "MUSCL_FLOW= YES",
            "SLOPE_LIMITER_FLOW= NONE",
            "ITER= 300",
            "MUSCL_FLOW= NO",
            "",
        ]
    )

    updated = module.force_single_su2_key(cfg, "MUSCL_FLOW", "YES")

    assert updated.count("MUSCL_FLOW=") == 1
    assert "MUSCL_FLOW= YES" in updated
    assert "MUSCL_FLOW= NO" not in updated


def test_prepare_second_order_fds_probe_cfg_removes_first_order_blocker(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.su2").write_text("NDIME= 3\n", encoding="utf-8")
    (source / "su2_runtime.cfg").write_text(
        "\n".join(
            [
                "SOLVER= INC_EULER",
                "CONV_NUM_METHOD_FLOW= FDS",
                "MUSCL_FLOW= NO",
                "SLOPE_LIMITER_FLOW= VENKATAKRISHNAN",
                "ITER= 300",
                "CFL_NUMBER= 1.0",
                "OUTPUT_FILES= (RESTART_ASCII)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    target = tmp_path / "target"
    prepared = module.prepare_probe_case(
        source_case_dir=source,
        output_case_dir=target,
        iteration_count=750,
        cfl_number=0.5,
    )

    cfg = (target / "su2_runtime.cfg").read_text(encoding="utf-8")
    assert prepared["status"] == "prepared"
    assert (target / "mesh.su2").is_file()
    assert "CONV_NUM_METHOD_FLOW= FDS" in cfg
    assert "MUSCL_FLOW= YES" in cfg
    assert "MUSCL_FLOW= NO" not in cfg
    assert "SLOPE_LIMITER_FLOW= NONE" in cfg
    assert "ITER= 750" in cfg
    assert "CFL_NUMBER= 0.5" in cfg
    assert "SURFACE_CSV" in cfg


def test_prepare_second_order_fds_probe_accepts_limited_reconstruction(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.su2").write_text("NDIME= 3\n", encoding="utf-8")
    (source / "su2_runtime.cfg").write_text(
        "\n".join(
            [
                "SOLVER= INC_EULER",
                "CONV_NUM_METHOD_FLOW= FDS",
                "MUSCL_FLOW= NO",
                "SLOPE_LIMITER_FLOW= NONE",
                "ITER= 300",
                "CFL_NUMBER= 1.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    target = tmp_path / "target"
    module.prepare_probe_case(
        source_case_dir=source,
        output_case_dir=target,
        iteration_count=300,
        cfl_number=0.02,
        slope_limiter_flow="VENKATAKRISHNAN",
    )

    cfg = (target / "su2_runtime.cfg").read_text(encoding="utf-8")
    assert "MUSCL_FLOW= YES" in cfg
    assert "SLOPE_LIMITER_FLOW= VENKATAKRISHNAN" in cfg
    assert "CFL_NUMBER= 0.02" in cfg


def test_config_diagnostic_flags_fds_with_muscl_disabled() -> None:
    module = _load_module()

    diagnostic = module.diagnose_flow_discretization(
        "\n".join(
            [
                "SOLVER= INC_EULER",
                "CONV_NUM_METHOD_FLOW= FDS",
                "MUSCL_FLOW= NO",
                "",
            ]
        )
    )

    assert diagnostic["status"] == "first_order_or_low_order_diagnostic_only"
    assert "fds_without_muscl_second_order_reconstruction" in diagnostic["blockers"]


def test_config_diagnostic_accepts_fds_with_muscl_enabled() -> None:
    module = _load_module()

    diagnostic = module.diagnose_flow_discretization(
        "\n".join(
            [
                "SOLVER= INC_EULER",
                "CONV_NUM_METHOD_FLOW= FDS",
                "MUSCL_FLOW= YES",
                "SLOPE_LIMITER_FLOW= NONE",
                "",
            ]
        )
    )

    assert diagnostic["status"] == "second_order_probe_ready"
    assert diagnostic["blockers"] == []
