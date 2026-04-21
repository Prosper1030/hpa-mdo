import json
from pathlib import Path

from hpa_meshing.providers import get_provider, materialize_geometry
from hpa_meshing.providers.openvsp_surface_intersection import _infer_import_scale
from hpa_meshing.schema import Bounds3D
from hpa_meshing.schema import GeometryProviderRequest, GeometryTopologyMetadata


def test_provider_registry_tracks_formal_and_experimental_entries():
    openvsp_provider = get_provider("openvsp_surface_intersection")
    esp_provider = get_provider("esp_rebuilt")

    assert openvsp_provider.name == "openvsp_surface_intersection"
    assert openvsp_provider.stage == "v1"
    assert esp_provider.name == "esp_rebuilt"
    assert esp_provider.stage == "experimental"


def test_openvsp_provider_materializes_normalized_geometry_and_topology_report(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging_dir = tmp_path / "out" / "providers" / "openvsp_surface_intersection"

    from hpa_meshing.providers import openvsp_surface_intersection as provider_module

    class FakeOpenVSP:
        def __init__(self) -> None:
            self._string_inputs = {}

        def ClearVSPModel(self) -> None:
            return None

        def ReadVSPFile(self, path: str) -> None:
            self.path = path

        def Update(self) -> None:
            return None

        def SetAnalysisInputDefaults(self, name: str) -> None:
            self.analysis_name = name

        def SetIntAnalysisInput(self, name: str, field: str, values) -> None:
            return None

        def SetStringAnalysisInput(self, name: str, field: str, values) -> None:
            self._string_inputs[field] = tuple(values)

        def ExecAnalysis(self, name: str) -> str:
            output_path = Path(self._string_inputs["STEPFileName"][0])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
            return "surface-intersection-result"

    monkeypatch.setattr(provider_module, "_load_openvsp", lambda: FakeOpenVSP())
    monkeypatch.setattr(
        provider_module,
        "_probe_step_topology",
        lambda path, staging: GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="vsp3",
            units="m",
            body_count=3,
            surface_count=38,
            volume_count=3,
            labels_present=True,
            label_schema="component/name",
        ),
    )

    request = GeometryProviderRequest(
        provider="openvsp_surface_intersection",
        source_path=source,
        component="aircraft_assembly",
        staging_dir=staging_dir,
        geometry_family_hint="thin_sheet_aircraft_assembly",
    )

    result = materialize_geometry(request)

    assert result.status == "materialized"
    assert result.geometry_source == "provider_generated"
    assert result.geometry_family_hint == "thin_sheet_aircraft_assembly"
    assert result.normalized_geometry_path == staging_dir / "normalized.stp"
    assert result.normalized_geometry_path.exists()
    assert result.artifacts["topology_report"].exists()
    topology_report = json.loads(result.artifacts["topology_report"].read_text(encoding="utf-8"))
    assert topology_report["representation"] == "brep_trimmed_step"
    assert topology_report["surface_count"] == 38
    assert result.provenance["analysis"] == "SurfaceIntersection"


def test_probe_step_topology_tracks_step_bounds_and_occ_import_scale(tmp_path: Path, monkeypatch):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text(
        "\n".join(
            [
                "ISO-10303-21;",
                "DATA;",
                "#1=(",
                "LENGTH_UNIT()",
                "NAMED_UNIT(*)",
                "SI_UNIT(.UNSET.,.METRE.)",
                ");",
                "#2=CARTESIAN_POINT('',(0.,0.,0.));",
                "#3=CARTESIAN_POINT('',(5.7,16.4746519585795,1.7));",
                "#4=CARTESIAN_POINT('',(-0.0000215655505732439,-16.4746519585795,-0.7));",
                "ENDSEC;",
                "END-ISO-10303-21;",
            ]
        ),
        encoding="utf-8",
    )

    from hpa_meshing.providers import openvsp_surface_intersection as provider_module

    class FakeOption:
        @staticmethod
        def setNumber(name: str, value: float) -> None:
            return None

    class FakeOCC:
        @staticmethod
        def importShapes(path: str):
            return [(3, 1)]

        @staticmethod
        def synchronize() -> None:
            return None

    class FakeModel:
        occ = FakeOCC()

        @staticmethod
        def add(name: str) -> None:
            return None

        @staticmethod
        def getEntities(dim: int):
            if dim == 3:
                return [(3, 1)]
            if dim == 2:
                return [(2, idx) for idx in range(1, 39)]
            return []

        @staticmethod
        def getBoundingBox(dim: int, tag: int):
            assert (dim, tag) == (3, 1)
            return (
                -0.0215655505732439,
                -16474.6519585795,
                -700.0,
                5700.0,
                16474.6519585795,
                1700.0,
            )

    class FakeGmsh:
        option = FakeOption()
        model = FakeModel()

        @staticmethod
        def initialize() -> None:
            return None

        @staticmethod
        def finalize() -> None:
            return None

    monkeypatch.setattr(provider_module, "load_gmsh", lambda: FakeGmsh())

    topology = provider_module._probe_step_topology(step_path, tmp_path)

    assert topology.units == "m"
    assert topology.bounds is not None
    assert topology.bounds.x_max == 5.7
    assert topology.bounds.y_max == 16.4746519585795
    assert topology.import_bounds is not None
    assert topology.import_bounds.x_max == 5700.0
    assert topology.import_scale_to_units == 0.001
    assert topology.backend_rescale_required is True


def test_probe_step_topology_ignores_near_identity_import_scale(tmp_path: Path, monkeypatch):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text(
        "\n".join(
            [
                "ISO-10303-21;",
                "DATA;",
                "#1=(",
                "LENGTH_UNIT()",
                "NAMED_UNIT(*)",
                "SI_UNIT(.UNSET.,.METRE.)",
                ");",
                "#2=CARTESIAN_POINT('',(0.,0.,0.));",
                "#3=CARTESIAN_POINT('',(5.7,16.4746519585795,1.7));",
                "#4=CARTESIAN_POINT('',(-0.0000215655505732439,-16.4746519585795,-0.7));",
                "ENDSEC;",
                "END-ISO-10303-21;",
            ]
        ),
        encoding="utf-8",
    )

    from hpa_meshing.providers import openvsp_surface_intersection as provider_module

    class FakeOption:
        @staticmethod
        def setNumber(name: str, value: float) -> None:
            return None

    class FakeOCC:
        @staticmethod
        def importShapes(path: str):
            return [(3, 1)]

        @staticmethod
        def synchronize() -> None:
            return None

    class FakeModel:
        occ = FakeOCC()

        @staticmethod
        def add(name: str) -> None:
            return None

        @staticmethod
        def getEntities(dim: int):
            if dim == 3:
                return [(3, 1)]
            if dim == 2:
                return [(2, idx) for idx in range(1, 47)]
            return []

        @staticmethod
        def getBoundingBox(dim: int, tag: int):
            assert (dim, tag) == (3, 1)
            return (
                -0.000021665550573239997,
                -16.474652058580002,
                -0.7000000999999999,
                5.7000001000000005,
                16.474652058580002,
                1.7000001,
            )

    class FakeGmsh:
        option = FakeOption()
        model = FakeModel()

        @staticmethod
        def initialize() -> None:
            return None

        @staticmethod
        def finalize() -> None:
            return None

    monkeypatch.setattr(provider_module, "load_gmsh", lambda: FakeGmsh())

    topology = provider_module._probe_step_topology(step_path, tmp_path)

    assert topology.units == "m"
    assert topology.import_scale_to_units == 1.0
    assert topology.backend_rescale_required is False


def test_infer_import_scale_prefers_consistent_axes_when_one_step_axis_is_contaminated():
    normalized_bounds = Bounds3D(
        x_min=0.0,
        x_max=4.8,
        y_min=-1.5,
        y_max=1.5,
        z_min=-0.036,
        z_max=0.036,
    )
    import_bounds = Bounds3D(
        x_min=4000.0,
        x_max=4800.0,
        y_min=-1500.0,
        y_max=1500.0,
        z_min=-36.0,
        z_max=36.0,
    )

    scale = _infer_import_scale(normalized_bounds, import_bounds)

    assert scale == 0.001
