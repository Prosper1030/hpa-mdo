#!/usr/bin/env python3
"""Decompose wire attach force vectors into local-detail design load components."""
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

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    load_current_candidate_reference,
)
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    load_current_wire_rigging,
    wire_force_vector_n,
)
from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    DEFAULT_DETAIL_SAFETY_FACTOR,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase34_wire_attach_load_decomposition"


@dataclass(frozen=True)
class WireAttachLoadComponentRow:
    wire_identifier: str
    component_key: str
    status: str
    service_load_n: float
    design_load_n: float
    force_x_n: float
    force_y_n: float
    force_z_n: float
    detail_safety_factor: float
    applicable_subcomponents: str
    engineering_role: str
    engineering_note: str


@dataclass(frozen=True)
class WireAttachLoadDecomposition:
    candidate_id: str
    overall_status: str
    detail_safety_factor: float
    max_resultant_wire_identifier: str
    max_resultant_service_load_n: float
    max_resultant_design_load_n: float
    rows: tuple[WireAttachLoadComponentRow, ...]


def build_wire_attach_load_decomposition(
    candidate_id: str,
    *,
    wire_rigging: list[dict[str, object]] | tuple[dict[str, object], ...],
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
) -> WireAttachLoadDecomposition:
    if not wire_rigging:
        raise ValueError("At least one wire rigging row is required.")
    if detail_safety_factor <= 0.0:
        raise ValueError("detail_safety_factor must be positive.")

    rows = tuple(
        component_row
        for rigging_row in wire_rigging
        for component_row in _component_rows(
            rigging_row,
            detail_safety_factor=detail_safety_factor,
        )
    )
    max_resultant = max(
        (row for row in rows if row.component_key == "resultant_xyz"),
        key=lambda row: row.service_load_n,
    )
    return WireAttachLoadDecomposition(
        candidate_id=str(candidate_id),
        overall_status="wire_attach_load_components_defined_not_signoff",
        detail_safety_factor=float(detail_safety_factor),
        max_resultant_wire_identifier=max_resultant.wire_identifier,
        max_resultant_service_load_n=float(max_resultant.service_load_n),
        max_resultant_design_load_n=float(max_resultant.design_load_n),
        rows=rows,
    )


def write_wire_attach_load_decomposition_package(
    out_dir: Path,
    candidate_id: str,
    *,
    wire_rigging: list[dict[str, object]] | tuple[dict[str, object], ...],
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    decomposition = build_wire_attach_load_decomposition(
        candidate_id,
        wire_rigging=wire_rigging,
        detail_safety_factor=detail_safety_factor,
    )
    outputs = [
        _write_csv(out_dir / "wire_attach_load_decomposition.csv", decomposition),
        _write_json(out_dir / "wire_attach_load_decomposition.json", decomposition),
        _write_markdown(out_dir / "wire_attach_load_decomposition.md", decomposition),
    ]
    return outputs


def build_current_wire_attach_load_decomposition() -> WireAttachLoadDecomposition:
    reference = load_current_candidate_reference()
    return build_wire_attach_load_decomposition(
        reference.candidate_id,
        wire_rigging=load_current_wire_rigging(),
    )


def _component_rows(
    rigging_row: dict[str, object],
    *,
    detail_safety_factor: float,
) -> tuple[WireAttachLoadComponentRow, ...]:
    fx, fy, fz = wire_force_vector_n(rigging_row)
    resultant = math.sqrt(fx * fx + fy * fy + fz * fz)
    transverse = math.sqrt(fx * fx + fz * fz)
    wire_id = str(rigging_row.get("identifier", "wire"))
    components = (
        (
            "resultant_xyz",
            resultant,
            "attach_ring_or_lug;bonded_load_path;insert_pullout_bearing;local_tube_wall_crushing",
            "scalar resultant for global attach-detail sizing",
        ),
        (
            "spanwise_y",
            abs(fy),
            "bonded_load_path;insert_pullout_bearing",
            "spanwise load entering the spar/insert/bond slip path",
        ),
        (
            "vertical_z",
            abs(fz),
            "attach_ring_or_lug;local_tube_wall_crushing;bonded_load_path",
            "vertical bearing, peel, and local crushing component",
        ),
        (
            "chordwise_x",
            abs(fx),
            "attach_ring_or_lug;local_tube_wall_crushing;bonded_load_path",
            "chordwise/lateral bearing and local wall component",
        ),
        (
            "transverse_xz",
            transverse,
            "attach_ring_or_lug;insert_pullout_bearing;local_tube_wall_crushing;bonded_load_path",
            "combined non-spanwise local wall and bearing component",
        ),
    )
    return tuple(
        WireAttachLoadComponentRow(
            wire_identifier=wire_id,
            component_key=component_key,
            status="component_load_defined_not_local_signoff",
            service_load_n=float(service_load),
            design_load_n=float(service_load) * float(detail_safety_factor),
            force_x_n=fx,
            force_y_n=fy,
            force_z_n=fz,
            detail_safety_factor=float(detail_safety_factor),
            applicable_subcomponents=applicable_subcomponents,
            engineering_role=engineering_role,
            engineering_note=(
                "Load component for local-detail sizing only; not local FEM signoff and not a "
                "substitute for ring, bond, insert, bearing, tube-wall, fatigue, or installation evidence."
            ),
        )
        for component_key, service_load, applicable_subcomponents, engineering_role in components
    )


def _write_csv(path: Path, decomposition: WireAttachLoadDecomposition) -> Path:
    fields = list(asdict(decomposition.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in decomposition.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, decomposition: WireAttachLoadDecomposition) -> Path:
    path.write_text(
        json.dumps(asdict(decomposition), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, decomposition: WireAttachLoadDecomposition) -> Path:
    lines = [
        "# Wire Attach Load Decomposition",
        "",
        f"Candidate: `{decomposition.candidate_id}`",
        f"Overall status: `{decomposition.overall_status}`",
        "",
        "These are local detail load components, not local FEM signoff.",
        "",
        f"- detail safety factor: `{decomposition.detail_safety_factor:.2f}`",
        f"- max resultant wire: `{decomposition.max_resultant_wire_identifier}`",
        f"- max resultant service load: `{decomposition.max_resultant_service_load_n:.3f} N`",
        f"- max resultant design load: `{decomposition.max_resultant_design_load_n:.3f} N`",
        "",
        "| wire | component | status | service N | design N | applicable subcomponents | role |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in decomposition.rows:
        lines.append(
            f"| {row.wire_identifier} | `{row.component_key}` | `{row.status}` | "
            f"{row.service_load_n:.3f} | {row.design_load_n:.3f} | "
            f"{row.applicable_subcomponents} | {row.engineering_role} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Treat global Y as the spanwise spar direction for this decomposition.",
            "- Use these components to size or FEM the attach ring, bond, insert, bearing, and local tube wall.",
            "- The component loads do not prove stress concentration, bond peel, fatigue, or manufacturing margins.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--detail-safety-factor", type=float, default=DEFAULT_DETAIL_SAFETY_FACTOR)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    outputs = write_wire_attach_load_decomposition_package(
        args.output_dir,
        reference.candidate_id,
        wire_rigging=load_current_wire_rigging(),
        detail_safety_factor=args.detail_safety_factor,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
