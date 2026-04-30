from pathlib import Path

import yaml

from hpa_meshing.schema import MeshJobConfig


def test_aircraft_assembly_baseline_config_validates():
    package_root = Path(__file__).resolve().parents[1]
    config_path = package_root / "configs" / "aircraft_assembly.openvsp_baseline.yaml"

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = MeshJobConfig.model_validate(raw)

    assert config.component == "aircraft_assembly"
    assert config.geometry_provider == "openvsp_surface_intersection"
    assert config.geometry == Path("../data/blackcat_004_origin.vsp3")
    assert config.su2.enabled is True
    assert config.su2.flow_conditions is not None
    assert config.su2.flow_conditions.source_label == "hpa_standard_6p5_mps"
    assert config.su2.velocity_mps == 6.5
    assert config.su2.dynamic_viscosity_pas == 1.7894e-5
