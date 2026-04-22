from __future__ import annotations

import json
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

    return {
        "artifact_type": "concept_openvsp_handoff",
        "concept_id": concept_id,
        "script_path": "concept_openvsp.vspscript",
        "vsp3_target_path": str(bundle_dir / "concept_openvsp.vsp3"),
        "station_count": len(stations_rows),
        "geometry": geometry,
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

    script_path = bundle_dir / "concept_openvsp.vspscript"
    metadata_path = bundle_dir / "concept_openvsp_metadata.json"
    script_path.write_text(script_text, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return script_path, metadata_path
