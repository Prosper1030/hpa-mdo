from __future__ import annotations


def test_fsi_coupling_import() -> None:
    from hpa_mdo.fsi.coupling import FSICoupling

    assert callable(FSICoupling)
