from __future__ import annotations

from pathlib import Path
from typing import Any


def load_openvsp_reference_data(source_path: Path) -> dict[str, Any] | None:
    if source_path.suffix.lower() != ".vsp3" or not source_path.exists():
        return None
    try:
        import openvsp as vsp  # type: ignore
    except Exception:
        return None

    try:
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(source_path))
        vsp.Update()
        geom_ids = list(vsp.FindGeoms())
        if not geom_ids:
            return None
    except Exception:
        return None

    settings: dict[str, float] = {}
    try:
        settings_id = vsp.FindContainer("VSPAEROSettings", 0)
    except Exception:
        settings_id = ""
    if settings_id:
        parm_specs = {
            "sref": "Sref",
            "bref": "bref",
            "cref": "cref",
            "xcg": "Xcg",
            "ycg": "Ycg",
            "zcg": "Zcg",
            "ref_flag": "RefFlag",
            "mac_flag": "MACFlag",
        }
        for key, parm_name in parm_specs.items():
            try:
                parm_id = vsp.FindParm(settings_id, parm_name, "VSPAERO")
            except Exception:
                parm_id = ""
            if not parm_id:
                continue
            try:
                settings[key] = float(vsp.GetParmVal(parm_id))
            except Exception:
                continue

    ref_wing_id = None
    ref_wing_name = None
    wing_quantities = None
    try:
        ref_wing_id = vsp.GetVSPAERORefWingID() or None
    except Exception:
        ref_wing_id = None
    if ref_wing_id:
        try:
            ref_wing_name = vsp.GetGeomName(ref_wing_id)
        except Exception:
            ref_wing_name = None
        try:
            sref, bref, cref = vsp.get_wing_reference_quantities(wing_id=ref_wing_id, vsp_instance=vsp)
            wing_quantities = {
                "sref": float(sref),
                "bref": float(bref),
                "cref": float(cref),
            }
        except Exception:
            wing_quantities = None

    warnings: list[str] = []
    area_method = "openvsp_reference_wing.sref"
    length_method = "openvsp_reference_wing.cref"
    if wing_quantities and wing_quantities["sref"] > 0.0 and wing_quantities["cref"] > 0.0:
        ref_area = wing_quantities["sref"]
        ref_length = wing_quantities["cref"]
        if settings:
            if "sref" in settings and abs(settings["sref"] - ref_area) > max(abs(ref_area) * 1e-3, 1e-9):
                warnings.append("openvsp_settings_sref_differs_from_reference_wing")
            if "cref" in settings and abs(settings["cref"] - ref_length) > max(abs(ref_length) * 1e-3, 1e-9):
                warnings.append("openvsp_settings_cref_differs_from_reference_wing")
    elif settings.get("sref", 0.0) > 0.0 and settings.get("cref", 0.0) > 0.0:
        ref_area = float(settings["sref"])
        ref_length = float(settings["cref"])
        area_method = "openvsp_vspaero_settings.sref"
        length_method = "openvsp_vspaero_settings.cref"
        warnings.append("reference_wing_quantities_unavailable_using_vspaero_settings")
    else:
        return None

    return {
        "ref_area": ref_area,
        "ref_length": ref_length,
        "ref_origin_moment": {
            "x": float(settings.get("xcg", 0.0)),
            "y": float(settings.get("ycg", 0.0)),
            "z": float(settings.get("zcg", 0.0)),
        },
        "area_method": area_method,
        "length_method": length_method,
        "moment_method": "openvsp_vspaero_settings.cg",
        "reference_wing_name": ref_wing_name,
        "reference_wing_id": ref_wing_id,
        "settings": settings,
        "wing_quantities": wing_quantities or {},
        "warnings": warnings,
    }


def resolve_reference_data(
    source_path: Path,
    *,
    provider_result: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    metadata = metadata or {}
    metadata_reference = metadata.get("reference_geometry")
    if isinstance(metadata_reference, dict):
        return metadata_reference

    provider_provenance = None if provider_result is None else getattr(provider_result, "provenance", None)
    if isinstance(provider_provenance, dict):
        provider_reference = provider_provenance.get("reference_geometry")
        if isinstance(provider_reference, dict):
            return provider_reference

    return load_openvsp_reference_data(source_path)


def resolve_reference_length(
    source_path: Path,
    *,
    provider_result: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> float | None:
    reference = resolve_reference_data(source_path, provider_result=provider_result, metadata=metadata)
    if reference is None:
        return None
    ref_length = reference.get("ref_length")
    if not isinstance(ref_length, (int, float)) or float(ref_length) <= 0.0:
        return None
    return float(ref_length)


def is_zero_vector(point: dict[str, Any], *, tolerance: float = 1.0e-9) -> bool:
    values = [float(point.get(axis, 0.0)) for axis in ("x", "y", "z")]
    return max(abs(value) for value in values) <= tolerance
