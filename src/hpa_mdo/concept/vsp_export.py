from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path
from typing import Any


def _validate_stations_rows(stations_rows: list[dict]) -> None:
    if not stations_rows:
        raise ValueError("stations_rows must not be empty.")

    expected_keys = set(stations_rows[0].keys())
    for row in stations_rows[1:]:
        if set(row.keys()) != expected_keys:
            raise ValueError("stations_rows rows must share the same schema.")

    required_keys = {"y_m", "chord_m", "twist_deg"}
    missing = required_keys - expected_keys
    if missing:
        raise ValueError(
            "stations_rows must include y_m, chord_m, and twist_deg."
        )


def _safe_identifier(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    return cleaned.strip("_") or "concept"


def _naca_4_series_params(name: str) -> tuple[float, float, float]:
    digits = "".join(ch for ch in str(name).upper() if ch.isdigit())
    if len(digits) < 4:
        return 0.0, 0.0, 0.12
    digits = digits[:4]
    camber = int(digits[0]) / 100.0
    camber_loc = int(digits[1]) / 10.0
    thick_chord = int(digits[2:]) / 100.0
    return camber, camber_loc, thick_chord


def _horizontal_tail_proxy_spec(concept_config: dict[str, Any]) -> dict[str, Any] | None:
    geometry = concept_config.get("geometry") or {}
    if not isinstance(geometry, dict):
        return None
    tail_area = float(geometry.get("tail_area_m2") or 0.0)
    if tail_area <= 0.0:
        return None
    tail_model = concept_config.get("tail_model") or {}
    if not isinstance(tail_model, dict):
        tail_model = {}
    tail_aspect_ratio = float(tail_model.get("tail_aspect_ratio") or 5.0)
    if tail_aspect_ratio <= 0.0:
        tail_aspect_ratio = 5.0
    root_chord = float(geometry.get("root_chord_m") or 1.0)
    tip_chord = float(geometry.get("tip_chord_m") or root_chord)
    mean_aerodynamic_chord = float(
        geometry.get("mean_aerodynamic_chord_m") or 0.5 * (root_chord + tip_chord)
    )
    tail_arm_to_mac = float(tail_model.get("tail_arm_to_mac") or 4.0)
    full_span = math.sqrt(tail_area * tail_aspect_ratio)
    chord = tail_area / max(full_span, 1.0e-9)
    return {
        "role": "horizontal_tail_proxy_for_geometry_review",
        "area_m2": tail_area,
        "aspect_ratio": tail_aspect_ratio,
        "full_span_m": full_span,
        "half_span_m": 0.5 * full_span,
        "chord_m": chord,
        "x_location_m": tail_arm_to_mac * mean_aerodynamic_chord,
        "z_location_m": 0.0,
        "airfoil": "NACA 0012",
        "authority": "tail_area_and_tail_arm_proxy_not_final_tail_sizing",
    }


def _airfoil_block(*, xsec_idx: int, xsec_var: str, label: str) -> str:
    camber, camber_loc, thick_chord = _naca_4_series_params(label)
    return textwrap.dedent(
        f"""\
            // Airfoil: {label}
            ChangeXSecShape( xsec_surf, {xsec_idx}, XS_FOUR_SERIES );
            SetParmVal( GetXSecParm( {xsec_var}, "Camber" ), {camber:.6f} );
            SetParmVal( GetXSecParm( {xsec_var}, "CamberLoc" ), {camber_loc:.6f} );
            SetParmVal( GetXSecParm( {xsec_var}, "ThickChord" ), {thick_chord:.6f} );
        """
    )


def _horizontal_tail_proxy_block(spec: dict[str, Any] | None) -> str:
    if spec is None:
        return ""
    root_block = _airfoil_block(
        xsec_idx=0,
        xsec_var='GetXSec( tail_xsec_surf, 0 )',
        label=str(spec["airfoil"]),
    )
    tip_block = _airfoil_block(
        xsec_idx=1,
        xsec_var="tail_tip_xs",
        label=str(spec["airfoil"]),
    )
    return textwrap.dedent(
        f"""\

            // Horizontal tail proxy: review-only surface from tail area and tail arm.
            string tail_id = AddGeom( "WING" );
            SetGeomName( tail_id, "HorizontalTail_proxy" );
            SetParmVal( FindParm( tail_id, "X_Rel_Location", "XForm" ), {float(spec["x_location_m"]):.6f} );
            SetParmVal( FindParm( tail_id, "Z_Rel_Location", "XForm" ), {float(spec["z_location_m"]):.6f} );
            SetParmVal( FindParm( tail_id, "Sym_Planar_Flag", "Sym" ), SYM_XZ );
            string tail_xsec_surf = GetXSecSurf( tail_id, 0 );
        {textwrap.indent(root_block, "    ")}
            string tail_tip_xs = GetXSec( tail_xsec_surf, 1 );
            SetDriverGroup( tail_id, 1, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER );
            SetParmVal( GetXSecParm( tail_tip_xs, "Root_Chord" ), {float(spec["chord_m"]):.6f} );
            SetParmVal( GetXSecParm( tail_tip_xs, "Tip_Chord" ), {float(spec["chord_m"]):.6f} );
            SetParmVal( GetXSecParm( tail_tip_xs, "Span" ), {float(spec["half_span_m"]):.6f} );
            SetParmVal( GetXSecParm( tail_tip_xs, "Sweep" ), 0.0 );
            SetParmVal( GetXSecParm( tail_tip_xs, "Dihedral" ), 0.0 );
        {textwrap.indent(tip_block, "    ")}
            Update();
        """
    )


def _assign_naca_4_series_api(vsp: Any, xsec_surf: str, xsec_idx: int, label: str) -> None:
    camber, camber_loc, thick_chord = _naca_4_series_params(label)
    vsp.ChangeXSecShape(xsec_surf, xsec_idx, vsp.XS_FOUR_SERIES)
    xsec = vsp.GetXSec(xsec_surf, xsec_idx)
    vsp.SetParmVal(vsp.GetXSecParm(xsec, "Camber"), camber)
    vsp.SetParmVal(vsp.GetXSecParm(xsec, "CamberLoc"), camber_loc)
    vsp.SetParmVal(vsp.GetXSecParm(xsec, "ThickChord"), thick_chord)


def _add_horizontal_tail_proxy_api(
    vsp: Any,
    *,
    concept_config: dict[str, Any],
) -> dict[str, Any] | None:
    spec = _horizontal_tail_proxy_spec(concept_config)
    if spec is None:
        return None

    tail_id = vsp.AddGeom("WING")
    vsp.SetGeomName(tail_id, "HorizontalTail_proxy")
    vsp.SetParmVal(vsp.FindParm(tail_id, "X_Rel_Location", "XForm"), float(spec["x_location_m"]))
    vsp.SetParmVal(vsp.FindParm(tail_id, "Z_Rel_Location", "XForm"), float(spec["z_location_m"]))
    vsp.SetParmVal(vsp.FindParm(tail_id, "Sym_Planar_Flag", "Sym"), vsp.SYM_XZ)

    xsec_surf = vsp.GetXSecSurf(tail_id, 0)
    _assign_naca_4_series_api(vsp, xsec_surf, 0, str(spec["airfoil"]))
    tail_tip_xs = vsp.GetXSec(xsec_surf, 1)
    vsp.SetDriverGroup(
        tail_id,
        1,
        vsp.SPAN_WSECT_DRIVER,
        vsp.ROOTC_WSECT_DRIVER,
        vsp.TIPC_WSECT_DRIVER,
    )
    vsp.SetParmVal(vsp.GetXSecParm(tail_tip_xs, "Root_Chord"), float(spec["chord_m"]))
    vsp.SetParmVal(vsp.GetXSecParm(tail_tip_xs, "Tip_Chord"), float(spec["chord_m"]))
    vsp.SetParmVal(vsp.GetXSecParm(tail_tip_xs, "Span"), float(spec["half_span_m"]))
    vsp.SetParmVal(vsp.GetXSecParm(tail_tip_xs, "Sweep"), 0.0)
    vsp.SetParmVal(vsp.GetXSecParm(tail_tip_xs, "Dihedral"), 0.0)
    _assign_naca_4_series_api(vsp, xsec_surf, 1, str(spec["airfoil"]))
    return spec


def _write_concept_openvsp_vsp3_api(
    *,
    bundle_dir: Path,
    concept_id: str,
    concept_config: dict[str, Any],
    stations_rows: list[dict],
) -> dict[str, Any]:
    target_path = Path(bundle_dir) / "concept_openvsp.vsp3"
    try:
        import openvsp as vsp  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local OpenVSP install
        return {
            "status": "openvsp_python_unavailable",
            "target_path": str(target_path),
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        _validate_stations_rows(stations_rows)
        wing_name = str(concept_config.get("name") or concept_id)
        n_segments = len(stations_rows) - 1
        if n_segments < 1:
            raise ValueError("at least two stations are required to write a VSP3 wing.")

        vsp.ClearVSPModel()
        wing_id = vsp.AddGeom("WING")
        vsp.SetGeomName(wing_id, wing_name)
        xsec_surf = vsp.GetXSecSurf(wing_id, 0)

        for _ in range(n_segments - 1):
            vsp.InsertXSec(wing_id, 1, vsp.XS_FOUR_SERIES)

        _assign_naca_4_series_api(vsp, xsec_surf, 0, "NACA 0012")
        root_xsec = vsp.GetXSec(xsec_surf, 0)
        vsp.SetParmVal(
            vsp.GetXSecParm(root_xsec, "Twist"),
            float(stations_rows[0]["twist_deg"]),
        )

        for seg_idx in range(n_segments):
            outboard_idx = seg_idx + 1
            inboard = stations_rows[seg_idx]
            outboard = stations_rows[seg_idx + 1]
            seg_span = float(outboard["y_m"]) - float(inboard["y_m"])
            if seg_span <= 0.0:
                raise ValueError("stations_rows y_m values must increase monotonically.")
            local_dihedral_deg = 0.5 * (
                float(inboard.get("dihedral_deg", 0.0))
                + float(outboard.get("dihedral_deg", 0.0))
            )

            xsec = vsp.GetXSec(xsec_surf, outboard_idx)
            vsp.SetDriverGroup(
                wing_id,
                outboard_idx,
                vsp.SPAN_WSECT_DRIVER,
                vsp.ROOTC_WSECT_DRIVER,
                vsp.TIPC_WSECT_DRIVER,
            )
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Root_Chord"), float(inboard["chord_m"]))
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Tip_Chord"), float(outboard["chord_m"]))
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Span"), seg_span)
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Sweep"), 0.0)
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Dihedral"), local_dihedral_deg)
            vsp.SetParmVal(vsp.GetXSecParm(xsec, "Twist"), float(outboard["twist_deg"]))
            vsp.Update()
            _assign_naca_4_series_api(vsp, xsec_surf, outboard_idx, "NACA 0012")

        vsp.SetParmVal(vsp.FindParm(wing_id, "Sym_Planar_Flag", "Sym"), vsp.SYM_XZ)
        tail_spec = _add_horizontal_tail_proxy_api(vsp, concept_config=concept_config)
        vsp.Update()
        vsp.WriteVSPFile(str(target_path))
        return {
            "status": "written",
            "target_path": str(target_path),
            "path": str(target_path),
            "source": "openvsp_python_api",
            "auxiliary_geometry": {
                "horizontal_tail_proxy": tail_spec,
            },
        }
    except Exception as exc:
        return {
            "status": "openvsp_api_failed",
            "target_path": str(target_path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_concept_openvsp_metadata(
    *,
    bundle_dir: Path,
    concept_id: str,
    concept_config: dict[str, Any],
    stations_rows: list[dict],
    airfoil_templates: dict[str, Any],
    lofting_guides: dict[str, Any],
    prop_assumption: dict[str, Any],
    concept_summary: dict[str, Any],
) -> dict[str, Any]:
    geometry = dict(concept_config.get("geometry") or {})
    if "span_m" not in geometry:
        geometry["span_m"] = 2.0 * max(float(row["y_m"]) for row in stations_rows)

    tail_spec = _horizontal_tail_proxy_spec(concept_config)
    return {
        "artifact_type": "concept_openvsp_handoff",
        "concept_id": concept_id,
        "script_path": "concept_openvsp.vspscript",
        "vsp3_target_path": str(bundle_dir / "concept_openvsp.vsp3"),
        "vsp3_build": {
            "status": "not_attempted",
            "target_path": str(bundle_dir / "concept_openvsp.vsp3"),
        },
        "station_count": len(stations_rows),
        "geometry": geometry,
        "auxiliary_geometry": {
            "horizontal_tail_proxy": tail_spec,
        },
        "stations": stations_rows,
        "airfoil_templates": airfoil_templates,
        "lofting_guides": lofting_guides,
        "prop_assumption": prop_assumption,
        "concept_summary": concept_summary,
    }


def build_concept_openvsp_vspscript(
    *,
    bundle_dir: Path,
    concept_id: str,
    concept_config: dict[str, Any],
    stations_rows: list[dict],
) -> str:
    _validate_stations_rows(stations_rows)

    wing_name = str(concept_config.get("name") or concept_id)
    n_segments = len(stations_rows) - 1

    script_target = (bundle_dir / "concept_openvsp.vsp3").as_posix()
    root_twist = float(stations_rows[0]["twist_deg"])
    root_xsec_block = _airfoil_block(
        xsec_idx=0,
        xsec_var='GetXSec( xsec_surf, 0 )',
        label="NACA 0012",
    )
    segment_lines: list[str] = []

    if n_segments < 1:
        segment_lines.append(
            '    // Single-station fallback: preserve a minimal, OpenVSP-readable wing.'
        )
        segment_lines.append(textwrap.indent(root_xsec_block, "    "))
        segment_lines.append(
            f'    SetParmVal( GetXSecParm( GetXSec( xsec_surf, 0 ), "Twist" ), {root_twist:.6f} );'
        )
        segment_lines.append("    Update();")
    else:
        for _ in range(n_segments - 1):
            segment_lines.append('    InsertXSec( wing_id, 1, XS_FOUR_SERIES );')

        segment_lines.append(textwrap.indent(root_xsec_block, "    "))
        segment_lines.append(
            f'    SetParmVal( GetXSecParm( GetXSec( xsec_surf, 0 ), "Twist" ), {root_twist:.6f} );'
        )

        for seg_idx in range(n_segments):
            outboard_idx = seg_idx + 1
            inboard = stations_rows[seg_idx]
            outboard = stations_rows[seg_idx + 1]
            seg_span = float(outboard["y_m"]) - float(inboard["y_m"])
            local_dihedral_deg = 0.5 * (
                float(inboard.get("dihedral_deg", 0.0)) + float(outboard.get("dihedral_deg", 0.0))
            )

            segment_lines.append(
                f'    // Station {seg_idx}: y={float(inboard["y_m"]):.3f} -> {float(outboard["y_m"]):.3f} m'
            )
            segment_lines.append(
                f'    string seg{seg_idx}_xs = GetXSec( xsec_surf, {outboard_idx} );'
            )
            segment_lines.append(
                f'    SetDriverGroup( wing_id, {outboard_idx}, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER );'
            )
            segment_lines.append(
                f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Root_Chord" ), {float(inboard["chord_m"]):.6f} );'
            )
            segment_lines.append(
                f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Tip_Chord" ), {float(outboard["chord_m"]):.6f} );'
            )
            segment_lines.append(
                f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Span" ), {seg_span:.6f} );'
            )
            segment_lines.append('    SetParmVal( GetXSecParm( seg{0}_xs, "Sweep" ), 0.0 );'.format(seg_idx))
            segment_lines.append(
                '    SetParmVal( GetXSecParm( seg{0}_xs, "Dihedral" ), {1:.6f} );'.format(
                    seg_idx, local_dihedral_deg
                )
            )
            segment_lines.append(
                f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Twist" ), {float(outboard["twist_deg"]):.6f} );'
            )
            segment_lines.append("    Update();")
            outboard_block = _airfoil_block(
                xsec_idx=outboard_idx,
                xsec_var=f"seg{seg_idx}_xs",
                label="NACA 0012",
            )
            segment_lines.append(textwrap.indent(outboard_block, "    "))

    segment_body = "\n".join(segment_lines)
    geometry = concept_config.get("geometry") or {}
    tail_body = _horizontal_tail_proxy_block(_horizontal_tail_proxy_spec(concept_config))

    return textwrap.dedent(
        f"""\
        // ─────────────────────────────────────────────────────────────
        // VSPScript: {wing_name} concept handoff
        // Generated from candidate bundle data, not a hardcoded aircraft
        // ─────────────────────────────────────────────────────────────
        // concept_id: {concept_id}
        // station_count: {len(stations_rows)}
        // geometry: {json.dumps(geometry, ensure_ascii=True)}

        void main()
        {{
            ClearVSPModel();

            string wing_id = AddGeom( "WING" );
            SetGeomName( wing_id, "{wing_name}" );
            string xsec_surf = GetXSecSurf( wing_id, 0 );

        {segment_body}

            SetParmVal( FindParm( wing_id, "Sym_Planar_Flag", "Sym" ), SYM_XZ );
            Update();
        {tail_body}
            WriteVSPFile( "{script_target}" );
            Print( "Saved: {Path(script_target).name}" );
        }}
        """
    )


def write_concept_openvsp_handoff(
    *,
    bundle_dir: Path,
    concept_id: str,
    concept_config: dict[str, Any],
    stations_rows: list[dict],
    airfoil_templates: dict[str, Any],
    lofting_guides: dict[str, Any],
    prop_assumption: dict[str, Any],
    concept_summary: dict[str, Any],
) -> tuple[Path, Path]:
    _validate_stations_rows(stations_rows)

    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    metadata = build_concept_openvsp_metadata(
        bundle_dir=bundle_dir,
        concept_id=concept_id,
        concept_config=concept_config,
        stations_rows=stations_rows,
        airfoil_templates=airfoil_templates,
        lofting_guides=lofting_guides,
        prop_assumption=prop_assumption,
        concept_summary=concept_summary,
    )
    script_text = build_concept_openvsp_vspscript(
        bundle_dir=bundle_dir,
        concept_id=concept_id,
        concept_config=concept_config,
        stations_rows=stations_rows,
    )

    metadata_path = bundle_dir / "concept_openvsp_metadata.json"
    script_path = bundle_dir / "concept_openvsp.vspscript"
    script_path.write_text(script_text, encoding="utf-8")
    metadata["vsp3_build"] = _write_concept_openvsp_vsp3_api(
        bundle_dir=bundle_dir,
        concept_id=concept_id,
        concept_config=concept_config,
        stations_rows=stations_rows,
    )
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return script_path, metadata_path
