from pathlib import Path

from hpa_meshing.schema import BatchManifest


def test_manifest_examples():
    manifest = BatchManifest.model_validate({
        "jobs": [
            {
                "component": "main_wing",
                "geometry": "wing.step",
                "out_dir": "out/wing"
            }
        ]
    })
    assert len(manifest.jobs) == 1
