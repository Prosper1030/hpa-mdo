from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import analyze_vsp  # noqa: E402
from hpa_mdo.aero.vsp_builder import VSPBuilder  # noqa: E402
from hpa_mdo.aero.vsp_introspect import (  # noqa: E402
    _extract_airfoil_refs,
    _scale_segments,
    merge_into_config_dict,
)
from hpa_mdo.core.config import HPAConfig  # noqa: E402


class _FakeXSec:
    def __init__(self, shape: int, *, upper=None, lower=None, **parms: float):
        self.shape = shape
        self.parms = parms
        self.upper = upper or []
        self.lower = lower or []


class _FakePoint:
    def __init__(self, x: float, y: float, z: float = 0.0):
        self._x = float(x)
        self._y = float(y)
        self._z = float(z)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def z(self) -> float:
        return self._z


class _FakeVSP:
    XS_FILE_AIRFOIL = 1
    XS_FOUR_SERIES = 2

    def __init__(self, xsecs: list[_FakeXSec]):
        self._xsecs = xsecs

    def GetXSecSurf(self, wing_id: str, surface_index: int) -> str:
        assert wing_id == "wing"
        assert surface_index == 0
        return "surf"

    def GetNumXSec(self, surf: str) -> int:
        assert surf == "surf"
        return len(self._xsecs)

    def GetXSec(self, surf: str, idx: int) -> _FakeXSec:
        assert surf == "surf"
        return self._xsecs[idx]

    def GetXSecShape(self, xs: _FakeXSec) -> int:
        return xs.shape

    def GetXSecParm(self, xs: _FakeXSec, name: str) -> tuple[_FakeXSec, str]:
        return (xs, name)

    def GetParmVal(self, parm_id: tuple[_FakeXSec, str]) -> float:
        xs, name = parm_id
        return float(xs.parms[name])

    def GetAirfoilUpperPnts(self, xs: _FakeXSec):
        return xs.upper

    def GetAirfoilLowerPnts(self, xs: _FakeXSec):
        return xs.lower


def _write_airfoil_dat(path: Path, thickness_tc: float) -> None:
    half_t = 0.5 * thickness_tc
    path.write_text(
        "\n".join(
            [
                path.stem,
                f"1.0 0.0",
                f"0.75 {0.6 * half_t:.6f}",
                f"0.50 {half_t:.6f}",
                f"0.25 {0.8 * half_t:.6f}",
                "0.0 0.0",
                f"0.25 {-0.8 * half_t:.6f}",
                f"0.50 {-half_t:.6f}",
                f"0.75 {-0.6 * half_t:.6f}",
                "1.0 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _base_config_dict() -> dict:
    return {
        "project_name": "Phase2 Demo",
        "flight": {"velocity": 8.0, "air_density": 1.225},
        "weight": {
            "airframe_kg": 30.0,
            "pilot_kg": 55.0,
            "max_takeoff_kg": 95.0,
        },
        "wing": {
            "span": 15.0,
            "root_chord": 1.30,
            "tip_chord": 0.60,
            "airfoil_root": "clarkysm",
            "airfoil_tip": "fx76mp140",
        },
        "main_spar": {"segments": [1.5, 3.0, 3.0], "material": "carbon_fiber_hm"},
        "io": {},
    }


def _build_config(*, dihedral_schedule: list[list[float]] | None = None) -> HPAConfig:
    payload = _base_config_dict()
    payload["wing"].update(
        {
            "span": 20.0,
            "root_chord": 1.4,
            "tip_chord": 0.6,
            "dihedral_root_deg": 0.0,
            "dihedral_tip_deg": 10.0,
            "dihedral_scaling_exponent": 1.0,
        }
    )
    payload["main_spar"] = {"segments": [5.0, 5.0], "material": "carbon_fiber_hm"}
    if dihedral_schedule is not None:
        payload["wing"]["dihedral_schedule"] = dihedral_schedule
    return HPAConfig(**payload)


def test_extract_airfoil_refs_recovers_naca_and_matched_afile(tmp_path: Path) -> None:
    upper = [_FakePoint(1.0, 0.0), _FakePoint(0.5, 0.08), _FakePoint(0.0, 0.0)]
    lower = [_FakePoint(0.0, 0.0), _FakePoint(0.5, -0.05), _FakePoint(1.0, 0.0)]
    _write_airfoil_dat(tmp_path / "fx76mp140.dat", thickness_tc=0.14)
    _write_airfoil_dat(tmp_path / "naca0009.dat", thickness_tc=0.09)

    vsp = _FakeVSP(
        [
            _FakeXSec(
                _FakeVSP.XS_FOUR_SERIES,
                Camber=0.02,
                CamberLoc=0.4,
                ThickChord=0.12,
                upper=upper,
                lower=lower,
            ),
            _FakeXSec(
                _FakeVSP.XS_FILE_AIRFOIL,
                ThickChord=0.14,
                upper=upper,
                lower=lower,
            ),
        ]
    )
    schedule = [{"y": 0.0}, {"y": 5.0}]

    refs = _extract_airfoil_refs(vsp, "wing", schedule, airfoil_dir=tmp_path)

    assert refs == [
        {
            "station_y": 0.0,
            "source": "naca",
            "name": "NACA 2412",
            "thickness_tc": pytest.approx(0.12),
        },
        {
            "station_y": 5.0,
            "source": "afile",
            "name": "fx76mp140",
            "thickness_tc": pytest.approx(0.14),
        },
    ]


def test_extract_airfoil_refs_can_embed_inline_coordinates(tmp_path: Path) -> None:
    _write_airfoil_dat(tmp_path / "fx76mp140.dat", thickness_tc=0.14)
    upper = [_FakePoint(1.0, 0.0), _FakePoint(0.4, 0.09), _FakePoint(0.0, 0.0)]
    lower = [_FakePoint(0.0, 0.0), _FakePoint(0.4, -0.04), _FakePoint(1.0, 0.0)]
    vsp = _FakeVSP(
        [
            _FakeXSec(
                _FakeVSP.XS_FILE_AIRFOIL,
                ThickChord=0.14,
                upper=upper,
                lower=lower,
            ),
        ]
    )

    refs = _extract_airfoil_refs(
        vsp,
        "wing",
        [{"y": 0.0}],
        airfoil_dir=tmp_path,
        include_coordinates=True,
    )

    assert refs[0]["name"] == "fx76mp140"
    assert refs[0]["coordinates"] == [
        [1.0, 0.0],
        [0.4, 0.09],
        [0.0, 0.0],
        [0.4, -0.04],
        [1.0, 0.0],
    ]


def test_merge_into_config_dict_merges_airfoils_dihedral_and_scaled_segments(
    tmp_path: Path,
) -> None:
    _write_airfoil_dat(tmp_path / "fx76mp140.dat", thickness_tc=0.14)
    base = _base_config_dict()
    base["io"]["airfoil_dir"] = str(tmp_path)
    summary = {
        "source_path": str(tmp_path / "demo.vsp3"),
        "main_wing": {
            "span_m": 20.0,
            "half_span_m": 10.0,
            "root_chord_m": 1.40,
            "tip_chord_m": 0.50,
            "dihedral_schedule": [[0.0, 0.0], [10.0, 1.0]],
            "airfoils": [
                {"station_y": 0.0, "source": "naca", "name": "NACA 2412", "thickness_tc": 0.12},
                {"station_y": 10.0, "source": "afile", "name": "fx76mp140", "thickness_tc": 0.14},
            ],
        },
        "horizontal_tail": None,
        "vertical_fin": None,
    }

    merged = merge_into_config_dict(base, summary)

    assert merged["wing"]["span"] == pytest.approx(20.0)
    assert merged["wing"]["airfoil_root"] == "NACA 2412"
    assert merged["wing"]["airfoil_tip"] == "fx76mp140"
    assert merged["wing"]["airfoil_root_tc"] == pytest.approx(0.12)
    assert merged["wing"]["airfoil_tip_tc"] == pytest.approx(0.14)
    assert merged["wing"]["dihedral_schedule"] == [[0.0, 0.0], [10.0, 1.0]]
    assert merged["main_spar"]["segments"] == pytest.approx([2.0, 4.0, 4.0])
    assert sum(merged["main_spar"]["segments"]) == pytest.approx(10.0, abs=1.0e-3)


def test_scale_segments_matches_new_half_span_within_tolerance() -> None:
    scaled = _scale_segments([1.5, 3.0, 3.0], template_half_span=7.5, new_half_span=10.0)

    assert scaled == pytest.approx([2.0, 4.0, 4.0])
    assert sum(scaled) == pytest.approx(10.0, abs=1.0e-3)


def test_vsp_builder_uses_explicit_dihedral_schedule_when_present() -> None:
    cfg = _build_config(dihedral_schedule=[[0.0, 0.0], [5.0, 0.5], [10.0, 1.5]])

    schedule = VSPBuilder(cfg)._wing_section_schedule()

    assert [entry["y"] for entry in schedule] == pytest.approx([0.0, 5.0, 10.0])
    assert [entry["source"] for entry in schedule] == ["config_dihedral_schedule"] * 3
    assert [entry.get("z_m", 0.0) for entry in schedule] == pytest.approx([0.0, 0.5, 1.5])
    assert schedule[1]["segment_dihedral_deg"] == pytest.approx(math.degrees(math.atan2(0.5, 5.0)))
    assert schedule[2]["segment_dihedral_deg"] == pytest.approx(math.degrees(math.atan2(1.0, 5.0)))


def test_vsp_builder_falls_back_to_progressive_dihedral_without_schedule() -> None:
    cfg = _build_config()

    schedule = VSPBuilder(cfg)._wing_section_schedule()

    assert [entry["y"] for entry in schedule] == pytest.approx([0.0, 5.0, 10.0])
    assert [entry["source"] for entry in schedule] == ["config"] * 3
    assert all("z_m" not in entry for entry in schedule)
    assert schedule[1]["dihedral_deg"] == pytest.approx(5.0)
    assert schedule[2]["dihedral_deg"] == pytest.approx(10.0)


def test_analyze_vsp_writes_controls_sidecar_and_passes_airfoil_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_path = tmp_path / "template.yaml"
    airfoil_dir = tmp_path / "airfoils"
    airfoil_dir.mkdir()
    _write_airfoil_dat(airfoil_dir / "fx76mp140.dat", thickness_tc=0.14)
    template_path.write_text(
        "\n".join(
            [
                "project_name: Phase2 Demo",
                "flight:",
                "  velocity: 8.0",
                "  air_density: 1.225",
                "weight:",
                "  airframe_kg: 30.0",
                "  pilot_kg: 55.0",
                "  max_takeoff_kg: 95.0",
                "wing:",
                "  span: 15.0",
                "  root_chord: 1.30",
                "  tip_chord: 0.60",
                "  airfoil_root: clarkysm",
                "  airfoil_tip: fx76mp140",
                "main_spar:",
                "  segments: [1.5, 3.0, 3.0]",
                "io:",
                f"  airfoil_dir: {airfoil_dir}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    vsp_path = tmp_path / "demo.vsp3"
    vsp_path.write_text("placeholder", encoding="utf-8")

    captured: dict[str, object] = {}

    import hpa_mdo.aero.vsp_introspect as introspect_mod
    import hpa_mdo.core.config as config_mod

    def fake_summarize(vsp_path_arg: Path, *, airfoil_dir: Path | None = None) -> dict:
        captured["vsp_path"] = vsp_path_arg
        captured["airfoil_dir"] = airfoil_dir
        return {
            "source_path": str(vsp_path_arg),
            "main_wing": {
                "span_m": 20.0,
                "half_span_m": 10.0,
                "root_chord_m": 1.40,
                "tip_chord_m": 0.50,
                "dihedral_schedule": [[0.0, 0.0], [10.0, 1.0]],
                "airfoils": [
                    {"station_y": 0.0, "source": "naca", "name": "NACA 2412", "thickness_tc": 0.12},
                    {"station_y": 10.0, "source": "afile", "name": "fx76mp140", "thickness_tc": 0.14},
                ],
                "controls": [
                    {
                        "name": "Main Aileron",
                        "type": "aileron",
                        "eta_start": 0.55,
                        "eta_end": 0.9,
                        "chord_fraction_start": 0.25,
                        "chord_fraction_end": 0.25,
                        "edge": "trailing",
                        "surf_type": "both",
                    }
                ],
            },
            "horizontal_tail": {
                "name": "Elevator",
                "span_m": 4.0,
                "half_span_m": 2.0,
                "root_chord_m": 0.8,
                "tip_chord_m": 0.8,
                "x_location": 6.5,
                "y_location": 0.0,
                "z_location": 0.0,
                "controls": [
                    {
                        "name": "Elevator",
                        "type": "elevator",
                        "eta_start": 0.05,
                        "eta_end": 0.95,
                        "chord_fraction_start": 0.3,
                        "chord_fraction_end": 0.3,
                        "edge": "trailing",
                        "surf_type": "both",
                    }
                ],
                "airfoils": [],
                "dihedral_schedule": [[0.0, 0.0], [2.0, 0.0]],
            },
            "vertical_fin": None,
        }

    monkeypatch.setattr(introspect_mod, "summarize_vsp_surfaces", fake_summarize)
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda path: SimpleNamespace(io=SimpleNamespace(airfoil_dir=airfoil_dir)),
    )
    monkeypatch.setattr(config_mod, "HPAConfig", lambda **kwargs: kwargs)

    rc = analyze_vsp.main(
        [
            "--vsp",
            str(vsp_path),
            "--template",
            str(template_path),
            "--output-root",
            str(tmp_path / "out"),
            "--no-run",
        ]
    )

    assert rc == 0
    assert captured["airfoil_dir"] == airfoil_dir

    out_dir = tmp_path / "out" / vsp_path.stem
    controls_path = out_dir / "controls.json"
    assert controls_path.is_file()

    payload = json.loads(controls_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "vsp_controls_v1"
    assert {item["surface"] for item in payload["controls"]} == {"main_wing", "horizontal_tail"}
    assert payload["surfaces"]["main_wing"]["controls"][0]["type"] == "aileron"
    assert (out_dir / "resolved_config.yaml").is_file()
