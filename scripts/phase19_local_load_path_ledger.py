#!/usr/bin/env python3
"""Build a local load-path ledger for unclosed hardware/detail checks."""
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
    CandidateReference,
    SELECTED_RUN,
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase19_local_load_path_ledger"

REQUIRED_LOCAL_LOAD_PATH_KEYS: tuple[str, ...] = (
    "wire_attach_local_load_path",
    "root_joint",
    "wire_termination",
    "rib_load_transfer",
)


@dataclass(frozen=True)
class LocalLoadPathEntry:
    key: str
    title: str
    status: str
    primary_load_n: float | None
    primary_moment_n_m: float | None
    utilization: float | None
    max_effective_bay_m: float | None
    evidence: str
    missing_evidence: str
    allowed_claim: str
    blocked_claim: str


@dataclass(frozen=True)
class LocalLoadPathLedger:
    candidate_id: str
    overall_status: str
    wire_count: int
    root_bending_moment_n_m: float
    max_effective_bay_m: float
    entries: tuple[LocalLoadPathEntry, ...]


def wire_force_vector_n(rigging: dict[str, object]) -> tuple[float, float, float]:
    """Return the force applied by the wire to the wing attach point."""

    attach = [float(value) for value in rigging["attach_point_loaded_m"]]  # type: ignore[index]
    anchor = [float(value) for value in rigging["anchor_point_m"]]  # type: ignore[index]
    tension = float(rigging["tension_force_n"])
    vector = [anchor[idx] - attach[idx] for idx in range(3)]
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 0.0:
        raise ValueError("Wire attach and anchor points coincide.")
    force = [tension * component / length for component in vector]
    return float(force[0]), float(force[1]), float(force[2])


def build_local_load_path_ledger(
    reference: CandidateReference,
    *,
    wire_rigging: list[dict[str, object]],
    spar_rows: list[dict[str, str]],
) -> LocalLoadPathLedger:
    if not wire_rigging:
        raise ValueError("At least one wire rigging row is required.")
    if len(spar_rows) < 2:
        raise ValueError("At least two spar rows are required.")

    wire_vectors = [wire_force_vector_n(row) for row in wire_rigging]
    wire_resultants = [
        math.sqrt(fx * fx + fy * fy + fz * fz)
        for fx, fy, fz in wire_vectors
    ]
    max_wire_idx = max(range(len(wire_resultants)), key=lambda idx: wire_resultants[idx])
    max_wire = wire_rigging[max_wire_idx]
    max_wire_force = wire_vectors[max_wire_idx]
    max_wire_allowable = float(max_wire.get("allowable_tension_n", reference.wire_allowable_n))
    max_wire_utilization = (
        wire_resultants[max_wire_idx] / max_wire_allowable
        if max_wire_allowable > 0.0
        else float("inf")
    )
    mandatory_y = _mandatory_bracing_stations_m(spar_rows, wire_rigging)
    max_bay = _max_spacing(mandatory_y)
    rib_station_load = _max_mandatory_station_vertical_load_n(spar_rows, mandatory_y)

    entries = (
        LocalLoadPathEntry(
            key="wire_attach_local_load_path",
            title="Wire attach local load path",
            status="load_defined_detail_allowable_missing",
            primary_load_n=wire_resultants[max_wire_idx],
            primary_moment_n_m=None,
            utilization=None,
            max_effective_bay_m=None,
            evidence=(
                f"Max wire attach force vector is Fx={max_wire_force[0]:.3f} N, "
                f"Fy={max_wire_force[1]:.3f} N, Fz={max_wire_force[2]:.3f} N "
                f"at {max_wire.get('identifier', 'wire')}."
            ),
            missing_evidence=(
                "attach detail allowable is missing: ring, lug, insert, bond, bearing, "
                "tube-wall crushing, and local load introduction are not checked"
            ),
            allowed_claim="Wire attach load vector is known for detail design.",
            blocked_claim="Do not claim attach ring, insert, bond, clamp, or local wall strength passes.",
        ),
        LocalLoadPathEntry(
            key="root_joint",
            title="Root joint",
            status="load_defined_detail_allowable_missing",
            primary_load_n=abs(float(reference.root_reaction_fz_n)),
            primary_moment_n_m=abs(float(reference.root_bending_moment_n_m)),
            utilization=None,
            max_effective_bay_m=None,
            evidence=(
                f"Root vertical reaction is {reference.root_reaction_fz_n:.3f} N and "
                f"root bending moment is {reference.root_bending_moment_n_m:.3f} N*m."
            ),
            missing_evidence=(
                "root fitting, clamp, bonded joint, insert, and bearing allowables are missing"
            ),
            allowed_claim="Root loads are known for joint sizing.",
            blocked_claim="Do not claim root fitting or bonded/clamped insert strength passes.",
        ),
        LocalLoadPathEntry(
            key="wire_termination",
            title="Wire termination",
            status="body_allowable_only_termination_missing",
            primary_load_n=wire_resultants[max_wire_idx],
            primary_moment_n_m=None,
            utilization=max_wire_utilization,
            max_effective_bay_m=None,
            evidence=(
                f"Cable-body utilization is {max_wire_utilization:.3f} against "
                f"{max_wire_allowable:.3f} N modeled allowable."
            ),
            missing_evidence=(
                "termination efficiency, splice/knot loss, bend radius, creep, abrasion, "
                "pin, anchor, and clamp allowables are missing"
            ),
            allowed_claim="Cable-body tension utilization is known.",
            blocked_claim="Do not treat cable-body allowable as termination allowable.",
        ),
        LocalLoadPathEntry(
            key="rib_load_transfer",
            title="Rib load transfer",
            status="layout_defined_stiffness_allowable_missing",
            primary_load_n=rib_station_load,
            primary_moment_n_m=None,
            utilization=None,
            max_effective_bay_m=max_bay,
            evidence=(
                f"Mandatory bracing stations imply max bay {max_bay:.3f} m; "
                f"max mandatory-station vertical load scale is {rib_station_load:.3f} N."
            ),
            missing_evidence=(
                "rib load-transfer stiffness is not proven; rib shear, cap, bond, and spar "
                "attachment allowables are missing"
            ),
            allowed_claim="Rib/bracing station layout is known for detail design.",
            blocked_claim="Do not claim ribs provide proven main/rear spar bracing load transfer.",
        ),
    )
    _assert_complete(entries)
    return LocalLoadPathLedger(
        candidate_id=reference.candidate_id,
        overall_status="loads_defined_but_not_detail_signoff",
        wire_count=len(wire_rigging),
        root_bending_moment_n_m=abs(float(reference.root_bending_moment_n_m)),
        max_effective_bay_m=max_bay,
        entries=entries,
    )


def write_local_load_path_ledger_package(
    out_dir: Path,
    reference: CandidateReference,
    *,
    wire_rigging: list[dict[str, object]],
    spar_rows: list[dict[str, str]],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = build_local_load_path_ledger(
        reference,
        wire_rigging=wire_rigging,
        spar_rows=spar_rows,
    )
    outputs = [
        _write_csv(out_dir / "local_load_path_ledger.csv", ledger),
        _write_json(out_dir / "local_load_path_ledger.json", ledger),
        _write_markdown(out_dir / "local_load_path_ledger.md", ledger),
    ]
    return outputs


def load_current_wire_rigging(path: Path = SELECTED_RUN / "lift_wire_rigging.json") -> list[dict[str, object]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["wire_rigging"])


def load_current_spar_rows(path: Path = SELECTED_RUN / "jig_shape_spar_data.csv") -> list[dict[str, str]]:
    return _read_csv_rows(path)


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


def _max_spacing(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    return max(values[idx + 1] - values[idx] for idx in range(len(values) - 1))


def _max_mandatory_station_vertical_load_n(
    spar_rows: list[dict[str, str]],
    mandatory_y_m: tuple[float, ...],
) -> float:
    max_load = 0.0
    for y_m in mandatory_y_m:
        nearest = min(spar_rows, key=lambda row: abs(float(row["Y_Position_m"]) - y_m))
        load = abs(float(nearest.get("Main_FZ_N", "0"))) + abs(
            float(nearest.get("Rear_FZ_N", "0"))
        )
        max_load = max(max_load, load)
    return float(max_load)


def _assert_complete(entries: tuple[LocalLoadPathEntry, ...]) -> None:
    keys = tuple(entry.key for entry in entries)
    if keys != REQUIRED_LOCAL_LOAD_PATH_KEYS:
        raise RuntimeError(
            "Local load path ledger key drift: "
            f"expected {REQUIRED_LOCAL_LOAD_PATH_KEYS!r}, got {keys!r}."
        )


def _write_csv(path: Path, ledger: LocalLoadPathLedger) -> Path:
    fields = [
        "key",
        "title",
        "status",
        "primary_load_n",
        "primary_moment_n_m",
        "utilization",
        "max_effective_bay_m",
        "evidence",
        "missing_evidence",
        "allowed_claim",
        "blocked_claim",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for entry in ledger.entries:
            writer.writerow(asdict(entry))
    return path


def _write_json(path: Path, ledger: LocalLoadPathLedger) -> Path:
    path.write_text(json.dumps(asdict(ledger), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, ledger: LocalLoadPathLedger) -> Path:
    lines = [
        "# Local Load Path Ledger",
        "",
        f"Candidate: `{ledger.candidate_id}`",
        f"Overall status: `{ledger.overall_status}`",
        "",
        "## Engineering Boundary",
        "",
        "- This ledger turns global reactions into local-detail input loads.",
        "- It does not create fitting, bond, insert, termination, or rib allowables.",
        "- Every row below remains blocked for hardware signoff until its missing evidence is supplied.",
        "",
        "## Summary",
        "",
        f"- wire count: `{ledger.wire_count}`",
        f"- root bending moment: `{ledger.root_bending_moment_n_m:.3f} N*m`",
        f"- max effective bracing bay from mandatory stations: `{ledger.max_effective_bay_m:.3f} m`",
        "",
        "## Ledger",
        "",
        "| item | status | load N | moment N*m | util | bay m | missing evidence |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for entry in ledger.entries:
        lines.append(
            f"| {entry.title} | `{entry.status}` | {_fmt(entry.primary_load_n)} | "
            f"{_fmt(entry.primary_moment_n_m)} | {_fmt(entry.utilization)} | "
            f"{_fmt(entry.max_effective_bay_m)} | {entry.missing_evidence} |"
        )
    lines.extend(
        [
            "",
            "## Readout",
            "",
            "- wire attach: attach detail allowable is missing even though the force vector is now explicit.",
            "- root joint: root bending moment is an input to fitting design, not proof of fitting strength.",
            "- rib load transfer: rib load-transfer stiffness is not proven by layout or nominal spacing alone.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    outputs = write_local_load_path_ledger_package(
        args.output_dir,
        reference,
        wire_rigging=load_current_wire_rigging(),
        spar_rows=load_current_spar_rows(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
