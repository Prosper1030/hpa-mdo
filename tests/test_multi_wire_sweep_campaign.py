from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.multi_wire_sweep_campaign import (
    _build_layout_config_payload,
    _extract_multi_wire_metrics,
    _parse_wire_layouts,
)


def test_parse_wire_layouts_reads_named_layouts() -> None:
    layouts = _parse_wire_layouts("single=7.5;dual=4.5|10.5;triple=4.5|7.5|10.5")

    assert [layout.label for layout in layouts] == ["single", "dual", "triple"]
    assert layouts[1].attachment_positions_m == pytest.approx((4.5, 10.5))
    assert layouts[2].wire_count == 3


def test_build_layout_config_payload_updates_attachments_and_drag() -> None:
    payload = {
        "aero_gates": {"cd_profile_estimate": 0.010},
        "lift_wires": {
            "enabled": True,
            "wire_angle_deg": 11.3,
            "attachments": [{"y": 7.5, "fuselage_z": -1.5, "label": "wire-1"}],
        },
    }
    layout = _parse_wire_layouts("dual=4.5|10.5")[0]

    updated = _build_layout_config_payload(
        base_payload=payload,
        layout=layout,
        base_fuselage_z=-1.5,
        base_wire_angle_deg=11.3,
        wire_drag_cd_per_wire=0.003,
    )

    assert updated["aero_gates"]["cd_profile_estimate"] == pytest.approx(0.016)
    assert [entry["y"] for entry in updated["lift_wires"]["attachments"]] == [4.5, 10.5]
    assert updated["lift_wires"]["attachments"][1]["label"] == "wire-2"


def test_extract_multi_wire_metrics_aggregates_all_records(tmp_path: Path) -> None:
    wire_path = tmp_path / "lift_wire_rigging.json"
    wire_path.write_text(
        json.dumps(
            {
                "wire_rigging": [
                    {"tension_force_n": 100.0, "tension_margin_n": 900.0},
                    {"tension_force_n": 120.0, "tension_margin_n": 880.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    total_n, max_n, min_margin_n, resolved_path = _extract_multi_wire_metrics(
        {"artifacts": {"wire_rigging_json": str(wire_path)}}
    )

    assert total_n == pytest.approx(220.0)
    assert max_n == pytest.approx(120.0)
    assert min_margin_n == pytest.approx(880.0)
    assert resolved_path == str(wire_path.resolve())
