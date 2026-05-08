#!/usr/bin/env python3
"""Convert the nominal local-wall rib bay into physical bracing station requirements."""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    load_current_spar_rows,
    load_current_wire_rigging,
)
from scripts.phase20_rear_spar_torsion_audit import NOMINAL_LOCAL_RIB_BAY_M  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase24_rib_spacing_requirements"


@dataclass(frozen=True)
class RibSpacingBayRequirement:
    bay_index: int
    start_y_m: float
    end_y_m: float
    current_bay_m: float
    target_bay_m: float
    required_segment_count: int
    required_intermediate_stations: int
    recommended_intermediate_y_m: tuple[float, ...]
    recommended_subbay_m: float
    bay_vertical_load_scale_n: float
    status: str
    evidence: str
    remaining_blocker: str


@dataclass(frozen=True)
class RibSpacingRequirements:
    candidate_id: str
    overall_status: str
    target_bay_m: float
    current_max_bay_m: float
    max_recommended_subbay_m: float
    mandatory_station_count: int
    recommended_station_count: int
    total_added_bracing_stations: int
    rows: tuple[RibSpacingBayRequirement, ...]


def build_rib_spacing_requirements(
    candidate_id: str,
    *,
    spar_rows: list[dict[str, str]],
    wire_rigging: list[dict[str, object]] | None = None,
    target_bay_m: float = NOMINAL_LOCAL_RIB_BAY_M,
) -> RibSpacingRequirements:
    if target_bay_m <= 0.0:
        raise ValueError("target_bay_m must be positive.")
    if len(spar_rows) < 2:
        raise ValueError("At least two spar rows are required.")

    wire_rows = [] if wire_rigging is None else wire_rigging
    mandatory_y = _mandatory_bracing_stations_m(spar_rows, wire_rows)
    rows = tuple(
        _build_bay_requirement(
            bay_index=idx,
            start_y_m=mandatory_y[idx],
            end_y_m=mandatory_y[idx + 1],
            target_bay_m=float(target_bay_m),
            spar_rows=spar_rows,
        )
        for idx in range(len(mandatory_y) - 1)
    )
    total_added = sum(row.required_intermediate_stations for row in rows)
    return RibSpacingRequirements(
        candidate_id=str(candidate_id),
        overall_status="layout_requirement_only_not_stiffness_signoff",
        target_bay_m=float(target_bay_m),
        current_max_bay_m=max((row.current_bay_m for row in rows), default=0.0),
        max_recommended_subbay_m=max((row.recommended_subbay_m for row in rows), default=0.0),
        mandatory_station_count=len(mandatory_y),
        recommended_station_count=len(mandatory_y) + total_added,
        total_added_bracing_stations=total_added,
        rows=rows,
    )


def write_rib_spacing_requirements_package(
    out_dir: Path,
    candidate_id: str,
    *,
    spar_rows: list[dict[str, str]],
    wire_rigging: list[dict[str, object]] | None = None,
    target_bay_m: float = NOMINAL_LOCAL_RIB_BAY_M,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    requirements = build_rib_spacing_requirements(
        candidate_id,
        spar_rows=spar_rows,
        wire_rigging=wire_rigging,
        target_bay_m=target_bay_m,
    )
    outputs = [
        _write_csv(out_dir / "rib_spacing_requirements.csv", requirements),
        _write_json(out_dir / "rib_spacing_requirements.json", requirements),
        _write_markdown(out_dir / "rib_spacing_requirements.md", requirements),
    ]
    return outputs


def build_current_rib_spacing_requirements() -> RibSpacingRequirements:
    return build_rib_spacing_requirements(
        CANDIDATE_ID,
        spar_rows=load_current_spar_rows(),
        wire_rigging=load_current_wire_rigging(),
    )


def _build_bay_requirement(
    *,
    bay_index: int,
    start_y_m: float,
    end_y_m: float,
    target_bay_m: float,
    spar_rows: list[dict[str, str]],
) -> RibSpacingBayRequirement:
    bay = float(end_y_m) - float(start_y_m)
    if bay < -1.0e-12:
        raise ValueError("Mandatory bracing stations must be sorted spanwise.")
    segment_count = max(1, int(math.ceil(max(bay, 0.0) / float(target_bay_m) - 1.0e-12)))
    intermediate_count = max(segment_count - 1, 0)
    recommended = tuple(
        float(start_y_m) + bay * float(idx) / float(segment_count)
        for idx in range(1, segment_count)
    )
    subbay = 0.0 if segment_count == 0 else bay / float(segment_count)
    status = (
        "requires_added_physical_bracing"
        if intermediate_count > 0
        else "target_spacing_met_for_layout"
    )
    load_scale = _max_vertical_load_scale_n(spar_rows, start_y_m, end_y_m)
    return RibSpacingBayRequirement(
        bay_index=int(bay_index),
        start_y_m=float(start_y_m),
        end_y_m=float(end_y_m),
        current_bay_m=float(bay),
        target_bay_m=float(target_bay_m),
        required_segment_count=int(segment_count),
        required_intermediate_stations=int(intermediate_count),
        recommended_intermediate_y_m=recommended,
        recommended_subbay_m=float(subbay),
        bay_vertical_load_scale_n=float(load_scale),
        status=status,
        evidence=(
            f"Current mandatory bay {bay:.3f} m needs {segment_count} segment(s) "
            f"to stay at or below {target_bay_m:.3f} m target bay."
        ),
        remaining_blocker=(
            "Physical rib/bracing stiffness, spar attachment, shear/cap/bond margins, "
            "and manufacturable station placement still need engineering closure."
        ),
    )


def _mandatory_bracing_stations_m(
    spar_rows: list[dict[str, str]],
    wire_rigging: list[dict[str, object]],
) -> tuple[float, ...]:
    stations = {float(spar_rows[0]["Y_Position_m"]), float(spar_rows[-1]["Y_Position_m"])}
    for row in spar_rows:
        if int(float(row.get("Is_Joint", "0"))) or int(float(row.get("Is_Wire_Attach", "0"))):
            stations.add(float(row["Y_Position_m"]))
    for row in wire_rigging:
        if "attach_y_m" in row:
            stations.add(float(row["attach_y_m"]))
    return tuple(sorted(stations))


def _max_vertical_load_scale_n(
    spar_rows: list[dict[str, str]],
    start_y_m: float,
    end_y_m: float,
) -> float:
    in_bay = [
        row
        for row in spar_rows
        if float(start_y_m) - 1.0e-12 <= float(row["Y_Position_m"]) <= float(end_y_m) + 1.0e-12
    ]
    if not in_bay:
        in_bay = [
            min(
                spar_rows,
                key=lambda row: min(
                    abs(float(row["Y_Position_m"]) - float(start_y_m)),
                    abs(float(row["Y_Position_m"]) - float(end_y_m)),
                ),
            )
        ]
    return max(
        abs(float(row.get("Main_FZ_N", "0"))) + abs(float(row.get("Rear_FZ_N", "0")))
        for row in in_bay
    )


def _write_csv(path: Path, requirements: RibSpacingRequirements) -> Path:
    fields = list(asdict(requirements.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in requirements.rows:
            raw = asdict(row)
            raw["recommended_intermediate_y_m"] = ";".join(
                f"{value:.6f}" for value in row.recommended_intermediate_y_m
            )
            writer.writerow(raw)
    return path


def _write_json(path: Path, requirements: RibSpacingRequirements) -> Path:
    path.write_text(
        json.dumps(asdict(requirements), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, requirements: RibSpacingRequirements) -> Path:
    lines = [
        "# Rib Spacing Requirements",
        "",
        f"Candidate: `{requirements.candidate_id}`",
        f"Overall status: `{requirements.overall_status}`",
        "",
        "This is a layout requirement only, not a rib stiffness signoff.",
        "",
        "## Summary",
        "",
        f"- target bay: `{requirements.target_bay_m:.3f} m`",
        f"- current max mandatory bay: `{requirements.current_max_bay_m:.3f} m`",
        f"- max recommended sub-bay: `{requirements.max_recommended_subbay_m:.3f} m`",
        f"- mandatory station count: `{requirements.mandatory_station_count}`",
        f"- recommended station count: `{requirements.recommended_station_count}`",
        f"- added physical bracing stations required: `{requirements.total_added_bracing_stations}`",
        "",
        "## Bay Requirements",
        "",
        "| bay | y start m | y end m | current bay m | segments | added stations | max sub-bay m | load scale N | status |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in requirements.rows:
        lines.append(
            f"| {row.bay_index} | {row.start_y_m:.3f} | {row.end_y_m:.3f} | "
            f"{row.current_bay_m:.3f} | {row.required_segment_count} | "
            f"{row.required_intermediate_stations} | {row.recommended_subbay_m:.3f} | "
            f"{row.bay_vertical_load_scale_n:.3f} | `{row.status}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- 0.300 m target bay comes from the current local-wall buckling assumption.",
            "- Recommended stations only close spacing as a layout requirement.",
            "- Rib stiffness, rib shear/cap/bond margins, and spar attachment load transfer are still unverified.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-bay-m", type=float, default=NOMINAL_LOCAL_RIB_BAY_M)
    args = parser.parse_args(argv)

    outputs = write_rib_spacing_requirements_package(
        args.output_dir,
        CANDIDATE_ID,
        spar_rows=load_current_spar_rows(),
        wire_rigging=load_current_wire_rigging(),
        target_bay_m=args.target_bay_m,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
