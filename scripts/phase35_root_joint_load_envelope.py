#!/usr/bin/env python3
"""Build a root-joint load envelope that keeps bending moment dominant."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    load_current_candidate_reference,
)
from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    DEFAULT_DETAIL_SAFETY_FACTOR,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase35_root_joint_load_envelope"
DEFAULT_ASSUMED_COUPLE_ARMS_M = (0.05, 0.10, 0.20)


@dataclass(frozen=True)
class RootJointLoadEnvelopeRow:
    load_case_key: str
    status: str
    service_force_n: float | None
    design_force_n: float | None
    service_moment_n_m: float | None
    design_moment_n_m: float | None
    assumed_couple_arm_m: float | None
    required_couple_force_n: float | None
    engineering_role: str
    engineering_note: str


@dataclass(frozen=True)
class RootJointLoadEnvelope:
    candidate_id: str
    overall_status: str
    detail_safety_factor: float
    design_root_force_n: float
    design_root_bending_moment_n_m: float
    force_only_check_is_misleading: bool
    rows: tuple[RootJointLoadEnvelopeRow, ...]


def build_root_joint_load_envelope(
    reference: Any,
    *,
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
    assumed_couple_arms_m: tuple[float, ...] = DEFAULT_ASSUMED_COUPLE_ARMS_M,
) -> RootJointLoadEnvelope:
    if detail_safety_factor <= 0.0:
        raise ValueError("detail_safety_factor must be positive.")
    if any(arm <= 0.0 for arm in assumed_couple_arms_m):
        raise ValueError("assumed_couple_arms_m values must be positive.")

    root_force = abs(float(reference.root_reaction_fz_n))
    root_moment = abs(float(reference.root_bending_moment_n_m))
    design_force = root_force * float(detail_safety_factor)
    design_moment = root_moment * float(detail_safety_factor)
    rows = (
        _force_row(design_force, root_force, detail_safety_factor),
        _moment_row(design_moment, root_moment, detail_safety_factor),
        *(
            _couple_row(design_moment, root_moment, detail_safety_factor, arm)
            for arm in assumed_couple_arms_m
        ),
    )
    return RootJointLoadEnvelope(
        candidate_id=str(reference.candidate_id),
        overall_status="root_joint_load_envelope_defined_not_signoff",
        detail_safety_factor=float(detail_safety_factor),
        design_root_force_n=design_force,
        design_root_bending_moment_n_m=design_moment,
        force_only_check_is_misleading=root_moment > 0.0,
        rows=rows,
    )


def write_root_joint_load_envelope_package(
    out_dir: Path,
    reference: Any,
    *,
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
    assumed_couple_arms_m: tuple[float, ...] = DEFAULT_ASSUMED_COUPLE_ARMS_M,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    envelope = build_root_joint_load_envelope(
        reference,
        detail_safety_factor=detail_safety_factor,
        assumed_couple_arms_m=assumed_couple_arms_m,
    )
    outputs = [
        _write_csv(out_dir / "root_joint_load_envelope.csv", envelope),
        _write_json(out_dir / "root_joint_load_envelope.json", envelope),
        _write_markdown(out_dir / "root_joint_load_envelope.md", envelope),
    ]
    return outputs


def build_current_root_joint_load_envelope() -> RootJointLoadEnvelope:
    return build_root_joint_load_envelope(load_current_candidate_reference())


def _force_row(
    design_force: float,
    service_force: float,
    detail_safety_factor: float,
) -> RootJointLoadEnvelopeRow:
    return RootJointLoadEnvelopeRow(
        load_case_key="root_vertical_reaction",
        status="load_defined_not_root_detail_signoff",
        service_force_n=service_force,
        design_force_n=design_force,
        service_moment_n_m=None,
        design_moment_n_m=None,
        assumed_couple_arm_m=None,
        required_couple_force_n=None,
        engineering_role="net vertical root reaction for bearing and shear checks",
        engineering_note=_engineering_note(detail_safety_factor),
    )


def _moment_row(
    design_moment: float,
    service_moment: float,
    detail_safety_factor: float,
) -> RootJointLoadEnvelopeRow:
    return RootJointLoadEnvelopeRow(
        load_case_key="root_bending_moment",
        status="moment_defined_not_root_detail_signoff",
        service_force_n=None,
        design_force_n=None,
        service_moment_n_m=service_moment,
        design_moment_n_m=design_moment,
        assumed_couple_arm_m=None,
        required_couple_force_n=None,
        engineering_role="root fitting, clamp, bond, and insert moment demand",
        engineering_note=_engineering_note(detail_safety_factor),
    )


def _couple_row(
    design_moment: float,
    service_moment: float,
    detail_safety_factor: float,
    arm_m: float,
) -> RootJointLoadEnvelopeRow:
    return RootJointLoadEnvelopeRow(
        load_case_key=f"moment_couple_arm_{arm_m:.3f}m".replace(".", "p"),
        status="couple_force_screening_not_root_detail_signoff",
        service_force_n=None,
        design_force_n=None,
        service_moment_n_m=service_moment,
        design_moment_n_m=design_moment,
        assumed_couple_arm_m=float(arm_m),
        required_couple_force_n=design_moment / float(arm_m),
        engineering_role="screening force if root moment is reacted as a clamp/bond couple",
        engineering_note=_engineering_note(detail_safety_factor),
    )


def _engineering_note(detail_safety_factor: float) -> str:
    return (
        f"Root envelope uses detail SF {detail_safety_factor:.2f}; not root fitting signoff and "
        "not a substitute for clamp, bond, insert, bearing, tube-wall, fatigue, or installation evidence."
    )


def _write_csv(path: Path, envelope: RootJointLoadEnvelope) -> Path:
    fields = list(asdict(envelope.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in envelope.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, envelope: RootJointLoadEnvelope) -> Path:
    path.write_text(
        json.dumps(asdict(envelope), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, envelope: RootJointLoadEnvelope) -> Path:
    lines = [
        "# Root Joint Load Envelope",
        "",
        f"Candidate: `{envelope.candidate_id}`",
        f"Overall status: `{envelope.overall_status}`",
        "",
        "This root joint load envelope is not root fitting signoff.",
        "",
        f"- detail safety factor: `{envelope.detail_safety_factor:.2f}`",
        f"- design root force: `{envelope.design_root_force_n:.3f} N`",
        f"- design root bending moment: `{envelope.design_root_bending_moment_n_m:.3f} N*m`",
        f"- force-only root check is misleading: `{envelope.force_only_check_is_misleading}`",
        "",
        "| case | status | design force N | design moment N*m | assumed arm m | required couple force N | role |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in envelope.rows:
        lines.append(
            f"| `{row.load_case_key}` | `{row.status}` | {_fmt(row.design_force_n)} | "
            f"{_fmt(row.design_moment_n_m)} | {_fmt(row.assumed_couple_arm_m)} | "
            f"{_fmt(row.required_couple_force_n)} | {row.engineering_role} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- The couple-force rows are screening loads for possible clamp/bond lever arms.",
            "- Replace the assumed arms with actual root fitting geometry before any margin claim.",
            "- A small net root reaction does not close the bending-moment load path.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--detail-safety-factor", type=float, default=DEFAULT_DETAIL_SAFETY_FACTOR)
    args = parser.parse_args(argv)

    outputs = write_root_joint_load_envelope_package(
        args.output_dir,
        load_current_candidate_reference(),
        detail_safety_factor=args.detail_safety_factor,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
